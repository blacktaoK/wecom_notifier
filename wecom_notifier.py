#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信群机器人（webhook）推送客户端 · wecom_notifier
=====================================================================
零强制依赖（requests / Pillow 为可选增强），配一个 key 即可推送。
详细用法见同目录《README.md》。

最快上手
---------------------------------------------------------------------
    export WECOM_WEBHOOK_KEY="你的-key"        # Windows: set WECOM_WEBHOOK_KEY=你的-key
    python wecom_notifier.py text "第一条消息"

命令行子命令
---------------------------------------------------------------------
    text      纯文本，支持 --mention @成员
    markdown  markdown_v2 富文本（--v1 切旧版）
    card      模板卡片，--item 键=值
    image     本地 JPEG/PNG，超限自动压缩到 2MB
    file      群文件，5B~20MB
内容参数三种写法：字面内容 / '-' 读 stdin / '@文件路径' 读文件。
公共参数：--key --webhook --secret --timeout --rate --dry-run -v（各子命令 --help 查看）。

Python 调用
---------------------------------------------------------------------
    from wecom_notifier import WeComBot, send_markdown

    bot = WeComBot(key="你的-key")            # 省略则读环境变量
    bot.send_markdown("# 标题\\n- **加粗**")
    bot.send_image("./chart.png")             # 自动压缩
    bot.send_file("./report.html")            # 群文件

    send_markdown("# 日报")                    # 模块级函数，返回 (ok, err)

要点
---------------------------------------------------------------------
  · 所有发送方法返回 SendResult(ok, errcode, errmsg)，可用 if 直接判断；
    模块级函数返回 (ok, err) 元组。
  · 网络 / 接口错误不抛异常，收敛为失败 SendResult；仅输入不合法抛 WeComError。
  · text 正文上限 2048B、markdown 上限 4096B，超限按 UTF-8 字节安全截断并告警。
  · 图片超 2MB 自动压缩；PNG 过大会转 JPEG 重试。
  · 机器人限频 20 条/分钟，可用 min_interval / --rate 自动节流。

配置优先级（高 → 低）
---------------------------------------------------------------------
  webhook 地址 : webhook 参数 > key 参数 > WECOM_WEBHOOK > WECOM_WEBHOOK_KEY
                 > QYWX_KEY（青龙面板）> 未配置则直接报错（无内置 key）
  签名密钥     : secret 参数 > WECOM_SECRET；超时 : timeout 参数 > WECOM_TIMEOUT
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:                                    # 可选增强：有 requests 就用它的连接池
    import requests as _requests        # type: ignore
except ImportError:                     # pragma: no cover - 无 requests 环境
    _requests = None                    # type: ignore

__all__ = [
    "WeComBot", "SendResult", "WeComError",
    "send_text", "send_markdown", "send_template_card", "send_image", "send_file",
    "gen_signature", "resolve_webhook", "prepare_image", "main",
]

__version__ = "2.3.0"

# ── 类型别名 ────────────────────────────────────────────────────────── #
JsonDict = Dict[str, Any]                 # 接口返回的 JSON 对象
Payload = Dict[str, Any]                  # 待发送的 webhook 请求体

# ── 官方网关与常量 ──────────────────────────────────────────────────── #
BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
UPLOAD_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media"
HELP_URL = "https://open.work.weixin.qq.com/devtool/query?e={errcode}"

# 只允许往企微官方域名发请求，避免把 key 拼进任意 URL 变成 SSRF 跳板
ALLOWED_HOSTS = ("qyapi.weixin.qq.com",)

ENV_WEBHOOK = "WECOM_WEBHOOK"
ENV_KEY = "WECOM_WEBHOOK_KEY"
ENV_QYWX_KEY = "QYWX_KEY"          # 青龙面板通知设置
ENV_SECRET = "WECOM_SECRET"
ENV_TIMEOUT = "WECOM_TIMEOUT"

DEFAULT_TIMEOUT = 8.0
DEFAULT_MAX_BYTES = 4096                    # markdown content 字节上限
TEXT_MAX_BYTES = 2048                       # text content 字节上限（企微硬限制）
DEFAULT_IMAGE_MAX_BYTES = 2 * 1024 * 1024   # image base64 上限（企微硬限制）
MAX_FILE_BYTES = 20 * 1024 * 1024           # 群文件上限 20MB
MIN_FILE_BYTES = 5                          # 群文件下限 5B
ALLOWED_IMAGE_MIMES = ("image/jpeg", "image/png")
MAX_COMPRESS_ROUNDS = 12                    # 图片自动压缩的最大迭代轮数
MAX_CARD_ITEMS = 6                          # 模板卡片最多展示的 key-value 项数
DEFAULT_CARD_URL = "https://work.weixin.qq.com/"
RATE_LIMIT_ERRCODE = 45009                  # 触发 20 条/分钟限频
RETRYABLE_ERRCODES = frozenset({-1, RATE_LIMIT_ERRCODE})
MIN_INTERVAL_LIMIT = 3.0                    # 20 条/分钟 → 建议最小间隔 3 秒

# 图片魔数 → (MIME, Pillow 格式名)；用于挡住「扩展名改一下」的假图片
_IMAGE_MAGIC: Tuple[Tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)

_THREAD_LOCAL = threading.local()


def _ssl_context() -> ssl.SSLContext:
    """惰性构造 SSL 上下文（import 时不碰系统证书库，精简环境也不炸）。"""
    context = getattr(_THREAD_LOCAL, "ssl_context", None)
    if context is None:
        try:
            context = ssl.create_default_context()
        except Exception:                       # pragma: no cover - 极端精简环境
            context = ssl._create_unverified_context()  # noqa: SLF001
        _THREAD_LOCAL.ssl_context = context
    return context


