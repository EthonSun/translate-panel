#!/usr/bin/env bash
# 划词翻译面板开关：在运行 → 关闭；没运行 → 在左下角开一个 foot 面板。
# 单纯开/关进程（轻量工具），不像微信那套藏到别的工作区。
# 用唯一 app-id "transpanel" 识别窗口，niri window-rule 据此浮动+定位。

APPID="transpanel"
SCRIPT="$HOME/.config/niri/translate/translate.py"

if pgrep -f "foot --app-id=$APPID" >/dev/null 2>&1; then
    pkill -f "foot --app-id=$APPID"
else
    # 字号调大、加内边距、Nord 深色背景（与脚本里的 Nord 配色一致）。
    exec foot --app-id="$APPID" --title="划词翻译" \
        -o font="monospace:size=14" \
        -o pad="20x18" \
        -o background="2e3440" \
        -o foreground="d8dee9" \
        -o "cursor.style=beam" \
        python3 "$SCRIPT"
fi
