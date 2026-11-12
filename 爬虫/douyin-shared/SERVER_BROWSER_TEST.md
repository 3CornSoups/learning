# 服务器浏览器与关机验收（进行中）

测试根目录：`./douyin-current-snapshot`。
代码：`releases/browser-20261110a`。
浏览器环境：`browser installation path`，与原 `shared system environment` 隔离。预演发现共享环境会升级 NumPy、降级 Redis，故没有向共享环境同步依赖。
依赖记录在 pyproject.toml 的 `remote_browser` 和 `server` 组，以及 uv.lock。

## 登录方式

用户不能给服务器浏览器扫码。本次使用本机 `export_auth.py` 导出已有抖音 Cookie、localStorage、IndexedDB，再通过 SSH 加密传到服务器私有 `auth/server_state.json`，导入服务器独立的 `server_profile`。
凭据值不会写入日志。服务器曾返回有效的“当前用户资料”响应；程序只记录认证是否有效和身份散列。
后续浏览器启动不再依赖本机文件，会复用服务器持久化配置。如果出现重新扫码要求，需要停下告知用户，不自行更换登录途径。

```powershell
.\.venv\Scripts\python.exe .\export_auth.py --output .\auth\server_state.json
```

## 后台会话

四个测试会话均在服务器 tmux 中，独立于 SSH：

- `czk_dy_display`：Xvfb `:88`，使用 Xauthority，不开放 X11 TCP。
- `czk_dy_vnc`：x11vnc，密码认证，仅监听 127.0.0.1/::1 的 5908。
- `czk_dy_web`：noVNC/websockify，仅监听 127.0.0.1:6088。
- `czk_dy_crawl`：常驻浏览器的持续采集任务，最多下载 24 条不超过 180 秒、30 MB 的视频，每条之间等待 90 秒；失败时保留报告并停止。旧版逐轮重启浏览器的诊断记录仍保留，不作为连续采集的验收证据。

需要临时查看桌面时，在本机建立 SSH 隧道：

```powershell
ssh -N -L 16088:127.0.0.1:6088 -o IdentitiesOnly=yes -i "$env:USERPROFILE\.ssh\id_ed25519_video_2" -p 32430 root@117.186.102.78
```

再打开 `http://127.0.0.1:16088/vnc.html`。VNC 临时密码位于服务器 `auth/vnc-password.txt`，仅通过本人 SSH 会话读取，不将其加入仓库或公共文档。关闭本机隧道不会终止服务器任务。

## 运行证据与限制

- `runs/server_continuous/每轮时间/report.json`：采集进程 PID/PPID、更新时间、逐条下载时间和状态。
- `reports/continuous.log`：持续采集过程与人工验证提示。
- `runs/server_browser/每轮时间/report.json`：来源接口、认证状态、发现作品和真实下载结果。
- `downloads/server_browser/`：视频及大小、MD5、轨道校验结果。
- `reports/poweroff_baseline.json`：关机前基线（准备实际关机前生成）。

推荐采集使用页面支持的方向键翻页，首次聚焦后避免重复抢焦点；先前重复导航和滚轮问题的尝试日志仍保留。服务器播放入口还返回过 `v5-hl-mly-ov.zjcdn.com`，已在保持 HTTPS 和原文件校验的前提下，只增加该精确主机。

当前已完成服务器首次独立发现和下载，尚未完成本机关机期间的最终验收。不能把 tmux 未连接或 SSH 已断开直接当作本机实际关机的证明。

最终流程：先确认常驻浏览器至少两条新视频下载成功，生成服务器时间和文件/轮次基线；用户关机约 10 分钟后重新开机回复；再检查该时间窗口内是否由同一服务器任务继续发现并下载新作品。若中途遇到验证码、登录失效或其他失败，应如实记录，不能认定持续采集通过。

验收结束后按会话名和 PID 核对本次进程，安全停止测试服务，避免误杀服务器上的其他 tmux 会话和模型任务。浏览器程序与下载缓存均在 `~/projects`，系统仅安装必要的显示、字体和 VNC 组件。
