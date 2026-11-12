# MiniMax H3：后训练、少步蒸馏与采样加速

本专题整合 H3 偏好优化、DMD/SGMD 少步蒸馏、二阶段采样、SeedVR 视频恢复，以及 2026-11-10 可审计的 Agnes FL2VA/REF2VA 权重配方。内容区分论文结论、本地代码/配置和线上运行证据。

## 阅读顺序

1. [h3.md](h3.md)：先看路线地图，随后读 DMD 训练过程、家族差异、二采和权重配方。
2. [index.html](index.html)：第 11–13 节是 H3 重点，第 1–10 节补 RL/扩散基础。
3. [二阶段采样专题](docs/二阶段采样技术科普.md)：比较 Full-X0、Mid-trajectory、插值、像素 i2i 和恢复模型。
4. [Agnes 权重融合记录](docs/Agnes权重融合与SGLang产线记录.md)：查看 base、LoRA scale、REF2VA 分层、QKV/FP8 导出及证据边界。
5. [论文索引](papers.md)：已将 H3 蒸馏和恢复文献排在基础 RL 之前。

## 方法结论速览

| 问题 | 路线 | 当前材料能证明什么 |
| --- | --- | --- |
| 少步生成 | H3 DMD、SGMD；外部 PDMD、DMAD、PTD、VA-TDM | DMD/SGMD 有选定源码与配置；研究路线不等于可部署 checkpoint |
| 提升高清生成效率 | Full-X0 / Mid-trajectory 二采 | 有参数/入口记录；总耗时取决于低清步、高清步和 upscaler |
| 成片后变清楚 | SeedVR / SeedVR2、SwiftVR-family | 独立视频恢复；增加后处理耗时，可能推断并改写纹理 |
| 产线 adapter 组合 | Agnes FL2VA / REF2VA | 有截至 2026-11-10 的可审计配方；缺少证明当前在线实例成功运行的日志 |

## 代码快照与边界

- code/dmd/：H3 DMD trainer、数学辅助代码和 4-NFE LoRA YAML。
- code/sgmd/：H3 SGMD trainer、DMD trainer 公用文件和 phase2 YAML。
- 这是局部源码快照，不是完整训练仓库；没有权重、prompt cache、checkpoint、W&B 运行日志或 SGLang 服务器部署包。
- LightX2V 许可证副本位于 code/LICENSE-LightX2V.txt。SGMD 派生快照没有保留上游仓库元数据，继续分发或商用前需核对其来源许可。
- 配置中的机器路径已替换为环境变量或相对输出目录；训练仍需自行配置模型、数据、依赖和硬件。

## 证据标签

- 论文报告：只适用于论文中的模型和评测设置。
- 本地代码/配置：说明实现或实验方案存在，不证明训练成功或质量达标。
- 可审计的权重 recipe：说明 merge manifest 能还原的 base、LoRA 与导出步骤，不等于当前线上状态。
- 在线验证：需要成功的服务启动、请求和模型清单；当前归档的 SGLang e2e 日志在依赖注册阶段退出。