def _requests_session() -> Any:
    """每个线程复用一个 requests.Session，真正用上连接池。"""
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = _requests.Session()           # type: ignore[union-attr]
        _THREAD_LOCAL.session = session
    return session


# ===================================================================== #
# 统一日志输出（信息/成功走 stdout，警告/错误走 stderr）
# ===================================================================== #
def _supports_unicode(stream: Any) -> bool:
    """判断输出流能否编码 emoji 图标（Windows GBK 控制台不能）。"""
    encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
    if encoding in ("", "utf8", "utf_8"):
        return True
    try:
        "❌".encode(encoding)
        return True
    except (LookupError, UnicodeEncodeError):
        return False


def _safe_print(text: str, stream: Any) -> None:
    """打印时对无法编码的字符降级为 '?'，绝不让编码问题把程序打崩。"""
    try:
        print(text, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"), file=stream)


def _emit(level: str, message: str) -> None:
    """统一输出：error / warn 走 stderr，其余走 stdout。"""
    stream = sys.stderr if level in ("error", "warn") else sys.stdout
    icon = {"error": "❌ ", "warn": "⚠️ "}.get(level, "") if _supports_unicode(stream) else ""
    _safe_print(f"[wecom] {icon}{message}", stream)


def _log_info(message: str) -> None:
    """普通信息，写 stdout。"""
    _emit("info", message)


def _log_warn(message: str) -> None:
    """警告（不影响执行，如内容被截断），写 stderr。"""
    _emit("warn", message)


def _log_error(message: str) -> None:
    """错误（会导致本次推送失败），写 stderr。"""
    _emit("error", message)


def _log_dry_run(payload: Payload) -> None:
    """打印 dry-run 模式下的请求体。

    图片 base64 换成体积占位符，避免一整屏乱码和分享日志时的数据外泄。
    """
    preview = json.loads(json.dumps(payload, ensure_ascii=False))
    image = preview.get("image")
    if isinstance(image, dict) and "base64" in image:
        image["base64"] = f"<base64 {len(image['base64'])} 字符已省略>"
    _safe_print("[dry-run] 将发送: " + json.dumps(preview, ensure_ascii=False), sys.stdout)


def _report_success(name: str) -> None:
    """CLI 结果行：单条推送成功。"""
    _safe_print(f"✅ 已发送: {name}" if _supports_unicode(sys.stdout) else f"已发送: {name}",
                sys.stdout)


def _report_failure(name: str, result: "SendResult") -> None:
    """CLI 结果行：单条推送失败。"""
    _safe_print(f"❌ 发送失败: {name} -> {result}" if _supports_unicode(sys.stdout)
                else f"发送失败: {name} -> {result}", sys.stdout)


def _describe_exception(exc: BaseException) -> str:
    """把异常格式化成统一的「异常类型: 说明」文本。"""
    return f"{type(exc).__name__}: {exc}"


# ===================================================================== #
# 异常与结果对象
# ===================================================================== #
class WeComError(Exception):
    """配置或输入不合法时抛出（缺 key、文件不存在、格式不支持、超限等）。"""


@dataclass
class SendResult:
    """一次推送的结果，支持 `if result:` 直接判断成功与否。"""

    ok: bool
    errcode: Optional[int] = None
    errmsg: str = ""
    status: Optional[int] = None    # HTTP 状态码（有响应时才有）

    @classmethod
    def success(cls, errmsg: str = "", status: Optional[int] = None) -> "SendResult":
        """构造成功结果。"""
        return cls(True, 0, errmsg, status)

    @classmethod
    def failure(cls, errmsg: str, errcode: Optional[int] = None,
                status: Optional[int] = None) -> "SendResult":
        """构造失败结果。"""
        return cls(False, errcode, errmsg, status)

    def __bool__(self) -> bool:
        return self.ok

    @property
    def retryable(self) -> bool:
        """是否值得重试：网络异常、限频、5xx。"""
        if self.ok:
            return False
        if self.errcode in RETRYABLE_ERRCODES:
            return True
        return self.status is not None and 500 <= self.status < 600

    def __repr__(self) -> str:
        if self.ok:
            return "SendResult(ok=True)"
        extra = f", status={self.status}" if self.status is not None else ""
        return f"SendResult(ok=False, errcode={self.errcode}, errmsg={self.errmsg!r}{extra})"


# ===================================================================== #
# 通用工具函数
# ===================================================================== #
def gen_signature(timestamp: str, secret: str) -> str:
    """生成机器人「签名校验」所需的 msg_signature。

    算法：Base64(HMAC-SHA256(key=secret, msg=timestamp + '\\n' + secret))。
    仅当机器人安全设置开启了「签名校验」时才需要。
    """
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                      hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def extract_key(url: str) -> Optional[str]:
    """从 webhook URL 中抽取 key（兼容带 timestamp / msg_signature 的地址）。"""
    matched = re.search(r"[?&]key=([^&]+)", url)
    return matched.group(1) if matched else None


def mask_url(url: str) -> str:
    """脱敏 webhook 地址，便于日志打印（隐藏 key / signature 主体）。"""
    if "key=" in url:
        prefix, _, tail = url.partition("key=")
        key = tail.split("&")[0]
        shown = key[:6] + "***" if len(key) > 6 else "***"
        return f"{prefix}key={shown}(已隐去)"
    return url


def _as_webhook_url(value: str) -> str:
    """把「完整地址」或「纯 key」统一成完整 webhook 地址。

    以 http(s):// 开头的值按完整地址处理（必须自带 key 参数），并校验域名属于
    企微官方，避免整段 URL 被误当 key 后把消息发到别处。
    """
    if value.startswith(("http://", "https://")):
        host = urllib.parse.urlsplit(value).hostname or ""
        if host not in ALLOWED_HOSTS:
            raise WeComError(f"webhook 地址域名不是企微官方域名: {host or '未知'}")
        return value
    return value if "key=" in value else f"{BASE_URL}?key={urllib.parse.quote(value, safe='')}"


def _append_signature(url: str, secret: str) -> str:
    """在 webhook 地址上追加 timestamp + msg_signature 查询参数。

    必须在每次请求前现算：企微会校验 timestamp 的新鲜度，复用旧值会被判过期。
    """
    timestamp = str(int(time.time()))
    signature = gen_signature(timestamp, secret)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}timestamp={timestamp}&msg_signature={signature}"


