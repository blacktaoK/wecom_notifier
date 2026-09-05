# wecom_notifier

企业微信群机器人（webhook）推送工具。单个 `wecom_notifier.py` 覆盖 **文本 / 富文本 / 模板卡片 / 图片 / 群文件** 五类消息，命令行与 Python API 双入口。

- **零强制依赖**：Python 3.8+ 标准库即可运行，`requests`、`Pillow` 为可选增强
- **零配置起步**：配一个 key 即可推送
- **适用场景**：告警通知、日报播报、运维提醒、报表与图片分发、青龙面板定时任务

## 快速开始

```bash
# 1. 取 key：群设置 → 群机器人 → 添加/查看机器人 → Webhook 地址里 ?key= 后面那串
#    https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx-xxxx-...
#                                                          ↑ 这就是 key

# 2. 配置 key（推荐走环境变量，不要写进代码）
export WECOM_WEBHOOK_KEY="你的-key"        # Linux / macOS
set WECOM_WEBHOOK_KEY=你的-key             # Windows CMD
$env:WECOM_WEBHOOK_KEY="你的-key"          # Windows PowerShell

# 3. 发第一条消息
python wecom_notifier.py text "Hello 企业微信"

# 不确定配没配对？先空跑看请求体，不会真发消息
python wecom_notifier.py text "测试" --dry-run -v
```

Python API 同样简洁：

```python
from wecom_notifier import WeComBot

bot = WeComBot()                 # 省略则读环境变量
bot.send_text("Hello 企业微信")
```

## key 配置优先级

由高到低：`--webhook` 完整地址 > `--key` > `WECOM_WEBHOOK` > `WECOM_WEBHOOK_KEY` > `QYWX_KEY`（青龙面板自动生成）> **未配置则直接报错**。

> 本项目**不含任何内置 key**。未配置时会抛出明确的配置指引错误，不会静默降级。

## 安全提醒

key 等同于"往这个群发消息的权限"：

- **不要**把真实 key 写进源码、配置文件或提交到版本库
- 推荐用环境变量注入；本项目 `.gitignore` 已排除 `.env`、`*.key` 等常见密钥文件
- 若 key 曾意外泄露，请到群机器人设置里**立即重置**

## 文档

完整用法见 [wecom_notifier使用文档.md](./wecom_notifier使用文档.md)，包含：

- 全部子命令与参数速查（`text` / `markdown` / `news` / `image` / `file`）
- 富文本、模板卡片、图片自动压缩、群文件上传的细节
- 加解密签名校验配置
- 常见 errcode 排查表
- 青龙面板集成方式
