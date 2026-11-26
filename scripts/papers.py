"""Discover ML systems preprints from public, versioned arXiv metadata."""

import json
import re
import time
import warnings
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from http.client import HTTPException
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from search_prompt import CATEGORIES, KEYWORDS


# A paper is relevant when it names a model family and a systems concern, a rollout
# system, or an accelerator vendor together with a kernel-level term. Recall matters
# here; digest.rank applies the stricter scope and topic gates afterwards.
MODEL = re.compile(r"\b(?:[lv]lms?|language models?|reasoning models?|transformers?|"
                   r"foundation models?|mixture.of.experts?|moes?|"
                   r"rlhf|rlvr|grpo|dapo|ppo|gspo|\brl\b|reward models?|vllm|sglang|megatron)\b", re.I)
SYSTEM = re.compile(r"\b(?:quantiz\w*|quantis\w*|(?:low|mixed).precision|[2468][ -]?bits?|"
                    r"(?:nv|mx)?fp[468]|int[248]|nf4|w4a\d+|a\d+w4|microscaling|block[ -]?scal\w*|"
                    r"master weights?|optimizer states?|weight sync\w*|weight compression|"
                    r"kv.cache\w*|key.value cach\w*|speculative decod\w*|prefill|continuous batching|paged|"
                    r"(?:model|llm|inference) serving|serving (?:systems?|llms?|latency|throughput|workloads?)|"
                    r"inference engines?|"
                    r"disaggregat\w*|parallelism|(?:tensor|expert|sequence|pipeline|context|data) parallel\w*|"
                    r"distributed training|communication overhead|communication (?:cost|volume)|all[ -]?to[ -]?all|"
                    r"offload\w*|activation checkpoint\w*|zero-\d|fsdp\d*|long.context|"
                    r"(?:training|inference|decoding) (?:throughput|latency|efficiency)|"
                    r"(?:attention|fused|gpu) kernels?|tensor cores?|cutlass|\bcute\b|triton|flashattention\w*|"
                    r"memory bandwidth|"
                    r"gradient (?:compression|checkpointing|synchronization)|fully sharded)\b", re.I)
ROLLOUT = re.compile(r"\brollouts?\b", re.I)
RL_SYSTEM = re.compile(r"\b(?:throughput|latency|wall.clock|asynchronous|synchronous|stragglers?|"
                       r"workers?|weight sync\w*|gpu.hours|rollout (?:budget|control|engine|schedul\w*)|"
                       r"kv.cache\w*|offload\w*|partial rollouts?|over.?generat\w*|long.tail|efficien\w*|"
                       r"speedup|truncat\w*|max (?:length|tokens|sequence))\b", re.I)
VENDOR = re.compile(r"\b(?:nvidia|amd|cuda|rocm|blackwell|rubin|hopper|instinct|"
                    r"(?:gb|b|h|mi)[1-9]\d{1,2}\w*|ascend|npu|huawei|tpu|intel|gaudi|habana|groq|cerebras|"
                    r"sambanova)\b", re.I)
KERNEL = re.compile(r"\b(?:gemm|matmul|matrix multiplication|tensor cores?|collectives?|"
                    r"all.reduce|all.to.all|attention kernels?|kernels?|(?:nv|mx)?fp[48]|int4|"
                    r"cutlass|\bcute\b|triton|tma|fused|microscaling|block.scal\w*|dequant\w*)\b", re.I)
ARXIV_ID = re.compile(r"(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})")


def hardware_kernel(text):
    return bool((VENDOR.search(text) or KEYWORDS["硬件与生态"].search(text)) and KERNEL.search(text))


def _relevant(title, body):
    text = f"{title} {body}".replace("‑", "-").replace("–", "-")
    if MODEL.search(text):
        if (SYSTEM.search(text) or KEYWORDS["数值格式"].search(text) or KEYWORDS["推理环节"].search(text)
                or (ROLLOUT.search(text) and RL_SYSTEM.search(text))):
            return True
        # A method name such as GRPO supplies the model match, but needs a separate systems term.
        if any(not (MODEL.fullmatch(hit[0]) or ROLLOUT.fullmatch(hit[0]))
               for hit in KEYWORDS["训练环节"].finditer(text)):
            return True
    return hardware_kernel(text)


def _read(url):
    if "arxiv.org/" in url:
        time.sleep(3.1)  # arXiv requests are serial and separated by at least three seconds.
    request = Request(url, headers={"User-Agent": "llm-systems-weekly/1.0 (+https://github.com/Burceoneo12345/llm-systems-weekly)"})
    with urlopen(request, timeout=35) as response:
        return response.read()


class _AbstractPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.history = []
        self.in_history = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name", "").startswith("citation_"):
            self.meta[attrs["name"]] = attrs.get("content", "")
        if tag == "div" and "submission-history" in attrs.get("class", "").split():
            self.in_history = True

    def handle_endtag(self, tag):
        if tag == "div":
            self.in_history = False

    def handle_data(self, text):
        if self.in_history:
            self.history.append(text)


def _abstract(identifier, suffix=""):
    page = _AbstractPage()
    page.feed(_read(f"https://arxiv.org/abs/{identifier}{suffix}").decode())
    stamps = re.findall(r"\[v(\d+)\]\s*([A-Z][a-z]{2},\s+\d{1,2} [A-Z][a-z]{2} \d{4} "
                        r"\d{2}:\d{2}:\d{2} (?:UTC|GMT))", " ".join(page.history))
    if not stamps or page.meta.get("citation_arxiv_id") not in (identifier, identifier + suffix):
        raise ValueError(f"arXiv submission history missing for {identifier}{suffix}")
    return (page.meta["citation_title"], page.meta["citation_abstract"],
            {int(n): parsedate_to_datetime(date) for n, date in stamps})


