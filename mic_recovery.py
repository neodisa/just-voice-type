"""Самовосстановление Just Voice Type после зависшего CoreAudio.

Что происходит (по логам): после диктовки фоновый stream.abort() навсегда
встаёт внутри CoreAudio, а следующий recorder.start() в control_loop
блокируется на открытии микрофона. control_loop — единственный поток,
который обслуживает команды, поэтому дальше приложение молчит, пока его не
перезапустят руками. Застрявший в CoreAudio поток изнутри процесса не убить
и Pa_Terminate поверх него ронять нельзя, а вот новый процесс получает
чистый аудио-контекст — ровно то, что делал ручной перезапуск.

Перезапуск — именно новым процессом (`open -n` бандла), а не execve на
месте: после execve macOS (проверено на 26.x) не показывает статус-иконку
нового образа — приложение работает по клавишам, а в строке меню его нет.

Здесь только чистая логика (когда перезапускаться, сколько раз можно,
диагностика перед перезапуском) — без GUI и аудио, чтобы её можно было
проверить тестами. Подключение — в voice_type._watchdog_tick.
"""
from __future__ import annotations

import faulthandler
import os
import subprocess
import sys
import time
from typing import Callable, Optional, Tuple

# recorder.start() дольше этого — микрофон не откроется уже никогда
# (нормальное открытие занимает десятки миллисекунд, «протухшее» — до ~1 с)
START_HANG_SEC = 4.0
# фоновый abort/close висит дольше этого — в логах все такие случаи
# заканчивались мёртвым микрофоном; перезапускаемся заранее, пока простаиваем
TEARDOWN_HANG_SEC = 8.0

# не больше BUDGET_MAX перезапусков за BUDGET_WINDOW_SEC: если CoreAudio
# висит системно (coreaudiod), перезапуск не поможет — не крутимся в цикле
BUDGET_MAX = 3
BUDGET_WINDOW_SEC = 15 * 60
# метки времени прошлых перезапусков переходят в новый процесс через окружение
ENV_KEY = "JVT_RELAUNCHES"
OPEN = "/usr/bin/open"

LOG_DIR = os.path.expanduser("~/Library/Logs/WhisperFlow")
LOG_FILES = ("whisper_flow.log", "whisper_flow.err.log")
MAX_LOG_BYTES = 20 * 1024 * 1024
KEEP_LOG_BYTES = 2 * 1024 * 1024


def relaunch_reason(
    now: float,
    start_since: Optional[float],
    teardown_age: Optional[float],
    idle: bool,
) -> Optional[str]:
    """Пора ли перезапускаться и почему.

    start_since — когда control_loop вошёл в recorder.start() (None — не в нём);
    teardown_age — возраст самого старого незакрытого abort/close (None — нет);
    idle — ничего не пишется, не распознаётся и не доставляется.
    """
    if start_since is not None and now - start_since > START_HANG_SEC:
        return "start_hung"
    if idle and teardown_age is not None and teardown_age > TEARDOWN_HANG_SEC:
        return "teardown_hung"
    return None


def budget_allows(value: str, now: float) -> Tuple[bool, str]:
    """(можно ли перезапуститься, новое значение для ENV_KEY).

    value — метки времени прошлых перезапусков через запятую; мусор и всё,
    что старше окна, отбрасываем."""
    kept = []
    for part in (value or "").split(","):
        try:
            t = float(part)
        except ValueError:
            continue
        if now - t < BUDGET_WINDOW_SEC:
            kept.append(t)
    if len(kept) >= BUDGET_MAX:
        return False, ",".join(str(t) for t in kept)
    kept.append(now)
    return True, ",".join(str(t) for t in kept)


def dump_threads(file) -> None:
    """Python-стеки всех потоков — видно, на какой строке встал control_loop
    и фоновый abort/close."""
    try:
        file.flush()
    except Exception:
        pass
    faulthandler.dump_traceback(file=file, all_threads=True)


