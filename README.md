# 大模型系统周报

按周收录大模型训练、强化学习、推理、低精度，以及 NVIDIA 和 AMD 的论文与源码进展。看板支持按主题筛选，每期都有固定链接和一份可在 GitHub 直接阅读的 Markdown 原文。

[打开看板](https://burceoneo12345.github.io/llm-systems-weekly/) · [历史归档](https://burceoneo12345.github.io/llm-systems-weekly/archive/) · [周报提示词](PROMPT.md)

## 发布一期

在 `reports/` 下新增 `YYYY-MM-DD.md`，使用北京时间截止日期命名。参照[首期周报](reports/2026-11-26.md)填写一级标题、覆盖区间和各条进展。每个二级标题下的一行代码标签依次表示日期、来源、状态和一个或多个主题。第一条自动成为本期首读，其中的表格会在看板上单独展示。「本周跟进」收录验证问题。

使用 Node.js 24 或更高版本在本地构建。

```sh
npm ci
npm run build
```

预览目录为 `_site/`。推送到 `main` 后，GitHub Actions 会构建并部署 GitHub Pages。
