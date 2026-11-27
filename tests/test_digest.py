import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import digest


class SourceCoverageTest(unittest.TestCase):
    def test_existing_edition_is_reused_without_collecting(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(digest, "REPORTS", Path(directory)), \
             patch.object(digest, "collect_papers") as papers, patch.object(digest, "collect_upstream") as upstream:
            report = Path(directory) / "2026-11-27.md"
            saved = "覆盖 2026-11-26 14:55 至 2026-11-27 09:00（北京时间）\n"
            report.write_text(saved)
            bundle = Path(directory) / "candidates.json"
            digest.collect(bundle, "2026-11-27T09:00:00+08:00")
            papers.assert_not_called()
            upstream.assert_not_called()
            self.assertFalse(bundle.exists())
            self.assertEqual(report.read_text(), saved)

    def test_pr_only_issue_and_paper_catchup(self):
        pr = {"url": "https://github.com/huggingface/trl/pull/1", "title": "AsyncGRPO rollout training",
              "source": "TRL", "status": "已合并", "body": "Batch training rollouts.",
              "date": "2026-11-24T18:00:00Z"}
        paper = {"url": "https://arxiv.org/abs/2611.00001v1", "title": "Quantization for LLM inference",
                 "source": "arXiv", "status": "预印本 v1", "body": "Low-precision model serving.",
                 "date": "2026-11-23T11:00:00Z"}
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory)
            with patch.object(digest, "REPORTS", reports):
                bundle = reports / "sources.json"
                with patch.object(digest, "collect_papers", side_effect=RuntimeError("temporary outage")), \
                     patch.object(digest, "collect_upstream", return_value=[pr]), \
                     patch.object(digest, "source_link", return_value=""):
                    digest.collect(bundle, "2026-11-25T09:00:00+08:00")
                partial = json.loads(bundle.read_text())
                self.assertEqual([item["url"] for item in partial["items"]], [pr["url"]])
                self.assertEqual(set(partial["pending"]), {"papers"})
                # Codex copies the pending-source cursor into the issue it writes.
                (reports / f"{partial['date']}.md").write_text(
                    f"覆盖 {partial['start']} 至 {partial['end']}（北京时间）\n"
                    f"<!-- pending-sources {json.dumps(partial['pending'])} -->\n"
                    f"[合并记录]({pr['url']})")
                with patch.object(digest, "collect_papers", return_value=[paper]) as recover, \
                     patch.object(digest, "collect_upstream", return_value=[pr]):
                    digest.collect(bundle, "2026-11-26T09:00:00+08:00")
                self.assertEqual(recover.call_args.args[0], datetime.fromisoformat(partial["pending"]["papers"]))
                final = json.loads(bundle.read_text())
                self.assertEqual([item["url"] for item in final["items"]], [paper["url"]])
                self.assertEqual(final["pending"], {})

    def test_all_sources_down_does_not_advance_archive(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(digest, "REPORTS", Path(directory)), \
             patch.object(digest, "collect_papers", side_effect=RuntimeError("offline")), \
             patch.object(digest, "collect_upstream", side_effect=RuntimeError("offline")):
            bundle = Path(directory) / "sources.json"
            with self.assertRaises(RuntimeError):
                digest.collect(bundle, "2026-11-25T09:00:00+08:00")
            self.assertFalse(bundle.exists())

    def test_yearly_search_skips_archived_versions_and_keeps_a_new_revision(self):
        paper = {"url": "https://arxiv.org/abs/2603.00001v1", "title": "LLM inference quantization",
                 "source": "arXiv", "status": "预印本 v1", "body": "Low-precision LLM inference.",
                 "date": "2026-03-01T12:00:00Z"}
        revised = dict(paper, url=paper["url"][:-1] + "3", status="修订版", date="2026-11-24T12:00:00Z")
        other = dict(paper, url="https://arxiv.org/abs/2603.00002v1", title="Quantization for LLM serving")
        with tempfile.TemporaryDirectory() as directory, patch.object(digest, "REPORTS", Path(directory)), \
             patch.object(digest, "collect_papers", return_value=[paper, revised, other]), \
             patch.object(digest, "collect_upstream", return_value=[]):
            reports = Path(directory)
            (reports / "2026-11-20.md").write_text(
                "覆盖 2026-11-13 09:00 至 2026-11-20 09:00（北京时间）\n"
                "[原文](https://arxiv.org/abs/2603.00001v2) · [原文](https://arxiv.org/abs/2603.00002v1)")
            bundle = reports / "sources.json"
            digest.collect(bundle, "2026-11-26T09:00:00+08:00")
            self.assertEqual([item["url"] for item in json.loads(bundle.read_text())["items"]], [revised["url"]])
