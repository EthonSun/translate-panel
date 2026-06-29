#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
划词翻译面板（在 foot 终端里跑的常驻循环）。

机制：每 ~0.3s 读一次 Wayland 主选区(primary selection)。一旦你在任意窗口里划选
高亮文字，文本会自动进主选区（无需 Ctrl+C）——本脚本读到变化、去抖去重后调
DeepSeek 翻译，把原文+译文刷在这个终端面板里。关掉这个窗口（Mod+Z）即停止监听。

依赖：wl-clipboard(wl-paste)、curl 无关（用 urllib 标准库）。API key 见 KEY_PATH。
"""
import os
import re
import sys
import json
import time
import signal
import shutil
import unicodedata
import subprocess
import urllib.request
import urllib.error

# ---- 配置 ----
KEY_PATH = os.path.expanduser("~/.config/deepseek/api_key")
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
POLL_INTERVAL = 0.3          # 轮询间隔(秒)
MIN_LEN = 2                  # 少于这个字符数不翻
MAX_LEN = 2000               # 超长截断，避免误选整页狂烧 token
TIMEOUT = 30

# ---- 配色：Nord 调色板（真彩色），与系统 fcitx5 Nord 主题呼应 ----
def fg(hexcol):
    r, g, b = int(hexcol[0:2], 16), int(hexcol[2:4], 16), int(hexcol[4:6], 16)
    return "\033[38;2;%d;%d;%dm" % (r, g, b)


def bg(hexcol):
    r, g, b = int(hexcol[0:2], 16), int(hexcol[2:4], 16), int(hexcol[4:6], 16)
    return "\033[48;2;%d;%d;%dm" % (r, g, b)


RESET = "\033[0m"
BOLD = "\033[1m"
CLEAR = "\033[2J\033[3J\033[H"

# Nord
N_BG = "2e3440"        # polar night 0（窗口底色）
N_BAR = "434c5e"       # polar night 2（标题栏底）
N_MUTED = "616e88"     # 弱化文字 / 分隔线
N_FAINT = "7b88a1"     # 原文文字
SNOW = "eceff4"        # 高亮白（译文）
FROST = "88c0d0"       # 青（标题图标 / 原文标记）
FROST2 = "81a1c1"      # 蓝青（方向徽标）
GREEN = "a3be8c"       # 译文标记
RED = "bf616a"
YELLOW = "ebcb8b"

CJK = re.compile(r"[一-鿿぀-ヿ゠-ヿ가-힯]")
JUNK = re.compile(r"^[\s\d\W_]+$")  # 纯空白/数字/标点 → 忽略


def load_key():
    try:
        with open(KEY_PATH, "r") as f:
            k = f.read().strip()
        if not k or k == "PASTE-YOUR-DEEPSEEK-API-KEY-HERE":
            return None
        return k
    except OSError:
        return None


def read_primary():
    try:
        out = subprocess.run(
            ["wl-paste", "--primary", "--no-newline", "--type", "text/plain"],
            capture_output=True, timeout=2,
        )
        if out.returncode != 0:
            # 某些内容没有 text/plain 类型时退回默认
            out = subprocess.run(
                ["wl-paste", "--primary", "--no-newline"],
                capture_output=True, timeout=2,
            )
        return out.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def unescape(text):
    # 某些源（部分 PDF 阅读器 / app）把文字以 \uXXXX / \xXX 转义形式放进选区，
    # 解码回真字符，否则中文被当成纯 ASCII、方向判错、原文显示成 \u 乱码。
    if re.search(r"\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\U[0-9a-fA-F]{8}", text):
        text = re.sub(r"\\U([0-9a-fA-F]{8})", lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    return text


def normalize(text):
    # 去掉 PDF/排版造成的硬换行：行尾连字符断词拼回、段内单换行按中英规则合并、
    # 保留空行作段落分隔。
    text = unescape(text).strip()
    # 行尾连字符断词： "inter-\nnational" -> "international"
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)

    def join(m):
        s = m.string
        left = s[m.start() - 1]
        right = s[m.end()] if m.end() < len(s) else ""
        # 中文/全角之间直接相接，不补空格；其余补一个空格
        if CJK.match(left) and CJK.match(right):
            return ""
        return " "

    # 仅合并“两侧都是非空白”的单换行（段落间的空行不动）
    text = re.sub(r"(?<=\S)[ \t]*\n[ \t]*(?=\S)", join, text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def detect_target(text):
    # 含中日韩 → 译成英文；否则 → 译成中文
    return "English" if CJK.search(text) else "Chinese (Simplified)"


def translate(text, key):
    target = detect_target(text)
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content":
                "You are a translation engine. Translate the user's text into "
                + target + ". The input may be copied from a PDF or document, so "
                "ignore line breaks, hyphenation and spacing introduced by "
                "formatting and treat it as continuous flowing text. Output ONLY "
                "the translation, no quotes, no notes, no explanations. Preserve "
                "the original meaning and tone."},
            {"role": "user", "content": text},
        ],
        "temperature": 1.0,
        "stream": False,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"].strip()


_ANSI = re.compile(r"\033\[[0-9;]*m")


def disp_len(s):
    # 显示宽度：CJK/全角算 2 列，忽略 ANSI 转义
    s = _ANSI.sub("", s)
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in s)


def wrap(text, width):
    # 按显示宽度折行（CJK 算 2 列）
    out = []
    for raw in text.split("\n"):
        line, w = "", 0
        for ch in raw:
            cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            if w + cw > width and line:
                out.append(line)
                line, w = "", 0
            line += ch
            w += cw
        out.append(line)
    return out


def badge(original):
    # 翻译方向徽标
    return "中文 → EN" if CJK.search(original) else "EN → 中文"


def render(status="", original="", result="", err=""):
    cols = shutil.get_terminal_size((68, 22)).columns
    inner = max(20, cols - 4)
    P = "  "
    o = [CLEAR]

    # 标题栏：整行底色，左标题 + 右方向徽标
    left = BOLD + fg(FROST) + " ✦  " + fg(SNOW) + "划词翻译 "
    right = (fg(FROST2) + badge(original) + " ") if original else ""
    gap = max(1, cols - disp_len(left) - disp_len(right))
    o.append(bg(N_BAR) + left + " " * gap + right + RESET + "\n\n")

    if status:
        o.append(P + fg(N_FAINT) + status + RESET + "\n")
    if err and not original:
        o.append(P + fg(RED) + err + RESET + "\n")

    if original:
        o.append(P + fg(FROST) + "▎ " + fg(N_MUTED) + "原文" + RESET + "\n")
        for ln in wrap(original, inner):
            o.append(P + fg(N_FAINT) + ln + RESET + "\n")
        o.append("\n")
        o.append(P + fg(GREEN) + "▎ " + fg(N_MUTED) + "译文" + RESET + "\n")
        if result:
            for ln in wrap(result, inner):
                o.append(P + BOLD + fg(SNOW) + ln + RESET + "\n")
        elif err:
            for ln in wrap(err, inner):
                o.append(P + fg(RED) + ln + RESET + "\n")
        else:
            o.append(P + fg(YELLOW) + "⠿ 翻译中…" + RESET + "\n")

    # 页脚
    o.append("\n" + P + fg(N_MUTED) + "─" * min(inner, 44) + RESET + "\n")
    o.append(P + fg(N_MUTED) + "Mod+Z 关闭 · 划选即译" + RESET + "\n")

    sys.stdout.write("".join(o))
    sys.stdout.flush()


def main():
    signal.signal(signal.SIGINT, lambda *a: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))

    key = load_key()
    if not key:
        render("", err="未找到 API key：请把 DeepSeek key 写入 " + KEY_PATH)
        # 没 key 也别退出，方便填好后无需重开；每 3s 重读一次
        while not key:
            time.sleep(3)
            key = load_key()

    render("划选任意文字即翻译…")

    last_seen = None        # 上一次轮询读到的选区(用于去抖)
    last_done = None        # 上一次实际翻译过的原文(去重)
    last_result = None      # 上一次的译文(避免把自己的译文当输入)
    stable = None           # 候选稳定值

    while True:
        time.sleep(POLL_INTERVAL)
        sel = read_primary().strip()
        if not sel or len(sel) < MIN_LEN or JUNK.match(sel):
            last_seen = sel
            continue
        # 去抖：要连续两次读到同一个值（说明拖选已结束）才翻
        if sel != last_seen:
            last_seen = sel
            stable = None
            continue
        if sel == stable:
            continue            # 已经处理过这个稳定值
        stable = sel
        # 去重：和上次翻过的、或上次的译文相同就跳过（后者防选中译文回环）
        if sel == last_done or sel == last_result:
            continue

        # 解转义 + 去除排版换行后，再显示/翻译（显示的就是清理后的流式文本）
        original = normalize(sel)[:MAX_LEN]
        last_done = sel
        if not original or len(original) < MIN_LEN:
            continue
        render("", original=original)   # 先显示原文 + “翻译中…”
        try:
            result = translate(original, key)
            last_result = result
            render("", original=original, result=result)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            render("", original=original, err="HTTP %s: %s" % (e.code, body))
        except urllib.error.URLError as e:
            render("", original=original, err="网络错误: %s（Clash 开着吗？）" % e.reason)
        except Exception as e:
            render("", original=original, err="出错: %r" % e)


if __name__ == "__main__":
    main()
