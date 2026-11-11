import datetime as dt
import unittest

import i18n
import menubar_icon
import model_catalog
import settings_model as sm
import sounds

PARAKEET = "mlx-community/parakeet-tdt-0.6b-v3"
LARGE = "mlx-community/whisper-large-v3-mlx"
NOW = dt.datetime(2026, 11, 10, 17, 0).timestamp()


def view(**kw):
    base = dict(
        version="0.14.0",
        now=NOW,
        snapshot=menubar_icon.Snapshot(now=NOW),
        model=PARAKEET,
        cached_models=frozenset({PARAKEET, LARGE}),
        favorites=["ru", "uk", "en"],
        terms={"фигма": "Figma", "хавар": "ховер"},
        input_devices=["BlackHole 2ch", "MacBook Pro Microphone"],
        auto_supported=True,
        login_available=True,
    )
    base.update(kw)
    return sm.View(**base)


def build(v=None, **kw):
    return sm.build(v or view(), rev=1, exists=lambda p: "gone" not in p, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        i18n.set_language("ru")

    def tearDown(self):
        i18n.set_language("en")


class TestMessage(Base):
    def test_envelope(self):
        m = build(ack="7", errors={"term": "x"})
        self.assertEqual(m["type"], "state")
        self.assertEqual((m["rev"], m["ack"], m["lang"]), (1, "7", "ru"))
        self.assertEqual(m["errors"], {"term": "x"})
        self.assertEqual(m["data"]["version"], "0.14.0")

    def test_strings_are_stripped_and_prefilled(self):
        s = build(view(call_hotkey="f13", update={"state": "update", "version": "0.15.0"}))["strings"]
        self.assertEqual(s["nav.general"], "Основное")
        self.assertIn("F13", s["calls.empty.caption"])
        self.assertNotIn("{key}", s["calls.empty.caption"])
        self.assertEqual(s["about.update.available"], "Доступна версия 0.15.0")
        self.assertIn("{n}", s["calls.show_all"])  # UI-local placeholder stays


class TestStatus(Base):
    def test_ready_names_model(self):
        st = build()["data"]["status"]
        self.assertEqual(st, {"dot": "ok", "text": "Готов · Parakeet v3", "timer_since": None})

    def test_call_recording_has_timer(self):
        snap = menubar_icon.Snapshot(now=NOW, call_state="recording", call_elapsed=60)
        st = build(view(snapshot=snap))["data"]["status"]
        self.assertEqual(st["text"], "Запись звонка")
        self.assertEqual(st["dot"], "rec")
        self.assertAlmostEqual(st["timer_since"], NOW - 60)

    def test_other_states_reuse_menu_text(self):
        snap = menubar_icon.Snapshot(now=NOW, enabled=False)
        self.assertEqual(build(view(snapshot=snap))["data"]["status"]["text"], "На паузе")


class TestGeneral(Base):
    def test_hotkey_picker_marks_call_key(self):
        p = build(view(hotkey="right_option", call_hotkey="f13"))["data"]["general"]["hotkey"]
        self.assertEqual(p["value"], "right_option")
        opt = {o["value"]: o for o in p["options"]}
        self.assertEqual(opt["right_option"]["label"], "правый Option")
        self.assertEqual(opt["right_option"]["glyph"], "⌥")
        self.assertTrue(opt["f13"]["disabled"])
        self.assertEqual(opt["f13"]["note"], "звонки")
        self.assertTrue(opt["f13"]["separator_before"])
        self.assertIsNone(opt["fn"]["glyph"])

    def test_unknown_current_hotkey_is_listed(self):
        p = build(view(hotkey="alt_r"))["data"]["general"]["hotkey"]
        self.assertEqual(p["options"][0]["value"], "alt_r")

    def test_live_typing_needs_parakeet_raw(self):
        g = build(view(smart_mode="clean"))["data"]["general"]["live_typing"]
        self.assertIsNotNone(g["disabled_reason"])
        self.assertEqual(g["link"]["section"], "recognition")
        g = build(view(model=LARGE))["data"]["general"]["live_typing"]
        self.assertIsNotNone(g["disabled_reason"])
        g = build()["data"]["general"]["live_typing"]
        self.assertIsNone(g["disabled_reason"])
        self.assertIsNone(g["link"])

    def test_login_unavailable_from_source(self):
        g = build(view(login_available=False))["data"]["general"]["launch_at_login"]
        self.assertIn("install_autostart.sh", g["disabled_reason"])

    def test_ui_language_system_note(self):
        p = build(view(system_language="en"))["data"]["general"]["ui_language"]
        self.assertEqual(p["options"][0]["note"], "сейчас English")
        self.assertTrue(p["options"][1]["separator_before"])

    def test_sounds_picker_lists_every_theme(self):
        p = build(view(sound_theme="mech"))["data"]["general"]["sounds"]
        self.assertEqual(p["value"], "mech")
        self.assertEqual([o["value"] for o in p["options"]], list(sounds.THEMES))
        opt = {o["value"]: o for o in p["options"]}
        self.assertEqual(opt["off"]["label"], "Без звуков")
        self.assertTrue(opt["macos"]["separator_before"])
        self.assertIsNone(p["disabled_reason"])
        self.assertTrue(p["caption"])


class TestRecognition(Base):
    def models(self, **kw):
        return {m["id"]: m for m in build(view(**kw))["data"]["recognition"]["models"]}

    def test_catalog_states(self):
        m = self.models()
        self.assertEqual(m[PARAKEET]["state"], "ready")
        self.assertTrue(m[PARAKEET]["selected"])
        self.assertTrue(m[PARAKEET]["default"])
        self.assertEqual(m[PARAKEET]["size"], "2,3 ГБ")
        small = m["mlx-community/whisper-small-mlx"]
        self.assertEqual((small["state"], small["note"]), ("absent", "Скачается при выборе."))

    def test_selected_loading_vs_downloading(self):
        m = self.models(model=LARGE, model_loading=True)
        self.assertEqual(m[LARGE]["state"], "loading")
        med = "mlx-community/whisper-medium-mlx"
        m = self.models(model=med, model_loading=True, model_progress=0.42)
        self.assertEqual(m[med]["state"], "downloading")
        self.assertEqual(m[med]["progress"], 0.42)
        self.assertEqual(m[med]["note"], "Скачивается · 42 % из 1,5 ГБ")

    def test_error_state(self):
        m = self.models(model_error="нет сети")
        self.assertEqual(m[PARAKEET]["state"], "error")
        self.assertIn("нет сети", m[PARAKEET]["note"])

    def test_custom_model_listed(self):
        m = self.models(model="someone/custom-model")
        self.assertEqual(m["someone/custom-model"]["name"], "custom-model")
        self.assertTrue(m["someone/custom-model"]["selected"])

    def test_language_chips(self):
        lang = build(view(active_language="de"))["data"]["recognition"]["language"]
        self.assertEqual(lang["value"], "de")
        self.assertEqual([c["value"] for c in lang["chips"]], [None, "en", "de", "ru", "uk"])  # порядок как в меню: по названию
        self.assertEqual(lang["chips"][0]["label"], "Авто")

    def test_language_sheet(self):
        langs = build(
            view(active_language="ru"), lang_name=lambda code, ui: code.upper()
        )["data"]["recognition"]["languages"]
        by = {l["code"]: l for l in langs}
        self.assertTrue(by["ru"]["favorite"])
        self.assertTrue(by["ru"]["locked"])
        self.assertFalse(by["uk"]["locked"])
        self.assertEqual(by["de"]["english"], "German")
        self.assertEqual([l["name"] for l in langs], sorted(l["name"] for l in langs))

    def test_smart_mode_download_hint(self):
        seg = build(view(polish_cached=False))["data"]["recognition"]["smart_mode"]
        clean = [o for o in seg["options"] if o["value"] == "clean"][0]
        self.assertIn("0,8 ГБ", clean["caption"])
        seg = build(view(polish_cached=True))["data"]["recognition"]["smart_mode"]
        clean = [o for o in seg["options"] if o["value"] == "clean"][0]
        self.assertNotIn("ГБ", clean["caption"])

    def test_vocabulary_only_for_whisper(self):
        self.assertFalse(build()["data"]["recognition"]["vocabulary"]["enabled"])
        self.assertTrue(build(view(model=LARGE))["data"]["recognition"]["vocabulary"]["enabled"])


class TestCalls(Base):
    def calls(self, **kw):
        return build(view(**kw))["data"]["calls"]

    def test_items_format(self):
        today = dt.datetime(2026, 11, 10, 16, 40).timestamp()
        older = dt.datetime(2026, 11, 6, 9, 5).timestamp()
        c = self.calls(calls=[
            {"ts": today, "duration_sec": 724, "path": "/c/a.txt", "preview": "Релиз"},
            {"ts": NOW - 86400, "duration_sec": 65, "path": "/c/gone.txt", "preview": "Вчера"},
            {"ts": older, "duration_sec": 5, "path": "/c/b.txt", "preview": "Старый"},
        ])
        self.assertEqual(c["count"], 3)
        a, b, old = c["items"]
        self.assertEqual((a["id"], a["day"], a["time"], a["duration"], a["missing"]),
                         ("/c/a.txt", "Сегодня", "16:40", "12:04", False))
        self.assertEqual((b["day"], b["missing"]), ("Вчера", True))
        self.assertEqual(old["day"], "Пт, 6 нояб.")

    def test_live(self):
        c = self.calls(call_state="recording", call_started_at=NOW - 5)
        self.assertEqual(c["live"], {"state": "recording", "started_at": NOW - 5})
        self.assertIsNone(self.calls()["live"]["started_at"])

    def test_device_picker(self):
        c = self.calls(call_device="Old Device", auto_capture=False)
        dev = c["device"]
        self.assertIsNone(dev["disabled_reason"])
        self.assertEqual(dev["options"][0]["value"], "Old Device")
        self.assertEqual(dev["options"][0]["note"], "не подключено")
        c = self.calls(auto_capture=True)
        self.assertIsNotNone(c["device"]["disabled_reason"])

    def test_unsupported_auto_capture(self):
        c = self.calls(auto_supported=False, auto_capture=True)
        self.assertFalse(c["auto_supported"])
        self.assertFalse(c["auto_capture"]["value"])
        self.assertIsNotNone(c["auto_capture"]["disabled_reason"])
        self.assertIsNone(c["device"]["disabled_reason"])

    def test_stealth_toggle(self):
        self.assertFalse(self.calls()["stealth"]["value"])
        t = self.calls(call_stealth=True)["stealth"]
        self.assertEqual(t, {"value": True, "disabled_reason": None, "link": None})

    def test_detect_rows(self):
        c = self.calls(detect_supported=True)
        self.assertEqual(c["detect"]["value"], "ask")
        self.assertEqual([o["value"] for o in c["detect"]["options"]], ["ask", "off"])
        self.assertEqual([o["label"] for o in c["detect"]["options"]], ["Спрашивать", "Ничего не делать"])
        self.assertIsNone(c["detect"]["disabled_reason"])
        self.assertIn("оранжевая точка", c["detect"]["caption"])
        self.assertEqual(c["auto_stop"], {"value": True, "disabled_reason": None, "link": None})
        c = self.calls(detect_supported=True, call_detect="off", call_auto_stop=False)
        self.assertEqual((c["detect"]["value"], c["auto_stop"]["value"]), ("off", False))

    def test_detect_unsupported(self):
        c = self.calls(detect_supported=False)
        self.assertEqual(c["detect"]["value"], "off")
        self.assertEqual(c["detect"]["disabled_reason"], "Нужна macOS 14.2 или новее")
        self.assertFalse(c["auto_stop"]["value"])
        self.assertEqual(c["auto_stop"]["disabled_reason"], "Нужна macOS 14.2 или новее")

    def test_call_hotkey_marks_dictation_key(self):
        p = self.calls(hotkey="right_option", call_hotkey="f13")["call_hotkey"]
        opt = {o["value"]: o for o in p["options"]}
        self.assertEqual(opt["right_option"]["note"], "диктовка")


class TestTermsAboutData(Base):
    def test_terms_newest_first(self):
        t = build(view(terms={"a": "A", "b": "B"}))["data"]["terms"]["items"]
        self.assertEqual(t, [{"heard": "b", "wanted": "B"}, {"heard": "a", "wanted": "A"}])

    def test_update_states(self):
        u = lambda **k: build(view(update=k))["data"]["about"]["update"]
        self.assertEqual(u(state="idle"), {"state": "idle", "text": None, "version": None})
        self.assertIn("09:12", u(state="uptodate", checked_at=dt.datetime(2026, 11, 10, 9, 12).timestamp())["text"])
        self.assertEqual(u(state="update", version="0.15.0")["version"], "0.15.0")
        self.assertIsNotNone(u(state="error")["text"])

    def test_links_and_author(self):
        about = build(view(logs_available=False))["data"]["about"]
        self.assertEqual([l["id"] for l in about["links"]], ["github", "config"])
        self.assertEqual(about["author"], {"name": "Sergey Arkhipov", "github": "neodisa"})


class TestValidateSet(Base):
    def ok(self, key, value, **kw):
        v, err = sm.validate_set(view(**kw), key, value)
        self.assertIsNone(err, (key, value))
        return v

    def bad(self, key, value, **kw):
        v, err = sm.validate_set(view(**kw), key, value)
        self.assertIsNotNone(err, (key, value))
        return err

    def test_hotkeys(self):
        self.assertEqual(self.ok("hotkey", "f14"), "f14")
        self.assertEqual(self.bad("hotkey", "f13", call_hotkey="f13"), "Эта клавиша уже занята звонками.")
        self.bad("hotkey", "nonsense")
        self.assertEqual(self.bad("call_hotkey", "right_option", hotkey="right_option"),
                         "Эта клавиша уже занята диктовкой.")

    def test_simple_enums(self):
        self.ok("insert_mode", "ax")
        self.bad("insert_mode", "telepathy")
        self.ok("ui_language", "ru")
        self.bad("ui_language", "de")
        self.ok("smart_mode", "prompt")
        self.bad("smart_mode", "loud")

    def test_bools(self):
        self.assertIs(self.ok("live_typing", False), False)
        self.bad("live_typing", "yes")
        self.bad("live_typing", True, smart_mode="clean")
        self.ok("launch_at_login", True)
        self.bad("launch_at_login", True, login_available=False)
        self.bad("auto_system_audio", True, auto_supported=False)
        self.ok("auto_system_audio", False, auto_supported=False)

    def test_model_and_language(self):
        self.ok("model", LARGE)
        self.ok("model", "x/custom", model="x/custom")
        self.bad("model", "x/other")
        self.assertIsNone(self.ok("active_language", None))
        self.assertEqual(self.ok("active_language", "de"), "de")
        self.bad("active_language", "xx")

    def test_sounds_and_stealth(self):
        self.assertEqual(self.ok("sound_theme", "bubble"), "bubble")
        self.ok("sound_theme", "off")
        self.bad("sound_theme", "kazoo")
        self.assertIs(self.ok("call_stealth", True), True)
        self.bad("call_stealth", "yes")

    def test_call_detect(self):
        self.assertEqual(self.ok("call_detect", "off", detect_supported=True), "off")
        self.ok("call_detect", "ask", detect_supported=True)
        self.bad("call_detect", "ask", detect_supported=False)
        self.ok("call_detect", "off", detect_supported=False)
        self.bad("call_detect", "always", detect_supported=True)
        self.assertIs(self.ok("call_auto_stop", False, detect_supported=True), False)
        self.ok("call_auto_stop", True, detect_supported=True)
        self.bad("call_auto_stop", True, detect_supported=False)
        self.bad("call_auto_stop", "yes", detect_supported=True)

    def test_device(self):
        self.ok("call_device", "BlackHole 2ch")
        self.bad("call_device", "Ghost")

    def test_unknown_key(self):
        self.bad("volume", 11)


class TestTermEdits(Base):
    def test_add_normalizes_and_rejects(self):
        terms, err = sm.term_add({}, "  Дейт   Пикер ", " дейтпикер ")
        self.assertIsNone(err)
        self.assertEqual(terms, {"дейт пикер": "дейтпикер"})
        _, err = sm.term_add(terms, "", "x")
        self.assertEqual(err, "Заполните оба поля.")
        _, err = sm.term_add(terms, "ДЕЙТ ПИКЕР", "y")
        self.assertEqual(err, "Такой термин уже есть: дейт пикер → дейтпикер. Исправьте его вместо нового.")

    def test_update_keeps_position(self):
        terms = {"a": "A", "b": "B", "c": "C"}  # display: c, b, a
        new, err = sm.term_update(terms, 1, "bb", "BB")
        self.assertIsNone(err)
        self.assertEqual(list(new.items()), [("a", "A"), ("bb", "BB"), ("c", "C")])
        _, err = sm.term_update(terms, 1, "a", "x")
        self.assertIsNotNone(err)
        new, err = sm.term_update(terms, 1, "b", "B2")  # same key, new spelling
        self.assertIsNone(err)
        self.assertEqual(new["b"], "B2")
        _, err = sm.term_update(terms, 9, "z", "Z")
        self.assertIsNotNone(err)

    def test_delete_and_restore(self):
        terms = {"a": "A", "b": "B"}
        new, deleted = sm.term_delete(terms, 0)  # display index 0 = "b"
        self.assertEqual(new, {"a": "A"})
        self.assertEqual(deleted, ("b", "B"))
        self.assertEqual(sm.term_delete(terms, 5), (terms, None))

    def test_vocab(self):
        v, err = sm.vocab_add(["Figma"], "  LIGA360 ")
        self.assertEqual((v, err), (["Figma", "LIGA360"], None))
        _, err = sm.vocab_add(v, "figma")
        self.assertEqual(err, "Это слово уже есть.")
        _, err = sm.vocab_add(v, "  ")
        self.assertIsNotNone(err)
        self.assertEqual(sm.vocab_remove(v, 0), ["LIGA360"])
        self.assertEqual(sm.vocab_remove(v, 7), v)


class TestDayLabel(Base):
    def test_english(self):
        i18n.set_language("en")
        ts = dt.datetime(2026, 11, 6, 9, 5).timestamp()
        self.assertEqual(sm.day_label(ts, NOW), "Fri, Nov 6")
        self.assertEqual(sm.day_label(NOW - 3600, NOW), "Today")


if __name__ == "__main__":
    unittest.main()


class TestPreview(unittest.TestCase):
    def test_strips_leading_timestamp(self):
        self.assertEqual(sm.clean_preview("[00:00] Привет, смотри"), "Привет, смотри")
        self.assertEqual(sm.clean_preview("[1:02:03]   Yeah."), "Yeah.")
        self.assertEqual(sm.clean_preview("Без метки [00:10] внутри"), "Без метки [00:10] внутри")
        self.assertEqual(sm.clean_preview(None), "")
