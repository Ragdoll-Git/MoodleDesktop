import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QMessageBox, QTabWidget,
    QListWidget, QTextEdit, QProgressBar, QApplication
)
from PySide6.QtCore import QThread, QUrl
from PySide6.QtGui import QDesktopServices
from utils.config import config_manager
from utils import autostart
from core import updater

class SettingsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Configuración IA - Desktop")
        self.resize(450, 500)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        
        # --- Pestaña 1: General (APIs y MCP) ---
        self.tab_general = QWidget()
        self.setup_general_tab()
        self.tabs.addTab(self.tab_general, "General / APIs")
        
        # --- Pestaña 2: Prompts ---
        self.tab_prompts = QWidget()
        self.setup_prompts_tab()
        self.tabs.addTab(self.tab_prompts, "Mis Prompts")

        # --- Pestaña 3: Actualizaciones ---
        self.tab_updates = QWidget()
        self.setup_updates_tab()
        self.tabs.addTab(self.tab_updates, "Actualizaciones")

        main_layout.addWidget(self.tabs)

        save_btn = QPushButton("Guardar Todo y Cerrar")
        save_btn.clicked.connect(self.save_all_settings)
        main_layout.addWidget(save_btn)

    def setup_general_tab(self):
        layout = QVBoxLayout(self.tab_general)

        layout.addWidget(QLabel("Google Gemini API Key:"))
        self.gemini_key = QLineEdit(config_manager.get("GEMINI_API_KEY", ""))
        self.gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.gemini_key)

        layout.addWidget(QLabel("Groq API Key:"))
        self.groq_key = QLineEdit(config_manager.get("GROQ_API_KEY", ""))
        self.groq_key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.groq_key)

        layout.addWidget(QLabel("Nvidia API Key:"))
        self.nvidia_key = QLineEdit(config_manager.get("NVIDIA_API_KEY", ""))
        self.nvidia_key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.nvidia_key)

        if not os.environ.get("MOODLE_DESKTOP_PORTABLE") == "1":
            layout.addWidget(QLabel("--- Sistema ---"))
            self.autostart_chk = QCheckBox("Iniciar automáticamente con Windows" if sys.platform == "win32" else "Iniciar automáticamente al iniciar sesión")
            self.autostart_chk.setChecked(autostart.is_in_startup())
            layout.addWidget(self.autostart_chk)

        layout.addWidget(QLabel("--- Contexto MCP ---"))
        
        self.mcp_enabled = QCheckBox("Activar MCP")
        self.mcp_enabled.setChecked(config_manager.get("MCP_ENABLED", False))
        layout.addWidget(self.mcp_enabled)

        layout.addWidget(QLabel("Modo MCP:"))
        self.mcp_mode = QComboBox()
        self.mcp_mode.addItems(["local", "online"])
        self.mcp_mode.setCurrentText(config_manager.get("MCP_MODE", "local"))
        layout.addWidget(self.mcp_mode)

        layout.addWidget(QLabel("URL MCP:"))
        self.mcp_url = QLineEdit(config_manager.get("MCP_URL", ""))
        layout.addWidget(self.mcp_url)

        layout.addStretch()

    def setup_prompts_tab(self):
        layout = QVBoxLayout(self.tab_prompts)

        self.prompts_data = config_manager.get("CUSTOM_PROMPTS", []).copy()

        # Lista de Prompts
        self.prompt_list = QListWidget()
        self.prompt_list.currentRowChanged.connect(self.on_prompt_selected)
        layout.addWidget(self.prompt_list)
        
        # Botones de lista
        list_btns_layout = QHBoxLayout()
        add_btn = QPushButton("Añadir Nuevo")
        add_btn.clicked.connect(self.add_new_prompt)
        del_btn = QPushButton("Eliminar Seleccionado")
        del_btn.clicked.connect(self.delete_selected_prompt)
        list_btns_layout.addWidget(add_btn)
        list_btns_layout.addWidget(del_btn)
        layout.addLayout(list_btns_layout)

        # Edición del Prompt
        layout.addWidget(QLabel("Título:"))
        self.prompt_title = QLineEdit()
        layout.addWidget(self.prompt_title)
        
        layout.addWidget(QLabel("Contenido del Prompt:"))
        self.prompt_text = QTextEdit()
        layout.addWidget(self.prompt_text)

        update_btn = QPushButton("Actualizar/Guardar Prompt Actual")
        update_btn.clicked.connect(self.update_current_prompt)
        layout.addWidget(update_btn)

        self.refresh_prompt_list()

    def refresh_prompt_list(self):
        self.prompt_list.clear()
        for p in self.prompts_data:
            self.prompt_list.addItem(p["title"])

    def on_prompt_selected(self, index):
        if index >= 0 and index < len(self.prompts_data):
            p = self.prompts_data[index]
            self.prompt_title.setText(p["title"])
            self.prompt_text.setText(p["text"])
        else:
            self.prompt_title.clear()
            self.prompt_text.clear()

    def add_new_prompt(self):
        self.prompts_data.append({"title": "Nuevo Prompt", "text": "..."})
        self.refresh_prompt_list()
        self.prompt_list.setCurrentRow(len(self.prompts_data) - 1)

    def delete_selected_prompt(self):
        row = self.prompt_list.currentRow()
        if row >= 0:
            del self.prompts_data[row]
            self.refresh_prompt_list()
            self.prompt_title.clear()
            self.prompt_text.clear()

    def update_current_prompt(self):
        row = self.prompt_list.currentRow()
        if row >= 0:
            self.prompts_data[row]["title"] = self.prompt_title.text().strip()
            self.prompts_data[row]["text"] = self.prompt_text.toPlainText().strip()
            self.refresh_prompt_list()
            self.prompt_list.setCurrentRow(row)

    def save_all_settings(self):
        # Guardar Generales
        config_manager.set("GEMINI_API_KEY", self.gemini_key.text().strip())
        config_manager.set("GROQ_API_KEY", self.groq_key.text().strip())
        config_manager.set("NVIDIA_API_KEY", self.nvidia_key.text().strip())
        
        if not os.environ.get("MOODLE_DESKTOP_PORTABLE") == "1":
            autostart.set_startup(self.autostart_chk.isChecked())

        config_manager.set("MCP_ENABLED", self.mcp_enabled.isChecked())
        config_manager.set("MCP_MODE", self.mcp_mode.currentText())
        config_manager.set("MCP_URL", self.mcp_url.text().strip())
        
        # Guardar Prompts
        config_manager.set("CUSTOM_PROMPTS", self.prompts_data)
        
        QMessageBox.information(self, "Guardado", "Configuración guardada correctamente.")
        self.close()

    # ---------------------- Actualizaciones ----------------------

    def setup_updates_tab(self):
        layout = QVBoxLayout(self.tab_updates)
        self._pending_url = None
        self._pending_html_url = None
        self._upd_thread = None
        self._upd_worker = None

        layout.addWidget(QLabel(f"Versión actual: {updater.CURRENT_VERSION}"))

        self.upd_status = QLabel("")
        self.upd_status.setWordWrap(True)
        layout.addWidget(self.upd_status)

        self.upd_check_btn = QPushButton("Buscar actualizaciones")
        self.upd_check_btn.clicked.connect(self.on_check_clicked)
        layout.addWidget(self.upd_check_btn)

        self.upd_progress = QProgressBar()
        self.upd_progress.setVisible(False)
        layout.addWidget(self.upd_progress)

        self.upd_update_btn = QPushButton("Actualizar ahora")
        self.upd_update_btn.setVisible(False)
        self.upd_update_btn.clicked.connect(self.on_update_clicked)
        layout.addWidget(self.upd_update_btn)

        if updater.is_portable():
            note = ("Modo portable: se descargará el nuevo ejecutable y se "
                    "reemplazará al reiniciarse la aplicación.")
        else:
            note = ("Se descargará el instalador y se ejecutará "
                    "(puede pedir permisos de administrador de Windows).")
        hint = QLabel(note)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()

    def _set_update_busy(self, busy):
        self.upd_check_btn.setEnabled(not busy)
        self.upd_update_btn.setEnabled(not busy)

    def _make_worker_thread(self):
        thread = QThread()
        worker = updater.UpdateWorker()
        worker.moveToThread(thread)
        worker.progress.connect(self.upd_progress.setValue)
        worker.error.connect(self._on_update_error)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Guardamos referencias para que el GC no destruya el hilo/worker.
        self._upd_thread = thread
        self._upd_worker = worker
        return thread, worker

    def on_check_clicked(self):
        self._set_update_busy(True)
        self.upd_status.setText("Buscando actualizaciones...")
        thread, worker = self._make_worker_thread()
        worker.check_finished.connect(self._on_check_finished)
        worker.check_finished.connect(thread.quit)
        thread.started.connect(worker.do_check)
        thread.start()

    def _on_check_finished(self, info):
        self._set_update_busy(False)
        if info["available"]:
            self._pending_url = info["download_url"]
            self._pending_html_url = info.get("html_url", "")
            self.upd_status.setText(f"¡Nueva versión disponible: {info['latest_str']}!")
            self.upd_update_btn.setVisible(True)
        else:
            self.upd_status.setText(f"Estás en la última versión ({info['current']}).")
            self.upd_update_btn.setVisible(False)

    def on_update_clicked(self):
        if not updater.is_frozen():
            QMessageBox.information(
                self, "Solo en la app compilada",
                "La auto-actualización solo funciona en la versión compilada "
                "(.exe), no en modo desarrollo.")
            return
        if not self._pending_url:
            return
        # El portable se reemplaza a sí mismo: si está en una carpeta sin
        # permisos de escritura (p. ej. Archivos de programa), avisamos antes
        # de descargar en vez de fallar en silencio.
        if updater.is_portable() and not updater.portable_target_writable():
            QMessageBox.warning(
                self, "No se puede actualizar en esta carpeta",
                "Moodle Desktop Portable está en una carpeta sin permisos de "
                "escritura, por lo que no puede reemplazarse a sí mismo.\n\n"
                "Movelo a un USB o a una carpeta de usuario como Documentos y "
                "volvé a intentarlo. También podés descargar la nueva versión "
                "manualmente desde la página del release.")
            if self._pending_html_url:
                QDesktopServices.openUrl(QUrl(self._pending_html_url))
            return
        self._set_update_busy(True)
        self.upd_progress.setVisible(True)
        self.upd_progress.setValue(0)
        self.upd_status.setText("Descargando actualización...")
        url = self._pending_url
        thread, worker = self._make_worker_thread()
        worker.download_finished.connect(self._on_download_finished)
        worker.download_finished.connect(thread.quit)
        thread.started.connect(lambda: worker.do_download(url))
        thread.start()

    def _on_download_finished(self, path):
        self.upd_status.setText("Descarga completa. Aplicando actualización...")
        try:
            updater.apply_update(path)
        except Exception as exc:
            self._set_update_busy(False)
            self.upd_progress.setVisible(False)
            QMessageBox.warning(self, "Error al actualizar", str(exc))
            return
        QMessageBox.information(
            self, "Actualizando",
            "Moodle Desktop se cerrará para completar la actualización.")
        QApplication.instance().quit()

    def _on_update_error(self, msg):
        self._set_update_busy(False)
        self.upd_progress.setVisible(False)
        QMessageBox.warning(
            self, "Error", f"No se pudo completar la operación:\n{msg}")
