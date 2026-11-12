# MiniMax H3 与生成模型后训练论文索引

先列 MiniMax H3 少步蒸馏与恢复路线，再回到后训练基础；配套 [index.html](index.html) 的原始文献。**★ = 建议先读**，其余按需查阅。
arXiv 编号写在每条后面，直接在 `arxiv.org/abs/<编号>` 打开即可。

---

## 一、MiniMax H3：后训练与少步蒸馏

本地代码、二采路径和 Agnes 配方细节见 [h3.md](h3.md)。阅读时请区分论文公开结果、本地有代码/配置、线上已验证权重，不能互相替代。

| 论文/方法 | 关注点 | H3 相关性 |
|---|---|---|
| [DMD 原论文](https://arxiv.org/abs/2311.18828) | teacher/fake-score 分布匹配与轨迹回归稳定项 | H3 本地 DMD 的基础参照，具体 trainer 配方以本地代码为准 |
| [DMD2](https://arxiv.org/abs/2405.14867) | 分布匹配蒸馏与对抗训练技巧 | 理解 DMD 家族；本地 H3 trainer 有 DMD，不应直接叫完整 DMD2 |
| [SGMD](https://arxiv.org/abs/2605.30116) | Fisher score matching 与 non-saturating 目标 | 仓库内有 H3 4-NFE SGMD trainer/config |
| [rCM](https://arxiv.org/abs/2510.08431) | rectified consistency matching | 本地有 dCM→DMD→可选 rCM 研究配置，无 checkpoint |
| [PDMD](https://arxiv.org/abs/2609.35768) / [代码](https://github.com/ZeamoxWang/pdmd) | progressive DMD | 公开 H3 2/4-step 结果；不代表此目录已有权重 |
| [DMAD](https://arxiv.org/abs/2610.02188) / [项目](https://yzmblog.github.io/projects/DMAD/) | 对抗式分布匹配 few-step 蒸馏 | 公开 H3 4-step 结果 |
| [PTD](https://arxiv.org/abs/2610.11498) | 轨迹蒸馏 | 外部论文/项目状态 |
| [VA-TDM](https://arxiv.org/abs/2611.06796) | 多视角 teacher 蒸馏 | 2026-11 论文结果；本地无对应部署权重证据 |
| [SeedVR](https://arxiv.org/abs/2501.01320) / [SeedVR2](https://arxiv.org/abs/2506.05301) | 成片视频恢复/增强 | 独立后处理模型，不减少 H3 采样 NFE |

## 二、基础 RL：先把 PPO 搞明白

| 论文 | 一句话 | arXiv |
|---|---|---|
| ★ **Proximal Policy Optimization (PPO)** | 引入 clip 的重要性比率目标，成为后续几乎所有 RLHF 的底座 | 1707.06347 |
| ★ **DPO: Direct Preference Optimization** | 跳过奖励模型与在线采样，直接拿偏好对做监督学习；理解「为什么还要在线 RL」的对照组 | 2305.18290 |
| **RLOO: Back to Basics** | 用「留一法」的组均值替代 critic，是 GRPO 思想的另一条独立来源 | 2402.14740 |
| ★ **DeepSeekMath（提出 GRPO）** | 组采样 + 组内标准化优势 + KL 约束，去掉价值网络；GRPO 的原始出处 | 2402.03300 |

**读法**：PPO 只需读懂 clip 目标那一节；DeepSeekMath 的第 4.2 节（Outcome Supervision RL）就是 GRPO 的全部。

---

## 三、扩散模型做 RL 的起点

| 论文 | 一句话 | arXiv |
|---|---|---|
| ★ **DDPO** | 把去噪过程当成多步 MDP，用策略梯度直接优化扩散采样器 | 2305.13301 |
| ★ **DPOK** | DDPO 的 KL 正则版本，训练稳定性明显更好 | 2305.16381 |
| **Diffusion-DPO** | 把 DPO 搬到扩散模型，用「胜/负」图像对做离线偏好优化 | 2311.12908 |

**注意**：这三篇都建立在「DDPM 式随机采样」之上，每步本来就有噪声注入，所以 log-prob 天然可算。Flow / Rectified Flow 模型没有这个前提，这正是第三节要解决的问题。

---

## 四、Flow-GRPO 与视频 RL

| 论文 | 一句话 | arXiv |
|---|---|---|
| ★ **Flow-GRPO** | ODE→SDE 等价转换 + Denoising Reduction + 组归一化，首次让 GRPO 在流匹配模型上跑通 | 2505.05470 |
| ★ **DanceGRPO** | 统一扩散/整流流的 SDE 表述，覆盖文生图、文生视频、图像编辑；工程最完整 | 2505.07818 |
| **Flow-GRPO-Fast** | 单步分叉 + 后半段共享轨迹，把采样成本压下来 | 2505.05470（同族后续版本） |

**核心公式**（两篇一致）：

```
x_{t-1} = x_t - v_θ(x_t, t)·Δt + σ_t·√Δt·ε ,  ε ~ N(0, I)
```

σ=0 时退化为原来的确定性 ODE，采样分布不变；σ>0 时获得探索能力与可计算的转移概率。

---

## 五、稳定性与替代范式（2025 下半年 — 2026）

| 论文 | 一句话 | arXiv |
|---|---|---|
| **MixGRPO** | ODE 段与 SDE 段混合，配合滑动窗口，减少无效随机步 | 2507.21802 |
| **BranchGRPO** | 树状分叉共享前缀，把「组采样」的算力开销摊薄 | 2509.06040 |
| **TempFlow-GRPO** | 按时间步重要性加权 + 过程奖励，缓解信用分配 | 2508.04324 |
| **Flash-GRPO** | 同一时间步内分组，约 6× 加速 | 2605.15980 |
| ★ **GRPO-Guard** | 指出重要性比率系统性偏小导致 clip 失效，给出 RatioNorm + 梯度重加权 | 2510.22319 |
| ★ **DiffusionNFT** | 前向加噪构造正负样本对，不需要 log-prob，可套任意黑盒采样器 | 2509.16117 |
| **CPS (Coefficients-Preserving Sampling)** | 噪声强度 noise_level≈0.8 的工程调参经验，几乎零成本提升稳定性 | 2509.05952 |
| **DiffusionART** | 面向自回归视频生成的后训练框架 | 2610.12572 |
| **Wan-R1** | 视频生成模型的 RL 复现与消融，超参参考价值高 | 2603.27866 |
| **A Post-Training Framework for Video Generation** | 系统性梳理视频 RL 的数据、奖励与评测 | 2604.25427 |

**读法**：先读 GRPO-Guard（解释你训练到后期为什么会崩），再读 DiffusionNFT（如果你用的采样器拿不到 log-prob，它是唯一出路）。

---

## 六、奖励模型：打分器怎么选

| 论文 | 用途 | arXiv |
|---|---|---|
| ★ **PickScore** | 文生图的人类偏好代理分，最常用的 baseline | 2305.01569 |
| **ImageReward** | 另一个通用图像偏好模型，对文字渲染更敏感 | 2304.05977 |
| **HPSv2** | 人类偏好集合训练，覆盖面广 | 2306.09341 |
| **VisionReward** | 多维度可解释打分，适合做细粒度诊断 | 2412.21059 |
| **VideoScore** | 视频质量与运动一致性打分 | 2406.15252 |
| ★ **CLAP** | 音频—文本对齐分，音视频 RL 的音频分支主力 | 2206.04769 |
| ★ **ImageBind** | 跨模态（音/视/文）共享嵌入，用来算音画同步 | 2305.05665 |

**原则**：奖励模型只当裁判，不要同时参与训练；至少留一个「没被优化的」金标指标做验收，否则分不清是真提升还是 reward hacking。

---

## 七、开源项目

| 项目 | 说明 |
|---|---|
| [flow_grpo](https://github.com/yifan123/flow_grpo) | Flow-GRPO 官方实现，SD3.5 / Flux + PickScore / OCR，最适合入门 |
| [DanceGRPO](https://github.com/XueZeyue/DanceGRPO) | 官方实现，覆盖图像 / 视频 / I2V，脚本最全 |
| [trl](https://github.com/huggingface/trl) | HuggingFace 的 RL 工具箱，GRPO / DPO / PPO 都有，适合改小模型验证想法 |
| [verl](https://github.com/volcengine/verl) | 面向 LLM 的大规模 RL 框架，支持多机与多种 rollout 后端 |
| [verl-omni](https://github.com/volcengine/verl) | verl 的全模态分支，音视频 RL 的工程底座（H3 路线 B 用到） |
| [miles_diffusion](https://github.com/yuanshi/miles_diffusion) | 扩散模型 RL 训练脚本集合，H3 路线 A 的起点 |
| [FastVideo](https://github.com/hao-ai-lab/FastVideo) | 视频生成推理/训练加速，降低 rollout 成本 |

---

## 八、推荐阅读顺序

1. **PPO**（只看 clip 目标）→ 知道「比率 + 裁剪」是什么。
2. **DeepSeekMath 第 4.2 节** → GRPO 的全部创新，不到 3 页。
3. **Flow-GRPO** → 重点看 ODE→SDE 的推导与 Denoising Reduction 的动机。
4. **DanceGRPO** → 看它如何把上面这套统一到视频与 I2V，工程细节最多。
5. **GRPO-Guard** → 训练跑不长时回来读。
6. **DiffusionNFT** → 拿不到 log-prob 时的替代方案。
7. 其余按需：视频看 Wan-R1 / TempFlow，音视频看 H3 相关仓库 README。

---

*本清单为阅读笔记，标题与结论以原论文为准；arXiv 编号用于定位，若版本更新请以最新 v 号为准。*
