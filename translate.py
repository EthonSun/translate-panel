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

# ---- ANSI ----
CLEAR = "\033[2J\033[H"
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

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
                + target + ". Output ONLY the translation, no quotes, no notes, "
                "no explanations. Preserve the original meaning and tone."},
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


def wrap(text, width=72):
    # 简单按宽度折行（按字符，中文也算 1，够用）
    lines = []
    for raw in text.split("\n"):
        while len(raw) > width:
            lines.append(raw[:width])
            raw = raw[width:]
        lines.append(raw)
    return "\n".join(lines)


def render(status, original="", result="", err=""):
    sys.stdout.write(CLEAR)
    sys.stdout.write(BOLD + CYAN + "  划词翻译 · DeepSeek" + RESET +
                     DIM + "   (Mod+Z 关闭)" + RESET + "\n")
    sys.stdout.write(DIM + "  " + "─" * 72 + RESET + "\n\n")
    if status:
        sys.stdout.write("  " + DIM + status + RESET + "\n")
    if original:
        sys.stdout.write("  " + DIM + "原文" + RESET + "\n")
        for ln in wrap(original).split("\n"):
            sys.stdout.write("  " + ln + "\n")
        sys.stdout.write("\n  " + GREEN + "译文" + RESET + "\n")
        if result:
            for ln in wrap(result).split("\n"):
                sys.stdout.write("  " + BOLD + ln + RESET + "\n")
        elif err:
            sys.stdout.write("  " + RED + err + RESET + "\n")
        else:
            sys.stdout.write("  " + YELLOW + "翻译中…" + RESET + "\n")
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

        original = sel[:MAX_LEN]
        last_done = sel
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
