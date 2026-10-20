# 生成 wecom_notifier README 配图（SVG，GitHub 原生渲染，深浅色自适应；PNG 仅为本地预览，不入库）

$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$F = "font-family='-apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif'"
$M = "font-family='ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'"

$defs = @"
<defs>
  <linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#2b7fff"/>
    <stop offset="100%" stop-color="#07c160"/>
  </linearGradient>
  <linearGradient id="g2" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="#07c160"/>
    <stop offset="100%" stop-color="#2b7fff"/>
  </linearGradient>
</defs>
"@

$head = @"
<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="{1}" viewBox="0 0 {0} {1}" role="img" aria-label="{2}">
$defs
<style>
  :root {{ --bg:#f6f8fa; --fg:#1f2328; --muted:#656d76; --line:#d0d7de; --card:#ffffff; --code:#eff2f5; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --line:#30363d; --card:#161b22; --code:#1c2128; }}
  }}
  text {{ fill: var(--fg); }}
  .m {{ fill: var(--muted); }}
  .cd {{ fill: var(--card); stroke: var(--line); stroke-width:1; }}
  .ln {{ stroke: var(--line); stroke-width:1; }}
  .ac {{ stroke: url(#g2); stroke-width:2; fill:none; }}
</style>
"@

# ================= 图 1：三入口 =================
$cols = @(
  @{ x=24;  t="命令行";     s="任何机器，一行搞定";        c="#2b7fff"; l1="python wecom_notifier.py"; l2="       text `"CPU 95%`"" },
  @{ x=308; t="Python API"; s="嵌进你自己的脚本";          c="#07c160"; l1="from wecom_notifier"; l2="       import WeComBot" },
  @{ x=592; t="定时任务";   s="青龙 / cron 自动播报";      c="#8b5cf6"; l1="QYWX_KEY 自动读取"; l2="退出码判断成败" }
)
$b = ""
foreach ($c in $cols) {
  $b += "  <rect class='cd' x='$($c.x)' y='64' width='264' height='136' rx='10' fill='var(--card)'/>`n"
  $b += "  <rect x='$($c.x)' y='64' width='264' height='4' rx='2' fill='$($c.c)'/>`n"
  $b += "  <text $F x='$($c.x + 20)' y='98' font-size='15' font-weight='700'>$($c.t)</text>`n"
  $b += "  <text $F x='$($c.x + 20)' y='120' font-size='12' class='m'>$($c.s)</text>`n"
  $b += "  <rect x='$($c.x + 20)' y='134' width='224' height='50' rx='6' fill='var(--code)'/>`n"
  $b += "  <text $M x='$($c.x + 32)' y='155' font-size='11.5'>$($c.l1)</text>`n"
  $b += "  <text $M x='$($c.x + 32)' y='174' font-size='11.5'>$($c.l2)</text>`n"
}
Set-Content -Path "$dir\hero.svg" -Encoding UTF8 -Value (($head -f 880, 224, "三种使用方式") + @"
  <text $F x='24' y='32' font-size='17' font-weight='700'>三种用法，同一份代码</text>
  <text $F x='856' y='32' font-size='12' class='m' text-anchor='end'>零强制依赖 · Python 3.8+</text>
$b
</svg>
"@)

# ================= 图 2：五类消息 =================
$rows = @(
  @{ y=64;  t="text";          d="纯文本 · 可 @人";             l="≤ 2048 字节";      c="#2b7fff" },
  @{ y=112; t="markdown_v2";   d="标题 / 列表 / 表格 / 引用";    l="≤ 4096 字节";      c="#07c160" },
  @{ y=160; t="template_card"; d="结构化 key-value 卡片";       l="≤ 6 项";           c="#8b5cf6" },
  @{ y=208; t="image";         d="JPEG / PNG · 按魔数判定";      l="base64 ≤ 2MB";     c="#f59e0b" },
  @{ y=256; t="file";          d="群文件 · 内置浏览器预览";      l="5B ~ 20MB";        c="#ef4444" }
)
$b = ""
foreach ($r in $rows) {
  $b += "  <rect class='cd' x='24' y='$($r.y)' width='200' height='40' rx='8' fill='var(--card)'/>`n"
  $b += "  <rect x='24' y='$($r.y)' width='4' height='40' rx='2' fill='$($r.c)'/>`n"
  $b += "  <text $M x='40' y='$($r.y + 25)' font-size='14' font-weight='600'>$($r.t)</text>`n"
  $b += "  <text $F x='248' y='$($r.y + 25)' font-size='14' class='m'>$($r.d)</text>`n"
  $b += "  <text $M x='836' y='$($r.y + 25)' font-size='13' class='m' text-anchor='end'>$($r.l)</text>`n"
}
Set-Content -Path "$dir\message-types.svg" -Encoding UTF8 -Value (($head -f 880, 308, "wecom_notifier 支持的 5 类消息") + @"
  <text $F x='24' y='32' font-size='17' font-weight='700'>一个文件，五类消息</text>
  <text $F x='836' y='32' font-size='12' class='m' text-anchor='end'>上限取自企业微信官方接口</text>
  <line class='ln' x1='24' y1='44' x2='836' y2='44'/>
$b
</svg>
"@)

# ================= 图 3：key 解析优先级 =================
$steps = @(
  @{ x=24;  l="--webhook";         n="完整地址" },
  @{ x=196; l="--key";             n="key 或地址" },
  @{ x=368; l="WECOM_WEBHOOK";     n="完整地址" },
  @{ x=540; l="WECOM_WEBHOOK_KEY"; n="只放 key" },
  @{ x=712; l="QYWX_KEY";          n="青龙自动注入" }
)
$b = ""
foreach ($s in $steps) {
  $b += "  <rect class='cd' x='$($s.x)' y='76' width='150' height='54' rx='8' fill='var(--card)'/>`n"
  $b += "  <text $M x='$($s.x + 75)' y='100' font-size='12.5' font-weight='600' text-anchor='middle'>$($s.l)</text>`n"
  $b += "  <text $F x='$($s.x + 75)' y='118' font-size='11.5' class='m' text-anchor='middle'>$($s.n)</text>`n"
}
for ($i = 0; $i -lt 4; $i++) {
  $x = 174 + $i * 172
  $b += "  <path class='ac' d='M$x 103 h18'/>`n"
  $b += "  <path d='M$($x + 14) 99 l7 4 -7 4 z' fill='#07c160'/>`n"
}
Set-Content -Path "$dir\key-resolution.svg" -Encoding UTF8 -Value (($head -f 880, 292, "webhook key 解析优先级") + @"
  <text $F x='24' y='32' font-size='17' font-weight='700'>key 从哪来：命中即止</text>
  <text $F x='856' y='32' font-size='12' class='m' text-anchor='end'>青龙面板用户无需任何配置</text>

  <rect x='24' y='56' width='832' height='94' rx='10' fill='none' stroke='url(#g2)' stroke-width='1.5' stroke-dasharray='6 4'/>
$b
  <rect class='cd' x='24' y='172' width='832' height='48' rx='8' fill='var(--card)'/>
  <text $F x='44' y='202' font-size='13.5'>以上都没有 → 打印配置指引，退出码 <tspan $M font-weight='700'>2</tspan>（没有内置 key）</text>

  <text $F x='24' y='252' font-size='12' class='m'>额外变量</text>
  <text $M x='98' y='252' font-size='12'>WECOM_SECRET</text>
  <text $F x='214' y='252' font-size='12' class='m'>启用签名校验</text>
  <text $M x='338' y='252' font-size='12'>WECOM_TIMEOUT</text>
  <text $F x='446' y='252' font-size='12' class='m'>超时秒数，默认 8.0</text>
</svg>
"@)

# ================= 图 4：一次发送的链路 =================
$stages = @(
  @{ y=60;  n="1"; t="解析 key";     d="参数 → 环境变量 → 域名白名单校验" },
  @{ y=122; n="2"; t="构造 payload"; d="截断 / 校验 / 魔数判定，非法直接抛 WeComError" },
  @{ y=184; n="3"; t="节流 + 签名";   d="min_interval 等待，每次请求前现算 timestamp" },
  @{ y=246; n="4"; t="发送 + 收敛";   d="网络异常与 5xx 不抛异常，统一为 SendResult" }
)
$b = ""
foreach ($s in $stages) {
  $b += "  <rect class='cd' x='24' y='$($s.y)' width='600' height='50' rx='8' fill='var(--card)'/>`n"
  $b += "  <circle cx='52' cy='$($s.y + 25)' r='13' fill='url(#g1)'/>`n"
  $b += "  <text x='52' y='$($s.y + 30)' font-size='13' font-weight='700' fill='#ffffff' text-anchor='middle'>$($s.n)</text>`n"
  $b += "  <text $F x='78' y='$($s.y + 22)' font-size='14' font-weight='600'>$($s.t)</text>`n"
  $b += "  <text $F x='78' y='$($s.y + 40)' font-size='12' class='m'>$($s.d)</text>`n"
}
for ($i = 0; $i -lt 3; $i++) {
  $y = 110 + $i * 62
  $b += "  <path class='ac' d='M324 $y v12'/>`n"
  $b += "  <path d='M320 $($y + 8) l4 7 4 -7 z' fill='#07c160'/>`n"
}
$b += "  <path class='ac' d='M629 271 h21'/>`n"
$b += "  <path d='M645 267 l7 4 -7 4 z' fill='#07c160'/>`n"
Set-Content -Path "$dir\send-pipeline.svg" -Encoding UTF8 -Value (($head -f 880, 320, "一次推送的完整链路") + @"
  <text $F x='24' y='32' font-size='17' font-weight='700'>一次发送发生了什么</text>
  <text $F x='856' y='32' font-size='12' class='m' text-anchor='end'>网络失败不让进程崩掉</text>

$b
  <rect x='656' y='122' width='200' height='114' rx='10' fill='none' stroke='var(--line)' stroke-dasharray='5 4'/>
  <text $F x='756' y='148' font-size='12.5' font-weight='600' text-anchor='middle'>失败也不崩</text>
  <text $M x='756' y='170' font-size='11.5' class='m' text-anchor='middle'>errcode / status</text>
  <text $M x='756' y='188' font-size='11.5' class='m' text-anchor='middle'>retryable</text>
  <text $F x='756' y='206' font-size='11.5' class='m' text-anchor='middle'>官方排查链接</text>
  <text $F x='756' y='224' font-size='11.5' class='m' text-anchor='middle'>退出码</text>

  <text $F x='24' y='312' font-size='11.5' class='m'>只有输入不合法（文件缺失 / 格式不支持 / 超过上限 / payload 缺 msgtype）才抛 WeComError</text>
</svg>
"@)

# ================= 导出 PNG 预览 =================
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (Test-Path $edge) {
  $sizes = @{ "hero" = "880,224"; "message-types" = "880,308"; "key-resolution" = "880,292"; "send-pipeline" = "880,320" }
  $p = $dir -replace '\\', '/'
  foreach ($k in $sizes.Keys) {
    & $edge --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 `
      --window-size=$($sizes[$k]) --user-data-dir="$env:TEMP\edge-shot" `
      --screenshot="$dir\$k.png" "file:///$p/$k.svg" 2>$null | Out-Null
  }
}
Get-ChildItem $dir | Select-Object Name, Length


