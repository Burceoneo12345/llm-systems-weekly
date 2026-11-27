"""Collect and rank primary-source candidates for a Codex-authored issue."""
import argparse
import json
import re
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from papers import AnnualPaperWarning, PUBLISHERS, collect_papers, hardware_kernel, paper_key, paper_since
from search_prompt import ISSUE_SIZE, KEYWORDS
from upstream import collect_upstream, parsed, source_link


BEIJING = ZoneInfo("Asia/Shanghai")
REPORTS = Path("reports")
TIME_FORMAT = "%Y-%m-%d %H:%M"
COVERAGE = re.compile(r"^覆盖 (\d{4}-\d\d-\d\d \d\d:\d\d) 至 (\d{4}-\d\d-\d\d \d\d:\d\d)（北京时间）$", re.M)
TOPICS = {
    "低精度": r"\b(?:quantiz\w*|quantis\w*|dequant\w*|mixed.precision|low.precision|fake.quant\w*|[a-z]*fp[468]|int[248]|nf4|"
              r"w[48]a\d+|[2468][ -]?bit|microscaling|block.scal\w*|\bqat\b)\b",
    "强化学习": r"\b(?:reinforcement learning|RLHF|(?:async)?GRPO|DAPO|PPO|GSPO|RLVR|policy optimiz\w*|"
                r"policy gradient|reward model\w*|rollouts?|RL)\b",
    "训练": r"\b(?:train(?:ing)?|pre.?train\w*|backward|gradients?|optimizers?|parallelism|fully.shard\w*|FSDP\d*|DTensor|reduce.scatter|recomputation)\b",
    "推理": r"\b(?:inference|serving|speculative decod\w*|prefill|decoding|KV[ -]cache|throughput|latency)\b",
}
TOPICS["低精度"] += "|" + KEYWORDS["数值格式"].pattern
FOUR_BIT = re.compile(r"\b(?:4[ -]?bit|(?:nv|mx|n)?fp4|mxfp4|int4|nf4|w4a\d+|a\d+w4)\b", re.I)
SYSTEMS = re.compile(r"\b(?:moe|attention|all.reduce|all.to.all|context parallel\w*|grouped gemm|weight sync\w*|expert parallel\w*)\b", re.I)
SCOPE = re.compile(r"\b(?:llms?|language models?|transformers?|reasoning models?|foundation models?|moe|inference engine|distributed training)\b", re.I)
HOUSEKEEPING = re.compile(r"^(?:\[[^\]]+\]\s*)*(?:chore|ci|docs?|typo|bump|revert|test)(?:[\s:(/\]]|$)", re.I)


def is_paper(item):
    return item["source"] == "arXiv" or item["status"].endswith(("会议论文", "期刊论文"))


def rank(item):
    title = item["title"].replace("_", " ")
    details = title + " " + item["body"][:1200]
    topics = [name for name, pattern in TOPICS.items() if re.search(pattern, details, re.I)]
    if item["source"] in {"vLLM", "SGLang", "FlashInfer", "TensorRT-LLM"} and "训练" in topics and not re.search(TOPICS["训练"], title, re.I):
        topics.remove("训练")
    if is_paper(item) and not SCOPE.search(details):
        if not hardware_kernel(details):
            return 0, topics
        if not topics:
            topics.append("算子")
    if not topics:
        topics = [topic for topic, dimension in (("训练", "训练环节"), ("推理", "推理环节"))
                  if KEYWORDS[dimension].search(details)]
    if not topics and SYSTEMS.search(title):
        topics.append("训练" if "megatron" in item["url"].lower() else "推理")
    if not topics or (HOUSEKEEPING.search(title) and item["status"] == "已合并"):
        return 0, topics
    score = 2 * len(topics) + sum(3 for pattern in TOPICS.values() if re.search(pattern, title, re.I))
    if FOUR_BIT.search(details) and "强化学习" in topics:
        topics.insert(0, "4-bit RL")
        score += 10
    score += 3 * bool(SYSTEMS.search(title)) + 2 * bool(FOUR_BIT.search(title))
    owner = urlsplit(item["url"]).path.split("/")[1].lower()
    group = {"nvidia": "NVIDIA", "rocm": "AMD"}.get(owner)
    if group:
        topics.append(group)
    elif re.search(r"\b(?:AMD|ROCm|gfx\d+|MI[234]\d\d\w*)\b", title, re.I):
        topics.append("AMD")
    elif re.search(r"\b(?:NVIDIA|CUDA|Blackwell|Rubin|H100|B200|GB200|GB300)\b", title, re.I):
        topics.append("NVIDIA")
    # Work still under review is a trend to watch; merged evidence wins a tie.
    if item["status"] == "未合并":
        score -= 3
    return score, topics