def _resolve_webhook_from_env() -> str:
    """从环境变量解析 webhook 地址；未配置时抛出明确错误（不再回退到内置 key）。

    :raises WeComError: 环境变量未提供可用的 key。
    """
    env_url = os.environ.get(ENV_WEBHOOK)
    if env_url:
        return env_url
    env_key = os.environ.get(ENV_KEY) or os.environ.get(ENV_QYWX_KEY)
    if env_key:
        return _as_webhook_url(env_key)
    raise WeComError(
        "未配置企业微信 webhook key，请任选一种方式配置：\n"
        f"  1) 环境变量 {ENV_KEY}=你的-key\n"
        f"  2) 环境变量 {ENV_WEBHOOK}=完整 webhook 地址\n"
        f"  3) 命令行参数 --key 你的-key 或 --webhook 完整地址\n"
        f"  4) 青龙面板：在通知设置中填写 {ENV_QYWX_KEY}"
    )


def resolve_webhook(webhook: Optional[str] = None, key: Optional[str] = None,
                    secret: Optional[str] = None) -> str:
    """按统一优先级解析最终可用的 webhook 地址（必要时追加签名参数）。

    优先级：webhook > key > WECOM_WEBHOOK > WECOM_WEBHOOK_KEY > QYWX_KEY > 报错。

    :param secret: 传了即在 URL 上追加签名校验参数。注意此处算出的 timestamp 只有
                   调用瞬间有效，长驻进程请改用 WeComBot（它每次请求前现算）。
    :raises WeComError: 解析结果中不含 key 参数，或域名不是企微官方域名。
    """
    if webhook:
        url = _as_webhook_url(webhook)
    elif key:
        url = _as_webhook_url(key)
    else:
        url = _resolve_webhook_from_env()

    if extract_key(url) is None:
        raise WeComError(f"webhook 地址缺少 key 参数：{mask_url(url)}")
    return _append_signature(url, secret) if secret else url


# ===================================================================== #
# HTTP 传输层（requests 优先，urllib 兜底）
# ===================================================================== #
def _parse_json_response(text: str, status: Optional[int] = None) -> JsonDict:
    """解析接口响应；非 JSON / 非对象响应统一包装成失败结构。"""
    try:
        obj = json.loads(text)
    except ValueError:
        prefix = f"HTTP {status} " if status is not None else ""
        return {"errcode": -1, "errmsg": f"{prefix}非 JSON 响应: {text[:200]}",
                "_status": status}
    if not isinstance(obj, dict):
        return {"errcode": -1, "errmsg": f"响应不是 JSON 对象: {text[:200]}",
                "_status": status}
    if status is not None:
        obj.setdefault("_status", status)
    return obj


def _http_post(url: str, body: bytes, headers: Dict[str, str], timeout: float) -> JsonDict:
    """发送一次 POST 并返回解析后的响应。

    requests 可用时复用线程内 Session（连接池），否则回退标准库 urllib；
    网络异常统一包装成 {errcode: -1, errmsg: ...}，不向上抛异常。
    返回体里的 ``_status`` 是 HTTP 状态码，供上层区分 5xx 等可重试错误。
    """
    if _requests is not None:
        try:
            response = _requests_session().post(
                url, data=body, headers=headers, timeout=timeout)
            return _parse_json_response(response.text, response.status_code)
        except Exception as exc:
            return {"errcode": -1, "errmsg": _describe_exception(exc)}

    try:
        request = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=_ssl_context()) as resp:
            return _parse_json_response(
                resp.read().decode("utf-8", "replace"), getattr(resp, "status", None))
    except urllib.error.HTTPError as exc:       # 4xx/5xx 也把响应体读出来解析
        text = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return _parse_json_response(text or str(exc), exc.code)
    except Exception as exc:
        return {"errcode": -1, "errmsg": _describe_exception(exc)}


