# 大模型系统周报

按周收录大模型训练、强化学习、推理、低精度，以及 NVIDIA 和 AMD 的论文与源码进展。看板支持按主题筛选，每期都有固定链接和一份可在 GitHub 直接阅读的 Markdown 原文。

[打开看板](https://burceoneo12345.github.io/llm-systems-weekly/) · [历史归档](https://burceoneo12345.github.io/llm-systems-weekly/archive/) · [周报提示词](PROMPT.md)

## 自动更新

GitHub Actions 每周一、周五 09:00（Asia/Shanghai）启动。托管运行器从上一期截止时间开始，检索 arXiv 论文以及 14 个上游仓库的合并记录与版本发布。来源包括 PyTorch、TorchAO、Transformers、TRL、FlashInfer、Triton、DeepSpeed，以及 NVIDIA、AMD 和推理、RL 框架。去重后每期最多六条，可全部来自已合并 PR。看板支持按来源类型筛选。[查看跟踪仓库](scripts/upstream.py)

中文摘要由云端 CPU 上的 Qwen3-8B 生成，模型权重按校验和缓存。每条摘要核对来源片段和数字，未经核实的生成内容退回原标题。仓库自带的 `GITHUB_TOKEN` 负责读取 GitHub 数据和提交周报。

工作流先构建看板，然后归档 Markdown 并在同一次运行中部署 Pages。再次运行同一期会保留原文。可以在 Actions 页面手动启动，也可以填写带时区的历史截止时间来补一段尚未收录的区间。[运行记录](https://github.com/Burceoneo12345/llm-systems-weekly/actions/workflows/pages.yml)

论文优先使用 arXiv 的版本元数据。对本期索引更新、提交时间早于上期截止的版本，在七天回看范围内单独注明「索引补录」。主接口不可用时可通过 Hugging Face Daily Papers 发现候选，再核对 arXiv 原文，并在当期说明覆盖范围。修订版的摘要概括当期可见的研究内容。

论文或 GitHub 有一方临时不可用时，当期仍可发布另一方已核实的进展，并记录缺口，下次补查。两方都不可用时保留上期截止时间。

## 手动编写

在 `reports/` 下新增 `YYYY-MM-DD.md`，使用北京时间截止日期命名。一级标题下写覆盖区间。每个二级标题下的一行代码标签依次表示日期、来源、状态和一个或多个主题。第一条自动成为本期首读，实验表格与补充源码可在看板展开。「本周跟进」收录验证问题。[编排示例](reports/2026-11-26.md)

使用 Node.js 24 或更高版本在本地构建。

```sh
npm ci
npm run build
```

预览目录为 `_site/`。推送到 `main` 后，GitHub Actions 会构建并部署 GitHub Pages。
