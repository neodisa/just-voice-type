import unittest

import polish


class TestBuildMessages(unittest.TestCase):
    def test_clean_mode_system_forbids_translation_and_answering(self):
        msgs = polish.build_messages("ну привет", "clean", language="ru")
        self.assertEqual(msgs[0]["role"], "system")
        sys_l = msgs[0]["content"].lower()
        self.assertIn("ru", sys_l)
        self.assertIn("clean", sys_l)
        self.assertEqual(msgs[-1]["role"], "user")
        self.assertIn("ну привет", msgs[-1]["content"])

    def test_prompt_mode_mentions_instruction(self):
        msgs = polish.build_messages("сделай скрипт", "prompt")
        self.assertIn("instruction", msgs[0]["content"].lower())

    def test_vocabulary_embedded_when_present(self):
        msgs = polish.build_messages("x", "prompt", vocabulary=["Anthropic", "Qwen"])
        self.assertIn("Anthropic", msgs[0]["content"])
        self.assertIn("Qwen", msgs[0]["content"])

    def test_no_vocabulary_section_when_empty(self):
        msgs = polish.build_messages("x", "prompt", vocabulary=[])
        self.assertNotIn("Anthropic", msgs[0]["content"])


class TestCleanOutput(unittest.TestCase):
    def test_strips_surrounding_whitespace(self):
        self.assertEqual(polish._clean_output("  hi  \n"), "hi")

    def test_strips_wrapping_double_quotes(self):
        self.assertEqual(polish._clean_output('"hello world"'), "hello world")

    def test_strips_markdown_code_fence(self):
        self.assertEqual(polish._clean_output("```\nhello\n```"), "hello")

    def test_leaves_inner_quotes_intact(self):
        self.assertEqual(polish._clean_output('say "hi" now'), 'say "hi" now')


class TestMaxTokens(unittest.TestCase):
    def test_scales_with_input_but_has_floor(self):
        self.assertGreaterEqual(polish._max_tokens_for("a"), 64)

    def test_has_ceiling(self):
        huge = "word " * 5000
        self.assertLessEqual(polish._max_tokens_for(huge), 512)