def _http_post_json(url: str, payload: Payload, timeout: float) -> JsonDict:
    """POST 一个 JSON 请求体（消息推送接口用）。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _http_post(url, body, {"Content-Type": "application/json"}, timeout)


def _errmsg_with_help(errmsg: str, errcode: Optional[int]) -> str:
    """给可查的 errcode 附上官方排查链接。"""
    if isinstance(errcode, int) and errcode not in (0, -1):
        return f"{errmsg}（排查：{HELP_URL.format(errcode=errcode)}）"
    return errmsg


# ===================================================================== #
# 媒体预处理（图片 / 文件）
# ===================================================================== #
def _read_local_file(path: str, label: str = "本地") -> bytes:
    """读取本地二进制文件。

    :param label: 用途描述（如「图片」），仅用于错误提示。
    :raises WeComError: 文件不存在或读取失败。
    """
    if not os.path.isfile(path):
        raise WeComError(f"{label}文件不存在: {path}")
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as exc:
        raise WeComError(f"{label}文件读取失败: {path} ({_describe_exception(exc)})") from exc


def _base64_length(size: int) -> int:
    """计算 size 字节数据 base64 编码后的长度（按 4 字节对齐向上取整）。"""
    return (size + 2) // 3 * 4


def _sniff_image_mime(raw: bytes) -> Optional[str]:
    """按文件头魔数判定图片类型，不依赖扩展名与系统 MIME 注册表。"""
    for magic, mime in _IMAGE_MAGIC:
        if raw.startswith(magic):
            return mime
    return None


def _load_image(path: str) -> Tuple[bytes, str]:
    """读取本地图片并校验类型（企微仅支持 JPEG/PNG）。

    以文件头为准：扩展名是 .png 但内容是 webp 的文件会在本地就被拦下。

    :return: (原始字节, MIME 类型)
    :raises WeComError: 文件不存在或类型不受支持。
    """
    raw = _read_local_file(path, label="图片")
    mime = _sniff_image_mime(raw)
    if mime is None:
        guessed = mimetypes.guess_type(path)[0] or "未知"
        raise WeComError(
            f"企微仅支持 JPEG/PNG 图片，当前文件内容不是有效 JPEG/PNG"
            f"（扩展名推断为 {guessed}）: {path}")
    return raw, mime


def _compress_image(data: bytes, mime: str, max_bytes: int) -> bytes:
    """对超限图片逐级降质 / 缩放，直到 base64 后满足限制。需要 Pillow。

    PNG 是无损格式，quality 对它无效，因此 PNG 超限时先转 JPEG 再降质；
    JPEG 直接降质 + 缩放。

    :raises WeComError: 未安装 Pillow，或压缩到轮数上限仍超限。
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        raise WeComError(
            f"图片 base64 后超过 {max_bytes // 1024 // 1024}MB 限制，且未安装 Pillow 无法自动压缩。"
            "请 pip install pillow，或先手动压缩图片。"
        )

    image = Image.open(BytesIO(data))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    fmt = "JPEG" if mime == "image/jpeg" else "PNG"
    quality, ratio = 92, 0.9
    for round_index in range(MAX_COMPRESS_ROUNDS):
        if fmt == "PNG" and round_index >= 2:
            fmt = "JPEG"             # PNG 降不动了，转 JPEG 才有意义
            quality = 92
        buffer = BytesIO()
        if fmt == "JPEG":
            image.convert("RGB").save(buffer, format=fmt, quality=quality, optimize=True)
        else:
            image.save(buffer, format=fmt, optimize=True)
        data = buffer.getvalue()
        if _base64_length(len(data)) <= max_bytes:
            return data
        quality = max(30, quality - 8)
        width, height = image.size
        image = image.resize((max(1, int(width * ratio)), max(1, int(height * ratio))))
    raise WeComError("图片过大，自动压缩后仍超过限制，请手动处理后再发送。")


def _ensure_base64_size(base64_data: str, max_bytes: int) -> None:
    """校验 base64 字符串未超企微 image 体积上限。

    :raises WeComError: 超过上限。
    """
    size = len(base64_data)
    if size > max_bytes:
        raise WeComError(f"图片 base64 后 {size} 字节，超过 {max_bytes} 上限，发送被阻止。")


def prepare_image(path: str, max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
                  allow_compress: bool = True) -> Tuple[str, str]:
    """把本地图片加工成企微 image 消息所需的 (base64, md5)。

    :param max_bytes:      base64 后的字节上限（企微硬限制 2MB）。
    :param allow_compress: 超限时是否自动压缩（需要 Pillow）。
    :raises WeComError:    文件不存在、类型不支持或压缩后仍超限。
    """
    data, mime = _load_image(path)
    if _base64_length(len(data)) > max_bytes and allow_compress:
        data = _compress_image(data, mime, max_bytes)
    base64_data = base64.b64encode(data).decode("ascii")
    _ensure_base64_size(base64_data, max_bytes)
    return base64_data, hashlib.md5(data).hexdigest()


def _build_multipart(field: str, filename: str, raw: bytes) -> Tuple[bytes, str]:
    """手工拼 multipart/form-data 请求体（纯标准库）。

    :return: (请求体字节, boundary)
    """
    boundary = "----wecom" + uuid.uuid4().hex
    crlf = "\r\n"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    head = (f"--{boundary}{crlf}"
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"{crlf}'
            f"Content-Type: {content_type}{crlf}{crlf}").encode("utf-8")
    tail = f"{crlf}--{boundary}--{crlf}".encode("utf-8")
    return head + raw + tail, boundary


