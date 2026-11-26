# 周报提示词

每周一、周五为做昇腾 NPU 研发的工程师写一期中文《大模型系统周报》，发布到同一个 GitHub Pages 看板，并为该期保留固定链接。每次从上期截止时间接续，使用北京时间注明检索区间。

## 追踪范围

- **训练、强化学习与推理。** 跟踪分布式并行、Attention、MoE、显存、吞吐、RL rollout、策略更新和训推权重同步。优先选择能解释瓶颈、改变工程选择或提供可复现实验的工作。
- **低精度与 4-bit RL。** 关注 FP8、FP6、FP4、INT4 等数值格式。写清低精度用在 rollout、奖励评分、策略更新还是权重传输，作用在权重、激活、梯度、优化器状态还是 KV cache。记录保留高精度的部分，以及公开的 reward、收敛、精度和吞吐数据。区分伪量化与原生低精度 kernel、权重存储位宽与实际计算位宽、单算子收益与端到端收益、短程数值一致性与长期收敛。
- **NVIDIA、AMD 与开源实现。** 从 NVIDIA、AMD 的官方发布，以及 Megatron-LM、Transformer Engine、cuDNN Frontend、Model Optimizer、NeMo RL、Dynamo、TensorRT-LLM、ROCm Libraries、Composable Kernel、ROCm/aiter、vLLM、SGLang、FlashInfer、FlashAttention、verl 和 OpenRLHF 等仓库的 PR、commit 和 release 中寻找实质变化。
- **量化工具链与行业通用仓库。** 同时检索 GPTQModel、bitsandbytes、AutoRound、PyTorch、TorchAO、Hugging Face Transformers、TRL、Triton 和 DeepSpeed 的已合并 PR。一个 PR 可以独立成为首读，整期也可以只收录代码。说明本次合入改变了哪条执行路径、影响哪些配置，给出合并记录和对应提交的源码。只有原作者报告了有基线的测试时才引用性能收益。
- **尚在评审的工作。** 标题明确涉及低精度格式、权重同步或训推一致性的未合并 PR，可以作为动向收录，每期最多一条并放在末尾。写明它仍是提案，不能当作已合入或已可用；同一工作已经合并或发布时，优先报道已落地的那一部分。

## 检索方法

分论文、源码、行业三路找，再汇总排序。社交媒体和媒体报道只提供线索，入选条目必须回到论文、代码或官方原文核验。

**论文。** 用 arXiv OAI-PMH 按版本元数据扫描 cs.CL、cs.LG、cs.DC、cs.AR、cs.AI、cs.PF、cs.PL、cs.NE 和 stat.ML。标题或摘要需要同时命中模型词与系统词，或同时命中厂商与 kernel 词。主接口不可用时改用 Hugging Face Daily Papers 发现候选，再逐篇核对 arXiv 原文，并在当期说明覆盖范围。

