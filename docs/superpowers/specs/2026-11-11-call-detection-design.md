# Call detection: offer to record, auto-stop, hint in hidden mode

Date: 11.11.2026. Branch `feat/call-detection`. Approved in chat on 11.11.2026.

## Problem

- Call recording starts and stops only by hand (call key F13 or the menu).
  After a call the user sometimes forgets to stop it, and the recording runs on
  until the 4-hour safety cap (`MAX_CALL_SESSION_SEC`).
- In hidden mode (`call_stealth`) the icon shows the plain microphone during a
  call. Pressing the dictation key then does nothing visible: `on_press`
  returns early while `call_session["active"]`, so the user cannot tell why
  dictation is dead, and is not reminded that a call is still recording.

## Signal: which apps hold the microphone

macOS 14.2+ lists Core Audio process objects, the same data behind the orange
microphone dot. Only metadata is read, never audio.

| what | selector |
|---|---|
| process list (on the system object) | `kAudioHardwarePropertyProcessObjectList` `'prs#'` |
| pid | `kAudioProcessPropertyPID` `'ppid'` |
| bundle id (CFString) | `kAudioProcessPropertyBundleID` `'pbid'` |
| uses input | `kAudioProcessPropertyIsRunningInput` `'piri'` |
| plays output | `kAudioProcessPropertyIsRunningOutput` `'piro'` |

Checked on 11.11.2026 from Python through ctypes: a `sounddevice.InputStream`
shows up as `(pid, "org.python.python")` with `piri = 1`; one full read takes
about 20 ms.

### `mic_users.py` (new, ctypes, no PyObjC)

- `snapshot(exclude_pids) -> list[AudioClient]` with
  `AudioClient(pid, bundle_id, input: bool, output: bool)`. It returns only
  processes that use input or output, minus `exclude_pids`.
- Fast path for the idle case: `snapshot(exclude_pids, need_output=False)`
  first checks `kAudioDevicePropertyDeviceIsRunningSomewhere` (`'gone'`) on
  every device with input streams (a handful of calls) and returns `[]` when
  none runs. The full process walk (~20 ms) happens only when some input runs
  or when `need_output` is set (during a call recording).
- `is_supported() -> bool`: the process-list property exists (macOS 14.2+).
  When it is unsupported, or any Core Audio call fails, `snapshot()` returns
  `[]`: the feature is simply off. The failure is logged once.
- `app_key(client) -> str` groups processes of one app. It strips helper
  suffixes from the bundle id (`com.google.Chrome.helper` → `com.google.Chrome`,
  likewise `.helper.renderer`, `.helper.plugin`, `.Helper`), or uses
  `pid:<n>` when there is no bundle id. Browsers run input and output in one
  helper, so input and output of the same app meet under one key.
- `app_name(key, pid) -> str | None` is a best-effort display name:
  1. `com.apple.WebKit.GPU` maps to «Safari»;
  2. the running app with the key as its bundle id (a Chrome helper pid
     would give «Google Chrome Helper», so the bundle goes first);
  3. otherwise `NSRunningApplication` for the pid;
  4. otherwise the key itself;
  5. for `pid:` keys, `None`, and the caller shows «Другая программа» /
     «Another app».
- Excluded pids: our own process and the system-audio helper
  (`SystemAudioCapture` exposes its child pid). Dictation and call recording
  by Voice Type itself never count.

## Detector (`call_detect.py`, new, pure)

The detector is polled every 2 s from a daemon thread `call-detect`. One poll
takes:
- `now`;
- `on_mic`: app keys with input running;
- `playing`: app keys with output running;
- `recording`: a call recording is active;
- `busy`: dictation is active or the app is paused;
- the settings `ask` (bool) and `auto_stop` (bool).

It returns a list of events.

State:
- `mic_since[key]`: since when the app holds the microphone without a break;
- `asked`: keys already offered during their current microphone session;
- `linked`: keys tied to the current recording;
- `quiet_since`: since when no linked key has input or output.

Constants: `ASK_AFTER_SEC = 8`, `STOP_AFTER_SEC = 20`, `POLL_SEC = 2`.

Events:

- **`Ask(key)`**. Fires when all of these hold:
  - `ask` is on;
  - nothing records;
  - not busy;
  - `key` has held the microphone for at least `ASK_AFTER_SEC`;
  - `key` is not in `asked`.

  The key is added to `asked`. The 8 s threshold filters out Siri, system
  dictation and short voice messages.
- **`Withdraw(key)`**: a key in `asked` released the microphone. Its
  notification is removed and the key leaves `asked`, so the next microphone
  session of that app is offered again.
- **`Stop(key)`**: fires during a recording when all of these hold:
  - `auto_stop` is on;
  - `linked` is not empty;
  - no linked key has had input **or** output for `STOP_AFTER_SEC`.

  `key` names the app for the log. The output condition protects a muted
  listener: if the call app releases the microphone on mute, the other side
  still plays, so recording continues. When any linked key gets input or
  output back, `quiet_since` resets.

Linking a recording to apps:
- When a recording starts, every key currently holding the microphone is
  linked, whether the recording came from the offer, the call key or the menu.
- During a recording, a key that holds the microphone for at least
  `ASK_AFTER_SEC` gets linked. A short Siri request during an in-person
  meeting is not linked, so it cannot stop that recording.
- With nothing linked (in-person meeting, recording without a call app),
  auto-stop never fires. Only the 4-hour cap stays.
- When a recording ends, `linked` and `quiet_since` reset. `asked` is kept: if
  the user stops by hand while Zoom still holds the microphone, the same Zoom
  session is not offered again.

