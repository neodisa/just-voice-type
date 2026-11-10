"""Отрисовка кадров menubar_icon в NSImage и вывод на статус-итем rumps.

Только AppKit-слой: какой кадр показать, решает menubar_icon. Ширина
статус-итема постоянная (ICON_LENGTH), чтобы соседние иконки не прыгали;
шире он становится только с таймером звонка.
"""
from __future__ import annotations

import AppKit
from AppKit import (
    NSAttributedString,
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSImageSymbolConfiguration,
    NSMakeRect,
    NSMakeSize,
)

import menubar_icon

HEIGHT = 18.0
SYMBOL_PT = 14.0
BADGE_PT = 9.0
BARS_WIDTH = 20.0
BAR_W = 2.4
ICON_LENGTH = 30.0
DIM_ALPHA = 0.45
TIMER_PT = 12.0
REC_RGB = (0xEB, 0x45, 0x37)
DOT_RGB = {
    "ok": (0x61, 0xCB, 0x7C),
    "rec": REC_RGB,
    "busy": (0xF0, 0xBA, 0x59),
    "error": (0xFB, 0x83, 0x6D),
    "paused": (0x8C, 0x8C, 0x8C),
}
DOT_SIZE = 8.0
_CACHE_MAX = 64


def _rgb(rgb, alpha: float = 1.0):
    r, g, b = rgb
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255, g / 255, b / 255, alpha)


def _symbol(name: str, pt: float, color=None):
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img is None:
        return None
    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
        pt, AppKit.NSFontWeightRegular
    )
    if color is not None:
        cfg = cfg.configurationByApplyingConfiguration_(
            NSImageSymbolConfiguration.configurationWithHierarchicalColor_(color)
        )
    return img.imageWithSymbolConfiguration_(cfg)


def _draw(size, fn):
    def handler(_rect):
        fn()
        return True

    return NSImage.imageWithSize_flipped_drawingHandler_(size, False, handler)


def _bars_image(fr: "menubar_icon.Frame"):
    color = _rgb(REC_RGB)
    badge = _symbol(fr.badge, BADGE_PT, color) if fr.badge else None
    width = BARS_WIDTH + (badge.size().width + 2.0 if badge is not None else 0.0)
    n = len(fr.bars)
    gap = (BARS_WIDTH - n * BAR_W) / max(1, n - 1)

    def paint():
        color.setFill()
        for i, step in enumerate(fr.bars):
            h = 3.0 + (HEIGHT - 6.0) * (step - 1) / (menubar_icon.BAR_STEPS - 1)
            rect = NSMakeRect(i * (BAR_W + gap), (HEIGHT - h) / 2, BAR_W, h)
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                rect, BAR_W / 2, BAR_W / 2
            ).fill()
        if badge is not None:
            bs = badge.size()
            badge.drawInRect_(NSMakeRect(BARS_WIDTH + 2.0, (HEIGHT - bs.height) / 2, bs.width, bs.height))

    return _draw(NSMakeSize(width, HEIGHT), paint)


def _with_alpha(src, alpha: float):
    def paint():
        src.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(0, 0, src.size().width, src.size().height),
            AppKit.NSZeroRect,
            AppKit.NSCompositingOperationSourceOver,
            alpha,
        )

    return _draw(src.size(), paint)


def render(fr: "menubar_icon.Frame"):
    """Кадр → NSImage. Шаблонные кадры следуют теме строки меню,
    красные (tint == "rec") рисуются как есть."""
    if fr.bars:
        img = _bars_image(fr)
    else:
        color = _rgb(REC_RGB) if fr.tint == "rec" else None
        img = _symbol(fr.symbol, SYMBOL_PT, color) or _symbol("mic", SYMBOL_PT)
    if fr.dim:
        img = _with_alpha(img, DIM_ALPHA)
    img.setTemplate_(fr.tint == "template")
    return img


class StatusItemView:
    """Кладёт кадры на кнопку NSStatusItem; одинаковый кадр — без работы."""

    def __init__(self):
        self._last = None
        self._cache: dict = {}

    def update(self, status_item, fr: "menubar_icon.Frame", label: str) -> bool:
        if status_item is None or fr == self._last:
            return False
        img = self._cache.get(fr)
        if img is None:
            if len(self._cache) >= _CACHE_MAX:
                self._cache.clear()
            img = self._cache[fr] = render(fr)
        button = status_item.button()
        button.setImage_(img)
        button.setImagePosition_(AppKit.NSImageLeft)
        if fr.text:
            attrs = {
                NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(
                    TIMER_PT, AppKit.NSFontWeightMedium
                ),
                NSForegroundColorAttributeName: _rgb(REC_RGB),
            }
            title = NSAttributedString.alloc().initWithString_attributes_(" " + fr.text, attrs)
            button.setAttributedTitle_(title)
            status_item.setLength_(ICON_LENGTH + title.size().width)
        else:
            button.setTitle_("")
            status_item.setLength_(ICON_LENGTH)
        button.setAccessibilityLabel_(label)
        self._last = fr
        return True


def dot_image(kind: str):
    color = _rgb(DOT_RGB.get(kind, DOT_RGB["paused"]))

    def paint():
        color.setFill()
        NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(1, 1, DOT_SIZE - 2, DOT_SIZE - 2)).fill()

    return _draw(NSMakeSize(DOT_SIZE, DOT_SIZE), paint)


def set_status_line(ns_menu_item, st: "menubar_icon.Status") -> None:
    """Строка статуса сверху меню: текст + цветная точка."""
    ns_menu_item.setTitle_(st.text)
    ns_menu_item.setImage_(dot_image(st.dot))


# ── помощники для пунктов меню ───────────────────────────────────────────
MENU_SYMBOL_PT = 13.0
_NSF1 = 0xF704  # NSF1FunctionKey; F13 = 0xF710


def ellipsize(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def set_subtitle(ns_item, text: str) -> None:
    """Вторая строка пункта меню (NSMenuItem.subtitle, macOS 14+)."""
    try:
        ns_item.setSubtitle_(text)
    except AttributeError:
        pass


def set_symbol(ns_item, name: str, color=None) -> None:
    img = _symbol(name, MENU_SYMBOL_PT, color)
    if img is not None:
        img.setTemplate_(color is None)
        ns_item.setImage_(img)


def decorate_call_item(ns_item, call_hotkey: str, active: bool) -> None:
    """Иконка пункта звонка и подсказка клавиши, если это F13–F19."""
    set_symbol(ns_item, "stop.circle" if active else "phone", _rgb(REC_RGB) if active else None)
    if call_hotkey[:1] == "f" and call_hotkey[1:].isdigit():
        n = int(call_hotkey[1:])
        if 1 <= n <= 35:
            ns_item.setKeyEquivalent_(chr(_NSF1 + n - 1))
            ns_item.setKeyEquivalentModifierMask_(0)


def make_alternate(primary_ns, alt_ns) -> None:
    """alt_ns показывается вместо primary_ns, пока зажат ⌥."""
    primary_ns.setKeyEquivalentModifierMask_(0)
    alt_ns.setKeyEquivalentModifierMask_(AppKit.NSEventModifierFlagOption)
    alt_ns.setAlternate_(True)


def make_section_header(rumps_item, title: str) -> None:
    """Заменить NSMenuItem у rumps-пункта на заголовок секции (macOS 14+)."""
    try:
        rumps_item._menuitem = AppKit.NSMenuItem.sectionHeaderWithTitle_(title)
    except AttributeError:
        pass