**源码。** 对 [scripts/upstream.py](https://github.com/Burceoneo12345/llm-systems-weekly/blob/main/scripts/upstream.py) 列出的 25 个仓库：按合并时间取已合并 PR，按标题预筛后读取正文排序；对创建于检索区间、标题含低精度或 RL 训练关键词的未合并 PR，每个仓库至多保留一条；release 全部读取。

**行业。** NVIDIA、AMD 的变化以官方仓库的合并记录和 release 为准，官方博客和文档只作为定位线索。新增仓库前先确认它仍在活跃开发，且有与主题相关的合并记录。

关键词按「数值格式 × 训练或推理环节 × 硬件生态」组合检索，英文为主：

| 维度 | 关键词 |
| --- | --- |
| 数值格式 | FP8、FP6、NVFP4、MXFP4、MXFP8、INT4、INT8、NF4、W4A4、W4A8、W4A16、A8W4、microscaling、block scaling、QAT、fake quant |
| 训练环节 | low precision training、QAT、gradient quantization、optimizer state、master weight、weight sync、train-inference mismatch、rollout、GRPO、DAPO、GSPO、policy update、reward model quantization |
| 推理环节 | KV cache quantization、MoE quantization、grouped GEMM、W4A16、W4A8、speculative decoding、continuous batching、prefill、decode |
| 硬件与生态 | Blackwell、Rubin、GB200、B200、B300、Hopper、H100、H20、CUDA、TensorRT、cuDNN、CUTLASS、CuTe DSL、ROCm、hipBLASLt、Instinct、MI300、MI355、MI450、gfx950、gfx1250 |

用事件日期而不是搜索引擎的「最近一周」过滤：论文取提交或修订时间，PR 取合并时间，未合并 PR 取创建时间，release 取发布时间。每期从上期截止时间接续；论文索引滞后于提交时，在七天回看内单独标注「索引补录」。已报道过的 URL 不再入选，同一工作的论文、实现和版本发布合并为一条。汇总后代码与论文分别排序，各取前五组成一期；同一仓库的条目轮换入选，避免一个繁忙仓库占满整期。

## 如何筛选和写作

1. 每期十条，代码与论文各五条，按工程价值排序。第一条说明为何值得先读。某一方候选不足时，先补该方排名靠后的候选，再用另一方补足数量，并在检索区间下写明；可核实的进展确实不足时有多少写多少。
2. 核对论文提交或修订时间、PR 合并时间及发布状态。把同一项工作的论文、实现、版本发布归在一起，交代本期新增的内容。以前报道过的项目，只在有新证据时续写。
3. 每条交代技术变化、影响范围和证据边界，附论文或上游 PR 的直链。涉及源码时，尽量链接到固定提交中的文件和函数。
4. 引用指标时同时给出模型、硬件、对比基线、测试规模和测量环节。说明单算子时延、rollout 吞吐、端到端训练时间或模型效果中实际测了哪一项。原文未给出的数据标明待测。
5. 低精度条目写明位宽作用在权重、激活、梯度、优化器状态还是 KV cache，发生在 rollout、奖励评分、策略更新还是权重传输，以及哪些部分保留高精度。
6. 结尾提出 1–2 个可验证的问题，具体到可以阅读的代码位置、可固定的变量或可观察的指标。涉及昇腾的推断写成待验证假设。

## 放到看板

GitHub Actions 在北京时间周一、周五 09:00 启动，在托管运行器上完成论文和仓库检索、中文摘要、归档与 Pages 发布。在仓库的 `reports/` 下按本期截止日期新增一篇 `YYYY-MM-DD.md`。一条进展对应一个二级标题，标题下依次用行内代码标明事件日期、来源、状态和主题。把首读放在第一条，末尾用「本周跟进」列验证问题。

每次拉取并形成有头条的新一期时，根据头条的标题和正文重新生成一张专属封面。画面体现该条进展具体在比较什么、传输了什么，或改变了哪一步计算。首页和本期固定链接使用同一张图，封面随该期归档。

发布前核对一手链接并执行 `npm ci`、`npm run build`。提交本期 Markdown 到 `main` 后检查 Pages 部署及本期链接。首页会展示最新一期，历史归档会保留每期原文。若检索完成且当周没有可核实的新进展，在覆盖区间下写明结果即可。

## Codex 自动化回查

读取 `main` 上最近一期周报，对照 `.github/workflows/pages.yml` 的北京时间排期、运行记录和 `reports/` 归档，核对上次检查以来到期的各期。已有归档就复用。已有任务排队或运行时，跟进到部署完成。遇临时故障，重试原运行。确认漏跑、该期区间尚未覆盖且没有检索排队或运行时，在 `main` 上将该期应截止的北京时间传入 `cutoff`，触发同一工作流补跑。

打开每个新发布期次的 `weeks/YYYY-MM-DD/` 固定链接并核对覆盖区间。有头条时，检查它的一手来源和本期专属封面。在当前对话给出固定链接，用一句话说明最值得读的一条影响了哪项工程选择。遇到来源缺口或本期没有可核实的新进展时，按归档说明。

[GitHub Pages 看板](https://burceoneo12345.github.io/llm-systems-weekly/) · [源码仓库](https://github.com/Burceoneo12345/llm-systems-weekly)
