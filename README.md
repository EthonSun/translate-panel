# 划词翻译面板（Niri + DeepSeek）

一个轻量的 Wayland 划词翻译小工具：按快捷键在屏幕左下角弹出一个 foot 面板，之后在
**任意窗口**里划选高亮文字即实时翻译（中↔英自动判断），再按一次关闭并停止监听。

为 [Niri](https://github.com/YaLTeR/niri) 合成器 + DeepSeek API 定制。

## 原理

Wayland/X11 有「主选区(primary selection)」：高亮文字会自动进入主选区，**无需 Ctrl+C**。
面板循环用 `wl-paste --primary` 读取选区变化，去抖/去重/过滤后调 DeepSeek 翻译。
因此本工具**不模拟复制、不触碰你的剪贴板**，比 Windows 划词工具干净。

误触控制：面板关闭时完全不监听；开启时有去抖（拖选结束才翻）、最小 2 字符、纯数字/
标点忽略、相同文本不重翻、选中译文不回环。

## 文件

| 文件 | 作用 |
|------|------|
| `translate.py` | 面板主体（Python 标准库，零依赖）。轮询主选区 → 过滤 → DeepSeek → 终端刷原文+译文 |
| `toggle.sh` | 开关：未运行则在左下角起 foot 面板，已运行则关闭 |

## 依赖

- `wl-clipboard`（`wl-paste`）
- `foot` 终端
- `python3`（仅标准库）
- DeepSeek API key，放在 `~/.config/deepseek/api_key`（权限 600，**不纳入版本控制**）

## 安装 / Niri 配置

把 key 写入 `~/.config/deepseek/api_key`：

```sh
echo 'sk-你的key' > ~/.config/deepseek/api_key && chmod 600 ~/.config/deepseek/api_key
```

在 `~/.config/niri/config.kdl` 里加（binds 段）：

```kdl
Mod+Z hotkey-overlay-title="Toggle Translate Panel" { spawn "sh" "-c" "exec ~/.config/niri/translate/toggle.sh"; }
```

以及一条 window-rule（浮动、固定大小、贴左下角）：

```kdl
window-rule {
    match app-id=r#"^transpanel$"#
    open-floating true
    default-column-width { fixed 340; }
    default-window-height { fixed 440; }
    default-floating-position x=20 y=20 relative-to="bottom-left"
}
```

面板的字号 / 内边距 / 配色在 `toggle.sh` 启动 foot 的 `-o` 参数里（`font=monospace:size=14`、
`pad=20x18`、Nord 背景）。窗口大小在上面的 window-rule，配色排版在 `translate.py`。

niri 监听配置文件，保存即热重载（可先 `niri validate -c ~/.config/niri/config.kdl`）。

## 用法

- `Mod+Z`：开/关面板。
- 面板开着时，在任意窗口划选文字即翻译。

## 微调

- 位置 / 大小：`config.kdl` 里 `transpanel` 规则的 `default-floating-position` 与 `fixed` 尺寸。
- 灵敏度 / 长度上限：`translate.py` 顶部的 `POLL_INTERVAL`、`MIN_LEN`、`MAX_LEN`。
- 模型 / 翻译风格：`translate.py` 的 `MODEL` 与 system prompt。
