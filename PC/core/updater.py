"""Sistema de auto-actualización de FMoodle Desktop.

Consulta el último release publicado en GitHub, compara versiones y, si hay una
nueva, descarga el instalador o el portable (según cómo se esté ejecutando la
app) y lo aplica:

* Instalador: se lanza el asistente descargado (UAC de Windows) y la app se
  cierra; al terminar, el propio instalador relanza FMoodle.
* Portable: se descarga el nuevo .exe y un script .bat (con CREATE_NO_WINDOW)
  espera a que el proceso actual termine, reemplaza el ejecutable con retry y
  vuelve a abrirlo.

La parte de red corre en un hilo aparte (UpdateWorker) para no congelar la UI.
"""
import os
import re
import sys
import subprocess
import tempfile

import requests
from PySide6.QtCore import QObject, Signal, Slot

try:
    from version import __version__ as CURRENT_VERSION
except Exception:  # pragma: no cover - fallback defensivo
    CURRENT_VERSION = "0.0.0"

GITHUB_REPO = "Ragdoll-Git/FMoodle"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_HEADERS = {
    "User-Agent": "FMoodle-Updater",
    "Accept": "application/vnd.github+json",
}

INSTALLER_ASSET = "FMoodle_Installer.exe"
PORTABLE_ASSET = "FMoodle_Portable.exe"


def is_portable():
    return os.environ.get("FMOODLE_PORTABLE") == "1"


def is_frozen():
    """True solo cuando corre como .exe compilado con PyInstaller."""
    return getattr(sys, "frozen", False)


def asset_name():
    return PORTABLE_ASSET if is_portable() else INSTALLER_ASSET


def portable_target_writable():
    """True si se puede escribir en la carpeta donde vive el .exe portable.

    Si el portable está en una carpeta protegida (p. ej. Archivos de programa),
    el reemplazo fallaría sin pedir UAC, así que conviene avisar antes.
    """
    target_dir = os.path.dirname(sys.executable)
    test_file = os.path.join(target_dir, ".fmoodle_write_test.tmp")
    try:
        with open(test_file, "w") as f:
            f.write("x")
        os.remove(test_file)
        return True
    except OSError:
        return False


def parse_version(text):
    """Extrae (mayor, menor, parche) de un texto como 'FMoodle-v3.6.3' o '3.6'."""
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not match:
        return (0, 0, 0)
    major, minor, patch = match.group(1), match.group(2), match.group(3)
    return (int(major), int(minor), int(patch or 0))


def check_for_update(current=CURRENT_VERSION, timeout=10):
    """Consulta el último release. Devuelve un dict con la info de actualización.

    Lanza requests.RequestException si falla la red, o ValueError si el release
    no incluye el asset que corresponde a esta variante (instalador/portable).
    """
    resp = requests.get(LATEST_RELEASE_API, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    latest_str = data.get("tag_name", "")
    wanted = asset_name()
    download_url = None
    for asset in data.get("assets", []):
        if asset.get("name") == wanted:
            download_url = asset.get("browser_download_url")
            break

    if download_url is None:
        raise ValueError(f"El release {latest_str} no incluye {wanted}.")

    return {
        "available": parse_version(latest_str) > parse_version(current),
        "current": current,
        "latest": parse_version(latest_str),
        "latest_str": latest_str,
        "download_url": download_url,
        "html_url": data.get("html_url", ""),
        "asset": wanted,
    }


def download(url, dest_path, progress_cb=None, timeout=30):
    """Descarga `url` a `dest_path` reportando el progreso (0-100) si se pasa cb."""
    with requests.get(url, headers=_HEADERS, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(int(done * 100 / total))
    if progress_cb:
        progress_cb(100)
    return dest_path


def apply_update(downloaded_path):
    """Aplica la actualización descargada. Solo funciona en la app compilada.

    Devuelve True si lanzó el proceso de actualización (la app debe cerrarse a
    continuación). Lanza RuntimeError si no está compilada (modo desarrollo).
    """
    if not is_frozen():
        raise RuntimeError(
            "La auto-actualización solo funciona en la app compilada (.exe)."
        )
    if is_portable():
        return _apply_portable(downloaded_path)
    return _apply_installer(downloaded_path)


def _apply_installer(installer_path):
    # Se lanza el asistente normal: pedirá UAC e instalará sobre la versión
    # actual. La casilla post-instalación de Inno relanza FMoodle al terminar.
    os.startfile(installer_path)  # noqa: S606 - ejecutable propio descargado del release
    return True


def _apply_portable(new_exe_path):
    current_exe = sys.executable
    if not portable_target_writable():
        raise PermissionError(
            "No hay permisos de escritura en la carpeta del portable."
        )
    pid = os.getpid()
    bat_path = os.path.join(tempfile.gettempdir(), "fmoodle_update.bat")

    # Espera a que el proceso actual termine (libera el lock del .exe), mueve el
    # nuevo ejecutable sobre el actual, lo relanza y se autoelimina.
    # Se usa un retry en el move porque Windows puede tardar unos instantes en
    # liberar el lock del archivo incluso después de que el proceso haya muerto.
    script = f"""@echo off
:waitloop
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto waitloop
)
set retries=0
:moveloop
move /Y "{new_exe_path}" "{current_exe}" >NUL 2>&1
if errorlevel 1 (
    set /a retries+=1
    if %retries% GEQ 10 goto fail
    timeout /t 1 /nobreak >NUL
    goto moveloop
)
start "" "{current_exe}"
del "%~f0"
exit /b 0
:fail
del "%~f0"
exit /b 1
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(script)

    # IMPORTANTE: CREATE_NO_WINDOW y DETACHED_PROCESS son mutuamente
    # excluyentes según la documentación de Windows. Usar ambos causa
    # comportamiento indefinido (cmd.exe se cierra inmediatamente).
    # CREATE_NO_WINDOW es el correcto: ejecuta cmd.exe sin ventana visible
    # pero con consola funcional (stdin/stdout) para los comandos del .bat.
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    cmd_exe = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"),
                           "System32", "cmd.exe")
    subprocess.Popen(
        [cmd_exe, "/c", bat_path],
        creationflags=no_window,
        close_fds=True,
    )
    return True


class UpdateWorker(QObject):
    """Worker que ejecuta chequeo y descarga en un hilo aparte (patrón QThread)."""

    check_finished = Signal(object)   # dict de check_for_update
    download_finished = Signal(str)   # ruta del archivo descargado
    progress = Signal(int)            # 0-100
    error = Signal(str)

    @Slot()
    def do_check(self):
        try:
            self.check_finished.emit(check_for_update())
        except Exception as exc:  # red, JSON, asset faltante, etc.
            self.error.emit(str(exc))

    @Slot(str)
    def do_download(self, url):
        try:
            suffix = ".exe"
            fd, dest = tempfile.mkstemp(prefix="FMoodle_update_", suffix=suffix)
            os.close(fd)
            download(url, dest, progress_cb=self.progress.emit)
            self.download_finished.emit(dest)
        except Exception as exc:
            self.error.emit(str(exc))
