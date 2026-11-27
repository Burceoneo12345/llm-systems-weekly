import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import digest
import papers
import upstream


class PaperRelevanceTest(unittest.TestCase):
    def test_low_precision_formats_and_rlx_systems_are_discovered(self):
        relevant = [
            ("Microscaling W4A4 training for large language models", ""),
            ("NVFP4 grouped GEMM for MoE on Ascend NPUs", ""),
            ("Partial rollouts reduce long-tail stragglers in RLHF", ""),
            ("GB300 kernel libraries for MXFP8 inference", ""),
        ]
        irrelevant = [
            ("Rewarding honest reasoning: a reinforcement learning guide for LLMs", ""),
            ("Prompt engineering for vision-language models", ""),
        ]
        for title, body in relevant:
            with self.subTest(title=title):
                self.assertTrue(papers._relevant(title, body))
        for title, body in irrelevant:
            with self.subTest(title=title):
                self.assertFalse(papers._relevant(title, body))

    def test_next_run_uses_the_categories_and_terms_in_its_own_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            shutil.copytree(ROOT / "scripts", checkout / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            (checkout / "PROMPT.md").write_text(
                "# 周报提示词\n\n## 检索方法\n\n论文扫描 cs.IR。\n"
                "- A 类会议主会包括 [ExampleConf](https://openalex.org/S1234)。\n"
                "其他来源包括 [OtherConf](https://openalex.org/S9999)。\n"
                "| 维度 | 关键词 |\n| --- | --- |\n| 数值格式 | ExampleFormat |\n"
                "| 训练环节 | example training |\n| 推理环节 | example serving |\n| 硬件与生态 | ExampleChip |\n"
            )
            check = """
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import digest, papers, upstream

def read(url):
    if "api.openalex.org" in url:
        return b'{"results":[]}'
    if "export.arxiv.org" in url:
        return b'<feed><totalResults>0</totalResults></feed>'
    return b'<OAI-PMH><error code="noRecordsMatch"/></OAI-PMH>'
with patch.object(papers, "_read", side_effect=read) as api:
    papers.collect_papers(datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
queries = [parse_qs(urlsplit(call.args[0]).query) for call in api.call_args_list]
assert [q["set"] for q in queries if "set" in q] == [["cs:cs:IR"]]
assert any("primary_location.source.id:S1234" in q.get("filter", [""])[0] for q in queries)
assert "S9999" not in papers.CCF_A_VENUES
assert all("from_publication_date:2025-01-02" in q["filter"][0] for q in queries if "filter" in q)
assert any("cat:cs.IR" in q.get("search_query", [""])[0] and "202501020000" in q["search_query"][0] for q in queries)
assert papers._relevant("ExampleFormat for LLMs", "")
assert papers._relevant("GEMM kernels for ExampleChip", "")
item = dict(title="Support ExampleFormat", source="PyTorch", status="已合并", date="2026-01-02",
            url="https://github.com/pytorch/pytorch/pull/1", body="")
assert upstream._rank(item) > upstream._rank(dict(item, title="Support another format"))
assert "低精度" in digest.rank(item)[1]
assert digest.rank(dict(item, title="GEMM kernels for ExampleChip", source="arXiv"))[0] > 0
"""
            subprocess.run([sys.executable, "-c", check], cwd=checkout / "scripts", check=True)

    def test_publication_venue_and_date_come_from_the_published_record(self):
        start, end = datetime(2025, 11, 26, tzinfo=timezone.utc), datetime(2026, 11, 26, tzinfo=timezone.utc)
        title = "Quantization for LLM inference"
        location = {"source": {"id": "https://openalex.org/S1", "type": "conference", "display_name": "TestConf"},
                    "is_published": True, "raw_source_name": "TestConf", "landing_page_url": "https://doi.org/10.1234/paper"}
        work = {"display_name": title, "publication_date": "2026-03-10", "primary_location": location,
                "type": "conference-paper", "abstract_inverted_index": {"LLM": [0], "inference": [1]},
                "locations": [{"landing_page_url": "http://arxiv.org/abs/2601.00001v2"}]}
        workshop = {**location, "raw_source_name": "TestConf Workshops", "landing_page_url": "https://doi.org/10.1234/workshop"}
        journal = {**location, "source": {"id": "https://openalex.org/S2", "type": "journal", "display_name": "TestJournal"},
                   "landing_page_url": "https://doi.org/10.1234/journal"}
        works = [work, dict(work, primary_location=workshop), dict(work, primary_location=journal, type="article"),
                 dict(work, publication_date="2025-11-25", primary_location=dict(location, landing_page_url="https://doi.org/10.1234/old"))]
        with patch.object(papers, "CCF_A_VENUES", {"S1": "TestConf", "S2": "TestJournal"}), \
             patch.object(papers, "_read", return_value=json.dumps({"results": works}).encode()):
            selected = papers._published_papers(start, end)
        self.assertEqual([p["status"] for p in selected], ["CCF A 类会议论文", "会议论文", "CCF A 类期刊论文"])
        self.assertEqual(selected[0]["preprint"], "https://arxiv.org/abs/2601.00001")
        leap = datetime(2024, 2, 29, 9, tzinfo=timezone.utc)
        self.assertEqual(papers.paper_since(leap), datetime(2023, 2, 28, tzinfo=timezone.utc))


class OpenPullWatchListTest(unittest.TestCase):
    def test_title_must_name_a_format_or_training_path(self):
        for title in ("Add NVFP4 W4A16 MoE backend", "Async GRPO rollout with weight sync",
                      "Fix FP8 dequantization in the PPO actor"):
            with self.subTest(title=title):
                self.assertTrue(upstream._watched(title))
        for title in ("Fix typo in README", "Bump vllm to 0.33.0", "Add FP8 GEMM path", "Speed up rollout packing"):
            with self.subTest(title=title):
                self.assertFalse(upstream._watched(title))

    def test_open_pulls_keep_one_in_window(self):
        start = datetime(2026, 11, 20, tzinfo=timezone.utc)
        end = datetime(2026, 11, 26, tzinfo=timezone.utc)
        nodes = [
            {"id": "a", "title": "Add NVFP4 W4A16 MoE backend", "url": "https://github.com/vllm-project/vllm/pull/1",
             "mergedAt": None, "createdAt": "2026-11-23T10:00:00Z"},
            {"id": "b", "title": "MXFP4 grouped GEMM for GRPO rollout", "url": "https://github.com/vllm-project/vllm/pull/2",
             "mergedAt": None, "createdAt": "2026-11-24T10:00:00Z"},
            {"id": "c", "title": "Fix typo in README", "url": "https://github.com/vllm-project/vllm/pull/3",
             "mergedAt": None, "createdAt": "2026-11-24T10:00:00Z"},
            {"id": "d", "title": "NVFP4 support", "url": "https://github.com/vllm-project/vllm/pull/4",
             "mergedAt": None, "createdAt": "2026-11-18T10:00:00Z"},
        ]
        with patch.object(upstream, "_github", return_value={"search": {"issueCount": len(nodes), "nodes": nodes}}) as query:
            found = upstream._open_pulls("vllm-project/vllm", start, end)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["status"], "未合并")
        self.assertEqual(found[0]["source"], "vLLM")
        self.assertIn(found[0]["url"], {nodes[0]["url"], nodes[1]["url"]})
        issued = query.call_args.kwargs["query"]
        self.assertIn("is:pr is:open created:2026-11-20T00:00:00Z..2026-11-26T00:00:00Z", issued)
        # GitHub search returns nothing for a query with more than five OR operators.
        self.assertLessEqual(issued.count(" OR "), 5)
        self.assertEqual(query.call_count, 1)

    def test_training_repos_get_the_weight_sync_group(self):
        start = datetime(2026, 11, 20, tzinfo=timezone.utc)
        end = datetime(2026, 11, 26, tzinfo=timezone.utc)
        page = {"search": {"issueCount": 0, "nodes": []}}
        with patch.object(upstream, "_github", return_value=page) as query:
            upstream._open_pulls("verl-project/verl", start, end)
        self.assertEqual(query.call_count, len(upstream.OPEN_GROUPS))
        self.assertIn('"weight sync"', query.call_args_list[1].kwargs["query"])

    def test_merge_queue_repositories_are_read_from_branch_history(self):
        start = datetime(2026, 11, 20, tzinfo=timezone.utc)
        end = datetime(2026, 11, 26, tzinfo=timezone.utc)
        history = {"repository": {"defaultBranchRef": {"target": {"history": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [
                {"committedDate": "2026-11-24T10:00:00Z", "messageHeadline": "[Inductor] NVFP4 scaled mm template for CUDA (#200893)"},
                {"committedDate": "2026-11-24T11:00:00Z", "messageHeadline": "[Inductor] NVFP4 scaled mm template for CUDA (#200893)"},
                {"committedDate": "2026-11-24T12:00:00Z", "messageHeadline": "Fix CI flakiness (#200894)"},
                {"committedDate": "2026-11-25T12:00:00Z", "messageHeadline": "Direct push without a pull request"},
                {"committedDate": "2026-11-19T12:00:00Z", "messageHeadline": "Old INT4 kernel (#200000)"},
            ]}}}}}
        pulls = {"repository": {"p200893": {"id": "n1", "title": "[Inductor] NVFP4 scaled mm template for CUDA",
                                           "url": "https://github.com/pytorch/pytorch/pull/200893",
                                           "mergedAt": "2026-11-24T10:00:00Z"},
                                "p200894": {"id": "n2", "title": "Fix CI flakiness",
                                            "url": "https://github.com/pytorch/pytorch/pull/200894",
                                            "mergedAt": "2026-11-24T12:00:00Z"}}}

        def github(document, **variables):
            return pulls if "pullRequest(number" in document else history
        with patch.object(upstream, "_github", side_effect=github):
            found = list(upstream._commit_pulls("pytorch/pytorch", start, end))
        self.assertEqual([item["url"] for item in found], [pulls["repository"]["p200893"]["url"],
                                                           pulls["repository"]["p200894"]["url"]])
        self.assertEqual(found[0]["status"], "已合并")
        self.assertEqual(found[0]["date"], "2026-11-24T10:00:00Z")


