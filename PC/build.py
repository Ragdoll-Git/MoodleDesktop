import os
import shutil
import subprocess
import sys

def build():
    # Cambiar al directorio donde está el script para que no falle si se llama desde otra ruta
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("Limpiando builds anteriores...")
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")

    # Usamos el PyInstaller del entorno virtual si existe (desarrollo local);
    # si no, recurrimos al módulo del intérprete actual (p. ej. en GitHub Actions).
    venv_pyinstaller = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "pyinstaller.exe")
    if os.path.exists(venv_pyinstaller):
        pyinstaller_cmd = [venv_pyinstaller]
    else:
        pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"]

    # Argumentos comunes: datos empaquetados y módulos ocultos
    common_args = [
        "--add-data", "images;images",
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        "--hidden-import", "keyring.backends",
        "--hidden-import", "keyring.backends.Windows",
    ]

    print("Compilando versión Persistente (MoodleDesktop.exe)...")
    subprocess.run([
        *pyinstaller_cmd,
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "MoodleDesktop",
        *common_args,
        "main.py"
    ], check=True)

    print("Compilando versión Portable (MoodleDesktop_Portable.exe)...")
    subprocess.run([
        *pyinstaller_cmd,
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", "MoodleDesktop_Portable",
        *common_args,
        "portable.py"
    ], check=True)

    print("¡Build finalizado con éxito!")
    print("Revisa la carpeta 'dist/'")

if __name__ == "__main__":
    build()
