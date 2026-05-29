#!/usr/bin/env python3
"""
request_mic_permission.py — заставить macOS показать диалог
«хочет получить доступ к микрофону» для текущего python.

После Allow процесс python3.13 появится в System Settings →
Privacy & Security → Microphone.

Использует встроенные модули через PyObjC (поставляется с большинством
дистрибутивов Python для macOS).
"""

import sys
import time


def request_via_avfoundation():
    """Корректный путь: AVFoundation.requestAccessForMediaType."""
    try:
        import AVFoundation  # type: ignore
        import objc  # type: ignore
    except ImportError:
        return None  # PyObjC не установлен

    AVMediaTypeAudio = "soun"  # AVMediaType.audio

    # Проверим текущий статус
    status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
        AVMediaTypeAudio
    )
    status_names = {0: "notDetermined", 1: "restricted", 2: "denied", 3: "authorized"}
    print(f"[i] Текущий статус: {status_names.get(int(status), status)}")

    if int(status) == 3:
        print("[✓] Уже есть доступ к микрофону.")
        return True

    done = {"granted": None}

    def callback(granted):
        done["granted"] = bool(granted)
        print(f"[i] Пользователь {'разрешил' if granted else 'отклонил'} доступ.")

    print("[i] Запрашиваю доступ через AVFoundation...")
    AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AVMediaTypeAudio, callback
    )

    # Ждём ответа до 30 секунд
    for _ in range(300):
        if done["granted"] is not None:
            break
        time.sleep(0.1)

    return done["granted"]


def request_via_sounddevice():
    """Запасной путь: просто открыть InputStream — это тоже триггерит TCC."""
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError as e:
        print(f"[!] sounddevice/numpy не установлены: {e}", file=sys.stderr)
        return None

    print("[i] Запрашиваю микрофон через sounddevice (открываю короткую запись)...")
    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16") as stream:
            data, _ = stream.read(16000)  # 1 секунда
            peak = float(np.max(np.abs(data)))
            print(f"[i] Записал 1с, пик: {peak}")
            return peak > 0
    except Exception as e:
        print(f"[!] Ошибка: {e}", file=sys.stderr)
        return False


def main():
    print("=" * 60)
    print("Запрос разрешения на доступ к микрофону для python3")
    print(f"sys.executable: {sys.executable}")
    print("=" * 60)

    # Сначала AVFoundation — корректный способ
    result = request_via_avfoundation()

    if result is None:
        print("[i] PyObjC не доступен, использую запасной путь.")
        result = request_via_sounddevice()
    else:
        # AVFoundation отработал — но дополнительно дёрнем sounddevice,
        # чтобы python точно засветился в TCC для AudioCapture клиента.
        print("[i] Дополнительно проверяю запись через sounddevice...")
        request_via_sounddevice()

    print("=" * 60)
    if result:
        print("[✓] Готово. Теперь python3 должен появиться в System Settings →")
        print("    Privacy & Security → Microphone (с включённым тумблером).")
    else:
        print("[!] Не удалось получить доступ. Проверьте System Settings вручную.")
    print("=" * 60)


if __name__ == "__main__":
    main()