# ===================================================================== #
# 客户端主类
# ===================================================================== #
class WeComBot:
    """企业微信群机器人推送客户端（文本 / 富文本 / 卡片 / 图片 / 文件）。"""

    SUPPORTED_TYPES = ("text", "markdown", "markdown_v2", "template_card",
                       "image", "news", "file")
    MARKDOWN_TYPES = ("markdown", "markdown_v2")

    def __init__(self, key: Optional[str] = None, webhook: Optional[str] = None,
                 secret: Optional[str] = None, timeout: Optional[float] = None,
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 image_max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
                 default_msgtype: str = "markdown_v2",
                 min_interval: float = 0.0):
        """
        :param key:             webhook key；与 webhook 二选一，缺省读环境变量。
        :param webhook:         完整 webhook 地址（含 ?key=），优先级高于 key。
        :param secret:          安全设置「加解密密钥」，传了即启用签名校验。
        :param timeout:         单次请求超时（秒），缺省读环境变量或 8.0。
        :param max_bytes:       markdown 正文字节上限，超出自动截断。
        :param image_max_bytes: 图片 base64 上限（默认 2MB）。
        :param default_msgtype: send_markdown 未指定类型时的默认值。
        :param min_interval:    两次发送之间的最小间隔秒数（0 表示不节流）。
                                企微限频 20 条/分钟，批量推送建议 3.0。
        :raises WeComError:     配置不合法（缺 key、超时非数字、域名不符等）。
        """
        if timeout is None:
            timeout = self._timeout_from_env()
        self.timeout = float(timeout)
        self.max_bytes = max_bytes
        self.image_max_bytes = image_max_bytes
        self.secret = secret or os.environ.get(ENV_SECRET) or None
        self.default_msgtype = default_msgtype if default_msgtype in self.SUPPORTED_TYPES \
            else "markdown_v2"
        self.min_interval = max(0.0, float(min_interval))
        self._last_sent = 0.0
        self._rate_lock = threading.Lock()
        # URL 只存「不含签名」的版本，签名在每次请求前现算，避免 timestamp 过期
        self._base_url = resolve_webhook(webhook=webhook, key=key)
        self._key = extract_key(self._base_url)

    @staticmethod
    def _timeout_from_env() -> float:
        """读取 WECOM_TIMEOUT，非法值转成明确的 WeComError。"""
        raw = os.environ.get(ENV_TIMEOUT)
        if raw is None or raw == "":
            return DEFAULT_TIMEOUT
        try:
            return float(raw)
        except ValueError:
            raise WeComError(f"环境变量 {ENV_TIMEOUT} 不是合法数字: {raw!r}") from None

    @property
    def url(self) -> str:
        """当前请求要用的完整地址（启用签名时每次调用都刷新 timestamp）。"""
        if self.secret:
            return _append_signature(self._base_url, self.secret)
        return self._base_url

    @property
    def webhook_masked(self) -> str:
        """脱敏后的 webhook 地址，可直接打日志。"""
        return mask_url(self._base_url)

    def __repr__(self) -> str:
        return f"WeComBot(url={self.webhook_masked}, timeout={self.timeout})"

    # ── 内部工具 ────────────────────────────────────────────────────── #
    def _truncate(self, content: str, limit: Optional[int] = None) -> str:
        """按 UTF-8 字节安全截断，超出时给出告警，保证最终不超限。

        :param limit: 字节上限，缺省用 self.max_bytes。
        """
        limit = self.max_bytes if limit is None else limit
        raw = content.encode("utf-8")
        if len(raw) <= limit:
            return content
        note = "\n\n…（内容过长已截断）"
        budget = max(0, limit - len(note.encode("utf-8")))
        head = raw[:budget].decode("utf-8", "ignore")
        # 尽量在换行处收尾，别把 markdown 结构切一半
        newline = head.rfind("\n")
        if newline > budget // 2:
            head = head[:newline]
        _log_warn(f"内容 {len(raw)}B 超过 {limit}B 上限，已截断至 "
                  f"{len(head.encode('utf-8'))}B")
        return head + note

    @staticmethod
    def _guard(action: Callable[[], SendResult]) -> SendResult:
        """执行发送动作并把异常收敛为失败 SendResult，避免异常外泄。"""
        try:
            return action()
        except WeComError as exc:
            return SendResult.failure(str(exc))
        except Exception as exc:
            return SendResult.failure(_describe_exception(exc))

    def _throttle(self) -> None:
        """按 min_interval 节流，避免撞上企微 20 条/分钟的限制。"""
        if self.min_interval <= 0:
            return
        with self._rate_lock:
            wait = self.min_interval - (time.monotonic() - self._last_sent)
            if wait > 0:
                time.sleep(wait)
            self._last_sent = time.monotonic()

    # ── 低层发送 ────────────────────────────────────────────────────── #
    def send(self, payload: Payload, dry_run: bool = False) -> SendResult:
        """发送任意合法 webhook payload，网络 / 接口错误收敛为 SendResult。

        :param payload: 符合企业微信机器人消息格式的请求体（想发 news 等未封装类型时用这个）。
        :param dry_run: True 时只打印请求体不真正发送（返回 ok=True）。
        :raises WeComError: payload 不是对象或缺少 msgtype（仅此两种输入问题）。
        """
        if not isinstance(payload, dict) or "msgtype" not in payload:
            raise WeComError("payload 必须是包含 msgtype 的对象")

        if dry_run:
            _log_dry_run(payload)
            return SendResult.success("dry-run")

        self._throttle()
        response = _http_post_json(self.url, payload, self.timeout)
        status = response.pop("_status", None)
        errcode = response.get("errcode")
        if errcode == 0:
            return SendResult.success(status=status)
        errmsg = _errmsg_with_help(response.get("errmsg", f"未知错误: {response}"), errcode)
        if errcode == RATE_LIMIT_ERRCODE:
            errmsg = f"{errmsg}（已触发 20 条/分钟限频，请放慢节奏或设置 min_interval=3）"
        return SendResult.failure(errmsg, errcode, status)

    # ── 高层便捷方法 ────────────────────────────────────────────────── #
    def send_text(self, content: str, mentioned_list: Optional[Sequence[str]] = None,
                  mentioned_mobile_list: Optional[Sequence[str]] = None,
                  dry_run: bool = False) -> SendResult:
        """纯文本消息，可选 @成员（userid 列表）或 @手机号列表。

        正文按企微 text 类型上限（2048B）截断，即使 max_bytes 被调大也不会超。
        """
        limit = min(self.max_bytes, TEXT_MAX_BYTES)
        text: JsonDict = {"content": self._truncate(content, limit)}
        if mentioned_list:
            text["mentioned_list"] = list(mentioned_list)
        if mentioned_mobile_list:
            text["mentioned_mobile_list"] = list(mentioned_mobile_list)
        return self.send({"msgtype": "text", "text": text}, dry_run=dry_run)

    def send_markdown(self, content: str, msgtype: Optional[str] = None,
                      dry_run: bool = False) -> SendResult:
        """富文本卡片。

        :param msgtype: "markdown_v2"（默认，支持列表 / 表格 / 引用）或
                        "markdown"（旧版，全客户端兼容）；其它值回退 markdown_v2。
        """
        resolved = msgtype or self.default_msgtype
        if resolved not in self.MARKDOWN_TYPES:
            _log_warn(f"不支持的 markdown msgtype: {msgtype!r}，已回退 markdown_v2")
            resolved = "markdown_v2"
        return self.send({"msgtype": resolved,
                          resolved: {"content": self._truncate(content)}}, dry_run=dry_run)

    def send_template_card(self, title: str, desc: str = "",
                           items: Optional[Sequence[Tuple[str, str]]] = None,
                           source_desc: str = "", url: Optional[str] = None,
                           card_type: str = "text_notice",
                           dry_run: bool = False) -> SendResult:
        """结构化模板卡片。

        :param items:       [(键, 值), ...]，最多展示 6 项，超出会被明确告警。
        :param source_desc: 卡片左上角来源小字。
        :param url:         点击跳转地址，缺省用官方兜底链接。
        :raises WeComError: 标题为空、item 数量超限或 card_type 不支持。
        """
        def _build() -> SendResult:
            if not title.strip():
                raise WeComError("模板卡片 title 不能为空")
            if card_type != "text_notice":
                raise WeComError(
                    f"当前仅封装 text_notice 卡片，card_type={card_type!r} 需自行用 "
                    "send(payload) 构造（button_interaction / news_notice 字段结构不同）")

            pairs = list(items or [])
            if len(pairs) > MAX_CARD_ITEMS:
                raise WeComError(
                    f"模板卡片最多 {MAX_CARD_ITEMS} 项，当前传入 {len(pairs)} 项；"
                    "请精简后用 send(payload) 发多张卡片")
            card: JsonDict = {
                "card_type": card_type,
                "main_title": {"title": title, "desc": desc},
                "horizontal_content_list": [
                    {"keyname": str(k), "value": "" if v is None else str(v)}
                    for k, v in pairs
                ],
                "card_action": {"type": 1, "url": url or DEFAULT_CARD_URL},
            }
            if source_desc:
                card["source"] = {"desc": source_desc, "desc_color": 0}
            return self.send({"msgtype": "template_card", "template_card": card},
                             dry_run=dry_run)

        return self._guard(_build)

    def send_image(self, path: Optional[str] = None, base64_data: Optional[str] = None,
                   md5: Optional[str] = None, allow_compress: bool = True,
                   dry_run: bool = False) -> SendResult:
        """图片消息。

        二选一：给本地 path（自动校验类型 / 压缩 / base64 / md5），或给已算好的
        (base64_data, md5)。任何输入问题都以失败 SendResult 返回，不抛异常。
        dry_run 时只校验文件与类型，不做压缩（大图 dry-run 也不会卡住）。
        """
        def _build() -> SendResult:
            encoded, digest = base64_data, md5
            if path and not encoded:
                if dry_run:
                    _load_image(path)       # 只做类型校验，跳过压缩与编码
                    encoded, digest = "<dry-run-base64>", "<dry-run-md5>"
                else:
                    encoded, digest = prepare_image(path, self.image_max_bytes, allow_compress)
            if not encoded or not digest:
                raise WeComError("send_image 需提供 path，或同时提供 (base64_data, md5)")
            _ensure_base64_size(encoded, self.image_max_bytes)
            return self.send({"msgtype": "image", "image": {"base64": encoded, "md5": digest}},
                             dry_run=dry_run)

        return self._guard(_build)

    def send_file(self, local_path: str, filename: Optional[str] = None,
                  dry_run: bool = False) -> SendResult:
        """把本地文件作为「群文件」推送（upload_media → media_id → file 消息）。

        文件需在 5B~20MB；media_id 3 天内有效，且只能由上传它的机器人使用。

        :param filename: 群文件显示名，缺省取本地文件名。
        """
        def _build() -> SendResult:
            if dry_run:  # 只做本地校验（存在性 / 体积），不真正上传，避免触网
                self._read_file_checked(local_path)
                media_id = "<dry-run-media-id>"
            else:
                media_id = self._upload_media(local_path, filename)
            return self.send({"msgtype": "file", "file": {"media_id": media_id}},
                             dry_run=dry_run)

        return self._guard(_build)

    @staticmethod
    def _read_file_checked(local_path: str) -> bytes:
        """读取本地文件并校验体积（5B~20MB）。先按 stat 判体积，避免整块读进内存。

        :raises WeComError: 文件不存在或体积超出企微群文件限制。
        """
        if not os.path.isfile(local_path):
            raise WeComError(f"本地文件不存在: {local_path}")
        size = os.path.getsize(local_path)
        if size > MAX_FILE_BYTES:
            raise WeComError(f"文件 {local_path} 大小 {size}B 超过企微 20MB 上限")
        if size < MIN_FILE_BYTES:
            raise WeComError(f"文件 {local_path} 大小 {size}B 低于企微 5B 下限")
        return _read_local_file(local_path)

    def _upload_media(self, local_path: str, filename: Optional[str] = None) -> str:
        """上传本地文件到企微服务器并返回 media_id。

        :raises WeComError: 地址缺 key、上传失败或响应缺少 media_id。
        """
        raw = self._read_file_checked(local_path)
        if not self._key:
            raise WeComError(f"无法从 webhook 地址中抽取 key: {self.webhook_masked}")

        body, boundary = _build_multipart(
            "media", filename or os.path.basename(local_path), raw)
        self._throttle()
        response = _http_post(
            f"{UPLOAD_URL}?key={urllib.parse.quote(self._key, safe='')}&type=file", body,
            {"Content-Type": f"multipart/form-data; boundary={boundary}",
             "Content-Length": str(len(body))},
            self.timeout,
        )
        if response.get("errcode") != 0:
            raise WeComError(f"upload_media 失败 errcode={response.get('errcode')} "
                             f"errmsg={response.get('errmsg')}")
        media_id = response.get("media_id")
        if not media_id:
            raise WeComError(f"upload_media 响应缺少 media_id: {response}")
        return media_id


