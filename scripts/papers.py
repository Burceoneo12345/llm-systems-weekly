"""Discover published ML systems papers and versioned arXiv preprints."""

import json
import re
import time
import warnings
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from search_prompt import CATEGORIES, CCF_A_VENUES, KEYWORDS


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
PUBLISHERS = {"doi.org", "dl.acm.org", "ieeexplore.ieee.org", "aclanthology.org", "openreview.net",
              "proceedings.mlr.press", "proceedings.neurips.cc", "papers.nips.cc", "papers.neurips.cc",
              "www.usenix.org", "usenix.org", "www.jmlr.org", "jmlr.org"}


class AnnualPaperWarning(UserWarning):
    """The next issue already repeats this search over the full year."""


def paper_since(end):
    year = end.year - 1
    return end.replace(year=year, day=min(end.day, monthrange(year, end.month)[1]),
                       hour=0, minute=0, second=0, microsecond=0)


def paper_key(url):
    url = url.split("#", 1)[0]
    arxiv = re.fullmatch(r"https?://arxiv\.org/(?:abs|html)/(" + ARXIV_ID.pattern + r")(?:v\d+)?/?", url, re.I)
    if arxiv:
        return "https://arxiv.org/abs/" + arxiv[1].lower()
    return url.lower() if url.startswith("https://doi.org/") else url


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
    for attempt in range(2):
        try:
            with urlopen(request, timeout=35) as response:
                return response.read()
        except HTTPError as error:
            delay = error.headers.get("Retry-After", "10")
            if attempt or error.code not in {429, 502, 503, 504} or not delay.isdigit() or int(delay) > 60:
                raise
            time.sleep(int(delay))


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


def _recent_preprints(start, end):
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


def _published_papers(start, end):
    dates = f"from_publication_date:{start.date()},to_publication_date:{end.date()},is_retracted:false,has_abstract:true"
    topics = ("keywords.id:large-language-models|distributed-training|quantization|mixture-of-experts|"
              "llm-serving|gpu-kernels|reinforcement-learning-from-human-feedback")
    found, failures = {}, []
    filters = [(name, f"primary_location.source.id:{source_id}") for source_id, name in CCF_A_VENUES.items()]
    filters.append(("其他会刊", "primary_location.source.type:journal|conference"))
    for label, venue_filter in filters:
        params = {"filter": f"{dates},{topics},{venue_filter}", "per_page": 100, "page": 1,
                  "select": "display_name,doi,type,publication_date,primary_location,locations,abstract_inverted_index"}
        # Numbered pages are available without an API key. Page each priority venue independently.
        works = []
        try:
            while True:
                page = json.loads(_read("https://api.openalex.org/works?" + urlencode(params)))
                works.extend(page["results"])
                if label == "其他会刊" or len(page["results"]) < params["per_page"] or len(works) >= page["meta"]["count"]:
                    break
                params["page"] += 1
        except (OSError, HTTPException, ValueError, KeyError) as error:
            failures.append(f"{label}（{error}）")
        for work in works:
            location = work.get("primary_location") or {}
            source = location.get("source") or {}
            kind = {"conference": "会议论文", "journal": "期刊论文"}.get(source.get("type"))
            if not kind or not location.get("is_published"):
                continue
            if work["type"] not in {"article", "conference-paper", "proceedings-article", "journal-article"}:
                continue
            when = datetime.fromisoformat(work["publication_date"]).replace(tzinfo=end.tzinfo)
            if not start <= when <= end:
                continue
            url = location.get("landing_page_url") or ""
            doi = work.get("doi") or ""
            if urlsplit(url).hostname not in PUBLISHERS:
                url = doi
            if urlsplit(url).hostname not in PUBLISHERS or "doi.org/10.48550/arxiv." in url.lower():
                continue
            url = "https://" + url.split("://", 1)[-1].replace("(", "%28").replace(")", "%29")
            if url in found:
                continue
            title = work.get("display_name") or ""
            index = work.get("abstract_inverted_index") or {}
            body = " ".join(word for _, word in sorted((pos, word) for word, positions in index.items() for pos in positions))
            if not body or not _relevant(title, body):
                continue
            venue = CCF_A_VENUES.get(source["id"].rsplit("/", 1)[-1])
            track = location.get("raw_source_name") or ""
            satellite = kind == "会议论文" and re.search(
                r"\b(?:workshops?|findings|companion|short papers?|demos?|demonstrations?|posters?|technical briefs?)\b",
                track, re.I)
            ccf_a = bool(venue and not satellite)
            paper = {"title": title, "body": body[:2200], "url": url, "date": when.isoformat(),
                     "source": track if satellite else venue or source["display_name"],
                     "status": ("CCF A 类" if ccf_a else "") + kind,
                     "ccf_a": ccf_a}
            for copy in work.get("locations") or []:
                key = paper_key(copy.get("landing_page_url") or "")
                if key.startswith("https://arxiv.org/abs/") and ARXIV_ID.fullmatch(key.split("/abs/")[1]):
                    paper["preprint"] = key
                    break
            found[url] = paper
    if failures:
        message = "OpenAlex 未能返回" + "、".join(failures) + "的记录。"
        if len(failures) == len(filters) and not found:
            raise RuntimeError(message)
        warnings.warn(message, AnnualPaperWarning)
    return list(found.values())


