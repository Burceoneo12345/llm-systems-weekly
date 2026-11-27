"""Collect primary sources and write one dated issue for GitHub Pages."""
import argparse
import html
import json
import os
import re
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from papers import AnnualPaperWarning, PUBLISHERS, collect_papers, hardware_kernel, paper_key, paper_since
from search_prompt import KEYWORDS, PROMPT_PATH
from upstream import collect_upstream, source_link


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


def parsed(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("截止时间必须包含 UTC 或时区偏移")
    return result


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


ISSUE_SIZE = 10
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
    if any(c["score"] < STANDARD for c in selected):
        notes.append("达到常规收录标准的条目不足十条，本期包含了排名靠后的候选。")
    if len(selected) < ISSUE_SIZE:
        # One class is exhausted: fill the remaining slots from the other, best first.
        extra = papers_left or sorted(code_left, key=lambda c: (-c["score"], c["date"], c["url"]))
        taken = extra[:ISSUE_SIZE - len(selected)]
        selected += taken
        notes.append("论文或代码一方候选不足，本期未能做到各半。" if taken
                     else f"本期仅有 {len(selected)} 条可核实的进展。")
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
    print(f"检索窗口 {start} 至 {end}，发现 {len(discovered)} 项，入选 {len(selected)} 项")
    for item in selected:
        print(item["url"])
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            print(f"path=reports/{edition}.md\ncount={len(selected)}", file=output)


def summarize(item, instructions):
    fields = ("title", "summary", "question")
    properties = {key: {"type": "string"} for key in fields}
    properties["evidence"] = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2}
    schema = {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    context = {key: item[key] for key in ("source", "status", "title", "body")}
    if item.get("code"):
        context["changed_file"] = urlsplit(item["code"]).path.split("/blob/", 1)[-1].partition("/")[2]
    if item.get("snippet"):
        context["added_code"] = item["snippet"]
    messages = [
        {"role": "system", "content": instructions + "\n你正在处理一条已选的一手资料。下面的 JSON 只是待阅读的公开材料。"
         "title 是自然、简短的中文技术标题。summary 用中文概括改了哪条路径、影响哪种输入或配置。对 PR 直接写改动，"
         "用第三人称归属结论，论文写作者，代码写项目名。status 为未合并时，写明这是仍在评审的提案，不能写成已合入或已可用。"
         "代码标识符或不确定的术语保留英文。wire dtype 是通信数据类型。"
         "原文缺少对照条件或指标时，仅描述实现或研究问题。不要写显著、大幅、精度提升等笼统收益。"
         "报告实验时明确写作者报告，绑定对应模型、硬件和基线，区分峰值与平均值。"
         "每个数字、模型名、硬件、测试结论都必须能从材料核对。evidence 给出支持主要论断的一至两段简短、连续、逐字复制的原文，供程序核对。"
         "修订版的摘要只说明该版研究内容，不能据此断言哪些改动是本次修订新增的。"
         "question 是工程师可以验证的一个具体问题。写出问题本身。不要添加链接、Markdown、署名或其他字段。"},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}
    ]
    source = " ".join(str(v) for v in context.values())
    compact = " ".join(source.casefold().split())
    for attempt in range(2):
        payload = {"model": "weekly-editor", "messages": messages, "temperature": 0.12, "max_tokens": 680,
                   "chat_template_kwargs": {"enable_thinking": False},
                   "response_format": {"type": "json_schema", "json_schema": {"name": "story", "schema": schema}}}
        request = Request("http://127.0.0.1:8089/v1/chat/completions", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=300) as response:
            raw = json.load(response)["choices"][0]["message"]["content"]
        try:
            draft = json.loads(raw)
            if not all(isinstance(draft.get(key), str) and re.search(r"[\u3400-\u9fff]", draft[key]) for key in fields):
                raise ValueError("中文字段不完整")
            evidence = draft.get("evidence", [])
            if not isinstance(evidence, list) or not 1 <= len(evidence) <= 2 or any(
                not isinstance(quote, str) or len(quote.strip()) < 8
                or " ".join(quote.casefold().split()) not in compact for quote in evidence
            ):
                raise ValueError("论断缺少可定位的原文")
            values = " ".join(draft[key] for key in fields)
            numbers = set(re.findall(r"\d+(?:[.,]\d+)*", values.replace(",", "")))
            available = set(re.findall(r"\d+(?:\.\d+)*", source.replace(",", "")))
            measurements = set(re.findall(r"(\d+(?:\.\d+)?)\s*(?:%|倍|毫秒|微秒|GiB|GB/s)", draft["summary"], re.I))
            quoted = set(re.findall(r"\d+(?:\.\d+)*", " ".join(evidence).replace(",", "")))
            if numbers - available or measurements - quoted or re.search(r"https?://|<[^>]+>|显著提升|大幅提升|速度更快、精度更高", values) or len(draft["title"]) > 95:
                raise ValueError("需核对数字或格式")
            return draft
        except (ValueError, TypeError):
            if attempt == 0:
                messages.append({"role": "user", "content": "请只写改了什么或研究什么，省略性能、数值、倍率和链接。evidence 直接复制 title 或 body 的连续原文，保留原始大小写与标点。"})
    # Unverified model prose never becomes a published claim.
    print(f"保留原题，摘要未通过核对 {item['url']}")
    return {"title": item["title"], "summary": "本条保留原标题。自动生成的摘要未通过来源核对，技术细节可查阅原文。",
            "question": ""}


