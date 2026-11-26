import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HeadlineCoverTest(unittest.TestCase):
    def test_per_edition_and_headline_with_stable_archive_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reports").mkdir()
            (root / "assets/covers").mkdir(parents=True)
            for asset in ("site.css", "filter.js", "assets/compute-cover.webp"):
                shutil.copy(ROOT / asset, root / asset)
            (root / "PROMPT.md").write_text("# 周报提示词")
            base = "# 周报\n\n覆盖区间\n"
            story = "\n## 同一头条\n\n`2026-11-20` `TRL` `已合并` `训练`\n\n打包微批次。\n"
            for date in ("2026-11-20", "2026-11-23"):
                (root / "reports" / f"{date}.md").write_text(base + story)
            (root / "reports/2026-11-16.md").write_text(base)

            pending = ["node", ROOT / "build.mjs", "--missing-covers"]
            covers = json.loads(subprocess.check_output(pending, cwd=root))
            files = [item["file"] for item in covers]
            self.assertEqual(len(covers), 2)
            self.assertNotEqual(*files)
            for file in files:
                (root / file).write_bytes(b"cover fixture")
            self.assertEqual(json.loads(subprocess.check_output(pending, cwd=root)), [])
            subprocess.run(["node", ROOT / "build.mjs"], cwd=root, check=True)
            for page, file in (("index.html", files[0]), ("weeks/2026-11-23/index.html", files[0]),
                               ("weeks/2026-11-20/index.html", files[1])):
                self.assertIn(file, (root / "_site" / page).read_text())
            self.assertNotIn("cover-art", (root / "_site/weeks/2026-11-16/index.html").read_text())
            (root / "reports/2026-11-23.md").write_text(base + story.replace("同一头条", "新的头条"))
            changed = json.loads(subprocess.check_output(pending, cwd=root))
            self.assertEqual(len(changed), 1)
            self.assertNotIn(changed[0]["file"], files)
