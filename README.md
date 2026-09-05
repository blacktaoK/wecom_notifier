# wecom_notifier 使用文档

企业微信群机器人（webhook）推送工具，一个文件覆盖**文本 / 富文本 / 模板卡片 / 图片 / 群文件**五类消息，
命令行与 Python API 双入口。

- 文件：`wecom_notifier.py`（v2.2.0）
- 依赖：**零强制依赖**，Python 3.8+ 标准库即可运行；`requests`、`Pillow` 为可选增强
- 适用：告警通知、日报播报、运维提醒、报表与图片分发、青龙面板定时任务

---

## 1. 30 秒上手

```bash
# ① 拿到 key：群设置 → 群机器人 → 添加/查看机器人 → Webhook 地址里 ?key= 后面那串
#    https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx-xxxx-...
#                                                          ↑ 这就是 key

# ② 配置 key（二选一）
export WECOM_WEBHOOK_KEY="你的-key"              # Linux / macOS
set WECOM_WEBHOOK_KEY=你的-key                   # Windows CMD
$env:WECOM_WEBHOOK_KEY="你的-key"                # Windows PowerShell

# ③ 发第一条消息
python wecom_notifier.py text "Hello 企业微信"

# 不确定配没配对？先空跑看看请求体，不会真发消息
python wecom_notifier.py text "测试" --dry-run -v
```

> ⚠️ key 等同于"往这个群发消息的权限"，不要写进公开仓库。

---

## 2. 配置 key 的四种方式（优先级由高到低）

| 优先级 | 方式 | 示例 |
| --- | --- | --- |
| 1 | `--webhook` 完整地址 | `--webhook "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"` |
| 2 | `--key` 只传 key | `--key "xxx"` |
| 3 | 环境变量 `WECOM_WEBHOOK` | 完整地址 |
| 4 | 环境变量 `WECOM_WEBHOOK_KEY` | 只放 key（最常用） |
| 5 | 环境变量 `QYWX_KEY` | **青龙面板**通知设置自动生成，无需手工填 |
| — | 以上均未配置 | 直接报错退出，并打印配置指引（无内置 key） |

其它环境变量：

| 变量 | 作用 |
| --- | --- |
| `WECOM_SECRET` | 机器人安全设置里的「加解密密钥」，设了即启用签名校验 |
| `WECOM_TIMEOUT` | 单次请求超时秒数，默认 8.0 |

---

## 3. 命令行速查

```
python wecom_notifier.py <子命令> [内容/路径] [公共参数]
```

### 公共参数（每个子命令都支持）

| 参数 | 说明 |
| --- | --- |
| `--key` | webhook key，也可传完整 URL |
| `--webhook` | 完整 webhook 地址，优先级高于 `--key` |
| `--secret` | 启用签名校验（值取机器人安全设置里的密钥） |
| `--timeout` | 请求超时秒数 |
| `--max-bytes` | 文本正文字节上限，超出截断（默认 4096） |
| `--image-max-bytes` | 图片 base64 上限（默认 2MB） |
| `--dry-run` | 只打印请求体，不真正发送 |
| `-v, --verbose` | 打印目标 webhook（脱敏） |

### 3.1 text — 纯文本

```bash
python wecom_notifier.py text "服务器 CPU 95%"
python wecom_notifier.py text "请值班同学处理" --mention zhangsan --mention lisi
python wecom_notifier.py text "紧急" --mention-mobile 13800000000
```

### 3.2 markdown — 富文本卡片

默认 `markdown_v2`（支持标题、列表、表格、引用、加粗）；`--v1` 切旧版（兼容性最好）。

```bash
python wecom_notifier.py markdown "# 日报\n- 样本 155\n- **耗时** 0.7s"
python wecom_notifier.py markdown --v1 "# 兼容旧客户端"
```

### 3.3 card — 模板卡片

