# Replacements dictionary (IT anglicism normalization) — design

**Date:** 2026-07-20
**Status:** Approved, pre-implementation
**Branch:** `claude/ax-text-insertion` (ships in the same v0.9.0 update)

## Problem

The user dictates Russified IT anglicisms ("апрув", "задеплоить", …). The default
engine is now Parakeet, which ignores the `vocabulary` `initial_prompt` bias, and
the vocabulary→LLM correction only runs in Clean/Prompt mode. So on the common
Parakeet+Raw setup, nothing normalizes these terms. The user wants a fixed set of
terms rendered a consistent way (Cyrillic forms) **while keeping the fast model**.

## Goal

A deterministic, engine-agnostic **replacements dictionary**: user-defined
`heard → wanted` rules applied to the final transcript after recognition (and after
any LLM polish), before it goes to history / clipboard / insertion. No model, no
latency, works in Raw mode on Parakeet.

Non-goals: no model fine-tuning (impractical for a few words); no fuzzy/AI matching
(that's the existing Clean/Prompt path); no user-authored regex.

## Decisions (from brainstorming)

- **Matching:** whole-word / whole-phrase, **case-insensitive**, Unicode word
  boundaries (Cyrillic-aware). Output is the literal replacement value.
- **Applies in all modes**, as the last text transformation (after LLM polish),
  so the normalized text lands everywhere consistently.
- **Instant effect:** rules are re-read from config on each finalization (a cheap
  `config.load()`), so edits apply on the next dictation without a restart.
- Rules are user-owned in `config.json`, edited via a new **Edit replacements…**
  menu item (mirrors **Edit vocabulary…**).

## Config

New key `replacements`: a JSON object mapping `heard` → `wanted`:

```json
"replacements": {
  "a prove": "апрув",
  "апруф": "апрув",
  "задиплоить": "задеплоить"
}
```

`config.py`: add `replacements` to `DEFAULTS` (`{}`), `_defaults_copy()`, and
`_validate` (keep only entries where both key and value are non-empty strings; drop
anything else). Persisted by `save()`.

## Components

### 1. `apply_replacements(text: str, rules: dict) -> str` (pure)

- If `text` or `rules` is empty → return `text` unchanged.
- Build ONE alternation regex from the keys, **longest key first** (so
  "pull request" wins over "pull"), each key `re.escape`d, wrapped so it matches on
  word boundaries: pattern = `r"\b(" + "|".join(escaped_sorted_keys) + r")\b"`,
  compiled with `re.IGNORECASE`.
- Build a lowercase lookup: `{k.lower(): v for k, v in rules.items()}`.
- `re.sub(pattern, lambda m: lookup[m.group(0).lower()], text)` — a function
  replacement so the `wanted` string is inserted literally (no group-ref
  interpretation). One pass → a rule's output is never re-scanned by another rule.
- Case-key collisions (keys differing only by case) resolve last-wins in the
  lowercase lookup; acceptable and documented.

Placed near the other pure text helpers (e.g. next to `polish_text_safe` /
`join_parts` usage in `voice_type.py`), unit-testable with no GUI/model deps.

### 2. `deliver`-path wiring (worker finalization)

In the session finalization (`voice_type.py` ~1409-1434), after `full` is assembled
(`streaming.join_parts`) and after the optional LLM polish, and BEFORE the
`if full:` block that writes history / last_text / delivers:

```python
                full = apply_replacements(full, config.load().get("replacements", {}))
```

Reading `config.load()` here gives instant-effect edits. `full` then flows unchanged
into `history.add`, `last_text`, and `deliver_text`.

### 3. Menu: "Edit replacements…"

A new menu item near "Edit vocabulary…" with the same mechanism:

```python
        def edit_replacements(self, _):
            persist()  # ensure the file exists
            subprocess.Popen(["open", config.config_path()])
            notify("Voice Type",
                   'Edit the "replacements" map in config.json — applies on your next dictation')
```

Attached in `_build_menu` right after the "Edit vocabulary…" item, matching the
surrounding attachment style.

## Error handling

- No rules / empty text → no-op.
- All keys are `re.escape`d → no user regex, no injection, no invalid-pattern risk.
- `config.load()` already returns defaults on a missing/corrupt file, so the
  finalization read is safe.
- A malformed `replacements` value in the file is dropped by `_validate` (→ `{}`).

## Testing

- **Unit** (`tests/test_replacements.py`, pure):
  - whole-word match replaced; substring inside another word NOT touched
    (e.g. rule `"prove"→"X"` leaves "improve" alone).
  - case-insensitive: "Апрув" and "апрув" both replaced; output is the literal value.
  - multi-word phrase replaced ("pull request" → "пул-реквест").
  - longest-key-first: with rules for "pull" and "pull request", the phrase wins.
  - Cyrillic word boundaries work; adjacent punctuation preserved.
  - empty rules / empty text → unchanged.
  - one-pass: a `wanted` value equal to another rule's `heard` is NOT re-replaced.
- **Config** (`tests/test_config.py`): `replacements` validation — valid dict
  round-trips; non-string keys/values dropped; non-dict → `{}`; missing → `{}`.
- **Manual:** on Parakeet+Raw, dictate the seed terms, observe Parakeet's actual
  output, refine the `heard` keys, confirm normalization; confirm it also applies
  after Clean/Prompt.

## Starter replacement set (PROPOSED — verify & prune)

Seeded into the user's `config.json` after the feature lands (NOT into code
`DEFAULTS`, which stays `{}`). **These are best-guess `heard` keys** — I know only
"апрув" and "задеплоить" for certain; the rest assume Parakeet either emits the
Latin word (→ Cyrillize it) or a common Cyrillic misspelling (→ canonical). The user
should dictate each term, see what Parakeet actually produces, and adjust. Caveat:
whole-word Latin keys (e.g. `build`) will also fire inside an all-English dictation —
prune any that cause that.

```json
"replacements": {
  "approve": "апрув",
  "апруф": "апрув",
  "deploy": "деплой",
  "задиплоить": "задеплоить",
  "merge": "мёрдж",
  "смержить": "смёржить",
  "pull request": "пул-реквест",
  "пулреквест": "пул-реквест",
  "merge request": "мёрдж-реквест",
  "commit": "коммит",
  "rollback": "роллбэк",
  "release": "релиз",
  "rebase": "ребейз",
  "review": "ревью",
  "refactor": "рефактор",
  "endpoint": "эндпоинт",
  "backend": "бэкенд",
  "frontend": "фронтенд",
  "feature": "фича",
  "bug": "баг"
}
```

## Ship

Same branch as the AX work; ships in the v0.9.0 GitHub update. If the user wants AX
released first, this moves to its own branch (noted at brainstorming).