def external_url(value):
    url = urlsplit(value)
    return url.scheme == "https" and url.netloc in PUBLISHERS | {"arxiv.org", "github.com"} and not re.search(r"[\s()<>]", value)


STANDARD = 5  # score a candidate needs before the bar is relaxed to fill an issue


def _ranked(group):
    """Prioritize CCF A papers, then rank by engineering score and rotate sources."""
    rest, counts, chosen, watched = list(group), {}, [], False
    while rest:
        item = max(rest, key=lambda c: (bool(c.get("ccf_a")), c["score"] >= STANDARD,
                                        c["score"] - 8 * counts.get(c["source"], 0), c["date"], c["url"]))
        rest.remove(item)
        # One open PR per issue; it moves to the end after selection.
        if item["status"] == "未合并":
            if watched:
                continue
            watched = True
        counts[item["source"]] = counts.get(item["source"], 0) + 1
        chosen.append(item)
    return chosen


def _halves(code, papers, room):
    """Take equal numbers of code and paper stories, at most `room` in total."""
    half = min(room // 2, len(code), len(papers))
    return code[:half] + papers[:half], code[half:], papers[half:]


def _select(pool, notes):
    """Fill an issue with half code and half papers, relaxing the bar only to reach ISSUE_SIZE."""
    code = _ranked(c for c in pool if not is_paper(c))
    papers = _ranked(c for c in pool if is_paper(c))
    selected, code_left, papers_left = _halves(code, papers, ISSUE_SIZE)
    if len(selected) < ISSUE_SIZE:
        # One class is exhausted: fill the remaining slots from the other, best first.
        extra = papers_left or sorted(code_left, key=lambda c: (-c["score"], c["date"], c["url"]))
        taken = extra[:ISSUE_SIZE - len(selected)]
        selected += taken
        notes.append("论文或代码一方候选不足，本期未能做到各半。" if taken
                     else f"本期仅有 {len(selected)} 条可核实的进展。")
    if any(c["score"] < STANDARD for c in selected):
        notes.append(f"本期目标为 {ISSUE_SIZE} 条，收录了排名靠后的候选。")
    selected.sort(key=lambda c: (-c["score"], c["date"], c["url"]))
    return sorted(selected, key=lambda item: item["status"] == "未合并")


def collect(bundle, until):
    end = (parsed(until) if until else datetime.now(timezone.utc)).astimezone(BEIJING).replace(second=0, microsecond=0)
    if end > datetime.now(BEIJING):
        raise ValueError("截止时间晚于当前时间")
    edition = end.date().isoformat()
    archive = []
    seen = set()
    archived_versions = {}
    for path in sorted(REPORTS.glob("????-??-??.md")):
        text = path.read_text()
        span = COVERAGE.search(text)
        if not span:
            raise ValueError(f"{path} 缺少可读取的覆盖区间")
        begin, stop = (datetime.strptime(t, TIME_FORMAT).replace(tzinfo=BEIJING) for t in span.groups())
        saved = re.search(r"^<!-- pending-sources (.+) -->$", text, re.M)
        archive.append((begin, stop, json.loads(saved[1]) if saved else {}))
        for url in re.findall(r"\]\((https://[^)\s]+)\)", text):
            key = paper_key(url)
            version = re.search(r"v(\d+)(?:#|$)", url) if key.startswith("https://arxiv.org/abs/") else None
            if version:
                archived_versions[key] = max(archived_versions.get(key, 0), int(version[1]))
            else:
                seen.add(key)
    if (REPORTS / f"{edition}.md").exists():
        print(f"{edition} 已存在，保留已发布内容")
        return
    previous = max((row for row in archive if row[1] <= end), key=lambda row: row[1], default=None)
    start = previous[1] if previous else end - timedelta(days=7)
    pending = previous[2] if previous else {}
    if any(start < stop and end > begin for begin, stop, _ in archive):
        raise ValueError("所选时间与已有周报重叠")
    sources = {"papers": (collect_papers, "论文"), "github": (collect_upstream, "GitHub 合并记录与发布")}
    starts = {key: parsed(pending[key]) if key in pending else start for key in sources}
    discovered, notes, unfinished, failures = [], [], {}, []
    with warnings.catch_warnings(record=True) as notices, ThreadPoolExecutor(max_workers=2) as pool:
        warnings.simplefilter("always", UserWarning)
        jobs = {key: pool.submit(fn, starts[key], end) for key, (fn, _) in sources.items()}
        for key, future in jobs.items():
            label = sources[key][1]
            try:
                records = future.result()
            except (OSError, RuntimeError, ValueError) as error:
                failures.append(f"{label}: {error}")
                unfinished[key] = starts[key].isoformat()
                notes.append(f"{label}本次检索未完成。下期将从上次成功检索的截止时间补查。")
            else:
                discovered.extend(records)
                if starts[key] < start:
                    notes.append(f"{label}本期一并补检了自 {starts[key].astimezone(BEIJING):%Y-%m-%d %H:%M} 起的区间。")
        for notice in notices:
            if issubclass(notice.category, UserWarning):
                notes.append(str(notice.message))
                if not issubclass(notice.category, AnnualPaperWarning):
                    unfinished["papers"] = starts["papers"].isoformat()
    if len(failures) == len(sources):
        raise RuntimeError("；".join(failures))
    for failure in failures:
        print(f"来源暂缺 {failure}")
    candidates = []
    since = paper_since(end)
    notes.insert(0, f"论文回看 {since:%Y-%m-%d} 至 {end:%Y-%m-%d}，优先收录 CCF 目录中的 A 类会议和 A 类期刊论文。")
    # Prefer the published record when multiple sources return the same paper.
    discovered.sort(key=lambda c: (bool(c.get("ccf_a")), "ccf_a" in c, c["date"]), reverse=True)
    paper_titles = set()
    for item in discovered:
        event = parsed(item["date"])
        paper = is_paper(item)
        in_window = since <= event <= end if paper else starts["github"] < event <= end
        keys = {paper_key(item["url"])}
        if item.get("preprint"):
            keys.add(paper_key(item["preprint"]))
        title = re.sub(r"[\W_]+", "", item["title"].casefold())
        if not in_window or keys & seen or not external_url(item["url"]) or (paper and title in paper_titles):
            continue
        prior = max((archived_versions.get(key, 0) for key in keys), default=0)
        if prior:
            version = re.search(r"v(\d+)$", item["url"]) if item["source"] == "arXiv" else None
            if not version or int(version[1]) <= prior:
                continue
        score, topics = rank(item)
        if item.get("index_day"):
            score -= 3
        if score > 0:
            seen.update(keys)
            if paper:
                paper_titles.add(title)
            candidates.append({**item, "score": score, "topics": topics})
    selected = _select(candidates, notes)
    for item in selected:
        if item["status"] == "已合并":
            code = source_link(item)
            if code and external_url(code):
                item["code"] = code
    bundle.write_text(json.dumps({"date": edition, "start": start.strftime(TIME_FORMAT),
                                  "end": end.strftime(TIME_FORMAT), "items": selected,
                                  "notes": notes, "pending": unfinished},
                                 ensure_ascii=False))
    print(f"检索窗口 {start} 至 {end}，发现 {len(discovered)} 项，写入 {len(selected)} 项候选到 {bundle}")
    for item in selected:
        print(item["url"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("collect",))
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--until")
    args = parser.parse_args()
    collect(args.bundle, args.until)
