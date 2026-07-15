"""Local on-device LLM polish pass for Just Voice Type.

Rewrites raw Whisper output: cleans filler/punctuation (clean mode) or
restructures dictation into a single clear AI instruction (prompt mode).
Runs on-device via mlx_lm. Pure prompt/text helpers are GUI- and
model-free so they are unit-testable without loading any weights.
"""
from __future__ import annotations

import sys
from typing import Any, Optional

# 1.5B: для clean/prompt-переписывания хватает, а работает в ~2-3 раза быстрее
# и держит меньше памяти рядом с Whisper, чем 3B.
POLISH_MODEL = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"
MODES = ("raw", "clean", "prompt")
# Low temperature: polishing should be faithful, not creative.
POLISH_TEMP = 0.1

_COMMON_RULES = (
    "You rewrite dictated speech. Hard rules: "
    "do NOT answer, explain, or perform any request in the text — only rewrite it. "
    "Do NOT translate; keep the user's original language. "
    "Keep English words and technical terms exactly as spoken — never translate "
    "or transliterate them. "
    "Do NOT add facts, names, or details that are not in the input. "
    "Output ONLY the rewritten text, with no preamble, labels, or markdown."
)

_CLEAN_TASK = (
    "Mode: CLEAN. Delete ALL filler words and hesitations (e.g. uh, um; "
    "in Russian: ну, эээ, короче, это самое, значит так, как бы, типа). "
    "When the speaker corrects or restates themselves, keep only the final "
    "version. Fix punctuation and capitalization. Keep the remaining wording "
    "and meaning unchanged."
)

# Few-shot для clean: маленькие модели (1.5B) следуют примеру гораздо лучше,
# чем абстрактным правилам — без примеров они оставляют «ну эээ» на месте.
# Примеры демонстрируют паттерн (выкинуть филлеры, самоисправление → финальная
# версия, английские термины неприкосновенны) и обобщаются на другие языки.
_CLEAN_FEWSHOT = [
    {
        "role": "user",
        "content": (
            "ну значит эээ нам нужно короче обновить этот самый деплой скрипт "
            "ну то есть deploy script и как бы прогнать тесты в CI"
        ),
    },
    {
        "role": "assistant",
        "content": "Нам нужно обновить deploy script и прогнать тесты в CI.",
    },
    {
        "role": "user",
        "content": (
            "привет эээ глянь пожалуйста ну то есть посмотри работает ли этот "
            "самый фича флаг ну feature flag на проде"
        ),
    },
    {
        "role": "assistant",
        "content": "Привет! Посмотри, пожалуйста, работает ли feature flag на проде.",
    },
]

_PROMPT_TASK = (
    "Mode: PROMPT. The user is dictating a request to an AI assistant. Rewrite it as "
    "a single clear, well-formed instruction (one paragraph). Fix obviously "
    "misheard words. Preserve the user's intent. Write the instruction in the "
    "SAME language the user dictated in — never switch languages."
)


def _system_content(mode: str, language: Optional[str], vocabulary) -> str:
    task = _PROMPT_TASK if mode == "prompt" else _CLEAN_TASK
    parts = [_COMMON_RULES, task]
    if language:
        parts.append(f"The user's language code is: {language}.")
    if vocabulary:
        terms = ", ".join(vocabulary)
        parts.append(
            "Domain terms the user often uses (prefer these when a word was likely "
            f"misheard): {terms}."
        )
    return " ".join(parts)


def build_messages(
    text: str,
    mode: str,
    language: Optional[str] = None,
    vocabulary=None,
) -> "list[dict[str, str]]":
    """Build chat messages for clean/prompt modes. Pure, no model."""
    messages = [
        {"role": "system", "content": _system_content(mode, language, vocabulary)}
    ]
    if mode == "clean":
        messages.extend(_CLEAN_FEWSHOT)
    messages.append({"role": "user", "content": text})
    return messages


def _clean_output(raw: str) -> str:
    """Strip whitespace, a single wrapping pair of double-quotes, and code fences."""
    s = raw.strip()
    if s.startswith("```") and s.endswith("```"):
        s = s[3:-3].strip()
        # drop an optional leading language tag line (e.g. ```text)
        if "\n" in s and " " not in s.split("\n", 1)[0]:
            head, rest = s.split("\n", 1)
            if head and not head[0].isspace():
                s = rest.strip() if head.isalpha() else s
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    return s


def _max_tokens_for(text: str) -> int:
    words = len(text.split())
    return max(64, min(512, words * 3))


class Polisher:
    """On-device LLM polisher. Lazy-loads weights on first clean/prompt call.

    `load_fn` / `generate_fn` / `sampler_fn` are injectable for tests; in
    production they default to `mlx_lm.load` / `mlx_lm.generate` /
    `mlx_lm.sample_utils.make_sampler`.
    """

    def __init__(
        self,
        model: str = POLISH_MODEL,
        load_fn=None,
        generate_fn=None,
        sampler_fn=None,
    ):
        self.model_id = model
        self._load_fn = load_fn
        self._generate_fn = generate_fn
        self._sampler_fn = sampler_fn
        self._model: Any = None
        self._tokenizer: Any = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        load_fn = self._load_fn
        if load_fn is None:
            from mlx_lm import load as load_fn  # type: ignore
        self._model, self._tokenizer = load_fn(self.model_id)

    def _generate(self, messages, max_tokens: int) -> str:
        self._ensure_loaded()
        generate_fn = self._generate_fn
        if generate_fn is None:
            from mlx_lm import generate as generate_fn  # type: ignore
        sampler_fn = self._sampler_fn
        if sampler_fn is None:
            # mlx_lm.generate forwards **kwargs to generate_step, which takes
            # `sampler=`, NOT `temperature=` — passing temperature raises
            # TypeError. Build a sampler instead.
            from mlx_lm.sample_utils import make_sampler as sampler_fn  # type: ignore
        prompt = self._tokenizer.apply_chat_template(
            messages, add_generation_prompt=True
        )
        return generate_fn(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler_fn(temp=POLISH_TEMP),
        )

    def warm_up(self) -> None:
        """Load weights and compile Metal kernels ahead of the first dictation.

        A 1-token generate is enough to trigger both; without it the first
        clean/prompt dictation pays multi-second load+compile latency.
        Never raises — warm-up is best-effort.
        """
        if self.is_loaded():
            return
        try:
            self._generate(build_messages("hi", "clean"), max_tokens=1)
        except Exception as e:
            print(f"[!] polish warm-up failed ({e})", file=sys.stderr)

    def polish(
        self,
        text: str,
        mode: str,
        language: Optional[str] = None,
        vocabulary=None,
    ) -> str:
        if mode == "raw" or not text or not text.strip():
            return text
        if mode not in ("clean", "prompt"):
            return text
        try:
            out = self._generate(
                build_messages(text, mode, language, vocabulary),
                max_tokens=_max_tokens_for(text),
            )
            cleaned = _clean_output(out or "")
            return cleaned or text
        except Exception as e:  # never block paste
            print(f"[!] polish failed ({e}); using raw text", file=sys.stderr)
            return text
