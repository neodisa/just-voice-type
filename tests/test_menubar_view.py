import unittest

import menubar_icon as mi

try:
    import AppKit  # noqa: F401

    import menubar_view as mv
except ImportError:  # pragma: no cover — без PyObjC
    mv = None


class FakeButton:
    def __init__(self):
        self.image = None
        self.title = None
        self.attributed = None
        self.label = None

    def setImage_(self, img):
        self.image = img

    def setImagePosition_(self, _):
        pass

    def setTitle_(self, t):
        self.title = t

    def setAttributedTitle_(self, t):
        self.attributed = t

    def setAccessibilityLabel_(self, t):
        self.label = t


class FakeStatusItem:
    def __init__(self):
        self.btn = FakeButton()
        self.length = None

    def button(self):
        return self.btn

    def setLength_(self, n):
        self.length = n


@unittest.skipIf(mv is None, "PyObjC not available")
class TestRender(unittest.TestCase):
    def test_symbol_frames_render_as_template(self):
        img = mv.render(mi.Frame(symbol="mic"))
        self.assertTrue(img.isTemplate())
        self.assertGreater(img.size().width, 0)

    def test_rec_frames_are_not_template(self):
        self.assertFalse(mv.render(mi.Frame(symbol="phone.fill", tint="rec")).isTemplate())

    def test_bars_render(self):
        img = mv.render(mi.Frame(symbol="", tint="rec", bars=(1, 2, 4, 2, 1)))
        self.assertAlmostEqual(img.size().height, mv.HEIGHT)
        badge = mv.render(
            mi.Frame(symbol="", tint="rec", bars=(1, 2, 4, 2, 1), badge="infinity")
        )
        self.assertGreater(badge.size().width, img.size().width)

    def test_unknown_symbol_falls_back_to_mic(self):
        self.assertIsNotNone(mv.render(mi.Frame(symbol="no.such.symbol.xyz")))

    def test_dim_frame_renders(self):
        self.assertIsNotNone(mv.render(mi.Frame(symbol="waveform", dim=True)))


@unittest.skipIf(mv is None, "PyObjC not available")
class TestStatusItemView(unittest.TestCase):
    def test_fixed_length_without_text(self):
        item, view = FakeStatusItem(), mv.StatusItemView()
        self.assertTrue(view.update(item, mi.Frame(symbol="mic"), "Ready"))
        self.assertEqual(item.length, mv.ICON_LENGTH)
        self.assertEqual(item.btn.title, "")
        self.assertEqual(item.btn.label, "Ready")

    def test_same_frame_is_not_reapplied(self):
        item, view = FakeStatusItem(), mv.StatusItemView()
        view.update(item, mi.Frame(symbol="mic"), "Ready")
        self.assertFalse(view.update(item, mi.Frame(symbol="mic"), "Ready"))

    def test_timer_widens_item(self):
        item, view = FakeStatusItem(), mv.StatusItemView()
        view.update(item, mi.Frame(symbol="phone.fill", tint="rec", text="12:04"), "Call")
        self.assertGreater(item.length, mv.ICON_LENGTH)
        self.assertIsNotNone(item.btn.attributed)

    def test_none_status_item_is_ignored(self):
        self.assertFalse(mv.StatusItemView().update(None, mi.Frame(), ""))


@unittest.skipIf(mv is None, "PyObjC not available")
class TestDot(unittest.TestCase):
    def test_every_dot_kind_renders(self):
        for kind in mv.DOT_RGB:
            self.assertIsNotNone(mv.dot_image(kind))
