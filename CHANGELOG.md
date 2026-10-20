# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [2.3.0] - 2026-10-20

### 修复

- **签名 timestamp 冻结**：`WeComBot` 原先在构造时算一次 `msg_signature` 并拼进 `self.url`，
  长驻进程所有后续发送都复用同一个已过期的 timestamp。改为 URL 只存不含签名的 base，
  `url` 属性每次请求前现算（`wecom_notifier.py` 的 `WeComBot.url` / `_append_signature`）。
- **text 消息长度上限错误**：text 与 markdown 共用 4096 字节上限，超出企微 text 类型 2048 字节限制。
  `send_text` 现按 `min(max_bytes, TEXT_MAX_BYTES)` 收口。
- **`WECOM_TIMEOUT` 非法值裸抛异常**：环境变量填非数字时抛出未捕获的 `ValueError`，
  CLI 直接打 traceback。改为转成 `WeComError`，退出码 2。
- **Windows GBK 控制台崩溃**：`✅ / ❌ / ⚠️` 触发 `UnicodeEncodeError`，程序中断。
  新增 `_supports_unicode` / `_safe_print`，无法编码时自动降级为纯文本。
- **模板卡片静默丢项**：超过 6 项的 `items` 被切片丢弃且无提示，现改为直接报错。
- **卡片空标题 / 非法 card_type**：`title=""` 与 `button_interaction` 等会构造出非法 payload
  发到服务端，现在本地拦截。
- **`items` 值为 None** 时渲染成字面字符串 `"None"`，改为空串。
- **PNG 大图压缩无效**：`quality` 对 PNG 无效，12 轮只靠缩放往往压不下去。PNG 降不动时转 JPEG 重试。
- **非 2xx 响应丢失状态码**：`requests` 分支不看 `status_code`，`urllib` 分支的 `HTTPError`
  走另一条异常路径。两分支统一解析，响应里的 `_status` 透传到 `SendResult.status`。
- **CLI 结果行显示原始参数**：`text` / `markdown` 用 `args.content[:20]` 作名称，
  读 stdin 或文件时会打印成 `已发送: -`。改为加载后取内容摘要。
- **`send_image` 的 dry-run 仍做完整压缩**：现只校验存在性与类型，跳过 Pillow 压缩。
- **`send()` 不校验 payload**：缺 `msgtype` 现在抛 `WeComError`，`SUPPORTED_TYPES` 不再是摆设。

### 真实接口验证后补充（同日，用真实 webhook 全类型实测发现）

- **输入校验绕过 `_guard`**：`send_template_card` / `send_image` / `send_file` 的本地校验
  在 `_guard` 之外执行，`items` 超 6 项时仍抛 `WeComError`，与文档"不向调用方抛异常"矛盾。
  改为校验统一放在 `send()` 内的 `_run()` 中再由 `_guard` 收敛，全部输入错误都返回失败 `SendResult`。
- **新增 `_validate_payload()`**：按 `msgtype` 校验本地可控的硬限制（不支持的 msgtype、
  `template_card` 的 `card_type` / 空标题 / 超 6 项、`image` 缺 base64 或 md5）。
  这些条件企微服务端同样会 40058 拒绝，本地先拦让报错更早更清楚，且不浪费限频额度。
- **全空白 key 被当成有效 key**：`WeComBot(key=" ")` 会被拼成 `?key=%20%20` 发出去再报 93000。
  现在 `resolve_webhook` 与 `_resolve_webhook_from_env` 都先 `strip()`，全空白视为未配置。
- **key 首尾空格导致签名失败**：环境变量复制粘贴常带空格/换行，现统一剥离。

### 实测数据（写进 README 的限频说明）

- 未节流连发 22 条：第 1–13 条成功，第 14–22 条全部 `errcode=45009`，`retryable=True`。
  即窗口内实际额度约 13 条而非 20 条（前一轮测试已消耗额度），文档改为"滚动窗口，**最多** 20 条"。
- `min_interval=4.0` 连发 5 条：0 次 45009。
- text 边界：2052B / 2118B / 6018B / 7595B / 12622B 输入全部本地截断至 ≤2048B 且服务端返回 0。
- 6.7MB 高频噪声 PNG（base64 ≈ 9MB）走 PNG → JPEG 回退后成功送达。### 变更

- `SendResult` 新增 `status` 字段与 `retryable` 属性（网络异常 / 45009 / HTTP 5xx 为可重试）。
- 新增 `min_interval` 构造参数与 `--rate` CLI 参数，批量推送可自动节流规避 20 条/分钟限频。
- `requests` 改为线程内复用 `Session`（原文每请求新建连接，README 承诺的连接池实际未生效）。
- `SSLContext` 改为惰性创建，import 阶段不再碰系统证书库。
- 图片类型判定改为**按文件头魔数**，不再依赖 `mimetypes` 与扩展名。
- `multipart/form-data` 的每段 `Content-Type` 按文件名推断，不再写死 `application/octet-stream`。
- 群文件体积先用 `os.path.getsize` 判定再读，避免整块读入内存。
- 失败返回值的 `errmsg` 自动附带官方排查链接 `devtool/query?e=<errcode>`。
- 超长内容截断时打印警告，并尽量在换行处收尾，避免切断 markdown 结构。
- `--dry-run` 打印的请求体里，图片 base64 换成体积占位符。

### 移除

- 删除未使用的 `FALLBACK_KEY` 常量。
- 删除 `resolve_webhook` / `_resolve_webhook_from_env` 的 `warn` 参数（自相矛盾的遗留签名）。
- 删除 `.gitignore` 后补充了最小版本（`__pycache__/`、`*.env`、IDE 目录等）。

### 安全

- webhook 地址域名白名单，仅接受 `qyapi.weixin.qq.com`。
- key 拼进 URL 时做百分号编码，含特殊字符不再破坏查询串。

## [2.2.0] - 2026-09-05

- 初始公开版本：text / markdown（v1 + v2）/ template_card / image / file 五类消息，
  CLI 与 Python API 双入口，青龙面板 `QYWX_KEY` 自动读取。
