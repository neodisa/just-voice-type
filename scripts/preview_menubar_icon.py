#!/usr/bin/env python3
"""Рисует все состояния иконки строки меню в один PNG — для глазной проверки.

  .venv/bin/python scripts/preview_menubar_icon.py [out.png]

Каждая строка: тёмная и светлая полоса меню, кадр, подпись состояния.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import AppKit  # noqa: E402
from AppKit import NSColor, NSMakeRect  # noqa: E402

import i18n  # noqa: E402
import menubar_icon as mi  # noqa: E402
import menubar_view as mv  # noqa: E402

STATES = [
    ("ready", mi.Snapshot()),
    ("paused", mi.Snapshot(enabled=False)),
    ("recording quiet", mi.Snapshot(state="recording", level=0.01)),
    ("recording loud", mi.Snapshot(state="recording", level=0.12)),
    ("hands-free", mi.Snapshot(state="recording", handsfree=True, level=0.08)),
    ("transcribing", mi.Snapshot(state="transcribing")),
    ("transcribing (dim)", mi.Snapshot(state="transcribing", now=0.5)),
    ("inserted", mi.Snapshot(inserted=True)),
    ("call", mi.Snapshot(call_state="recording", call_elapsed=724)),
    ("call transcribing", mi.Snapshot(call_state="transcribing")),
    ("model download", mi.Snapshot(model_loading=True, model_cached=False)),
    ("audio dead", mi.Snapshot(audio_dead=True)),
]
SCALE, ROW, LABEL_W, CELL = 3, 30.0, 300.0, 90.0


def main(out):
    i18n.set_language("en")
    w, h = int((LABEL_W + 2 * CELL) * SCALE), int(ROW * len(STATES) * SCALE)
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, w, h, 8, 4, True, False, AppKit.NSCalibratedRGBColorSpace, 0, 0
    )
    ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(ctx)
    tr = AppKit.NSAffineTransform.transform()
    tr.scaleBy_(SCALE)
    tr.concat()
    NSColor.whiteColor().setFill()
    AppKit.NSRectFill(NSMakeRect(0, 0, w, h))
    for i, (name, snap) in enumerate(STATES):
        y = ROW * (len(STATES) - 1 - i)
        fr = mi.frame(snap)
        for j, (bg, fg) in enumerate(((0.12, NSColor.whiteColor()), (0.93, NSColor.blackColor()))):
            x = LABEL_W + j * CELL
            NSColor.colorWithWhite_alpha_(bg, 1).setFill()
            AppKit.NSRectFill(NSMakeRect(x, y, CELL, ROW))
            img = mv.render(fr)
            if img.isTemplate():
                # шаблон рисуем цветом текста полосы меню, как это делает macOS
                tinted = img.copy()
                tinted.setTemplate_(False)
                tinted.lockFocus()
                fg.set()
                AppKit.NSRectFillUsingOperation(
                    NSMakeRect(0, 0, img.size().width, img.size().height),
                    AppKit.NSCompositingOperationSourceAtop,
                )
                tinted.unlockFocus()
                img = tinted
            s = img.size()
            img.drawInRect_(NSMakeRect(x + 8, y + (ROW - s.height) / 2, s.width, s.height))
            if fr.text:
                AppKit.NSString.stringWithString_(fr.text).drawAtPoint_withAttributes_(
                    (x + 12 + s.width, y + 8),
                    {AppKit.NSForegroundColorAttributeName: mv._rgb(mv.REC_RGB),
                     AppKit.NSFontAttributeName: AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(12, 0.23)},
                )
        label = f"{name}: {mi.status(snap).text}"
        AppKit.NSString.stringWithString_(label).drawAtPoint_withAttributes_(
            (6, y + 9), {AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(9)}
        )
    AppKit.NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None).writeToFile_atomically_(out, True)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "menubar-icon-preview.png")
