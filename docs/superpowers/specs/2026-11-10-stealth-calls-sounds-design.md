# Hidden call recording, custom sounds, clickable call notification

Date: 10.11.2026. Branch `feat/stealth-sounds`. Approved in chat on 10.11.2026.

## 1. Hidden call recording

Setting `call_stealth` (bool, default off), Settings → Calls, toggle «Скрытая запись».

- While a call records or transcribes, the menubar icon shows the plain idle
  icon: no red phone, no timer, no pulsing. Dictation states still show as usual.
- The menu is unchanged: the status line reads «Запись звонка · 12:34», the
  stop item and recent calls are there. The settings window shows the live
  call as before.
- Call sounds (start, stop, transcript ready) are silent in this mode, so the
  speakers and the call do not carry them. Dictation sounds are unaffected.
- The «transcript ready» notification is not posted in this mode; the call
  shows up in the menu's recent calls.
- The macOS orange microphone indicator is a system privacy indicator and is
  left alone. It is on during every dictation, so it does not single out calls.

Implementation: `menubar_icon.Snapshot.stealth`; `frame()` ignores the call
state when it is set, `status()` (the menu line) does not.

## 2. Custom sounds

Sounds come from cuelume 0.2.8 (MIT, © 2026 Daniel Belyi), the library Bencho
rebuilt its mech/bubble/press styles from. Bencho itself is not used: its WAV
downloads need Pro.

Events and cues:

| event | cue | emphasis |
|---|---|---|
| dictation_start | open | subtle |
| dictation_stop | close | subtle |
| done (text inserted) | success | subtle |
| error | error | normal |
| call_start | loading | normal |
| call_stop | close | normal |
| call_ready | ready | normal |

- Files: `sounds/<theme>/<event>.wav` for themes default, mech, bubble, press,
  plus `sounds/LICENSE-cuelume.txt`. Rendered once with cuelume's own engine in
  a browser OfflineAudioContext, then trimmed and loudness-matched to the old
  macOS sounds (`scripts/render_sounds.html` + `scripts/finish_sounds.py`).
- Setting `sound_theme`: `default` | `mech` | `bubble` | `press` | `macos`
  (Tink/Pop/Ping/Basso as before) | `off`. Default `default`. Settings →
  General, picker «Звуки»; choosing a style plays its dictation-start sound.
- Playback stays `afplay`, non-blocking.

## 3. Clickable call notification

Notifications move from `osascript display notification` to
UNUserNotificationCenter (pyobjc-framework-UserNotifications). The «transcript
ready» notification carries the call file path; clicking it reveals the file
selected in Finder (`activateFileViewerSelectingURLs`). Other notifications
have no action. When the process has no bundle id (raw venv python) or
permission is denied, `notify()` falls back to osascript.

## 4. Settings window comes to front

The helper calls `orderFrontRegardless()`: macOS 14+ refuses `activate()` for a
background child process, so the window opened behind the active app.

## Testing

Unit tests for the icon model (stealth), sound path resolution, config
validation, settings model (new rows, set validation), notifier fallback and
reveal handling. Contract test keeps `demo-state.json` in sync. Live check in
the installed app after merge.
