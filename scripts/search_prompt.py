"""Search inputs from the Markdown prompt published on the weekly board."""
import re
from pathlib import Path


ISSUE_SIZE = 30
PROMPT_PATH = Path(__file__).resolve().parents[1] / "PROMPT.md"
method = PROMPT_PATH.read_text(encoding="utf-8").partition("\n## 检索方法\n")[2].split("\n## ", 1)[0]
CATEGORIES = tuple(dict.fromkeys(re.findall(r"\b([a-z][a-z-]+)\.([A-Z]{2})\b", method, re.ASCII)))
if not CATEGORIES:
    raise ValueError("PROMPT.md 的检索方法缺少 arXiv 分类")

venue_lines = re.findall(r"^- A 类(?:会议|期刊).*$", method, re.M)
CCF_A_VENUES = {
    source_id: label for label, source_id in
    re.findall(r"\[([^\]\n]+)\]\(https://openalex\.org/(S\d+)\)", "\n".join(venue_lines))
}

rows = dict(re.findall(r"^\|[ \t]*([^|\n]+?)[ \t]*\|[ \t]*([^|\n]+?)[ \t]*\|[ \t]*$", method, re.M))
KEYWORDS = {}
for dimension in ("数值格式", "训练环节", "推理环节", "硬件与生态"):
    terms = [term.strip() for term in re.split(r"[、，,]", rows.get(dimension, "")) if term.strip()]
    if not terms:
        raise ValueError(f"PROMPT.md 的关键词表缺少{dimension}")
    phrases = [r"[\s_-]+".join(re.escape(word) for word in re.split(r"[\s_-]+", term)) for term in terms]
    KEYWORDS[dimension] = re.compile(r"(?<![a-z0-9])(?:" + "|".join(phrases) + r")(?![a-z0-9])", re.I | re.ASCII)
