# 周报提示词

由 Codex 为做昇腾 NPU 研发的工程师撰写中文《大模型系统周报》。周一、周五北京时间 09:00 截稿，每期保留固定链接。手动出刊和定时出刊都读取仓库主分支最新版 `PROMPT.md`。论文回看近一年，源码与版本发布从上期截止时间接续。

## 追踪范围

- **训练、强化学习与推理。** 跟踪分布式并行、Attention、MoE、显存、吞吐、RL rollout、策略更新和训推权重同步。优先选择能解释瓶颈、改变工程选择或提供可复现实验的工作。
- **低精度与 4-bit RL。** 关注 FP8、FP6、FP4、INT4 等数值格式。写清低精度用在 rollout、奖励评分、策略更新还是权重传输，作用在权重、激活、梯度、优化器状态还是 KV cache。记录保留高精度的部分，以及公开的 reward、收敛、精度和吞吐数据。区分伪量化与原生低精度 kernel、权重存储位宽与实际计算位宽、单算子收益与端到端收益、短程数值一致性与长期收敛。
- **NVIDIA、AMD 与开源实现。** 从 NVIDIA、AMD 的官方发布，以及 Megatron-LM、Transformer Engine、cuDNN Frontend、Model Optimizer、NeMo RL、Dynamo、TensorRT-LLM、ROCm Libraries、Composable Kernel、ROCm/aiter、vLLM、SGLang、FlashInfer、FlashAttention、verl 和 OpenRLHF 等仓库的 PR、commit 和 release 中寻找实质变化。
- **量化工具链与行业通用仓库。** 同时检索 GPTQModel、bitsandbytes、AutoRound、PyTorch、TorchAO、Hugging Face Transformers、TRL、Triton 和 DeepSpeed 的已合并 PR。一个 PR 可以独立成为首读，整期也可以只收录代码。说明本次合入改变了哪条执行路径、影响哪些配置，给出合并记录和对应提交的源码。只有原作者报告了有基线的测试时才引用性能收益。
- **尚在评审的工作。** 标题明确涉及低精度格式、权重同步或训推一致性的未合并 PR，可以作为动向收录，每期最多一条并放在末尾。写明它仍是提案，不能当作已合入或已可用；同一工作已经合并或发布时，优先报道已落地的那一部分。

## 检索方法

分论文、源码、行业三路找，再汇总排序。社交媒体和媒体报道只提供线索，入选条目必须回到论文、代码或官方原文核验。