def sample_process(pid: int, out_path: str, seconds: int = 1) -> None:
    """Нативные стеки через /usr/bin/sample — показывают, где именно внутри
    CoreAudio залип поток. Best-effort: нет sample / нет прав — молча идём
    дальше."""
    try:
        subprocess.run(
            ["/usr/bin/sample", str(pid), str(seconds), "-file", out_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=seconds + 8,
            check=False,
        )
    except Exception:
        pass


def default_diagnose(reason: str) -> None:
    """Снять диагностику до перезапуска: после выхода её уже не получить."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    print(
        f"[{time.strftime('%H:%M:%S')}] [recovery] {reason} — thread stacks:",
        file=sys.stderr,
        flush=True,
    )
    dump_threads(sys.stderr)
    os.makedirs(LOG_DIR, exist_ok=True)
    out = os.path.join(LOG_DIR, f"hang-{stamp}.txt")
    sample_process(os.getpid(), out)
    if os.path.exists(out):
        print(f"[recovery] native stacks: {out}", file=sys.stderr, flush=True)


def relaunch_commands(value: str, app_path: Optional[str]) -> "list[list[str]]":
    """Чем запускать свежую копию, по порядку попыток.

    Внутри .app — `open -n` того же бандла: ровно тот путь, которым
    приложение стартует всегда (лаунчер, его окружение и файлы логов, права
    macOS). Запасной путь и запуск из venv — тот же интерпретатор с тем же
    argv."""
    direct = [sys.executable, *list(sys.orig_argv)[1:]]
    if app_path:
        return [[OPEN, "-n", "-a", app_path, "--env", f"{ENV_KEY}={value}"], direct]
    return [direct]


def _spawn(cmd: "list[str]", env: dict) -> None:
    if cmd[0] == OPEN:
        # open возвращается, когда LaunchServices запустил новую копию
        subprocess.run(
            cmd, env=env, check=True, timeout=15,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        # stdout/stderr наследуются — новая копия пишет в те же логи
        subprocess.Popen(cmd, env=env, start_new_session=True)


def _bundle_path() -> Optional[str]:
    import login_item

    return login_item.app_bundle_path()


_AUTO = object()


def relaunch(
    reason: str,
    *,
    env: Optional[dict] = None,
    now: Optional[float] = None,
    app_path=_AUTO,
    spawn: Callable[[list, dict], None] = _spawn,
    exit: Callable[[int], None] = os._exit,
    diagnose: Callable[[str], None] = default_diagnose,
) -> bool:
    """Запустить свежую копию себя и выйти.

    False — бюджет перезапусков исчерпан или новую копию запустить не
    удалось; ничего не сделано, решать дальше вызывающему. При успехе
    процесс завершается (os._exit: потоки, застрявшие в CoreAudio, не
    держат выход); True возвращается только из тестов с подменённым exit."""
    env = dict(os.environ if env is None else env)
    now = time.time() if now is None else now
    ok, value = budget_allows(env.get(ENV_KEY, ""), now)
    if not ok:
        return False
    try:
        diagnose(reason)
    except Exception as e:
        print(f"[recovery] diagnostics failed: {e}", file=sys.stderr, flush=True)
    env[ENV_KEY] = value
    path = _bundle_path() if app_path is _AUTO else app_path
    for cmd in relaunch_commands(value, path):
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            spawn(cmd, env)
        except Exception as e:
            print(f"[recovery] relaunch via {cmd[0]} failed: {e}", file=sys.stderr, flush=True)
            continue
        print(f"[recovery] new copy started via {cmd[0]} — exiting", file=sys.stderr, flush=True)
        exit(0)
        return True
    return False


def trim_log(path: str, max_bytes: int, keep_bytes: int) -> bool:
    """Если лог больше max_bytes — оставить в нём последние keep_bytes.

    Режем на месте, а не переименованием: лаунчер держит файл открытым как
    `2>>file` (O_APPEND), и после обрезки запись продолжится в конец файла."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size <= max_bytes:
        return False
    with open(path, "r+b") as f:
        f.seek(max(0, size - keep_bytes))
        tail = f.read()
        f.seek(0)
        f.write(tail)
        f.truncate()
    return True


def trim_app_logs() -> None:
    """Обрезать раздутые логи приложения при старте. Best-effort."""
    for name in LOG_FILES:
        try:
            trim_log(os.path.join(LOG_DIR, name), MAX_LOG_BYTES, KEEP_LOG_BYTES)
        except Exception as e:
            print(f"[!] log trim {name}: {e}", file=sys.stderr)