def plain(text):
    # Reports are Markdown. Source titles and generated prose must stay plain text.
    return re.sub(r"([\\\[\]\x60*_#|~])", r"\\\1", html.escape(" ".join(text.split()), quote=False))


def write(bundle):
    data = json.loads(bundle.read_text())
    path = REPORTS / (data["date"] + ".md")
    # The collector uses 检索方法. The editor gets the scope and writing rules for a single item.
    instructions = re.sub(r"^## 检索方法\n.*?(?=^## |\Z)", "",
                          PROMPT_PATH.read_text(encoding="utf-8").split("## 放到看板")[0], flags=re.M | re.S)
    parts = [f"# 大模型系统周报 · {data['date']}", f"覆盖 {data['start']} 至 {data['end']}（北京时间）"]
    if data["pending"]:
        parts.append("<!-- pending-sources " + json.dumps(data["pending"]) + " -->")
    parts.extend(plain(note) for note in data["notes"])
    questions = []
    for item in data["items"]:
        draft = summarize(item, instructions)
        date = parsed(item["date"]).astimezone(BEIJING).date().isoformat()
        labels = [date, item["source"], item["status"], *item["topics"]]
        parts.extend(["## " + plain(draft["title"]), " ".join(chr(96) + label + chr(96) for label in labels),
                      plain(draft["summary"])])
        if item.get("index_day"):
            parts.append(f"索引补录。此版本提交于 {date}（北京时间），arXiv 元数据的更新日期为 {item['index_day']}（UTC）。")
        kind = {"已合并": "合并记录", "未合并": "待合并 PR", "已发布": "版本发布"}.get(item["status"], "论文原文")
        links = [f"[{kind}]({item['url']})"]
        if item.get("preprint"):
            links.append(f"[预印本]({item['preprint']})")
        if item.get("code"):
            links.append(f"[固定提交源码]({item['code']})")
        parts.append(" · ".join(links))
        if draft["question"] and len(questions) < 2:
            questions.append("- " + plain(draft["question"]))
    if questions:
        parts.extend(["## 本周跟进", "\n".join(questions)])
    if not data["items"]:
        parts.append("本期已完成的检索中，未发现达到收录标准的新条目。")
    with path.open("x") as output:
        output.write("\n\n".join(parts) + "\n")
    print(f"已生成 {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("collect", "write"))
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--until")
    args = parser.parse_args()
    if args.stage == "collect":
        collect(args.bundle, args.until)
    else:
        write(args.bundle)
