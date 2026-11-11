# Settings window protocol (Python ⇄ JustVoiceTypeSettings)

The SwiftUI helper only **renders** and **reports intents**. Python owns every
rule, every validation and every translated string. Spec:
`docs/superpowers/specs/2026-11-10-ui-redesign-design.md`.

Transport: JSON Lines over the helper's stdin (Python → helper) and stdout
(helper → Python). UTF-8, one JSON object per line, `\n`-terminated. The helper
writes nothing else to stdout (logs go to stderr). EOF on stdin → the helper
closes its window and exits 0.

`demo-state.json` next to this file is a complete, valid `state` message in
Russian. `JustVoiceTypeSettings --demo` renders it without Python;
`tests/test_settings_contract.py` checks that Python produces the same shape.

## Python → helper

| type | fields | meaning |
|---|---|---|
| `state` | `rev` int, `ack` string\|null, `lang` "ru"\|"en", `strings` {key: text}, `data` {...}, `errors` {key: text} | full snapshot; replace everything you show |
| `focus` | `section` "general"\|"recognition"\|"calls"\|"terms"\|"about"\|null | bring the window to front; select the section unless null |
| `toast` | `text`, `action` {`name`, `label`, `args`}\|null | bottom toast for 5 s; the button sends `action` |
| `quit` | — | close the window and exit 0 |

`ack` is the `req` of the last `set`/`action` Python handled before building
this snapshot (null otherwise). The helper uses it to close an inline editor:
when `ack` equals the editor's request id and `errors` has no entry for that
editor's key, the edit succeeded.

## Helper → Python

| type | fields | meaning |
|---|---|---|
| `ready` | — | window is up, send a `state` |
| `set` | `req` string, `key`, `value` | change one setting |
| `action` | `req` string, `name`, `args` {} | do something |
| `closed` | — | window closed; the helper exits right after |

`req` is any unique string (a counter is fine).

### `set` keys

| key | value |
|---|---|
| `hotkey`, `call_hotkey` | an option `value` from the matching picker |
| `insert_mode` | `"paste"` \| `"ax"` |
| `live_typing`, `auto_system_audio`, `launch_at_login`, `call_stealth`, `call_auto_stop` | bool |
| `ui_language` | `"system"` \| `"ru"` \| `"en"` |
| `sound_theme` | `"default"` \| `"mech"` \| `"bubble"` \| `"press"` \| `"macos"` \| `"off"` (Python plays a sample) |
| `call_detect` | `"ask"` \| `"off"` |
| `model` | a model `id` |
| `active_language` | `null` (Auto) or a language code |
| `smart_mode` | `"raw"` \| `"clean"` \| `"prompt"` |
| `call_device` | a device option `value` |

### `action` names

| name | args | error key on failure |
|---|---|---|
| `term_add` | `heard`, `wanted` | `term` |
| `term_update` | `index`, `heard`, `wanted` | `term` |
| `term_delete` | `index` | — |
| `term_undo_delete` | — | — |
| `vocab_add` | `word` | `vocab` |
| `vocab_remove` | `index` | — |
| `favorite_toggle` | `code` | — |
| `call_toggle` | — | — |
| `call_copy`, `call_open` | `id` | — |
| `call_unignore` | `id` (key from `calls.ignored`) | — |
| `calls_open_folder` | — | — |
| `model_retry` | `id` | — |
| `check_updates` | — | — |
| `open_link` | `id`: `github` \| `releases` \| `config` \| `logs` \| `call_setup` \| `update` | — |

Unknown keys, names or values are ignored by Python (logged). A `set` with an
invalid value answers with a `state` whose `errors[key]` explains why.

## `strings`

Every static text of the window, already in the UI language, keys without the
`settings.` prefix (`"nav.general"`, `"calls.empty.caption"`, …). Python
pre-fills placeholders that depend on app state (`{key}` in
`calls.empty.caption`). The helper itself replaces only these UI-local
placeholders: `{n}` (a count it computes) and `{q}` (the search text).

## `data`

```
version            "0.15.0"
status             {dot: "ok"|"rec"|"busy"|"paused"|"error", text, timer_since: epoch|null}
                   timer_since set → append " · m:ss" counted locally every second
general
  hotkey           Picker
  live_typing      Toggle
  insert_mode      Picker
  sounds           Picker           (sound theme; set key `sound_theme`)
  ui_language      Picker
  launch_at_login  Toggle
  warning          text|null        (key conflict etc., shown above the group in warn color)
recognition
  models           [Model]
  language         {value: code|null, chips: [{value: code|null, label}]}
  languages        [{code, name, english, favorite: bool, locked: bool}]   (sheet list; locked = active language, checkbox disabled)
  smart_mode       Segmented
  vocabulary       {items: [text], enabled: bool}
calls
  count            int
  live             {state: "idle"|"recording"|"transcribing", started_at: epoch|null}
  items            [Call]           newest first, at most 30
  auto_supported   bool
  call_hotkey      Picker
  stealth          Toggle           (hidden recording; set key `call_stealth`)
  detect           Picker           (offer to record when another app holds the mic; set key `call_detect`)
  auto_stop        Toggle           (stop when the call app leaves the mic; set key `call_auto_stop`)
  ignored          [{id, name}]     apps never offered and never linked to a recording (remove: `call_unignore`)
  auto_capture     Toggle
  device           Picker
terms
  items            [{heard, wanted}]
about
  update           {state: "idle"|"checking"|"uptodate"|"update"|"error", text: text|null, version: text|null}
  links            [{id, label, button}]
  author           {name, github}
```

Shared shapes:

```
Picker     {value: string|null, caption: text|null, disabled_reason: text|null,
            options: [{value: string|null, label, glyph: text|null, note: text|null,
                       disabled: bool, separator_before: bool}]}
Toggle     {value: bool, disabled_reason: text|null, link: {label, section}|null}
Segmented  {value, disabled_reason: text|null, options: [{value, label, caption}]}
Model      {id, name, desc, size, default: bool, selected: bool,
            state: "ready"|"absent"|"loading"|"downloading"|"error",
            progress: 0..1|null, note: text|null}
Call       {id, day, time, duration, preview, missing: bool}
```

Rendering rules the helper must follow:

- `disabled_reason` non-null → control disabled, reason shown as the caption
  (instead of `caption`), plus `link` as a text button that selects `section`.
- Picker option `glyph` is drawn as a key cap before the label (`⌥ right Option`),
  `note` right-aligned and dimmed, `disabled` options are not selectable.
- Model `note` replaces the description line when present; `state` drives the
  control: `absent` → size + "will download" note, `loading` → spinner,
  `downloading` → segmented progress bar with `progress`, `error` → `note` in
  danger color + `recognition.model.retry` button (`model_retry`).
- Calls: show the first 5 items, then `calls.show_all` (`{n}` = count) expands
  the full list with search and day headers (`day` groups consecutive items);
  `missing` rows are dimmed with `calls.missing` and disabled buttons.
- `errors.term` / `errors.vocab` are shown under the inline editor;
  `errors.<setting key>` under that setting's row.