class OpenPullSelectionTest(unittest.TestCase):
    def test_open_pulls_are_demoted_capped_and_not_the_lead(self):
        def item(number, title, status):
            return {"url": f"https://github.com/vllm-project/vllm/pull/{number}", "title": title, "source": "vLLM",
                    "status": status, "body": "", "date": "2026-11-24T18:00:00Z"}
        merged = item(1, "AsyncGRPO rollout training", "已合并")
        first = item(2, "NVFP4 W4A16 MoE backend for GRPO rollout", "未合并")
        second = item(3, "MXFP4 W4A16 MoE backend for GRPO rollout", "未合并")
        self.assertGreater(digest.rank(merged)[0], 5)
        self.assertLess(digest.rank(first)[0], digest.rank(dict(first, status="已合并"))[0])
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "sources.json"
            with patch.object(digest, "REPORTS", Path(directory)), patch.dict(digest.os.environ, {"GITHUB_OUTPUT": ""}), \
                 patch.object(digest, "collect_papers", return_value=[]), \
                 patch.object(digest, "collect_upstream", return_value=[second, first, merged]), \
                 patch.object(digest, "source_link", return_value=""):
                digest.collect(bundle, "2026-11-26T09:00:00+08:00")
            selected = json.loads(bundle.read_text())["items"]
        self.assertEqual([entry["status"] for entry in selected], ["已合并", "未合并"])
        self.assertEqual(selected[0]["url"], merged["url"])

    def test_write_labels_open_pulls_and_keeps_search_method_out_of_the_model_prompt(self):
        item = {"url": "https://github.com/vllm-project/vllm/pull/2", "title": "NVFP4 backend",
                "source": "vLLM", "status": "未合并", "body": "", "date": "2026-11-24T18:00:00Z",
                "topics": ["低精度", "推理"]}
        data = {"date": "2026-11-26", "start": "2026-11-20 09:00", "end": "2026-11-26 09:00",
                "items": [item], "notes": [], "pending": {}}
        previous = os.getcwd()
        os.chdir(ROOT)
        try:
            with tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory) / "sources.json"
                bundle.write_text(json.dumps(data))
                with patch.object(digest, "REPORTS", Path(directory)), \
                     patch.object(digest, "summarize", return_value={"title": "待合并的后端", "summary": "提案", "question": ""}) as model:
                    digest.write(bundle)
                text = (Path(directory) / "2026-11-26.md").read_text()
        finally:
            os.chdir(previous)
        self.assertIn("`未合并`", text)
        self.assertIn("[待合并 PR](https://github.com/vllm-project/vllm/pull/2)", text)
        instructions = model.call_args.args[1]
        self.assertIn("## 追踪范围", instructions)
        self.assertIn("## 如何筛选和写作", instructions)
        self.assertNotIn("检索方法", instructions)


