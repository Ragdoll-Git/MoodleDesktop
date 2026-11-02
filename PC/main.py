import os
import sys
import threading

_ON_WAYLAND = sys.platform == 'linux' and os.environ.get('XDG_SESSION_TYPE') == 'wayland'

if _ON_WAYLAND:
    # Use XWayland for Qt so windows can be freely positioned.
    # evdev handles hotkeys from /dev/input so they still work on all Wayland apps.
    os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
    import evdev
    from evdev import ecodes
else:
    from pynput import keyboard

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QObject, Signal

from ui.overlay import OverlayWindow
from ui.settings import SettingsWindow
from utils.capture import capture_screen_base64, init_screencast
from utils.config import get_resource_path, config_manager


class MainController(QObject):
    trigger_capture_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.overlay = OverlayWindow()
        self.settings_win = None

        self.trigger_capture_signal.connect(self.overlay.show_for_capture)

        self.setup_silent_capture()
        self.setup_tray()
        self.start_hotkey_listener()

    def setup_silent_capture(self):
        """Open a silent ScreenCast session on Wayland (no flash, no sound)."""
        if not _ON_WAYLAND:
            return

        def on_token(token):
            config_manager.set("SCREENCAST_RESTORE_TOKEN", token)

        token = config_manager.get("SCREENCAST_RESTORE_TOKEN")
        init_screencast(restore_token=token, on_token=on_token)

    def setup_tray(self):
        icon = QIcon(get_resource_path("images/icon16.png"))
        if icon.isNull():
            icon = self.app.style().standardIcon(self.app.style().StandardPixmap.SP_ComputerIcon)

        self.tray = QSystemTrayIcon(icon, self.app)
        self.tray.setToolTip("Moodle Desktop IA")

        menu = QMenu()

        config_action = QAction("Configuración", self.app)
        config_action.triggered.connect(self.show_settings)
        menu.addAction(config_action)

        menu.addSeparator()

        quit_action = QAction("Salir", self.app)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def show_settings(self):
        if not self.settings_win:
            self.settings_win = SettingsWindow()
        self.settings_win.show()
        self.settings_win.activateWindow()

    def on_activate_hotkey(self):
        if self.overlay.isVisible():
            self.overlay.hide()
            return

        try:
            b64_img = capture_screen_base64()
            self.trigger_capture_signal.emit(b64_img)
        except Exception as e:
            print(f"Error al capturar: {e}")

    def start_hotkey_listener(self):
        if _ON_WAYLAND:
            self._start_evdev_listener()
        else:
            self._start_pynput_listener()

    def _start_evdev_listener(self):
        # Read directly from /dev/input — works on Wayland regardless of focus.
        # Requires the user to be in the 'input' group.
        ALT_KEYS = {ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT}
        SHIFT_KEYS = {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}
        TARGET_KEY = ecodes.KEY_Z

        pressed = set()
        self._evdev_devices = []
        self._evdev_stop = threading.Event()

        def read_device(dev):
            try:
                for event in dev.read_loop():
                    if self._evdev_stop.is_set():
                        break
                    if event.type != ecodes.EV_KEY:
                        continue
                    if event.value == 1:  # key down
                        pressed.add(event.code)
                        if (event.code == TARGET_KEY
                                and pressed & ALT_KEYS
                                and pressed & SHIFT_KEYS):
                            self.on_activate_hotkey()
                    elif event.value == 0:  # key up
                        pressed.discard(event.code)
            except (OSError, IOError):
                pass

        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                if ecodes.EV_KEY in caps and ecodes.KEY_Z in caps[ecodes.EV_KEY]:
                    self._evdev_devices.append(dev)
                    t = threading.Thread(target=read_device, args=(dev,), daemon=True)
                    t.start()
            except (PermissionError, OSError):
                pass

        print(f"evdev listener activo en {len(self._evdev_devices)} dispositivo(s)")

    def _start_pynput_listener(self):
        combination = '<alt>+<shift>+z'

        self.hotkey = keyboard.HotKey(
            keyboard.HotKey.parse(combination),
            self.on_activate_hotkey)

        def on_press(k):
            self.hotkey.press(self.listener.canonical(k))

        def on_release(k):
            self.hotkey.release(self.listener.canonical(k))

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.start()

    def quit_app(self):
        if _ON_WAYLAND:
            self._evdev_stop.set()
            for dev in getattr(self, '_evdev_devices', []):
                try:
                    dev.close()
                except OSError:
                    pass
        else:
            self.listener.stop()
        self.tray.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    controller = MainController()
    controller.run()