# ===================================================================== #
# 模块级便捷函数（返回 (ok, err) 元组，成功时 err 为空串）
# ===================================================================== #
def _new_bot(key: Optional[str], webhook: Optional[str], secret: Optional[str],
             timeout: Optional[float], min_interval: float = 0.0) -> WeComBot:
    """按公共入参构造一个临时客户端。"""
    return WeComBot(key=key, webhook=webhook, secret=secret, timeout=timeout,
                    min_interval=min_interval)


def _as_tuple(result: SendResult) -> Tuple[bool, str]:
    """把 SendResult 转成 (ok, err) 元组。"""
    return result.ok, ("" if result.ok else (result.errmsg or f"errcode={result.errcode}"))


def send_text(content: str, mentioned_list: Optional[Sequence[str]] = None,
              mentioned_mobile_list: Optional[Sequence[str]] = None, *,
              key: Optional[str] = None, webhook: Optional[str] = None,
              secret: Optional[str] = None, timeout: Optional[float] = None,
              dry_run: bool = False) -> Tuple[bool, str]:
    """推送纯文本。key / webhook / secret 缺省读环境变量。"""
    bot = _new_bot(key, webhook, secret, timeout)
    return _as_tuple(bot.send_text(content, mentioned_list, mentioned_mobile_list, dry_run))


