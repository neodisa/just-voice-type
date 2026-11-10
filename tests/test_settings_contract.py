"""Снимок из settings_model совпадает по форме с native/settings/demo-state.json —
тем, на чём собирается и проверяется SwiftUI-хелпер."""
import json
import os
import unittest

import i18n
import menubar_icon
import settings_model as sm

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "..", "native", "settings", "demo-state.json")


def shape_diff(a, b, path="$"):
    """Расхождения формы: ключи словарей, типы значений (None совместим с чем угодно),
    форма первого элемента списков."""
    if a is None or b is None:
        return []
    if isinstance(a, bool) or isinstance(b, bool):
        return [] if isinstance(a, bool) and isinstance(b, bool) else [f"{path}: {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return []
    if type(a) is not type(b):
        return [f"{path}: {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, dict):
        out = []
        if set(a) != set(b):
            out.append(f"{path}: keys {sorted(set(a) ^ set(b))}")
        for k in set(a) & set(b):
            out += shape_diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and a and b:
        return shape_diff(a[0], b[0], f"{path}[0]")
    return []


class TestContract(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_python_snapshot_matches_demo_shape(self):
        with open(DEMO, encoding="utf-8") as f:
            demo = json.load(f)
        i18n.set_language("ru")
        v = sm.View(
            version="0.14.0",
            now=1_762_790_000.0,
            snapshot=menubar_icon.Snapshot(now=1_762_790_000.0),
            calls=[{"ts": 1_762_780_000.0, "duration_sec": 60, "path": "/x.txt", "preview": "p"}],
            terms={"фигма": "Figma"},
            vocabulary=["Figma"],
            favorites=["ru"],
            input_devices=["BlackHole 2ch"],
            update={"state": "update", "version": "0.15.0"},
        )
        msg = sm.build(v, rev=1, exists=lambda p: True, lang_name=lambda c, u: c)
        strings_demo, strings_py = demo.pop("strings"), msg.pop("strings")
        self.assertEqual(shape_diff(msg, demo), [])
        self.assertEqual(sorted(set(strings_demo) - set(strings_py)), [])
