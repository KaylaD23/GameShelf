"""GameShelf themes, applied live and saved through the existing Settings file.

Qt palette + stylesheet + delegate colors are kept in one place.
"""
from __future__ import annotations

THEMES = {
    "dark": {"label": "GameShelf Dark", "window": "#10141d", "sidebar": "#131a25", "details": "#151c28", "panel": "#1d2735", "button": "#273448", "button_hover": "#34465e", "border": "#35465d", "soft_border": "#293345", "text": "#e5eaf3", "muted": "#98a6bd", "accent": "#58adeb", "accent_hover": "#9ad5ff", "accent_text": "#081421", "selection": "#28435c", "grid": "#1c2635", "grid_hover": "#243449", "grid_border": "#283a4e", "highlight_border": "#ffe99e", "footer": "#172131"},
    "graphite": {"label": "Graphite", "window": "#17191b", "sidebar": "#202225", "details": "#222527", "panel": "#292d31", "button": "#363c41", "button_hover": "#4b5259", "border": "#515a61", "soft_border": "#3b4147", "text": "#f0f2f4", "muted": "#afb7bf", "accent": "#a6b9d0", "accent_hover": "#d1e0ef", "accent_text": "#121719", "selection": "#485463", "grid": "#272d31", "grid_hover": "#343d44", "grid_border": "#59616a", "highlight_border": "#e2ddd0", "footer": "#2b2f34"},
    "midnight": {"label": "Midnight Blue", "window": "#08162b", "sidebar": "#0b203c", "details": "#0d2746", "panel": "#143454", "button": "#1a4164", "button_hover": "#25618d", "border": "#396f96", "soft_border": "#224e77", "text": "#e9f5ff", "muted": "#adc6df", "accent": "#42c5fa", "accent_hover": "#92e4ff", "accent_text": "#071a2b", "selection": "#205a86", "grid": "#102b48", "grid_hover": "#18436a", "grid_border": "#2a5981", "highlight_border": "#9ce5ff", "footer": "#0f2e4e"},
    "violet": {"label": "Neon Violet", "window": "#150f25", "sidebar": "#1d1531", "details": "#201735", "panel": "#302347", "button": "#43325a", "button_hover": "#60417c", "border": "#655184", "soft_border": "#382750", "text": "#f5edff", "muted": "#c1afd8", "accent": "#bd7bff", "accent_hover": "#deb3ff", "accent_text": "#170e27", "selection": "#51316e", "grid": "#271c3d", "grid_hover": "#3c2759", "grid_border": "#583d72", "highlight_border": "#f3c7ff", "footer": "#26193f"},
    "amoled": {"label": "OLED Black", "window": "#050505", "sidebar": "#0c0c0e", "details": "#101012", "panel": "#1a1a1e", "button": "#26262b", "button_hover": "#34343b", "border": "#50505b", "soft_border": "#29292e", "text": "#f5f5f8", "muted": "#babac7", "accent": "#66dfff", "accent_hover": "#aff1ff", "accent_text": "#02121a", "selection": "#1b4a5b", "grid": "#111116", "grid_hover": "#1c1c25", "grid_border": "#393943", "highlight_border": "#eafaff", "footer": "#111118"},
}
THEME_KEYS = tuple(THEMES)
CURRENT_THEME = "dark"

# Exact replacements avoid unintended text substitutions. The original STYLE
# remains canonical so theme changes cannot compound colors repeatedly.
BASE_COLORS = {
    "#10141d": "window", "#131a25": "sidebar", "#151c28": "details",
    "#1d2735": "panel", "#273448": "button", "#34465e": "button_hover",
    "#35465d": "border", "#293345": "soft_border", "#e5eaf3": "text",
    "#98a6bd": "muted", "#58adeb": "accent", "#9ad5ff": "accent_hover",
    "#081421": "accent_text", "#28435c": "selection", "#1c2635": "grid",
    "#243449": "grid_hover", "#283a4e": "grid_border", "#ffe99e": "highlight_border",
    "#172131": "footer", "#f4f6fa": "text", "#f8fbff": "text", "#f7faff": "text",
    "#b3c0d3": "muted", "#a8bad0": "muted", "#7893b0": "muted",
    "#98aec7": "muted", "#becbe0": "muted", "#f6fbff": "text",
    "#3b4b5f": "border", "#415675": "border", "#69baf4": "accent",
    "#6ebcf3": "accent", "#9ed9ff": "accent_hover", "#277cbd": "selection",
    "#1f2b3c": "panel", "#345d7c": "selection", "#b6dfff": "accent",
    "#5b8aac": "accent", "#3c2530": "button", "#ffc6ce": "text",
    "#34465c": "button_hover", "#243449": "grid_hover", "#415675": "border",
}


def normalize_theme(key: str | None) -> str:
    return key if key in THEMES else "dark"


def color(value: str, theme: str | None = None) -> str:
    palette = THEMES[normalize_theme(theme or CURRENT_THEME)]
    return palette.get(BASE_COLORS.get(value.lower(), ""), value)


def stylesheet(default: str, theme: str) -> str:
    import re
    theme = normalize_theme(theme)
    themed = re.sub(r"#[0-9a-fA-F]{6}\b", lambda m: color(m.group(), theme), default)
    p = THEMES[theme]
    return themed + ("\nQToolTip {background:%s; color:%s; border:1px solid %s;}\n"
                     "QComboBox QAbstractItemView {background:%s; color:%s; selection-background-color:%s;}\n" %
                     (p['panel'], p['text'], p['border'], p['panel'], p['text'], p['selection']))


def activate(theme: str) -> str:
    global CURRENT_THEME
    CURRENT_THEME = normalize_theme(theme)
    return CURRENT_THEME
