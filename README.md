# 大模型系统周报

面向昇腾 NPU 工程师，跟踪大模型训练、强化学习、推理与低精度的论文和上游实现。每期保留独立页面、Markdown 原文和当期头条封面。

[打开看板](https://burceoneo12345.github.io/llm-systems-weekly/) · [历史归档](https://burceoneo12345.github.io/llm-systems-weekly/archive/) · [周报提示词](PROMPT.md)

## 用 Codex 出刊

在仓库中打开 Codex，输入“按主分支 PROMPT.md 出本期周报，先给我本地预览”。周一、周五北京时间 09:00 截稿，手动出刊和定时出刊共用这份提示词。Codex 负责检索、核对原文、选头条和撰稿。论文回看一年，优先 CCF A 类会议主会和 A 类期刊。代码进展从上期截止时间接续，目标为论文和代码各 15 条。[完整出刊规则](PROMPT.md)

1. 先检查 `reports/` 中已有期次。可用仓库的检索工具按指定截止时间生成候选 JSON。下例中的 `edition` 替换为到期的北京时间日期，GitHub 检索使用只读凭据。已在环境中设置 `GH_TOKEN` 或 `GITHUB_TOKEN` 时，可直接运行 Python 命令。

   ```sh
   edition=YYYY-MM-DD
   GH_TOKEN="$(gh auth token)" python3 scripts/digest.py collect "/tmp/weekly-$edition.json" \
     --until "${edition}T09:00:00+08:00"
   ```

2. 阅读论文、PR 或 release 与固定提交源码，按证据选取并排序。在 `reports/YYYY-MM-DD.md` 写入覆盖区间、中文条目、一手链接和本周跟进问题。已有归档可作格式参考。[周报原文](reports/) · [上游仓库列表](scripts/upstream.py)
3. 安装 Node.js 24 或更高版本，首次运行 `npm ci`。写好首读后运行 `node build.mjs --missing-covers`。Codex 对照首读的一手来源，用内置 ChatGPT Image（imagegen）画出可辨认的研究对象和关键操作。图内使用短标签，必要时在首读正文后用 `> 图注：…` 说明。将实际生成的图片转为 WebP，保存到清单指定的 `assets/covers/` 路径。新一期有头条就生成新图，首页和该期固定页共用它。无条目的检索记录可以直接构建。

## 本地预览与发布

在仓库根目录运行以下命令，然后打开 [本机预览](http://127.0.0.1:8000/)，查看首页及“本期固定链接”。

```sh
npm ci
python3 -m unittest discover -s tests
npm run build
python3 -m http.server 8000 --bind 127.0.0.1 --directory _site
```

需要本地审稿时，Markdown、图片与预览留在工作区。发布时将成稿和封面一起推送至 `main`，Pages 工作流校验、构建并部署该提交里的静态文件。出刊时间由 Codex 端的排程决定。[Pages 工作流](.github/workflows/pages.yml)