def send_markdown(content: str, msgtype: str = "markdown_v2", *,
                  key: Optional[str] = None, webhook: Optional[str] = None,
                  secret: Optional[str] = None, timeout: Optional[float] = None,
                  dry_run: bool = False) -> Tuple[bool, str]:
    """推送 markdown 富文本卡片。msgtype 可选 markdown_v2（默认）/ markdown。"""
    bot = _new_bot(key, webhook, secret, timeout)
    return _as_tuple(bot.send_markdown(content, msgtype, dry_run))


def send_template_card(title: str, desc: str = "",
                       items: Optional[Sequence[Tuple[str, str]]] = None,
                       source_desc: str = "", url: Optional[str] = None, *,
                       key: Optional[str] = None, webhook: Optional[str] = None,
                       secret: Optional[str] = None, timeout: Optional[float] = None,
                       dry_run: bool = False) -> Tuple[bool, str]:
    """推送结构化模板卡片。items 为 [(键, 值), ...]，最多 6 项。"""
    bot = _new_bot(key, webhook, secret, timeout)
    return _as_tuple(bot.send_template_card(title, desc, items, source_desc, url,
                                            dry_run=dry_run))


def send_image(local_path: str, *, key: Optional[str] = None, webhook: Optional[str] = None,
               secret: Optional[str] = None, timeout: Optional[float] = None,
               allow_compress: bool = True,
               dry_run: bool = False) -> Tuple[bool, str]:
    """推送本地 JPEG/PNG 图片，超限时自动压缩（需 Pillow）。"""
    bot = _new_bot(key, webhook, secret, timeout)
    return _as_tuple(bot.send_image(local_path, allow_compress=allow_compress,
                                    dry_run=dry_run))


def send_file(local_path: str, filename: Optional[str] = None, *,
              key: Optional[str] = None, webhook: Optional[str] = None,
              secret: Optional[str] = None, timeout: Optional[float] = None,
              dry_run: bool = False) -> Tuple[bool, str]:
    """推送本地群文件（5B~20MB）。filename 为群内显示名，缺省取本地文件名。"""
    bot = _new_bot(key, webhook, secret, timeout)
    return _as_tuple(bot.send_file(local_path, filename, dry_run=dry_run))


