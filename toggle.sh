#!/usr/bin/env bash
# 划词翻译面板开关：在运行 → 关闭；没运行 → 在左下角开一个 foot 面板。
# 单纯开/关进程（轻量工具），不像微信那套藏到别的工作区。
# 用唯一 app-id "transpanel" 识别窗口，niri window-rule 据此浮动+定位。

APPID="transpanel"
SCRIPT="$HOME/.config/niri/translate/translate.py"

if pgrep -f "foot --app-id=$APPID" >/dev/null 2>&1; then
    pkill -f "foot --app-id=$APPID"
else
    exec foot --app-id="$APPID" --title="划词翻译" python3 "$SCRIPT"
fi
