# Cookie 获取与更新

1. 在本机 Edge 或 Chrome 登录自己的抖音账号，打开一个可正常播放的公开视频。
2. 按 F12，打开 Network（网络），保持录制，刷新并播放视频。过滤 `aweme`，选发往 `www.douyin.com` 的详情或投稿接口请求。不要选择视频 CDN 请求。
3. 打开 Headers → Request Headers，复制 `Cookie` 的完整值。只复制值，不要复制 `Set-Cookie`、整段 cURL、浏览器 Cookie 表格或 JSON。
4. 保存为 UTF-8 单行文本：`name=value; name2=value2`。不要额外加引号；读取器也兼容 `Cookie:` 前缀。本项目需要同一会话中的 `UIFID` 或 `UIFID_TEMP`。不要拼接不同会话字段。
5. 通过私有 SSH/SCP 或远程编辑器传到本人 `~/projects` 目录，再用 `import-cookie --from-file 路径` 导入。文件权限设为 600，目录只给必要人员访问。

普通文本请求头与 Netscape Cookie 文件不是同一格式，不能只改扩展名。`document.cookie` 无法读取 HttpOnly 字段，已清理 HAR 也可能移除登录态。不要把真实 Cookie 放进 README、报告、命令参数、Git 或部署包。

首次与更新后的检查：

```bash
bash run.sh cookie-check
bash run.sh doctor
# 以下命令会真实请求并下载；仅在准备好后人工执行
bash run.sh download -i urls.txt --limit 1 -o downloads/auth_check_001
```

`cookie-check` 不联网，不确认登录有效。若 403、登录跳转、空数据或验证页持续出现，停止批次，在本机完成验证，重新抓取完整请求头并 `import-cookie --replace`，再用单条验收。Cookie 可能受有效期、账号状态、网络环境和站点策略影响，不承诺迁移后永久有效。正常服务器下载无需保持本机在线；更新会话时仍需人工配合。
