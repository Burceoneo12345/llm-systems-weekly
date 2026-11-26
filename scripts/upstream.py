"""Collect weekly engineering candidates from their upstream GitHub repositories."""

import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


REPOSITORIES = {
    "NVIDIA/TransformerEngine": "Transformer Engine",
    "NVIDIA/Megatron-LM": "Megatron-LM",
    "NVIDIA/TensorRT-LLM": "TensorRT-LLM",
    "ROCm/aiter": "ROCm aiter",
    "vllm-project/vllm": "vLLM",
    "sgl-project/sglang": "SGLang",
    "verl-project/verl": "verl",
}

SEARCH = """
query($query: String!, $after: String) {
  search(type: ISSUE, query: $query, first: 100, after: $after) {
    issueCount pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { id title url mergedAt } }
  }
}"""
RELEASES = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    releases(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { id name tagName url publishedAt isDraft isPrerelease }
    }
  }
}"""
EVIDENCE = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on PullRequest { id bodyText }
    ... on Release { id descriptionHTML }
  }
}"""
FILES = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      mergeCommit { oid }
      files(first: 100, after: $after) {
        nodes { path changeType }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}"""


def _github(document, **variables):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GitHub upstream collection needs GH_TOKEN or GITHUB_TOKEN.")
    request = Request("https://api.github.com/graphql", json.dumps({
        "query": document, "variables": variables,
    }).encode(), headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "User-Agent": "llm-systems-weekly",
    })
    for attempt in range(4):
        delay = 2 ** (attempt + 1)
        try:
            with urlopen(request, timeout=45) as response:
                payload = json.load(response)
                headers = response.headers
            if not payload.get("errors"):
                return payload["data"]
            errors = payload["errors"]
            message = "; ".join(error["message"] for error in errors)
            retry = any(error.get("type") in {"RATE_LIMITED", "SERVICE_UNAVAILABLE", "INTERNAL"}
                        for error in errors) or "timeout" in message.lower()
            if "rate limit" in message.lower():
                retry, delay = True, 60
        except HTTPError as error:
            headers = error.headers
            message = f"HTTP {error.code}: {error.read(500).decode(errors='replace')}"
            limited = error.code == 403 and (
                headers.get("X-RateLimit-Remaining") == "0" or
                headers.get("Retry-After") or "rate limit" in message.lower()
            )
            retry = limited or error.code in {408, 429, 500, 502, 503, 504}
            if limited or error.code == 429:
                delay = 60
        except (TimeoutError, URLError, ConnectionError, IncompleteRead, json.JSONDecodeError) as error:
            headers, retry, message = {}, True, str(error)
        if headers.get("Retry-After", "").isdigit():
            delay = int(headers["Retry-After"]) + 1
        elif headers.get("X-RateLimit-Remaining") == "0" and headers.get("X-RateLimit-Reset"):
            delay = max(1, int(headers["X-RateLimit-Reset"]) - int(time.time()) + 1)
        if not retry or attempt == 3 or delay > 120:
            raise RuntimeError(f"GitHub query failed: {message}")
        time.sleep(delay)


def _pulls(repo, start, end):
    # GitHub search exposes at most 1,000 results per query. Split dense windows
    # by merge time, which has one-second resolution.
    windows = [(start.replace(microsecond=0), end.replace(microsecond=0))]
    while windows:
        left, right = windows.pop()
        bounds = "..".join(t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in (left, right))
        query = f"repo:{repo} is:pr is:merged merged:{bounds} sort:created-asc"
        after = None
        seen = set()
        while True:
            page = _github(SEARCH, query=query, after=after)["search"]
            if page["issueCount"] > 1000:
                if left == right:
                    raise RuntimeError(f"More than 1,000 merges in one second: {repo} {bounds}")
                middle = (left + (right - left) / 2).replace(microsecond=0)
                windows.extend([(left, middle), (middle + timedelta(seconds=1), right)])
                break
            for pr in page["nodes"]:
                seen.add(pr["id"])
                when = pr["mergedAt"]
                if when and start < datetime.fromisoformat(when) <= end:
                    yield dict(id=pr["id"], title=pr["title"], url=pr["url"], date=when,
                               source=REPOSITORIES[repo], status="已合并")
            if not page["pageInfo"]["hasNextPage"]:
                if len(seen) != page["issueCount"]:
                    raise RuntimeError(f"Read {len(seen)} of {page['issueCount']} matches for {bounds}")
                break
            after = page["pageInfo"]["endCursor"]


def _releases(repo, start, end):
    owner, name = repo.split("/")
    after = None
    while True:
        result = _github(RELEASES, owner=owner, name=name, after=after)["repository"]
        if result is None:
            raise RuntimeError(f"GitHub repository unavailable: {repo}")
        page = result["releases"]
        for release in page["nodes"]:
            when = release["publishedAt"]
            if not release["isDraft"] and when and start < datetime.fromisoformat(when) <= end:
                title = release["name"] or release["tagName"]
                if release["isPrerelease"]:
                    title += " (pre-release)"
                yield dict(id=release["id"], title=title, url=release["url"], date=when,
                           source=REPOSITORIES[repo], status="已发布")
        # Release ordering is by creation, not publication: a draft can be
        # published weeks after its creation. Read the lightweight index to its end.
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]


LOW4 = re.compile(r"\b(?:(?:nv|mx)?fp4|nf4|int4|4[ -]?bit(?:rl)?|w4a(?:4|8|16)|a(?:4|8|16)w4)\b")
RL = re.compile(r"\b(?:rollouts?|rl|rlhf|rlvr|ppo|grpo|dapo|qat|reinforcement learning|reward|policy|weight sync)\b")
SYSTEMS = re.compile(
    r"\b(?:parallel(?:ism)?|distributed|attention|moe|experts?|kv cache|throughput|memory|prefill|decoding|"
    r"all[ -]?(?:to[ -]?all|gather|reduce)|offload|gemm|speculative|checkpointing|activation recomput\w*)\b"
)
PRECISION = re.compile(r"\b(?:(?:mx)?fp8|int8|quantiz\w*|dequantiz\w*|low[ -]precision)\b")
HOUSEKEEPING = re.compile(
    r"(?:^|\[)(?:ci|chore|lint|build)(?:\]|:|\b)|"
    r"\b(?:typos?|pre-commit|dependabot|copyright|release notes|bump dependency)\b"
)


def _rank(item):
    title = item["title"].lower().replace("_", " ")
    low4 = bool(LOW4.search(title))
    rl = bool(RL.search(title))
    score = 6 * low4 + 3 * rl + 10 * (low4 and (rl or item["source"] == "verl"))
    score += 2 * bool(SYSTEMS.search(title)) + 2 * bool(PRECISION.search(title))
    score -= 7 * bool(HOUSEKEEPING.search(title))
    score -= 3 * title.startswith(("revert ", "cherry-pick ", "[backport]"))
    if item["status"] == "已发布":
        score += 4 if "(pre-release)" not in title else 1
    return score, item["date"]


class _ReleaseText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "li", "pre", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")


def collect_upstream(start, end):
    """Return ranked source-backed candidates for start < event time <= end."""
    if start.utcoffset() is None or end.utcoffset() is None or start > end:
        raise ValueError("Expected ordered timezone-aware start and end datetimes.")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    candidates = {}
    for repo in REPOSITORIES:
        try:
            pulls = {item["url"]: item for item in _pulls(repo, start, end)}
            for item in sorted(pulls.values(), key=_rank, reverse=True)[:8]:
                candidates[item["id"]] = item
            for item in _releases(repo, start, end):
                candidates[item["id"]] = item
        except (RuntimeError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"Incomplete GitHub coverage for {repo}: {error}") from error

    ids = list(candidates)
    for offset in range(0, len(ids), 60):
        batch = ids[offset:offset + 60]
        nodes = _github(EVIDENCE, ids=batch)["nodes"]
        if len(nodes) != len(batch) or any(not node for node in nodes):
            raise RuntimeError("Incomplete GitHub evidence: a selected public PR or release disappeared.")
        for node in nodes:
            if "bodyText" in node:
                body = node["bodyText"]
            else:
                parser = _ReleaseText()
                parser.feed(node["descriptionHTML"] or "")
                body = "".join(parser.parts)
            clean = "".join(c for c in body if c.isspace() or unicodedata.category(c) not in {"Cc", "Cf"})
            clean = "\n".join(" ".join(line.split()) for line in clean.splitlines() if line.strip())
            item = candidates[node["id"]]
            item["body"] = clean if len(clean) <= 2000 else clean[:1999] + "…"
            del item["id"]
    return sorted(candidates.values(), key=_rank, reverse=True)


def source_link(item):
    """Choose a changed source file at the merge commit of a selected public PR."""
    match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", item["url"])
    if not match or match[1] not in REPOSITORIES:
        return ""
    repo = match[1]
    owner, name = repo.split("/")
    words = set(re.findall(r"[a-z0-9]{3,}", item["title"].lower()))
    files = []
    after = None
    while True:
        pr = _github(FILES, owner=owner, name=name, number=int(match[2]), after=after)["repository"]["pullRequest"]
        if not pr or not pr["mergeCommit"] or not pr["files"]:
            return ""
        for file in pr["files"]["nodes"]:
            if file["changeType"] == "DELETED":
                continue
            path = file["path"]
            lower = path.lower()
            implementation = lower.endswith((
                ".py", ".cc", ".cpp", ".cu", ".cuh", ".c", ".h", ".hpp", ".hip", ".rs", ".sh", ".triton", ".mlir",
            ))
            fixture = bool(re.search(r"(?:^|/)(?:tests?|docs?|\.github|benchmarks?)(?:/|_)", lower))
            overlap = len(words.intersection(re.findall(r"[a-z0-9]{3,}", lower)))
            files.append(((implementation, not fixture, overlap), path))
        if not pr["files"]["pageInfo"]["hasNextPage"]:
            break
        after = pr["files"]["pageInfo"]["endCursor"]
    if not files:
        return ""
    path = max(files, key=lambda entry: entry[0])[1]
    return f"https://github.com/{repo}/blob/{pr['mergeCommit']['oid']}/{quote(path)}"
