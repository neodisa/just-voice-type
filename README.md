# Just Voice Type

**Локальная push-to-talk диктовка для macOS** на базе Whisper (Apple Silicon, MLX).
Зажал Right Option — наговорил — отпустил — текст вставился туда, где курсор. Никаких облаков, никаких API ключей, никаких подписок.

> Аналог Wispr Flow / Superwhisper, только всё крутится локально и бесплатно. RU/EN/мультиязычно.

## Возможности

- 🎙 **Иконка в menubar** (статусы: idle, REC, распознаю, пауза).
- ⌨️ **Push-to-talk** на любую системную клавишу: Right Option (по умолчанию), Fn, F13–F20, etc.
- 🧠 **MLX Whisper** (по умолчанию `large-v3`) — быстрый на M-чипах. Альтернативно `faster-whisper` на CPU.
- 📋 **Авто-вставка** распознанного текста через буфер обмена + `Cmd+V`, с восстановлением исходного буфера.
- 🔔 macOS-звуки на старт/стоп записи, опциональные уведомления.
- 🚀 **Автозапуск** через LaunchAgent — иконка появляется сразу после логина.
- 🇷🇺 Заточено под русский, но работает на любом языке Whisper.

## Требования

- macOS на Apple Silicon (M1/M2/M3/M4).
- Python 3.10+.
- Первый запуск качает модель Whisper (~3 GB для `large-v3`).

## Установка

```bash
git clone https://github.com/neodisa/just-voice-type.git
cd just-voice-type
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install rumps   # для UI в menubar
```

### Права macOS (обязательно)

`System Settings → Privacy & Security`:

- **Microphone** ✓
- **Accessibility** ✓ — без этого `pynput` не увидит Right Option
- **Input Monitoring** ✓

Выдать нужно тому процессу, из которого запускаете: Terminal/iTerm на этапе разработки, либо `~/just-voice-type/.venv/bin/python3` если ставите автозапуск через LaunchAgent.

После выдачи прав **полностью** перезапустите Terminal (Cmd+Q + открыть заново).

## Запуск

```bash
python3 whisper_flow_app.py
```

В строке меню сверху появится 🎙. Зажмите Right Option — внизу всплывёт капсула с пульсацией. Отпустили — текст вставился туда, где был курсор.

### CLI-флаги

| Флаг | Значение |
|---|---|
| `--engine mlx \| faster` | Движок. По умолчанию `mlx` (быстрее на Apple Silicon). |
| `--model <id>` | HF id модели. По умолчанию `mlx-community/whisper-large-v3-mlx`. |
| `--lang ru` | Язык. По умолчанию `ru`. |
| `--hotkey right_option` | `right_option`, `left_option`, `fn`, `right_shift`, `f13`..`f20`. |
| `--no-paste` | Не вставлять, только класть в буфер. |
| `--no-restore-clipboard` | Не восстанавливать предыдущее содержимое буфера. |
| `--notify` | macOS-уведомление с распознанным текстом. |

Без UI (только CLI) есть `whisper_flow.py` с тем же набором флагов.

## Автозапуск при логине

```bash
./install_autostart.sh
```

Скрипт:
1. Рендерит `com.whisperflow.local.plist` (шаблон) под путь вашего проекта.
2. Кладёт результат в `~/Library/LaunchAgents/`.
3. Регистрирует через `launchctl bootstrap` и стартует.

После этого 🎙 появляется сама при каждом входе. Логи: `whisper_flow.log` и `whisper_flow.err.log` в корне проекта.

**Важно:** после установки автозапуска права (Accessibility / Input Monitoring / Microphone) нужны не Terminal, а самому `python3` из `.venv` — потому что launchd запускает его напрямую. macOS обычно сам спросит при первой попытке прочитать клавиатуру или микрофон.

### Удалить автозапуск

```bash
./uninstall_autostart.sh
```

### Проверить статус / логи

```bash
launchctl print gui/$(id -u)/com.whisperflow.local | head -30
tail -f whisper_flow.log
tail -f whisper_flow.err.log
```

## Альтернативные модели

```bash
python3 whisper_flow_app.py --model mlx-community/whisper-medium-mlx        # быстрее, чуть хуже
python3 whisper_flow_app.py --model mlx-community/whisper-small-mlx         # ещё быстрее
python3 whisper_flow_app.py --engine faster --model large-v3                # CPU faster-whisper
```

Первый раз модель скачивается из HuggingFace (~1-3 GB), дальше живёт в `~/.cache/huggingface/`.

## Troubleshooting

| Симптом | Что делать |
|---|---|
| Нет иконки в menubar | Проверьте, не свернули ли её Bartender/HiddenBar. |
| Иконка есть, но хоткей не реагирует | Не выданы Accessibility/Input Monitoring. Перезапустите Terminal после выдачи. |
| Капсула не появляется | Tkinter не собран в системном Python. Поставьте Python через Homebrew или python.org. |
| Звуки не играют | `ls /System/Library/Sounds/` — проверьте, что есть Tink/Pop. |
| Модель долго грузит | Первый раз — да, ~3 GB. Возьмите `medium` для скорости. |
| Распознаёт галлюцинации («Thanks for watching!») | Это известный артефакт Whisper на тишине. Они фильтруются автоматически, остальное — увеличьте длину фразы. |
| LaunchAgent падает в цикле | `launchctl print gui/$(id -u)/com.whisperflow.local` покажет exit code. Часто — нет прав или нет `.venv`. |

## Лицензия

[MIT](LICENSE)

## Имена

Кодовое имя модуля и LaunchAgent label — `whisper_flow` / `com.whisperflow.local` — историческое, осталось с первой ревизии. Проект называется **Just Voice Type**.
