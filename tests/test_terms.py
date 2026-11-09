"""Словарь терминов: формы слова, бренды латиницей, ввод из меню."""
import unittest

import terms


class TestExactRulesKeepOldBehaviour(unittest.TestCase):
    def test_exact_word(self):
        self.assertEqual(terms.apply("тут хавар есть", {"хавар": "ховер"}), "тут ховер есть")

    def test_output_is_literal(self):
        self.assertEqual(terms.apply("Хавар есть", {"хавар": "ховер"}), "ховер есть")

    def test_multiword_phrase_has_no_forms(self):
        self.assertEqual(
            terms.apply("открой клод код сейчас", {"клод код": "Claude Code"}),
            "открой Claude Code сейчас",
        )


class TestBrandFormsCollapseToBrand(unittest.TestCase):
    RULES = {"фигма": "Figma"}

    def test_oblique_cases_of_a_final_word(self):
        for heard in ("фигме", "фигму", "фигмой", "фигмы", "Фигме"):
            with self.subTest(heard=heard):
                self.assertEqual(
                    terms.apply(f"посмотри в {heard} макет", self.RULES),
                    "посмотри в Figma макет",
                )

    def test_consonant_final_brand(self):
        rules = {"гитхаб": "GitHub"}
        self.assertEqual(terms.apply("залей на гитхабе", rules), "залей на GitHub")
        self.assertEqual(terms.apply("из гитхаба", rules), "из GitHub")

    def test_unrelated_longer_word_is_untouched(self):
        # «фигмовка» — другое слово, не форма «фигмы»
        self.assertEqual(terms.apply("Фигмовка готова", self.RULES), "Фигмовка готова")


class TestCyrillicFormsCarryTheEnding(unittest.TestCase):
    def test_consonant_final_to_consonant_final(self):
        rules = {"хавар": "ховер"}
        self.assertEqual(terms.apply("по хавару видно", rules), "по ховеру видно")
        self.assertEqual(terms.apply("с хаваром", rules), "с ховером")

    def test_a_final_to_a_final(self):
        rules = {"лейбла": "лейбла"}  # тождество не ломает формы
        self.assertEqual(terms.apply("у лейблы", rules), "у лейблы")

    def test_class_mismatch_only_exact(self):
        # хотят «попап» из «попапа»: классы разные — только точная форма
        rules = {"попапа": "попап"}
        self.assertEqual(terms.apply("это попапа", rules), "это попап")
        self.assertEqual(terms.apply("это попапу", rules), "это попапу")


class TestInflectedKeyIsExactOnly(unittest.TestCase):
    def test_vowel_final_key_does_not_expand(self):
        # «пройде» — словоформа (и настоящее украинское слово): никаких
        # «пройду»/«пройди» трогать нельзя
        rules = {"пройде": "проде"}
        self.assertEqual(terms.apply("на пройде", rules), "на проде")
        self.assertEqual(terms.apply("я пройду", rules), "я пройду")

    def test_short_keys_do_not_expand(self):
        rules = {"баг": "bug"}
        self.assertEqual(terms.apply("бага нет", rules), "бага нет")


class TestPriorities(unittest.TestCase):
    def test_explicit_rule_beats_generated_form(self):
        rules = {"фигма": "Figma", "фигму": "FIGMU"}
        self.assertEqual(terms.apply("в фигму", rules), "в FIGMU")

    def test_longest_match_wins(self):
        rules = {"клод": "Claude", "клод код": "Claude Code"}
        self.assertEqual(terms.apply("клод код и клода", rules), "Claude Code и Claude")

    def test_single_pass(self):
        self.assertEqual(terms.apply("b", {"b": "a", "a": "z"}), "a")

    def test_empty_inputs(self):
        self.assertEqual(terms.apply("", {"a": "b"}), "")
        self.assertEqual(terms.apply("text", {}), "text")
        self.assertEqual(terms.apply("text", {"": "X"}), "text")


class TestParseTermInput(unittest.TestCase):
    def test_equals_separator(self):
        self.assertEqual(terms.parse_input("хавар = ховер"), ("хавар", "ховер"))

    def test_arrow_separators(self):
        self.assertEqual(terms.parse_input("фигма -> Figma"), ("фигма", "Figma"))
        self.assertEqual(terms.parse_input("фигма → Figma"), ("фигма", "Figma"))

    def test_heard_side_is_lowercased_wanted_kept(self):
        self.assertEqual(terms.parse_input("  Клод Код =  Claude Code "), ("клод код", "Claude Code"))

    def test_invalid_inputs(self):
        for raw in ("", "   ", "хавар", "= ховер", "хавар =", "a = b = c"):
            with self.subTest(raw=raw):
                self.assertIsNone(terms.parse_input(raw))


if __name__ == "__main__":
    unittest.main()
