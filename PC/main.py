import sys
import threading
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QObject, Signal
from pynput import keyboard

from ui.overlay import OverlayWindow
from ui.settings import SettingsWindow
from utils.capture import capture_screen_base64
from utils.config import get_resource_path

class MainController(QObject):
    # Usamos Signals para comunicarnos desde el hilo de pynput al hilo principal de Qt
    trigger_capture_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # Ventanas
        self.overlay = OverlayWindow()
        self.settings_win = None

        # Conectar señal
        self.trigger_capture_signal.connect(self.overlay.show_for_capture)

        self.setup_tray()
        self.start_hotkey_listener()

    def setup_tray(self):
        # Intentar cargar icono existente si hay
        icon = QIcon(get_resource_path("images/icon16.png"))
        if icon.isNull():
            # Fallback a algo interno
            icon = self.app.style().standardIcon(self.app.style().StandardPixmap.SP_ComputerIcon)
            
        self.tray = QSystemTrayIcon(icon, self.app)
        self.tray.setToolTip("Moodle Desktop IA")

        menu = QMenu()
        
        # Acción Configurar
        config_action = QAction("Configuración", self.app)
        config_action.triggered.connect(self.show_settings)
        menu.addAction(config_action)
        
        menu.addSeparator()

        # Acción Salir
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
        """ Callback cuando se presiona Alt+Shift+Z """
        # Si la ventana ya está visible, la ocultamos (Toggle)
        if self.overlay.isVisible():
            self.overlay.hide()
            return
            
        # La captura debe hacerse inmediatamente aquí para que no haya delay
        try:
            b64_img = capture_screen_base64()
            self.trigger_capture_signal.emit(b64_img)
        except Exception as e:
            print(f"Error al capturar: {e}")

    def start_hotkey_listener(self):
        # Mapeo de teclas. En Mac sería <cmd>+<shift>+z pero la app es para Windows
        combination = '<alt>+<shift>+z'
        
        def for_canonical(f):
            return lambda k: f(self.listener.canonical(k))

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
        self.listener.stop()
        self.tray.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    controller = MainController()
    controller.run()
