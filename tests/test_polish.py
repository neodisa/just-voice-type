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

    def test_clean_mode_includes_fewshot_examples(self):
        msgs = polish.build_messages("текст", "clean", language="ru")
        roles = [m["role"] for m in msgs]
        # system, затем пары user/assistant (few-shot), затем реальный ввод
        self.assertEqual(roles[0], "system")
        self.assertIn("assistant", roles)
        self.assertEqual(roles[-1], "user")
        self.assertEqual(msgs[-1]["content"], "текст")

    def test_prompt_mode_has_no_fewshot(self):
        msgs = polish.build_messages("текст", "prompt")
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])

    def test_rules_protect_english_terms(self):
        msgs = polish.build_messages("x", "clean")
        self.assertIn("never translate", msgs[0]["content"].lower())


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


class _FakeTokenizer:
    def apply_chat_template(self, messages, add_generation_prompt=True):
        # echo a deterministic prompt string built from messages
        return "PROMPT::" + messages[-1]["content"]


class TestPolisher(unittest.TestCase):
    def _polisher(self, gen):
        return polish.Polisher(
            model="fake",
            load_fn=lambda m: ("FAKE_MODEL", _FakeTokenizer()),
            generate_fn=gen,
            sampler_fn=lambda temp=0.0, **k: f"sampler(temp={temp})",
        )

    def test_raw_mode_returns_input_without_loading(self):
        calls = {"load": 0, "gen": 0}

        def load_fn(m):
            calls["load"] += 1
            return ("M", _FakeTokenizer())

        def gen_fn(*a, **k):
            calls["gen"] += 1
            return "should not run"

        p = polish.Polisher(model="fake", load_fn=load_fn, generate_fn=gen_fn)
        self.assertEqual(p.polish("verbatim text", "raw"), "verbatim text")
        self.assertEqual(calls["load"], 0)
        self.assertEqual(calls["gen"], 0)
        self.assertFalse(p.is_loaded())

    def test_empty_text_returns_input_without_loading(self):
        p = self._polisher(lambda *a, **k: "x")
        self.assertEqual(p.polish("   ", "prompt"), "   ")
        self.assertFalse(p.is_loaded())

    def test_clean_mode_calls_model_and_cleans_output(self):
        p = self._polisher(lambda *a, **k: '  "cleaned text"  ')
        out = p.polish("ну эээ привет", "clean", language="ru")
        self.assertEqual(out, "cleaned text")
        self.assertTrue(p.is_loaded())

    def test_prompt_passed_through_chat_template(self):
        seen = {}

        def gen_fn(model, tokenizer, prompt=None, **k):
            seen["prompt"] = prompt
            return "ok"

        p = self._polisher(gen_fn)
        p.polish("сделай скрипт", "prompt")
        self.assertTrue(seen["prompt"].startswith("PROMPT::"))
        self.assertIn("сделай скрипт", seen["prompt"])

    def test_model_error_falls_back_to_raw_text(self):
        def boom(*a, **k):
            raise RuntimeError("mlx blew up")

        p = self._polisher(boom)
        self.assertEqual(p.polish("original", "prompt"), "original")

    def test_empty_generation_falls_back_to_raw_text(self):
        p = self._polisher(lambda *a, **k: "   ")
        self.assertEqual(p.polish("original", "clean"), "original")

    def test_model_loaded_only_once(self):
        calls = {"load": 0}

        def load_fn(m):
            calls["load"] += 1
            return ("M", _FakeTokenizer())

        p = polish.Polisher(
            model="fake",
            load_fn=load_fn,
            generate_fn=lambda *a, **k: "out",
            sampler_fn=lambda **k: "S",
        )
        p.polish("a", "clean")
        p.polish("b", "clean")
        self.assertEqual(calls["load"], 1)

    def test_warm_up_loads_model_and_runs_tiny_generate(self):
        calls = {"load": 0, "gen": 0, "max_tokens": None}

        def load_fn(m):
            calls["load"] += 1
            return ("M", _FakeTokenizer())

        def gen_fn(model, tokenizer, *, prompt, max_tokens, sampler):
            calls["gen"] += 1
            calls["max_tokens"] = max_tokens
            return "x"

        p = polish.Polisher(
            model="fake",
            load_fn=load_fn,
            generate_fn=gen_fn,
            sampler_fn=lambda temp=0.0, **k: "S",
        )
        p.warm_up()
        self.assertTrue(p.is_loaded())
        self.assertEqual(calls["load"], 1)
        self.assertEqual(calls["gen"], 1)
        # прогрев должен быть дешёвым — единицы токенов, не полноценная генерация
        self.assertLessEqual(calls["max_tokens"], 4)

    def test_warm_up_never_raises(self):
        def boom(*a, **k):
            raise RuntimeError("no weights")

        p = polish.Polisher(model="fake", load_fn=boom, generate_fn=boom)
        p.warm_up()  # не должно кинуть
        self.assertFalse(p.is_loaded())

    def test_warm_up_idempotent_loads_once(self):
        calls = {"load": 0}

        def load_fn(m):
            calls["load"] += 1
            return ("M", _FakeTokenizer())

        p = polish.Polisher(
            model="fake",
            load_fn=load_fn,
            generate_fn=lambda *a, **k: "x",
            sampler_fn=lambda **k: "S",
        )
        p.warm_up()
        p.warm_up()
        p.polish("a", "clean")
        self.assertEqual(calls["load"], 1)

    def test_generate_called_with_sampler_not_temperature(self):
        # Regression guard: mlx_lm's generate_step takes `sampler=`, not
        # `temperature=`. This fake mirrors the REAL keyword-only signature so
        # the suite fails loudly if polish ever passes `temperature` again.
        captured = {}

        def strict_generate(model, tokenizer, *, prompt, max_tokens, sampler):
            captured["sampler"] = sampler
            captured["max_tokens"] = max_tokens
            return "polished"

        p = polish.Polisher(
            model="fake",
            load_fn=lambda m: ("M", _FakeTokenizer()),
            generate_fn=strict_generate,
            sampler_fn=lambda temp=0.0, **k: f"sampler(temp={temp})",
        )
        out = p.polish("hello there friend", "clean")
        self.assertEqual(out, "polished")
        self.assertEqual(captured["sampler"], "sampler(temp=0.1)")
        self.assertGreaterEqual(captured["max_tokens"], 64)
