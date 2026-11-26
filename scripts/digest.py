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

from papers import collect_papers
from upstream import collect_upstream, source_link


BEIJING = ZoneInfo("Asia/Shanghai")
REPORTS = Path("reports")
TIME_FORMAT = "%Y-%m-%d %H:%M"
COVERAGE = re.compile(r"^覆盖 (\d{4}-\d\d-\d\d \d\d:\d\d) 至 (\d{4}-\d\d-\d\d \d\d:\d\d)（北京时间）$", re.M)
TOPICS = {
    "低精度": r"\b(?:quantiz\w*|quantis\w*|dequant\w*|mixed.precision|low.precision|fake.quant\w*|[a-z]*fp[468]|int[48]|nf4|w[48]a\d+|[248][ -]?bit)\b",
    "强化学习": r"\b(?:reinforcement learning|RLHF|(?:async)?GRPO|DAPO|PPO|RLVR|policy optimiz\w*|policy gradient|reward model\w*|rollouts?|RL)\b",
    "训练": r"\b(?:train(?:ing)?|pre.?train\w*|backward|gradients?|optimizers?|parallelism|fully.shard\w*|FSDP\d*|DTensor|reduce.scatter|recomputation)\b",
    "推理": r"\b(?:inference|serving|speculative decod\w*|prefill|decoding|KV[ -]cache|throughput|latency)\b",
}
FOUR_BIT = re.compile(r"\b(?:4[ -]?bit|(?:nv|mx|n)?fp4|mxfp4|int4|nf4|w4a\d+|a\d+w4)\b", re.I)
SYSTEMS = re.compile(r"\b(?:moe|attention|all.reduce|all.to.all|context parallel\w*|grouped gemm|weight sync\w*|expert parallel\w*)\b", re.I)
SCOPE = re.compile(r"\b(?:llms?|language models?|transformers?|reasoning models?|foundation models?|moe|inference engine|distributed training)\b", re.I)
HOUSEKEEPING = re.compile(r"^(?:\[[^\]]+\]\s*)*(?:chore|ci|docs?|typo|bump|revert|test)(?:[\s:(/\]]|$)", re.I)


def parsed(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("截止时间必须包含 UTC 或时区偏移")
    return result


def rank(item):
    title = item["title"].replace("_", " ")
    details = title + " " + item["body"][:1200]
    topics = [name for name, pattern in TOPICS.items() if re.search(pattern, details, re.I)]
    if item["source"] in {"vLLM", "SGLang", "FlashInfer", "TensorRT-LLM"} and "训练" in topics and not re.search(TOPICS["训练"], title, re.I):
        topics.remove("训练")
    if item["source"] == "arXiv" and not SCOPE.search(details):
        return 0, topics
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
    return score, topics


def external_url(value):
    url = urlsplit(value)
    return url.scheme == "https" and url.netloc in {"arxiv.org", "github.com"} and not re.search(r"[\s()<>]", value)


def collect(bundle, until):
    end = (parsed(until) if until else datetime.now(timezone.utc)).astimezone(BEIJING).replace(second=0, microsecond=0)
    if end > datetime.now(BEIJING):
        raise ValueError("截止时间晚于当前时间")
    edition = end.date().isoformat()
    archive = []
    seen = set()
    for path in sorted(REPORTS.glob("????-??-??.md")):
        text = path.read_text()
        span = COVERAGE.search(text)
        if not span:
            raise ValueError(f"{path} 缺少可读取的覆盖区间")
        begin, stop = (datetime.strptime(t, TIME_FORMAT).replace(tzinfo=BEIJING) for t in span.groups())
        saved = re.search(r"^<!-- pending-sources (.+) -->$", text, re.M)
        archive.append((begin, stop, json.loads(saved[1]) if saved else {}))
        seen.update(re.findall(r"\]\((https://[^)\s]+)\)", text))
    if (REPORTS / f"{edition}.md").exists():
        print(f"{edition} 已存在，保留已发布内容")
        return
    previous = max((row for row in archive if row[1] <= end), key=lambda row: row[1], default=None)
    start = previous[1] if previous else end - timedelta(days=7)
    pending = previous[2] if previous else {}
    if any(start < stop and end > begin for begin, stop, _ in archive):
        raise ValueError("所选时间与已有周报重叠")
    sources = {"papers": (collect_papers, "arXiv 论文"), "github": (collect_upstream, "GitHub 合并记录与发布")}
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
                unfinished["papers"] = starts["papers"].isoformat()
    if len(failures) == len(sources):
        raise RuntimeError("；".join(failures))
    for failure in failures:
        print(f"来源暂缺 {failure}")
    candidates = []
    for item in discovered:
        event = parsed(item["date"])
        source_start = starts["papers" if item["source"] == "arXiv" else "github"]
        late_paper = item["source"] == "arXiv" and item.get("index_day") and event <= source_start
        if (not late_paper and not source_start < event <= end) or item["url"] in seen or not external_url(item["url"]):
            continue
        seen.add(item["url"])
        score, topics = rank(item)
        if late_paper:
            score -= 3
        if score >= 5:
            candidates.append({**item, "score": score, "topics": topics})
    selected = []
    counts = {}
    while candidates and len(selected) < 6:
        # Give another source a turn when several candidates have similar evidence.
        item = max(candidates, key=lambda c: (c["score"] - 8 * counts.get(c["source"], 0), c["date"], c["url"]))
        candidates.remove(item)
        counts[item["source"]] = counts.get(item["source"], 0) + 1
        if item["status"] == "已合并":
            code = source_link(item)
            if code and external_url(code):
                item["code"] = code
        selected.append(item)
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
    instructions = Path("PROMPT.md").read_text().split("## 放到看板")[0]
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
        kind = {"已合并": "合并记录", "已发布": "版本发布"}.get(item["status"], "论文原文")
        links = [f"[{kind}]({item['url']})"]
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