```bash
python wecom_notifier.py card "扫描完成" \
  --desc "2026-09-05 收盘" \
  --item 样本=155 --item 耗时=0.7s --item 命中=12 \
  --source "板块扫描器" \
  --url "https://gu.qq.com"
```
`--item` 可重复，最多 6 项；`--url` 省略时用官方兜底链接。

### 3.4 image — 图片（JPEG/PNG）

```bash
python wecom_notifier.py image ./chart.png
python wecom_notifier.py image a.png b.jpg          # 多图批量
python wecom_notifier.py image big.png --no-compress # 超限直接报错，不自动压缩
```
超过 2MB 会自动降质/缩放（需要 `pip install pillow`），未装 Pillow 则报错并提示。

### 3.5 file — 群文件（5B~20MB）

```bash
python wecom_notifier.py file ./report.html
python wecom_notifier.py file ./data.xlsx --name "2026-09-05 数据.xlsx"
```
群成员点开用企微内置浏览器预览；media_id 3 天内有效，且只能由上传它的机器人使用。

### 3.6 内容参数的三种写法

| 写法 | 含义 | 示例 |
| --- | --- | --- |
| 字面内容 | 直接写文本 | `... text "hello"` |
| `-` | 从 stdin 读 | `cat report.md \| ... markdown -` |
| `@文件路径` | 从文件读（UTF-8） | `... markdown @report.md` |

> `@` 开头但文件不存在时，仍按字面文本发送，方便发 `@all` 这类内容。

---

## 4. Python 调用

### 4.1 客户端类（推荐）

```python
from wecom_notifier import WeComBot

bot = WeComBot(key="你的-key")          # 省略 key 则读环境变量
# bot = WeComBot(key="...", secret="...", timeout=10.0)   # 启用签名 / 改超时

result = bot.send_markdown("# 标题\n- **加粗**\n1. 有序列表")
if result:                              # SendResult 可直接当 bool 用
    print("发送成功")
else:
    print("失败", result.errcode, result.errmsg)
```

全部方法：

| 方法 | 说明 |
| --- | --- |
| `send_text(content, mentioned_list=None, mentioned_mobile_list=None)` | 纯文本，可 @人 |
| `send_markdown(content, msgtype=None)` | 富文本，`msgtype` 取 `markdown_v2` / `markdown` |
| `send_template_card(title, desc, items, source_desc, url)` | 模板卡片，`items=[(k, v), ...]` |
| `send_image(path)` | 本地图片，自动压缩；也可传 `base64_data` + `md5` |
| `send_file(local_path, filename=None)` | 群文件 |
| `send(payload)` | 发送任意合法 payload（news 等未封装类型） |

每个方法都带 `dry_run=False` 参数，置 True 只打印请求体不发送，便于调试。

### 4.2 模块级函数（一行调用，返回 `(ok, err)`）

```python
from wecom_notifier import send_text, send_markdown, send_image, send_file

ok, err = send_markdown("# 日报")
ok, err = send_image("./chart.png", key="你的-key")
ok, err = send_file("./report.html")
if not ok:
    print("推送失败:", err)
```

### 4.3 返回值

- 类方法 → `SendResult(ok, errcode, errmsg)`，支持 `if result:` 判断
- 模块级函数 → `(ok, err)` 元组，成功时 `err` 为空串
- 网络/接口错误**不抛异常**，一律收敛为失败返回值；只有输入不合法（文件不存在、格式不支持、超限）才抛 `WeComError`

---

## 5. 消息类型与限制

| 类型 | 体积上限 | 格式要求 | 备注 |
| --- | --- | --- | --- |
| text | 建议 ≤ 2048 字节 | 纯文本 | 超限时用 `--max-bytes 2048` |
| markdown / markdown_v2 | 4096 字节 | markdown | v2 支持列表/表格/引用，更美观 |
| template_card | — | key-value，≤ 6 项 | 结构化展示，正文纯文本 |
| image | base64 前 ≤ 2MB | **仅 JPEG / PNG** | 超限自动压缩（需 Pillow） |
| file | 5B ~ 20MB | 任意 | 走 upload_media，HTML 可被企微内置浏览器渲染 |

