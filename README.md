# Moodle Desktop 🚀

Moodle Desktop es una aplicación de escritorio nativa para Windows, diseñada para integrar y gestionar de forma centralizada múltiples proveedores de Inteligencia Artificial dentro de plataformas estudiantiles como Moodle para ayuda en temas o asignaturas donde la persona necesita comprender de otra forma el contenido.

## ✨ Características Principales

* **🤖 Soporte Multi-Proveedor con fallback automático:**
  * **Google Gemini**
  * **Groq**
  * **Nvidia Labs**

  La app detecta automáticamente un modelo **multimodal** válido para cada proveedor (consultando sus modelos disponibles). Para Groq, el modelo preferido actual es **Qwen 3.6 27B** (`qwen/qwen3.6-27b`), con soporte de visión y alta velocidad. Ante un fallo, hace **fallback** al siguiente proveedor disponible, quedándose en el que funcione hasta que vuelva a fallar. Los proveedores cuyo modelo no soporta imágenes se omiten cuando la consulta incluye una captura.
* **🔒 Seguridad Zero-Knowledge:** Todas las claves de API (API Keys) se almacenan de manera completamente segura utilizando el Administrador de Credenciales nativo de Windows (Windows Credential Vault). Las claves jamás se guardan en texto plano.
* **🌐 Soporte MCP (Model Context Protocol):** Integración nativa para consumir recursos y herramientas desde servidores MCP remotos o locales, ampliando las capacidades del asistente de IA.
* **🚀 Modo Portable (RAM-Only):** Puede ejecutarse en modo 100% portable donde los datos residen únicamente en la memoria RAM, sin dejar rastros de configuración o claves en el disco de la computadora.
* **💻 Interfaz Moderna (PySide6):** UI construida con Qt/PySide6, con soporte de temas, modo siempre-visible (Always on Top) y diseño responsivo.
* **⚡ Autoinicio de Windows:** Se integra silenciosamente con Windows, ejecutándose en segundo plano al iniciar sesión mediante el registro de Windows (`winreg`).
* **🔄 Auto-actualización:** Desde el menú de Configuración (pestaña *Actualizaciones*) la app consulta el último release en GitHub y, si hay una versión nueva, descarga y aplica la actualización automáticamente (el instalador se relanza; el portable se reemplaza a sí mismo).

## 📁 Estructura del Proyecto

El repositorio está organizado en dos carpetas según el tipo de distribución:

### `PC/` — Aplicación de escritorio (Python / PySide6)

* `core/`: Contiene el enrutador de IA (`providers.py`) y la lógica de conexión al servidor MCP (`mcp.py`).
* `ui/`: Todos los componentes visuales interactivos (`overlay.py`, `settings.py`, `theme.py`).
* `utils/`: Herramientas del sistema, persistencia y capturas (`config.py`, `capture.py`, `autostart.py`).
* `main.py`: Punto de entrada clásico para la aplicación instalable persistente.
* `portable.py`: Punto de entrada especial que bloquea la escritura en disco (Modo RAM).
* `build.py` / `inno_setup.iss`: Scripts de compilación del portable y del instalador.

### `extension/` — Extensión de navegador (Chrome / Manifest V3)

* `manifest.json`: Manifiesto de la extensión (Manifest V3).
* `background.js`: Service worker que orquesta la captura y las peticiones a las IAs.
* `content.js`: Script inyectado en la pestaña activa para capturar y mostrar resultados.
* `claude.js`, `groq.js`, `openai.js`: Conectores por proveedor de IA.
* `options.html` / `options.js`: Página de opciones y configuración.
* `prompts.js`: Gestión de prompts personalizados.

## 🛡️ Versiones y Distribución

El proyecto ofrece **tres formatos de distribución**. La app de escritorio se compila con el script de automatización `PC/build.py` (impulsado por **PyInstaller**), y la extensión se empaqueta como `.zip`. En cada release de GitHub se publican los tres:

1. **MoodleDesktop Installer:** Versión de escritorio estándar para instalar permanentemente en el sistema.
2. **MoodleDesktop Portable:** Un solo `.exe` que puedes llevar en un USB, ejecutar sin permisos de administrador y usar con privacidad absoluta.
3. **MoodleDesktop Extension (Chrome):** La extensión de navegador (`MoodleDesktop_Extension.zip`) para cargar en Chrome/Edge mediante "Cargar descomprimida" (modo desarrollador).

---
Para aprender cómo instalar, compilar desde el código fuente o configurar tu versión portable, por favor lee la guía en el archivo **[INSTRUCCIONES.md](INSTRUCCIONES.md)**.

## ❓ Preguntas Frecuentes (FAQ)

**¿El instalador es persistente? ¿Iniciará con Windows al reiniciar?**
Sí. La versión instalada (persistente) guarda sus datos en tu carpeta secreta de usuario (`AppData`) para no tener problemas de permisos. Además, si activas la opción "Iniciar automáticamente con Windows" en la configuración, el programa se añadirá al registro interno de tu sistema (`winreg`) y se ejecutará silenciosamente en segundo plano cada vez que enciendas tu computadora.

**¿Dónde se guarda o cómo funciona exactamente la versión Portable?**
La versión portable (`MoodleDesktop_Portable.exe`) es un archivo único que se genera en la carpeta `PC/dist/` al compilar. Puedes llevarte ese ejecutable en un pendrive a cualquier PC. Al ejecutarse, entra en modo "Zero-Knowledge": no escribe NADA en el disco duro (ni archivos de configuración, ni guarda contraseñas en el administrador de credenciales de Windows). Todo se guarda exclusivamente en la memoria RAM y se pierde de forma segura en cuanto cierras la aplicación.

**¿Qué pasa con los "warnings" o advertencias naranjas de Inno Setup al compilar el instalador?**
En versiones modernas de Inno Setup (6+), advertencias como `Warning: Architecture identifier "x64" is deprecated` o referidas al uso de `{pf}` son normales y no rompen tu instalador. De todas formas, la plantilla `inno_setup.iss` de este proyecto ya utiliza la sintaxis moderna (`x64compatible` y `{autopf}`) para evitar esas alertas.

**Para usar la integración MCP (Model Context Protocol), ¿es necesario instalar Docker localmente?**
No. El sistema MCP de Moodle Desktop se comunica enviando peticiones web (HTTP POST) a la URL que le indiques. Puedes autohostear tu servidor MCP en cualquier máquina remota, servidor local o a través de una VPN (por ejemplo, `http://10.0.0.5:8080`) y Moodle Desktop consumirá esos recursos directamente, sin requerir Docker ni otras herramientas instaladas en tu computadora local.
