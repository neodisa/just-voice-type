"""Уведомления macOS.

Основной путь — UNUserNotificationCenter: у таких уведомлений есть клик, и
клик по уведомлению о звонке показывает файл звонка в Finder. Он доступен,
только когда процесс — бандл с bundle id (установленный Voice Type.app);
из голого venv-python остаётся osascript, как было.

Ответ на запрос разрешения не окончательный: у Voice Type, который годами
слал «старые» уведомления, macOS сразу отвечает «not allowed», но доставку
всё равно решают переключатели в Системных настройках → Уведомления. Поэтому
шлём через центр всегда и падаем на osascript, только если сама отправка
вернула ошибку. Старый NSUserNotificationCenter в том же процессе usernoted
не пускает («You can't mix modern clients with legacy clients»), см.
voice_type.run_app.
"""

import os
import subprocess
import uuid
from typing import Callable, Optional

REVEAL_KEY = "reveal"
DEFAULT_ACTION = "com.apple.UNNotificationDefaultActionIdentifier"
# запуск из venv: mainBundle — Python.app, уведомления ушли бы от имени Python
FOREIGN_BUNDLES = frozenset({"org.python.python"})


def osascript_notify(title: str, message: str) -> None:
    safe = message.replace('"', '\\"').replace("\n", " ")
    safe_title = title.replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e", f'display notification "{safe}" with title "{safe_title}"'],
        check=False,
    )


def reveal_in_finder(path: str, workspace=None) -> bool:
    """Выделить файл в Finder; если файла уже нет — открыть его папку."""
    from AppKit import NSURL, NSWorkspace

    ws = workspace or NSWorkspace.sharedWorkspace()
    if path and os.path.exists(path):
        ws.activateFileViewerSelectingURLs_([NSURL.fileURLWithPath_(path)])
        return True
    folder = os.path.dirname(path) if path else ""
    if folder and os.path.isdir(folder):
        ws.openURL_(NSURL.fileURLWithPath_(folder))
        return True
    return False


def handle_click(user_info, action: str, reveal: Callable[[str], object]) -> None:
    """Клик по уведомлению: по умолчанию — показать файл, если он привязан."""
    if action != DEFAULT_ACTION or not user_info:
        return
    path = user_info.get(REVEAL_KEY)
    if path:
        reveal(str(path))


def _bundle_id() -> Optional[str]:
    from Foundation import NSBundle

    return NSBundle.mainBundle().bundleIdentifier()


_delegate_class = None


def _make_delegate_class():
    """ObjC-класс делегата создаётся один раз на процесс (имена классов глобальны)."""
    global _delegate_class
    if _delegate_class is not None:
        return _delegate_class
    import objc
    import UserNotifications as UN
    from Foundation import NSObject

    class JVTNotificationDelegate(
        NSObject, protocols=[objc.protocolNamed("UNUserNotificationCenterDelegate")]
    ):
        def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
            self, center, response, handler
        ):
            try:
                content = response.notification().request().content()
                action = str(response.actionIdentifier())
                self.log(f"[notify] clicked ({action})")
                handle_click(content.userInfo(), action, self.reveal)
            except Exception as e:  # клик не должен ронять приложение
                self.log(f"[notify] click failed: {e}")
            finally:
                handler()

        def userNotificationCenter_willPresentNotification_withCompletionHandler_(
            self, center, notification, handler
        ):
            handler(UN.UNNotificationPresentationOptionBanner | UN.UNNotificationPresentationOptionList)

    _delegate_class = JVTNotificationDelegate
    return _delegate_class


class Notifier:
    def __init__(
        self,
        log: Callable[[str], None] = print,
        fallback: Callable[[str, str], None] = osascript_notify,
        reveal: Callable[[str], object] = reveal_in_finder,
    ):
        self._log = log
        self._fallback = fallback
        self._reveal = reveal
        self._center = None
        self._delegate = None

    @property
    def native(self) -> bool:
        return self._center is not None

    def use_center(self, center) -> None:
        """Подменить центр уведомлений (тесты)."""
        self._center = center

    def start(self, bundle_id: Callable[[], Optional[str]] = _bundle_id) -> None:
        """Подключиться к UNUserNotificationCenter. Вызывать с главного потока."""
        try:
            bid = bundle_id()
            if not bid or bid in FOREIGN_BUNDLES:
                self._log(f"[notify] not inside Voice Type.app ({bid}) — using osascript")
                return
            import UserNotifications as UN
        except Exception as e:
            self._log(f"[notify] UserNotifications unavailable ({e}) — using osascript")
            return
        center = UN.UNUserNotificationCenter.currentNotificationCenter()
        self._delegate = _make_delegate_class().alloc().init()
        self._delegate.reveal = self._reveal
        self._delegate.log = self._log
        center.setDelegate_(self._delegate)

        def on_auth(granted, error):
            if not granted:
                # не приговор: доставку решают Системные настройки (см. выше)
                self._log(f"[notify] authorization: not granted ({error}); posting anyway")

        center.requestAuthorizationWithOptions_completionHandler_(
            UN.UNAuthorizationOptionAlert | UN.UNAuthorizationOptionSound, on_auth
        )
        self._center = center

    def notify(self, title: str, message: str, reveal: Optional[str] = None) -> None:
        if self._center is None:
            self._fallback(title, message)
            return
        import UserNotifications as UN

        content = UN.UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(message)
        if reveal:
            content.setUserInfo_({REVEAL_KEY: reveal})
        request = UN.UNNotificationRequest.requestWithIdentifier_content_trigger_(
            str(uuid.uuid4()), content, None
        )

        def done(error):
            if error is not None:
                self._log(f"[notify] not delivered ({error}) — osascript")
                self._fallback(title, message)

        self._center.addNotificationRequest_withCompletionHandler_(request, done)