**限频**：每个机器人 **20 条/分钟**。批量脚本请自行控制节奏（如 `time.sleep(3)`），
超限会返回 `errcode=45009`。

---

## 6. 签名校验（可选）

机器人安全设置若开启了「签名校验」，需要带上密钥：

```bash
python wecom_notifier.py text "带签名的消息" --secret "你的-加解密密钥"
export WECOM_SECRET="你的-加解密密钥"          # 或放环境变量
```

```python
bot = WeComBot(key="...", secret="...")
```

脚本会自动在 URL 上追加 `timestamp` 与 `msg_signature`
（算法：`Base64(HMAC-SHA256(key=secret, msg=timestamp + "\n" + secret))`）。
未开启签名校验的机器人不要传 `--secret`，否则会报错。

---

## 7. 青龙面板部署

1. 把 `wecom_notifier.py` 放到青龙 scripts 目录（如 `/ql/data/scripts/`）。
2. 依赖管理（可选）：装 `requests`（发大图再装 `pillow`）。
3. 在「系统设置 → 通知设置 → 企业微信机器人」填 key，青龙会存成环境变量 `QYWX_KEY`，**脚本自动读取，无需再传 key**。
4. 新建任务，命令示例：

```bash
python3 /ql/data/scripts/wecom_notifier.py text "定时任务执行完毕"
python3 /ql/data/scripts/wecom_notifier.py markdown @/ql/data/scripts/report.md
python3 /ql/data/scripts/wecom_notifier.py image /ql/data/repo/chart.png
```

---

## 8. 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 全部推送成功 |
| 1 | 有一条或多条推送失败 |
| 2 | 配置或输入错误（如 webhook 缺 key、内容文件读失败） |

调度平台可根据退出码判断是否告警。

---

## 9. 常见问题排查

| 现象 / errcode | 原因 | 处理 |
| --- | --- | --- |
| `93000 invalid webhook url` | key 填错、失效，或机器人已被移除 | 核对群机器人 Webhook 地址里的 key |
| `45009 api freq out of limit` | 超过 20 条/分钟 | 批量推送加延时 |
| `40058 请求参数不合法` | 正文超长、msgtype 不支持等 | 用 `--max-bytes` 调小；text 建议 ≤ 2048 字节 |
| 提示"未配置企业微信 webhook key" | 环境变量没生效 | 确认变量已 `export`/`set`，青龙环境用 `QYWX_KEY` |
| 图片报"仅支持 JPEG/PNG" | 文件类型不符（如 webp/gif） | 先转成 JPG/PNG |
| 图片报"未安装 Pillow 无法自动压缩" | 大图超过 2MB | `pip install pillow`，或先把图压到 2MB 内 |
| 群文件报"低于 5B 下限 / 超过 20MB 上限" | 文件体积不合规 | 压缩或分包 |
| 其它 errcode | — | 返回值里有官方排查链接 `open.work.weixin.qq.com/devtool/query?e=<errcode>` |

调试三板斧：

```bash
python wecom_notifier.py text "测试" --dry-run -v    # ① 看请求体与目标地址（不发消息）
python wecom_notifier.py text "测试" -v              # ② 真实发送并看脱敏地址
python wecom_notifier.py text "测试" --timeout 20    # ③ 网络慢时延长超时
```

---

## 10. 可选依赖

| 包 | 缺失时的表现 | 安装 |
| --- | --- | --- |
| `requests` | 自动回退标准库 `urllib`，功能不受影响 | `pip install requests`（连接池更稳） |
| `Pillow` | 图片超 2MB 时无法自动压缩，会报错 | `pip install pillow` |

---

## 11. 安全建议

- key 走环境变量或参数注入，不要硬编码进脚本或提交到仓库。
- 分享日志时注意：脚本打印的 webhook 已脱敏（只显示 key 前 6 位），但 `--dry-run` 会打印完整请求体（含图片 base64），外发前留意。
- 机器人限频 20 条/分钟，批量任务务必限速。
