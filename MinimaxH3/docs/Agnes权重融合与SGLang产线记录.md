# Agnes H3 权重融合与 SGLang 归档记录

整理日期：2026-11-10。依据本地 merge manifest、生成日志、SGLang Git 状态和版本文件整理。具体生产目录、服务器挂载点和本机运行路径不公开；归档中未包含融合权重。

## 摘要

- 最新可审计的 Agnes 配方有 FL2VA 与 REF2VA 两套。两者都是对应 MiniMax-H3 base 加多个 LoRA delta 后导出为 FP8 E4M3；不是把完整模型按百分比分配。
- FL2VA：MiniMax-H3 FL2VA base + OpenVDN stage-dmd-step-250 turbo adapter（mode=back_0.7）+ Combat V2（global 0.6）+ Realism People（global 0.3），产物名 Agnes-2.6-1016-FL2VA-FP8。
- REF2VA：官方 MiniMax-H3 REF2VA BF16 base + Larryvrh Turbo V4 Step600 EMA（flat 1.0）+ Combat V2（global 0.6）+ Realism People（global 0.3），产物名 Agnes-2.6-1018-REF2VA-FP8；manifest 标记 1018-v5-turbo-flat1.0。
- SGLang 归档的 e2e 启动在 Transformers qwen3_asr config 重复注册时报错退出。因此这里记录的是最新可审计 recipe，不代表当前线上实例健康或正在加载这些权重。

## REF2VA 的层级 scale

| 层范围 | Combat V2 | Realism People |
| --- | ---: | ---: |
| Token Refiner | 1.0 | 1.0 |
| DiT blocks 0–4 | 0.7 | 0.7 |
| DiT blocks 5–24 | 1.0 | 1.0 |
| DiT blocks 25–29 | 0.6 | 0.6 |
| DiT blocks 30–34 | 0.4 | 0.4 |
| DiT blocks 35–39 | 0.1 | 0.1 |
| DiT blocks 40–49 | 0.0 | 0.0 |

manifest 同时记录 global scale 与 layer schedule。现有记录不足以确认融合器如何组合这两项，因此不要自行相乘并称为实际有效系数。FL2VA 1016 对 DMD adapter 只记录 back_0.7，没有同等完整的逐层表。

## 融合语义与导出

LoRA 是按各自 scale 加到 base 权重上的 delta，不是把 base 与 adapter 当成总和为 100% 的完整 checkpoint 加权平均。FL2VA 配方只记录 OpenVDN turbo adapter，没有 linear branch/default adapter，因此不等同完整 VDN-H3；FL2VA 本身支持 T2V、单参考帧与首尾双参考模式。

REF2VA 记录的导出路径为 FP32 融合、QKV 从 [q_all;k_all;v_all] 转成逐头交错 [q,k,v]、再转 BF16，随后以 128×128 block 做 FP8 E4M3 量化。记录中敏感输出/投影层不量化。FL2VA 1016 的导出资料不完整，不能将 REF2VA 的步骤直接套用到它。

## 来源与许可

- [MiniMax-H3 官方模型页](https://huggingface.co/MiniMaxAI/MiniMax-H3)
- [OpenVDN H3 DMD turbo adapter](https://huggingface.co/OpenVDN/vdn-minimax-h3/tree/main/stage-dmd-step-250/adapters/turbo)
- [Larryvrh Turbo V4](https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora)
- [Combat V2](https://huggingface.co/JOKER141/MiniMax-H3-Combat-Base-V2)
- [Realism People](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA)

H3 及部分 adapter 页面使用 MiniMax H3 Community License；各 adapter 的许可分别核对。权重没有随本目录复制，recipe 文档不授予权重再分发权。

## SGLang 归档状态

本地归档记录的 SGLang fork 是 dev build，记录含 H3 sigma/time-request 调度改造。VAE 多 GPU chunk decode patch 只作为未跟踪文件出现，Git 工作树证据不能确认它已应用。唯一归档的 e2e 日志以 qwen3_asr Transformers config 重复注册错误结束。需要判定当前生产服务时，应检查当前模型清单、成功请求日志或运行容器版本。
