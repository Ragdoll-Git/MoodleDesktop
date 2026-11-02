# Instrucciones de Uso y Compilación 🛠️

Este documento detalla cómo utilizar, instalar y compilar **Moodle Desktop** desde cero.

---

## 1. Instalación Rápida (Usuarios Finales)

Si solo quieres usar el programa, dirígete a la carpeta `PC/Releases/` en el código fuente (o descárgalos desde GitHub Releases) y elige tu versión preferida:

### Opción A: Instalador Persistente (`MoodleDesktop_Installer.exe`)
Ideal para tu computadora personal de uso diario.
1. Ejecuta `MoodleDesktop_Installer.exe`.
2. Sigue el asistente de instalación clásico (Siguiente > Instalar).
3. Una vez instalado, ábrelo. Ve a la pestaña **Ajustes** (ícono del engranaje).
4. Introduce tus API Keys (se guardarán en el *Administrador de Credenciales de Windows*, jamás en texto plano).
5. (Opcional) Activa "Iniciar con Windows" para que el asistente esté siempre activo al encender tu PC.

### Opción B: Modo Portable (`MoodleDesktop_Portable.exe`)
Ideal para computadoras de terceros, bibliotecas, oficinas o pendrives.
1. Copia `MoodleDesktop_Portable.exe` a tu pendrive.
2. Ejecútalo. **No pedirá permisos de administrador**.
3. Pon tus API Keys temporalmente en Ajustes.
4. Cuando cierres la ventana, la memoria RAM se vaciará y la PC quedará sin ningún rastro de tus configuraciones o claves.

### Opción C: Extensión de Chrome (`MoodleDesktop_Extension.zip`)
Ideal para usar Moodle Desktop directamente dentro del navegador.
1. Descarga `MoodleDesktop_Extension.zip` desde GitHub Releases y descomprímelo (o usa directamente la carpeta `extension/` del código fuente).
2. Abre Chrome/Edge y ve a `chrome://extensions`.
3. Activa el **Modo de desarrollador** (interruptor en la esquina superior derecha).
4. Pulsa **"Cargar descomprimida"** y selecciona la carpeta descomprimida (la que contiene `manifest.json`).
5. Abre las **Opciones** de la extensión e introduce tus API Keys.

---

## 2. Configuración para Desarrolladores (App de Escritorio)

Si quieres modificar el código de la aplicación de escritorio (carpeta `PC/`), sigue estos pasos.

### Prerrequisitos
* **Python 3.10+** (Recomendado 3.11 o superior).
* Entorno Windows 10 u 11 (Usa la API `winreg` y el `Credential Manager` de Windows).

### Configuración del Entorno Virtual
1. Abre tu terminal (PowerShell o CMD).
2. Clona el repositorio y entra a la carpeta de la app de escritorio:
   ```powershell
   git clone https://github.com/Ragdoll-Git/MoodleDesktop.git
   cd MoodleDesktop/PC
   ```
3. Crea y activa tu entorno virtual (dentro de `PC/`):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```
4. Instala las dependencias:
   ```powershell
   pip install -r requirements.txt
   ```
   *(Asegúrate de instalar PySide6, keyring, requests, mcp, etc)*

### Ejecutar en Desarrollo
Puedes ejecutar las dos versiones directo desde el intérprete:
- **Modo normal:** `python main.py`
- **Modo en RAM (Portable):** `python portable.py`

### Ejecutar los Tests
La carpeta `PC/tests/` contiene una suite de `pytest` (smoke tests de importación y verificación del contrato del modo portable: que no escribe a disco ni toca el Almacén de Credenciales). Desde `PC/`:
```powershell
pip install -r requirements-dev.txt
pytest
```

---

## 3. Compilación y Empaquetado

Para generar tus propios `.exe`, Moodle Desktop cuenta con un script de compilación inteligente que usa `PyInstaller` encapsulado.

1. Asegúrate de tener tu entorno virtual activo (`..venv\Scripts\activate`).
2. Verifica que `pyinstaller` esté instalado:
   ```powershell
   pip install pyinstaller
   ```
3. Ejecuta el empaquetador:
   ```powershell
   python build.py
   ```
4. Esto limpiará las builds anteriores y creará una carpeta `PC/dist/` con las nuevas compilaciones, lista para distribuir.

> **Nota:** todos los comandos de esta sección (`pip install`, `python main.py`, `python portable.py`, `python build.py`) se ejecutan desde la carpeta `PC/`.

### Crear un Instalador Profesional
Si deseas generar un instalador con formato asistente (Next > Next > Install), puedes descargar **Inno Setup Compiler**. 
Abre el archivo `PC/inno_setup.iss` con este programa y dale al botón "Compile". Generará el instalador automáticamente en la carpeta `PC/Output/`. *(Nota vital: Debes haber ejecutado `build.py` primero para que se genere la carpeta `PC/dist/`, o de lo contrario Inno Setup lanzará un error de "No files found").*

---

## 🐧 Linux (desarrollo/pruebas)

`PC/main.py` también corre en Linux: X11 (hotkeys vía `pynput`) y Wayland (hotkeys vía `evdev`, requiere estar en el grupo `input`).

```bash
cd PC
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

**Captura silenciosa en Wayland (GNOME/Zorin):** se usa el portal ScreenCast/PipeWire, sin flash ni sonido. Necesita `gi` (PyGObject) + GStreamer del sistema (`python3-gi`, `gir1.2-gst-plugins-base-1.0`, `gstreamer1.0-pipewire`), por eso el venv se crea con `--system-site-packages` (o `include-system-site-packages = true` en `.venv/pyvenv.cfg`). Sin `gi` cae al portal de screenshot de GNOME, con flash y sonido.

La primera vez aparece el diálogo de *compartir pantalla*: elige el monitor y acepta. El permiso se guarda (`SCREENCAST_RESTORE_TOKEN` en `~/.config/MoodleDesktop/config.json`) y no vuelve a preguntar.

La app corre en la bandeja del sistema: no abre ventana al iniciar; usa `Alt+Shift+Z` para el overlay.

**Entrada en el menú de apps (opcional):** crear `~/.local/share/applications/moodledesktop.desktop` con `Exec=<repo>/PC/.venv/bin/python3 <repo>/PC/main.py`, `Path=<repo>/PC` e `Icon=<repo>/PC/images/icon128.png`.

---

## 🔄 Selección automática de modelos

Moodle Desktop elige solo el modelo de cada proveedor (Gemini, Groq, Nvidia) y lo mantiene actualizado:

- Lista los modelos del proveedor y prueba los mejores candidatos con una consulta mínima de **texto** y otra de **imagen** (una imagen roja de 32×32). Se queda con el primero que responde bien en menos de 15 s y que realmente ve imágenes.
- El resultado se guarda en `config.json` (`MODEL_CACHE`) durante **1 semana**; mientras tanto no hay llamadas extra. Si cambiás la API key, se vuelve a detectar.
- Al vencer la semana se usa el modelo guardado y se actualiza en segundo plano, sin demorar la respuesta.
- Si una consulta falla porque el modelo ya no existe (404 / "does not exist"), se vuelve a detectar al instante y se reintenta una vez.
