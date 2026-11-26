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
    def test_pr_only_issue_and_paper_catchup(self):
        pr = {"url": "https://github.com/huggingface/trl/pull/1", "title": "AsyncGRPO rollout training",
              "source": "TRL", "status": "已合并", "body": "Batch training rollouts.",
              "date": "2026-11-24T18:00:00Z"}
        paper = {"url": "https://arxiv.org/abs/2611.00001v1", "title": "Quantization for LLM inference",
                 "source": "arXiv", "status": "预印本 v1", "body": "Low-precision model serving.",
                 "date": "2026-11-23T11:00:00Z"}
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory)
            with patch.object(digest, "REPORTS", reports), patch.dict(digest.os.environ, {"GITHUB_OUTPUT": ""}):
                bundle = reports / "sources.json"
                with patch.object(digest, "collect_papers", side_effect=RuntimeError("temporary outage")), \
                     patch.object(digest, "collect_upstream", return_value=[pr]), \
                     patch.object(digest, "source_link", return_value=""):
                    digest.collect(bundle, "2026-11-25T09:00:00+08:00")
                partial = json.loads(bundle.read_text())
                self.assertEqual([item["url"] for item in partial["items"]], [pr["url"]])
                self.assertEqual(set(partial["pending"]), {"papers"})
                with patch.object(digest, "summarize", return_value={"title": "打包改动", "summary": "已合并", "question": ""}):
                    digest.write(bundle)
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
