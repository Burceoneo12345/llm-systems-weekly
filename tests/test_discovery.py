import json
import os
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

    def test_new_categories_use_oai_set_names(self):
        self.assertIn(("stat", "ML"), papers.CATEGORIES)
        self.assertIn(("cs", "NE"), papers.CATEGORIES)


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