class BalancedSelectionTest(unittest.TestCase):
    @staticmethod
    def code(number, score, status="已合并", repo="vllm-project/vllm"):
        return {"url": f"https://github.com/{repo}/pull/{number}", "title": f"code {number}", "source": repo.split("/")[1],
                "status": status, "body": "", "date": "2026-11-24T18:00:00Z", "score_hint": score}

    @staticmethod
    def paper(number, score):
        return {"url": f"https://arxiv.org/abs/2611.{number:05d}v1", "title": f"paper {number}", "source": "arXiv",
                "status": "预印本 v1", "body": "", "date": "2026-11-24T18:00:00Z", "score_hint": score}

    def select(self, items):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "sources.json"
            with patch.object(digest, "REPORTS", Path(directory)), patch.dict(digest.os.environ, {"GITHUB_OUTPUT": ""}), \
                 patch.object(digest, "collect_papers", return_value=[]), \
                 patch.object(digest, "collect_upstream", return_value=items), \
                 patch.object(digest, "source_link", return_value=""), \
                 patch.object(digest, "rank", side_effect=lambda item: (item["score_hint"], ["低精度"])):
                digest.collect(bundle, "2026-11-26T09:00:00+08:00")
            data = json.loads(bundle.read_text())
        return data["items"], data["notes"]

    def test_ten_stories_split_evenly_with_the_best_first(self):
        code = [self.code(n, 20 - n) for n in range(8)]
        code[0]["status"], code[1]["status"] = "未合并", "未合并"
        papers = [self.paper(n, 12 - n) for n in range(8)]
        selected, notes = self.select(code + papers)
        self.assertEqual(len(selected), 10)
        self.assertEqual(sum(item["source"] == "arXiv" for item in selected), 5)
        # Both open PRs outscore the merged work, yet only the first is kept and it goes last.
        self.assertEqual(selected[0]["url"], "https://github.com/vllm-project/vllm/pull/2")
        self.assertEqual(selected[-1]["url"], "https://github.com/vllm-project/vllm/pull/0")
        self.assertTrue(all(item["score"] >= digest.STANDARD for item in selected))
        self.assertEqual([item["status"] for item in selected].count("未合并"), 1)
        self.assertEqual(selected[-1]["status"], "未合并")
        self.assertFalse(any("不足" in note for note in notes))

    def test_short_class_is_topped_up_from_the_other_and_noted(self):
        selected, notes = self.select([self.paper(1, 15), self.paper(2, 14)] + [self.code(n, 20 - n) for n in range(12)])
        self.assertEqual(len(selected), 10)
        self.assertEqual(sum(item["source"] == "arXiv" for item in selected), 2)
        self.assertTrue(any("未能做到各半" in note for note in notes))

    def test_annual_papers_prefer_ranked_venues_without_extending_the_code_window(self):
        preprints = [self.paper(n, 20 + n) for n in range(8)]
        published = dict(self.paper(8, 6), date="2025-11-26T00:00:00+08:00", status="CCF A 类期刊论文",
                         url="https://doi.org/10.1234/annual", source="TPDS", ccf_a=True, preprint=preprints[7]["url"])
        old = dict(published, date="2025-11-25T23:59:59+08:00", url="https://doi.org/10.1234/old", title="older")
        future = dict(published, date="2026-11-26T09:01:00+08:00", url="https://doi.org/10.1234/future", title="future")
        old_pr = dict(self.code(9, 100), date="2026-03-10T00:00:00Z")
        selected, _ = self.select(preprints + [published, old, future, old_pr] + [self.code(n, 20) for n in range(5)])
        links = [item["url"] for item in selected]
        self.assertIn(published["url"], links)
        self.assertEqual(len(links), 10)
        for rejected in (preprints[7], old, future, old_pr):
            self.assertNotIn(rejected["url"], links)

    def test_lower_ranked_candidates_fill_a_short_class_before_topping_up(self):
        items = ([self.code(n, 20 - n) for n in range(3)] + [self.paper(n, 17 - n) for n in range(3)]
                 + [self.code(n, 3) for n in range(10, 14)] + [self.paper(n, 4) for n in range(10, 14)])
        selected, notes = self.select(items)
        self.assertEqual(len(selected), 10)
        self.assertEqual(sum(item["source"] == "arXiv" for item in selected), 5)
        self.assertEqual(sum(item["score"] < digest.STANDARD for item in selected), 4)
        self.assertTrue(any("排名靠后" in note for note in notes))
        self.assertFalse(any("未能做到各半" in note for note in notes))

    def test_fewer_than_ten_reports_what_exists(self):
        selected, notes = self.select([self.code(1, 9), self.paper(1, 9)])
        self.assertEqual(len(selected), 2)
        self.assertTrue(any("仅有 2 条" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
