# wecom_notifier 使用文档

企业微信群机器人（webhook）推送工具，一个文件覆盖**文本 / 富文本 / 模板卡片 / 图片 / 群文件**五类消息，
命令行与 Python API 双入口。

- 文件：`wecom_notifier.py`（v2.3.0）
- 依赖：**零强制依赖**，Python 3.8+ 标准库即可运行；`requests`、`Pillow` 为可选增强
- 适用：告警通知、日报播报、运维提醒、报表与图片分发、青龙面板定时任务

<img src="docs/hero.svg" alt="三种用法：命令行 / Python API / 定时任务" width="880">

```bash
python wecom_notifier.py text "Hello 企业微信"
```

---

## 目录

| 章节 | 解决什么问题 |
| --- | --- |
| [1. 30 秒上手](#1-30-秒上手) | 拿到 key，发出第一条消息 |
| [2. key 从哪来](#2-key-从哪来) | 五种配置方式与优先级、域名白名单 |
| [3. 命令行速查](#3-命令行速查) | 五类消息的具体参数 |
| [4. Python 调用](#4-python-调用) | 嵌进你自己的脚本 |
| [5. 消息类型与限制](#5-消息类型与限制) | 体积上限、限频、v2.2.0 → v2.3.0 行为变化 |
| [6. 签名校验](#6-签名校验可选) | 机器人开了「签名校验」怎么办 |
| [7. 青龙面板部署](#7-青龙面板部署) | 定时任务零配置 |
| [8. 退出码](#8-退出码) | 调度平台如何判断成败 |
| [9. 常见问题排查](#9-常见问题排查) | 报错对照表 |
| [10. 可选依赖](#10-可选依赖) / [11. 安全建议](#11-安全建议) | 收尾两件事 |

---

## 1. 30 秒上手

```bash
# ① 拿到 key：群设置 → 群机器人 → 添加/查看机器人 → Webhook 地址里 ?key= 后面那串
#    https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx-xxxx-...
#                                                          ↑ 这就是 key

# ② 配置 key（任选其一）
export WECOM_WEBHOOK_KEY="你的-key"              # Linux / macOS
set WECOM_WEBHOOK_KEY=你的-key                   # Windows CMD
$env:WECOM_WEBHOOK_KEY="你的-key"                # Windows PowerShell

# ③ 发第一条消息
python wecom_notifier.py text "Hello 企业微信"

# 不确定配没配对？先空跑看看请求体，不会真发消息
python wecom_notifier.py text "测试" --dry-run -v
```

> ⚠️ key 等同于「往这个群发消息的权限」，不要写进公开仓库。

### Windows 中文控制台乱码？

`✅ / ❌ / ⚠️` 在 GBK 控制台下无法编码，v2.3.0 起会自动降级成纯文本，不会崩溃。想看中文与图标：

```powershell
$env:PYTHONIOENCODING="utf-8"; chcp 65001
```

---

## 2. key 从哪来

环境变量、命令行参数、青龙面板注入 —— 五种来源按顺序命中即止：

<img src="docs/key-resolution.svg" alt="key 解析优先级：--webhook → --key → WECOM_WEBHOOK → WECOM_WEBHOOK_KEY → QYWX_KEY" width="880">

| 顺序 | 来源 | 说明 |
| --- | --- | --- |
| 1 | `--webhook` | 完整地址，优先级最高 |
| 2 | `--key` | 只传 key，也可直接传完整地址 |
| 3 | `WECOM_WEBHOOK` | 完整地址 |
| 4 | `WECOM_WEBHOOK_KEY` | 只放 key（最常用） |
| 5 | `QYWX_KEY` | **青龙面板**通知设置自动生成；与第 4 项同级，`WECOM_WEBHOOK_KEY` 存在时优先用它 |
| — | 以上均未配置 | 打印配置指引，退出码 2；**没有内置 key** |

其它环境变量：

| 变量 | 作用 |
| --- | --- |
| `WECOM_SECRET` | 机器人安全设置里的「加解密密钥」，设了即启用签名校验 |
| `WECOM_TIMEOUT` | 单次请求超时秒数，默认 8.0；填非数字会报「配置错误」并退出 2 |

> webhook 地址的域名必须是 `qyapi.weixin.qq.com`，其它域名会被本地直接拒绝，避免 key 泄漏到第三方。

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
| `--max-bytes` | markdown 正文字节上限，超出截断（默认 4096） |
| `--image-max-bytes` | 图片 base64 上限（默认 2MB） |
| `--rate SEC` | 两次发送的最小间隔秒数；批量推送建议 `3`（对应 20 条/分钟） |
| `--dry-run` | 只打印请求体，不真正发送 |
| `-v, --verbose` | 打印目标 webhook（脱敏） |
| `--version` | 打印版本号 |

### 3.1 text — 纯文本

```bash
python wecom_notifier.py text "服务器 CPU 95%"
python wecom_notifier.py text "请值班同学处理" --mention zhangsan --mention lisi
python wecom_notifier.py text "紧急" --mention-mobile 13800000000
```

正文上限 **2048 字节**（企微 text 类型硬限制），超限自动截断并打印警告，不受 `--max-bytes` 放大影响。

### 3.2 markdown — 富文本卡片

默认 `markdown_v2`（支持标题、列表、表格、引用、加粗）；`--v1` 切旧版（兼容性最好）。

```bash
# 真换行：用 printf / $'...' / heredoc，别写 "\n"（那是字面反斜杠加 n）
printf '# 日报\n- 样本 155\n- **耗时** 0.7s' | python wecom_notifier.py markdown -
python wecom_notifier.py markdown $'# 日报\n- **耗时** 0.7s'          # bash / zsh
python wecom_notifier.py markdown @report.md                            # 从文件读（最省事）
python wecom_notifier.py markdown --v1 "# 兼容旧客户端"
```

正文上限 **4096 字节**（`--max-bytes` 可调）。

### 3.3 card — 模板卡片

```bash
python wecom_notifier.py card "扫描完成" \
  --desc "2026-09-05 收盘" \
  --item 样本=155 --item 耗时=0.7s --item 命中=12 \
  --source "板块扫描器" \
  --url "https://gu.qq.com"
```

- `--item` 可重复，**最多 6 项**，超过会直接报错（不再静默丢弃）
- `--url` 省略时用官方兜底链接 `https://work.weixin.qq.com/`
- 标题不能为空
- 当前只封装 `text_notice` 卡片；`button_interaction` / `news_notice` 字段结构不同，请用 `bot.send(payload)` 自行构造

### 3.4 image — 图片（JPEG/PNG）

```bash
python wecom_notifier.py image ./chart.png
python wecom_notifier.py image a.png b.jpg --rate 3      # 多图批量，自动限速
python wecom_notifier.py image big.png --no-compress     # 超限直接报错，不自动压缩
```

- 类型按**文件头魔数**判定，扩展名是 `.png` 但实际是 webp 的文件会在本地被拦下
- 超过 2MB 自动降质 + 缩放（需要 `pip install pillow`）；PNG 降不动时会自动转 JPEG 再压
- 未装 Pillow 则报错并提示

### 3.5 file — 群文件（5B~20MB）

```bash
python wecom_notifier.py file ./report.html
python wecom_notifier.py file ./data.xlsx --name "2026-09-05 数据.xlsx"
```

群成员点开用企微内置浏览器预览；media_id 3 天内有效，且只能由上传它的机器人使用。
体积在读取前用文件属性判定，不会为了判断大小先把 20MB 读进内存。

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
# bot = WeComBot(key="...", secret="...", timeout=10.0, min_interval=3.0)

result = bot.send_markdown("# 标题\n- **加粗**\n1. 有序列表")   # 这里是真换行
if result:                              # SendResult 可直接当 bool 用
    print("发送成功")
else:
    print("失败", result.errcode, result.errmsg, "可重试:", result.retryable)
```

全部方法：

| 方法 | 说明 |
| --- | --- |
| `send_text(content, mentioned_list=None, mentioned_mobile_list=None)` | 纯文本，可 @人；正文按 2048B 截断 |
| `send_markdown(content, msgtype=None)` | 富文本，`msgtype` 取 `markdown_v2` / `markdown` |
| `send_template_card(title, desc, items, source_desc, url, card_type="text_notice")` | 模板卡片，`items=[(k, v), ...]`，最多 6 项 |
| `send_image(path)` | 本地图片，自动压缩；也可传 `base64_data` + `md5` |
| `send_file(local_path, filename=None)` | 群文件 |
| `send(payload)` | 发送任意合法 payload（news 等未封装类型） |

每个方法都带 `dry_run=False` 参数，置 True 只打印请求体不发送（图片 dry-run 连压缩都跳过）。

构造参数补充：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `min_interval` | `0.0` | 两次发送最小间隔秒数，批量推送设 `3.0` 可自动规避限频 |
| `max_bytes` | `4096` | markdown 上限；text 另有 2048 硬上限 |
| `image_max_bytes` | `2MB` | 图片 base64 上限 |

### 4.2 模块级函数（一行调用，返回 `(ok, err)`）

```python
from wecom_notifier import send_text, send_markdown, send_image, send_file

ok, err = send_markdown("# 日报")
ok, err = send_image("./chart.png", key="你的-key")
ok, err = send_file("./report.html")
if not ok:
    print("推送失败:", err)
```

### 4.3 返回值与重试

一次发送会经过四个阶段，失败一律收敛成返回值，不会把异常抛给调用方：

<img src="docs/send-pipeline.svg" alt="发送链路：解析 key → 构造 payload → 节流与签名 → 发送与错误收敛" width="880">

- 类方法 → `SendResult(ok, errcode, errmsg, status)`，支持 `if result:` 判断
- 模块级函数 → `(ok, err)` 元组，成功时 `err` 为空串
- 网络/接口错误**不抛异常**，一律收敛为失败返回值；只有输入不合法（文件不存在、格式不支持、超限、payload 缺 msgtype）才抛 `WeComError`
- `SendResult.retryable`：`True` 表示值得重试（网络异常 / 45009 限频 / HTTP 5xx）
- `SendResult.status`：HTTP 状态码，有响应时才有值

```python
import time

for attempt in range(3):
    result = bot.send_text("巡检完成")
    if result or not result.retryable:
        break
    time.sleep(2 ** attempt)
```

---

## 5. 消息类型与限制

<img src="docs/message-types.svg" alt="五类消息与各自上限" width="880">

| 类型 | 体积上限 | 格式要求 | 备注 |
| --- | --- | --- | --- |
| text | 2048 字节 | 纯文本 | 超限自动截断（v2.3.0 起按此上限收口） |
| markdown / markdown_v2 | 4096 字节 | markdown | v2 支持列表/表格/引用；`--max-bytes` 可调 |
| template_card | — | key-value，≤ 6 项 | 结构化展示，标题必填 |
| image | base64 后 ≤ 2MB | **仅 JPEG / PNG**（按魔数判定） | 超限自动压缩（需 Pillow） |
| file | 5B ~ 20MB | 任意 | 走 upload_media，HTML 可被企微内置浏览器渲染 |

**限频**：每个机器人 **20 条/分钟**。v2.3.0 起可用 `--rate 3` 或 `min_interval=3.0` 自动节流；
超限返回 `errcode=45009`，错误信息会明确提示「已触发限频」，且 `retryable=True`。

### 从 v2.2.0 升级

| 项 | v2.2.0 行为 | v2.3.0 行为 |
| --- | --- | --- |
| 签名 timestamp | 构造对象时算一次，长驻进程复用导致过期 | 每次请求前现算 |
| text 长度 | 与 markdown 共用 4096 | 独立收口到 2048 |
| 超长截断 | 静默截断 | 截断并打印警告，尽量在换行处收尾 |
| 卡片超过 6 项 | 静默丢弃 | 直接报错 |
| 图片 dry-run | 仍做完整压缩 | 只校验类型 |
| PNG 大图压缩 | 只缩放不降质，容易压不下去 | 降不动时转 JPEG 重试 |
| `WECOM_TIMEOUT` 非法 | 裸抛 ValueError + traceback | 转成「配置错误」退出码 2 |
| Windows GBK 控制台 | emoji 触发 UnicodeEncodeError 崩溃 | 自动降级为纯文本输出 |

完整改动见 [CHANGELOG.md](CHANGELOG.md)。

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

脚本会在**每次请求前**追加 `timestamp` 与 `msg_signature`
（算法：`Base64(HMAC-SHA256(key=secret, msg=timestamp + "\n" + secret))`）。
由于签名对时间新鲜度敏感，长驻进程请**复用同一个 `WeComBot` 实例**，它每次发送都会重算 timestamp。

> 未开启签名校验的机器人不要传 `--secret`，否则会报错。

---

## 7. 青龙面板部署

1. 把 `wecom_notifier.py` 放到青龙 scripts 目录（如 `/ql/data/scripts/`）。
2. 依赖管理（可选）：
   - 推荐在面板「依赖管理 → Python3」里添加 `requests`（发大图再加 `pillow`）
   - 或容器内执行 `pip3 install requests pillow`
3. 在「系统设置 → 通知设置 → 企业微信机器人」填 key，青龙会存成环境变量 `QYWX_KEY`，**脚本自动读取，无需再传 key**。
4. 新建任务，命令示例：

```bash
python3 /ql/data/scripts/wecom_notifier.py text "定时任务执行完毕"
python3 /ql/data/scripts/wecom_notifier.py markdown @/ql/data/scripts/report.md
python3 /ql/data/scripts/wecom_notifier.py image /ql/data/repo/chart.png --rate 3
```

---

## 8. 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 全部推送成功 |
| 1 | 有一条或多条推送失败 |
| 2 | 配置或输入错误（webhook 缺 key、域名不符、超时非数字、内容文件读失败、卡片参数非法等） |

调度平台可根据退出码判断是否告警。

---

## 9. 常见问题排查

| 现象 / errcode | 原因 | 处理 |
| --- | --- | --- |
| `93000 invalid webhook url` | key 填错、失效，或机器人已被移除 | 核对群机器人 Webhook 地址里的 key |
| `45009 api freq out of limit` | 超过 20 条/分钟 | 加 `--rate 3` 或 `min_interval=3.0` |
| `40058 请求参数不合法` | 正文超长、msgtype 不支持等 | 确认正文长度；text 上限 2048B |
| 「webhook 地址域名不是企微官方域名」 | 传了第三方域名的 URL | 只用 `qyapi.weixin.qq.com` 的地址 |
| 提示「未配置企业微信 webhook key」 | 环境变量没生效 | 确认变量已 `export`/`set`，青龙用 `QYWX_KEY` |
| 提示「环境变量 WECOM_TIMEOUT 不是合法数字」 | 变量填了非数字 | 改成秒数（如 `8`）或删掉该变量 |
| 图片报「文件内容不是有效 JPEG/PNG」 | 实际是 webp/gif，或扩展名造假 | 先转成真正的 JPG/PNG |
| 图片报「未安装 Pillow 无法自动压缩」 | 大图超过 2MB | `pip install pillow`，或先把图压到 2MB 内 |
| 群文件报「低于 5B 下限 / 超过 20MB 上限」 | 文件体积不合规 | 压缩或分包 |
| 卡片报「最多 6 项」 | `--item` 传多了 | 精简到 6 项以内，或拆成多张卡片 |
| Windows 控制台输出问号/乱码 | GBK 编码无法显示中文图标 | `$env:PYTHONIOENCODING="utf-8"; chcp 65001` |
| 其它 errcode | — | 失败返回值里的 `errmsg` 已附带官方排查链接 `open.work.weixin.qq.com/devtool/query?e=<errcode>` |

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
| `requests` | 自动回退标准库 `urllib`，功能不受影响 | `pip install requests`（用线程内 Session 复用连接池） |
| `Pillow` | 图片超 2MB 时无法自动压缩，会报错 | `pip install pillow` |

---

## 11. 安全建议

- key 走环境变量或参数注入，不要硬编码进脚本或提交到仓库。
- 分享日志时注意：脚本打印的 webhook 已脱敏（只显示 key 前 6 位）；`--dry-run` 打印的请求体里，
  **图片 base64 已替换成体积占位符**，可以放心贴群排查。
- 机器人限频 20 条/分钟，批量任务务必限速。
- webhook 域名做了白名单校验，只有 `qyapi.weixin.qq.com` 会被接受。

---

<sub>配图为 `docs/*.svg`，用 `pwsh docs/build_diagrams.ps1` 重新生成；矢量图在 GitHub 上随深浅色主题自动切换。</sub>