# ===================================================================== #
# 命令行入口
# ===================================================================== #
def _load_content(value: str) -> str:
    """解析内容入参：'-' 读 stdin，'@文件路径' 读文件，其余按字面内容处理。

    注意：以 @ 开头但文件不存在时，仍按字面内容发送（兼容 "@all" 这类文本）。

    :raises WeComError: 读文件时发生 IO 错误。
    """
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@") and os.path.isfile(value[1:]):
        try:
            with open(value[1:], "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError as exc:
            raise WeComError(f"内容文件读取失败: {value[1:]} ({_describe_exception(exc)})") \
                from exc
    return value


def _summarize(content: str, width: int = 20) -> str:
    """把内容压成一行摘要，供 CLI 结果行展示（换行、空白折成空格）。"""
    flat = " ".join(content.split())
    return flat[:width] or "<空内容>"


def _parse_key_values(pairs: Optional[Sequence[str]]) -> List[Tuple[str, str]]:
    """把 --item k=v 序列解析成卡片项列表；无 '=' 时值取空串。"""
    items: List[Tuple[str, str]] = []
    for pair in pairs or []:
        name, separator, value = pair.partition("=")
        items.append((name, value if separator else ""))
    return items


def _build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器（子命令 + 公共参数）。"""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--key", help="webhook key（也可传完整 URL）")
    common.add_argument("--webhook", help="完整 webhook 地址（优先级高于 --key）")
    common.add_argument("--secret", help="安全设置「加解密密钥」，传了即启用签名校验")
    common.add_argument("--timeout", type=float, default=None, help="请求超时秒数")
    common.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                        help=f"markdown content 字节上限（默认 {DEFAULT_MAX_BYTES}）")
    common.add_argument("--image-max-bytes", type=int, default=DEFAULT_IMAGE_MAX_BYTES,
                        help="图片 base64 上限（默认 2MB）")
    common.add_argument("--rate", type=float, default=0.0, metavar="SEC",
                        help="两次发送的最小间隔秒数（批量推送建议 3，对应 20 条/分钟）")
    common.add_argument("--dry-run", action="store_true", help="只打印请求体，不真正发送")
    common.add_argument("-v", "--verbose", action="store_true", help="打印目标 webhook（脱敏）")

    parser = argparse.ArgumentParser(
        prog="wecom_notifier",
        description="企业微信群机器人推送工具（文本 / 富文本 / 卡片 / 图片 / 文件）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  wecom_notifier text '告警内容' --mention zhangsan\n"
               "  wecom_notifier markdown - < report.md\n"
               "  wecom_notifier markdown @report.md\n"
               "  wecom_notifier card '任务完成' --item 样本=155 --item 耗时=0.7s\n"
               "  wecom_notifier image a.png b.jpg --rate 3\n"
               "  wecom_notifier file ./report.html\n")
    parser.add_argument("--version", action="version",
                        version=f"wecom_notifier {__version__}")

    subparsers = parser.add_subparsers(dest="cmd", required=True)

    text_cmd = subparsers.add_parser("text", parents=[common], help="发送纯文本")
    text_cmd.add_argument("content", help="文本内容；'-' 读 stdin，'@文件路径' 读文件")
    text_cmd.add_argument("--mention", action="append", default=[], help="@成员 userid（可重复）")
    text_cmd.add_argument("--mention-mobile", action="append", default=[],
                          help="@手机号（可重复）")

    md_cmd = subparsers.add_parser("markdown", parents=[common], help="发送 markdown 卡片")
    md_cmd.add_argument("content", help="markdown 内容；'-' 读 stdin，'@文件路径' 读文件")
    md_cmd.add_argument("--v1", action="store_true", help="用旧版 markdown（默认 markdown_v2）")

    card_cmd = subparsers.add_parser("card", parents=[common], help="发送模板卡片")
    card_cmd.add_argument("title")
    card_cmd.add_argument("--desc", default="", help="标题下方描述")
    card_cmd.add_argument("--item", action="append", default=[],
                          help=f"卡片项 key=value（最多 {MAX_CARD_ITEMS} 项）")
    card_cmd.add_argument("--source", default="", dest="source_desc", help="卡片来源小字")
    card_cmd.add_argument("--url", default=None, help="点击卡片跳转链接")

    image_cmd = subparsers.add_parser("image", parents=[common], help="发送本地图片（JPEG/PNG）")
    image_cmd.add_argument("paths", nargs="+")
    image_cmd.add_argument("--no-compress", action="store_true",
                           help="超限时不自动压缩，直接报错")

    file_cmd = subparsers.add_parser("file", parents=[common], help="发送本地群文件（5B~20MB）")
    file_cmd.add_argument("path")
    file_cmd.add_argument("--name", default=None, help="群文件显示名，默认取本地文件名")

    return parser


def _run_command(args: argparse.Namespace, bot: WeComBot) -> List[Tuple[str, SendResult]]:
    """按子命令分发执行，返回 [(任务名, 结果), ...]；image 子命令支持多图批量。"""
    if args.cmd == "text":
        content = _load_content(args.content)
        return [(_summarize(content), bot.send_text(
            content, args.mention, args.mention_mobile, args.dry_run))]
    if args.cmd == "markdown":
        content = _load_content(args.content)
        msgtype = "markdown" if args.v1 else "markdown_v2"
        return [(_summarize(content), bot.send_markdown(content, msgtype, args.dry_run))]
    if args.cmd == "card":
        return [(args.title, bot.send_template_card(
            args.title, args.desc, _parse_key_values(args.item), args.source_desc, args.url,
            dry_run=args.dry_run))]
    if args.cmd == "image":
        return [(path, bot.send_image(path, allow_compress=not args.no_compress,
                                      dry_run=args.dry_run)) for path in args.paths]
    if args.cmd == "file":
        return [(args.path, bot.send_file(args.path, args.name, args.dry_run))]
    return []


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口。

    :return: 0 全部成功；1 有推送失败；2 配置或输入错误。
    """
    args = _build_parser().parse_args(argv)

    try:
        bot = WeComBot(key=args.key, webhook=args.webhook, secret=args.secret,
                       timeout=args.timeout, max_bytes=args.max_bytes,
                       image_max_bytes=args.image_max_bytes,
                       min_interval=args.rate)
    except WeComError as exc:
        _log_error(f"配置错误: {exc}")
        return 2

    if args.verbose or args.dry_run:
        _log_info(f"目标 webhook: {bot.webhook_masked}")

    try:
        results = _run_command(args, bot)
    except WeComError as exc:
        _log_error(f"输入错误: {exc}")
        return 2

    failed = 0
    for name, result in results:
        if result.ok:
            _report_success(name)
        else:
            failed += 1
            _report_failure(name, result)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass
    sys.exit(main())