def _annual_preprints(start, end):
    categories = " OR ".join(f"cat:{archive}.{category}" for archive, category in CATEGORIES)
    topics = ('((abs:"language model" OR abs:LLM OR abs:MoE OR abs:RLHF) AND '
              '(abs:quantization OR abs:serving OR abs:rollout OR abs:"KV cache" OR abs:"distributed training")) '
              'OR ((abs:GPU OR abs:NPU) AND (abs:GEMM OR abs:"attention kernel"))')
    lo, hi = (t.astimezone(timezone.utc).strftime("%Y%m%d%H%M") for t in (start, end))
    params = {"search_query": f"({categories}) AND ({topics}) AND submittedDate:[{lo} TO {hi}]",
              "sortBy": "relevance", "max_results": 100}
    feed = ElementTree.fromstring(_read("https://export.arxiv.org/api/query?" + urlencode(params)))
    if feed.find("{*}totalResults") is None:
        raise ValueError("Invalid arXiv search response")
    found = {}
    for entry in feed.findall("{*}entry"):
        link = entry.findtext("{*}id", "")
        match = re.fullmatch(r"https?://arxiv\.org/abs/(" + ARXIV_ID.pattern + r")v(\d+)", link)
        if not match:
            raise ValueError(f"Invalid arXiv search result: {link}")
        identifier, version = match[1], int(match[2])
        versions = {1: datetime.fromisoformat(entry.findtext("{*}published").replace("Z", "+00:00")),
                    version: datetime.fromisoformat(entry.findtext("{*}updated").replace("Z", "+00:00"))}
        title, body = entry.findtext("{*}title", ""), entry.findtext("{*}summary", "")
        if versions[version] > end and version > 1:
            title, body, versions = _abstract(identifier)
        _consider(found, identifier, title, body, versions, start - timedelta(microseconds=1), end)
    return list(found.values())


def collect_papers(start, end):
    if start.utcoffset() is None or end.utcoffset() is None or start >= end:
        raise ValueError("Expected an increasing timezone-aware window")
    since = paper_since(end)
    results, failures = [], []
    warning = AnnualPaperWarning
    feeds = [("会刊论文", _published_papers, since), ("arXiv 年度检索", _annual_preprints, since),
             ("arXiv 近期版本", _recent_preprints, max(start, since))]
    for label, collect, begin in feeds:
        try:
            results.extend(collect(begin, end))
        except (OSError, HTTPException, RuntimeError, ValueError, KeyError, ElementTree.ParseError) as error:
            failures.append(f"{label}检索未完成（{error}）")
            if collect is _recent_preprints:
                warning = UserWarning
    if len(failures) == len(feeds):
        raise RuntimeError("；".join(failures))
    if failures:
        warnings.warn("、".join(failures) + "。本期论文覆盖有限。", warning)
    return results