**论文。** 以本期截止日向前回看一年。A 类按中国计算机学会（CCF）目录认定。优先寻找与周报主题直接相关的 A 类会议主会长文和 A 类期刊论文，按正式发表日期判断是否在窗口内，注明会刊名称并附论文集、期刊原文或 DOI。同一档内按工程价值排序，轮换发表来源。其余名额可收录窗口内其他会刊论文及 arXiv 预印本，预印本按公开提交或修订时间判断。[中国计算机学会推荐国际学术会议和期刊目录](https://www.ccf.org.cn/Academic_Evaluation/By_category/)

用 OpenAlex 按正式发表来源查找论文，优先检索下列与大模型系统相关的会刊。Workshop、Findings 等按各自的发表来源判断。

- A 类会议主会包括 [OSDI](https://openalex.org/S4306420647)、[SOSP](https://openalex.org/S7407089168)、[EuroSys](https://openalex.org/S4306418317)、[ASPLOS](https://openalex.org/S7407086669)、[ISCA](https://openalex.org/S4393916863)、[HPCA](https://openalex.org/S4210184388)、[MICRO](https://openalex.org/S4210171338)、[PPoPP](https://openalex.org/S4306417578)、[NeurIPS](https://openalex.org/S4363606243)、[ICML](https://openalex.org/S4306419644)、[ACL](https://openalex.org/S4393915740)。
- A 类期刊包括 [TPDS](https://openalex.org/S97130795)、[TC](https://openalex.org/S157670870)、[TOCS](https://openalex.org/S193109227)、[TACO](https://openalex.org/S26056741)、[JMLR](https://openalex.org/S118988714)。

在 arXiv 按主题检索近一年的候选，并用 OAI-PMH 追踪本期的新增和修订。扫描 cs.CL、cs.LG、cs.DC、cs.AR、cs.AI、cs.PF、cs.PL、cs.NE 和 stat.ML。标题或摘要需要同时命中模型词与系统词，或同时命中厂商与 kernel 词。本期批量接口不可用时，通过 Hugging Face Daily Papers 补查并核对 arXiv 原文。

**源码。** 按合并时间从上游仓库收集已合并 PR，按标题预筛后读取正文排序。对创建于检索区间、标题含低精度或 RL 训练关键词的未合并 PR，每个仓库至多保留一条。读取全部 release。[上游仓库列表](https://github.com/Burceoneo12345/llm-systems-weekly/blob/main/scripts/upstream.py)

**行业。** NVIDIA、AMD 的变化以官方仓库的合并记录和 release 为准，官方博客和文档只作为定位线索。新增仓库前先确认它仍在活跃开发，且有与主题相关的合并记录。

关键词按「数值格式 × 训练或推理环节 × 硬件生态」组合检索，英文为主：

| 维度 | 关键词 |
| --- | --- |
| 数值格式 | FP8、FP6、NVFP4、MXFP4、MXFP8、INT4、INT8、NF4、W4A4、W4A8、W4A16、A8W4、microscaling、block scaling、QAT、fake quant |
| 训练环节 | low precision training、QAT、gradient quantization、optimizer state、master weight、weight sync、train-inference mismatch、rollout、GRPO、DAPO、GSPO、policy update、reward model quantization |
| 推理环节 | KV cache quantization、MoE quantization、grouped GEMM、W4A16、W4A8、speculative decoding、continuous batching、prefill、decode |
| 硬件与生态 | Blackwell、Rubin、GB200、B200、B300、Hopper、H100、H20、CUDA、TensorRT、cuDNN、CUTLASS、CuTe DSL、ROCm、hipBLASLt、Instinct、MI300、MI355、MI450、gfx950、gfx1250 |

PR 取合并时间，未合并 PR 取创建时间，release 取发布时间。论文可以早于上期截止日，列出原始日期，方便读者判断工作发表了多久。对照历期链接去重，同一论文有预印本和正式版时优先引用正式版。汇总后按下文的篇数筛选，同一仓库的条目轮换入选。

## 如何筛选和写作

1. 每期 30 条，代码与论文各 15 条，按工程价值排序。第一条说明为何值得先读。某一方候选不足时，先补该方排名靠后的候选，再用另一方补足数量，并在检索区间下写明。可核实的进展确实不足时有多少写多少。
2. 核对论文的会刊、发表或预印本版本日期，以及 PR 合并时间和发布状态。回顾较早的论文时，说明其结果对当前工程选择的价值。把同一项工作的论文、实现、版本发布归在一起。以前报道过的项目，只在有新证据时续写。
3. 每条交代技术变化、影响范围和证据边界，附论文或上游 PR 的直链。涉及源码时，尽量链接到固定提交中的文件和函数。
4. 引用指标时同时给出模型、硬件、对比基线、测试规模和测量环节。说明单算子时延、rollout 吞吐、端到端训练时间或模型效果中实际测了哪一项。原文未给出的数据标明待测。
5. 低精度条目写明位宽作用在权重、激活、梯度、优化器状态还是 KV cache，发生在 rollout、奖励评分、策略更新还是权重传输，以及哪些部分保留高精度。
6. 结尾提出 1–2 个可验证的问题，具体到可以阅读的代码位置、可固定的变量或可观察的指标。涉及昇腾的推断写成待验证假设。

## 出刊与归档

1. 确定本期应截止的北京时间，检查 `reports/YYYY-MM-DD.md` 的覆盖区间。已有同日归档就返回该期；遇到漏期，按应截止的先后顺序补查。延迟运行仍使用该期原定的截止时间。
2. Codex 按上文检索论文、上游源码和行业进展。可用 `python3 scripts/digest.py collect <候选.json> --until <含时区的截止时间>` 收集候选，再打开一手资料核验、补查并决定首读。论文或 GitHub 有一路暂缺时，注明缺口，候选 JSON 的 `pending` 非空时，在覆盖区间后用 HTML 注释保存该对象，供下期接续。例如 `<!-- pending-sources {"papers":"2026-11-26T14:55:00+08:00"} -->`。两路都未完成时，保留上期截止时间。
3. Codex 直接撰写 `reports/YYYY-MM-DD.md`。一级标题后单列“覆盖 YYYY-MM-DD HH:MM 至 YYYY-MM-DD HH:MM（北京时间）”。每条用二级标题，下一段用行内代码依次标明事件日期、来源、状态和主题，正文后单列一手链接。第一条是首读，末尾用“本周跟进”列验证问题。完成检索后若没有可核实的新条目，只在覆盖区间下说明结果。
4. 每个有头条的新期次都要用 Codex 内置 ChatGPT Image（imagegen）生成一张新封面。从论文图表或固定提交中选一个可核对的机制，画清研究对象、输入和发生变化的步骤，让读者能认出具体工作。需要对照时，在两处使用相同的编号和位置，画出变化的量。图内只放必要的短标签，在首读正文后可用 `> 图注：…` 解释示意内容。用 `node build.mjs --missing-covers` 取得预期路径，把工具返回的实际图片转为 WebP，归档到对应的 `assets/covers/` 文件。重复构建复用已归档封面。
5. 本地运行单测和静态构建，打开首页和 `weeks/YYYY-MM-DD/` 核对条数、来源、覆盖区间及两页显示的当期封面。在桌面和手机宽度下对照一手原文检查封面，确保关键标签和连接完整可读。请求本地预览时交付本机页面和图片。发布时将本期 Markdown 和封面一起推送至 `main`，由 GitHub Pages 工作流校验、构建和部署，再核对线上固定链接。

[GitHub Pages 看板](https://burceoneo12345.github.io/llm-systems-weekly/) · [源码仓库](https://github.com/Burceoneo12345/llm-systems-weekly)