The detector must not raise. The thread wraps each poll and logs repeated
errors once, the same way the watchdog does.

## Offer to record (notification)

- Title «Voice Type». Body «{app} использует микрофон. Записать звонок?» /
  «{app} is using the microphone. Record the call?». No sound: the
  notifier never sets one.
- Identifier `call-ask:<key>`, so `Withdraw` can remove a delivered
  notification and a repeat cannot stack. `userInfo = {"action": "record_call",
  "app": key}`.
- `notifier` gains:
  - `notify(..., ident=None, user_info=None)`;
  - `withdraw(ident)` (`removeDeliveredNotificationsWithIdentifiers_`);
  - routing of the default click through a registered handler per `action`.

  The existing `reveal` click keeps working.
- A click starts a call recording through the same path as the menu item,
  but only when all of these still hold; otherwise the click is logged and
  ignored:
  - the key still holds the microphone;
  - nothing records;
  - no dictation is running.
- The offer is shown in hidden mode too: nothing records yet, and macOS hides
  notifications while the screen is shared.
- Without the modern notification center (osascript fallback, raw venv run)
  the notification cannot be clicked. The body then ends with «Нажмите {key},
  чтобы записать.» / «Press {key} to record.», naming the call key.

## Auto-stop

- `Stop` behaves exactly like the user pressing the call key:
  `ctrl.put("call_stop")`, then transcription, saving and the usual
  notification rules (silent in hidden mode).
- Log line: `[call] auto-stop: {app} left the microphone {n}s ago`.

## Hint in hidden mode

- When the dictation key is pressed while a call records, `on_press` sets
  `call_peek_until = now + PEEK_SEC` (`PEEK_SEC = 3`). It still returns
  without starting dictation.
- `menubar_icon.Snapshot` gains `peek: bool` (`now < call_peek_until`).
  `frame()` applies `stealth` only when `peek` is off, so the icon shows the
  red phone and timer for 3 s, then returns to the plain microphone.
- No sound, so nothing reaches the call. Outside hidden mode the icon already
  shows the call and nothing changes.

## Settings

Config (`config.py`, validated like the other keys):
- `call_detect`: `"ask"` | `"off"`, default `"ask"`;
- `call_auto_stop`: bool, default `True`.

Settings → Calls, group «Запись», after «Скрытая запись», two new rows:
- **Picker `call_detect`.**
  - Label: «Когда другая программа включает микрофон» / «When another app
    turns on the microphone».
  - Options: «Спрашивать» / «Ask to record» and «Ничего не делать» /
    «Do nothing».
  - Caption: «Voice Type видит только, какие программы держат микрофон, — как
    оранжевая точка macOS. Звук не слушается.» / «Voice Type only sees which
    apps hold the microphone, like the macOS orange dot. It does not listen.»
- **Toggle `call_auto_stop`.**
  - Label: «Останавливать запись после звонка» / «Stop recording after the
    call».
  - Caption: «Когда программа звонка отпустила микрофон и 20 секунд ничего
    не играет. Запись без программы звонка останавливается вручную.» / «When
    the call app has released the microphone and played nothing for 20
    seconds. A recording without a call app is stopped by hand.»
- When `mic_users.is_supported()` is false, both rows are disabled with
  «Нужна macOS 14.2 или новее» / «Needs macOS 14.2 or later».

Contract changes:
- `settings_model._calls` gains `detect` (Picker) and `auto_stop` (Toggle).
- `settings_model` set-validation accepts the two keys.
- `native/settings/PROTOCOL.md`, `demo-state.json`, `Protocol.swift` and
  `CallsSection.swift` get the two rows.
- `i18n.py` gets the RU and EN strings.

## README

Calls section, one short paragraph:
- the offer to record and its click;
- auto-stop, and that a recording without a call app is stopped by hand;
- the privacy note that only the list of apps using the microphone is read.

## Testing

Unit tests:
- `tests/test_call_detect.py`, timelines:
  - Zoom holds the microphone, an offer comes after 8 s, exactly once;
  - a 5 s Siri request gets no offer;
  - when the app releases the microphone the offer is withdrawn, and the next
    session is offered again;
  - no offer while recording, while dictating, while paused, or with
    `ask` off;
  - a manual start while Zoom holds the microphone links Zoom;
  - Zoom leaves, and the stop comes after 20 s, not before;
  - muted listener (input off, output on): no stop;
  - in-person meeting (nothing linked): never stops;
  - Siri for 5 s during an in-person meeting: not linked, no stop;
  - two linked apps, one leaves: no stop;
  - `auto_stop` off: no stop;
  - a stop by hand resets `linked` and keeps `asked`.
- `tests/test_mic_users.py`:
  - app-key grouping with helper suffixes;
  - excluded pids;
  - unsupported or failing Core Audio gives `[]`;
  - a darwin-only smoke test that `snapshot()` returns a list.
- `tests/test_menubar_icon.py`: peek shows the phone and timer in stealth;
  without peek the plain microphone.
- Notifier: identifiers, `withdraw`, click routing by `action`, and that
  `reveal` still works.
- Config, settings-model and contract tests for `call_detect` and
  `call_auto_stop`.

Live check in the installed app after merge, on real calls:
- Meet in Chrome and one native app (Zoom or Telegram): the offer appears and
  a click starts recording.
- Muted for over a minute: the recording keeps going.
- Leaving the call: the recording stops within about 25 s and the transcript
  is saved.
- Hidden mode: the dictation key shows the phone for 3 s.

## Out of scope

- Starting a recording without asking.
- A per-app «never ask» list (add it if the offers become a nuisance).
- Calls taken on the iPhone, beyond whatever process holds the Mac
  microphone.