def _consider(found, identifier, title, body, versions, start, end, index_day=None):
    if not ARXIV_ID.fullmatch(identifier) or not versions:
        raise ValueError(f"Invalid arXiv version metadata for {identifier!r}")
    if not title.strip() or not body.strip() or any(date.utcoffset() is None for date in versions.values()):
        raise ValueError(f"Incomplete arXiv metadata for {identifier}")
    eligible = [version for version, stamp in versions.items() if start < stamp <= end]
    latest = max(versions)
    # A version submitted before a cutoff can first appear in the index after it.
    late = (not eligible and index_day and start.date() <= index_day <= end.date()
            and start - timedelta(days=7) < versions[latest] <= start)
    if (not eligible and not late) or not _relevant(title, body):
        return
    version = max(eligible) if eligible else latest
    url = f"https://arxiv.org/abs/{identifier}v{version}"
    if url in found:
        return
    if version != max(versions):  # The latest abstract may describe changes after the cutoff.
        title, body, history = _abstract(identifier, f"v{version}")
        if history.get(version) != versions[version]:
            raise ValueError(f"Conflicting arXiv submission dates for {url}")
    if not _relevant(title, body) or re.search(r"\b(?:paper|submission) (?:has been|is) withdrawn\b", body, re.I):
        return
    found[url] = {"title": " ".join(title.split()), "url": url,
                  "date": versions[version].astimezone(timezone.utc).isoformat(), "source": "arXiv",
                  "status": "预印本 v1" if version == 1 else "修订版", "body": " ".join(body.split())[:2200]}
    if late:
        found[url]["index_day"] = index_day.isoformat()


def collect_papers(start, end):
    """Return versioned papers and separately marked late-indexed candidates."""
    if start.utcoffset() is None or end.utcoffset() is None or start >= end:
        raise ValueError("Expected an increasing timezone-aware window")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    # Announcement and indexing can lag submission over weekends. Never use an index date as the event.
    first = start.date() - timedelta(days=1)
    last = min(end.date() + timedelta(days=5), datetime.now(timezone.utc).date())
    found = {}
    try:
        for archive, category in CATEGORIES:
            params = {"verb": "ListRecords", "metadataPrefix": "arXivRaw", "set": f"{archive}:{archive}:{category}",
                      "from": first.isoformat(), "until": last.isoformat()}
            seen_tokens = set()
            while True:
                root = ElementTree.fromstring(_read("https://oaipmh.arxiv.org/oai?" + urlencode(params)))
                error = root.find("{*}error")
                if error is not None and error.get("code") == "noRecordsMatch":
                    break
                records = root.find("{*}ListRecords")
                if error is not None or records is None or records.find("{*}record") is None:
                    raise ValueError(f"Invalid OAI response for {archive}.{category}: {getattr(error, 'text', '')}")
                for record in records.findall("{*}record"):
                    header = record.find("{*}header")
                    if header is None:
                        raise ValueError(f"Missing OAI record header in {archive}.{category}")
                    if header.get("status") == "deleted":
                        continue
                    raw = record.find("{*}metadata/{*}arXivRaw")
                    if raw is None:
                        raise ValueError(f"Missing arXivRaw metadata in {archive}.{category}")
                    versions = {int(v.attrib["version"].removeprefix("v")): parsedate_to_datetime(v.findtext("{*}date", ""))
                                for v in raw.findall("{*}version")}
                    stamp = header.findtext("{*}datestamp")
                    index_day = datetime.fromisoformat(stamp[:10]).date() if stamp else None
                    _consider(found, raw.findtext("{*}id", ""), raw.findtext("{*}title", ""),
                              raw.findtext("{*}abstract", ""), versions, start, end, index_day)
                token = records.findtext("{*}resumptionToken")
                if not token:
                    break
                if token in seen_tokens:
                    raise ValueError("Repeated OAI resumption token")
                seen_tokens.add(token)
                params = {"verb": "ListRecords", "resumptionToken": token}
    except (OSError, HTTPException, ValueError, KeyError, ElementTree.ParseError) as primary:
        try:
            day = start.date()
            checked = set()
            while day <= last:
                params = {"date": day.isoformat(), "limit": 100}
                entries = json.loads(_read("https://huggingface.co/api/daily_papers?" + urlencode(params)))
                if not isinstance(entries, list):
                    raise ValueError("Invalid Hugging Face daily papers response")
                for entry in entries:
                    paper = entry["paper"]
                    identifier = paper["id"]
                    if identifier in checked or not _relevant(paper["title"], paper["summary"]):
                        continue
                    if not ARXIV_ID.fullmatch(identifier):
                        raise ValueError("Invalid arXiv identifier in Hugging Face feed")
                    checked.add(identifier)
                    _consider(found, identifier, *_abstract(identifier), start, end)
                day += timedelta(days=1)
        except (OSError, HTTPException, ValueError, KeyError) as secondary:
            raise RuntimeError(f"Paper discovery failed: arXiv OAI-PMH ({primary}), fallback ({secondary})") from secondary
        if not found:
            raise RuntimeError("arXiv OAI-PMH failed and curated discovery found no verified matches") from primary
        warnings.warn("arXiv 批量接口未完成检索，已从 Hugging Face Daily Papers 补查并逐篇核对版本，论文覆盖范围有限。")
    return sorted(found.values(), key=lambda paper: (paper["date"], paper["url"]), reverse=True)
