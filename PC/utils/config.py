import os
import sys
import json
import keyring

def get_resource_path(relative_path):
    """Resuelve la ruta a un recurso empaquetado (PyInstaller) o en desarrollo."""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

CONFIG_FILE = "config.json"
PROMPTS_FILE = "prompts.json"
SERVICE_NAME = "MoodleDesktop"

DEFAULT_CONFIG = {
    "MCP_ENABLED": False,
    "MCP_MODE": "local",
    "MCP_URL": "",
    "preferredProvider": "gemini"
}

DEFAULT_PROMPTS = [
    {
        "title": "Contenido de pantalla",
        "text": "Necesito que analices el contenido de pantalla, y respondas la pregunta que esta ahi dentro, mirando las opciones multiple choice, datos, y contexto que te doy. Responde de forma concisa y clara con la letra de la respuesta correcta o las opciones a marcar correctas o la respuesta escrita. Despues da una breve explicacion de tu respuesta pero abajo de la respuesta corta. No incluyas el texto de la pregunta, ni nada de eso, solo la respuesta, y abajo la explicacion si queres."
    }
]

class ConfigManager:
    def __init__(self, config_path=CONFIG_FILE, prompts_path=PROMPTS_FILE):
        self.is_portable = os.environ.get("MOODLE_DESKTOP_PORTABLE") == "1"
        
        if not self.is_portable:
            if sys.platform == "win32":
                appdata_dir = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
            else:
                appdata_dir = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
            base_dir = os.path.join(appdata_dir, SERVICE_NAME)
            os.makedirs(base_dir, exist_ok=True)
            self.config_path = os.path.join(base_dir, config_path)
            self.prompts_path = os.path.join(base_dir, prompts_path)
        else:
            self.config_path = config_path
            self.prompts_path = prompts_path

        self.portable_secrets = {}
        self.config = self.load()
        self.prompts = self.load_prompts()
        if not self.is_portable:
            self._migrate_old_keys()

    def _migrate_old_keys(self):
        # Si había claves en el viejo config.json, las pasamos a keyring y las borramos del json
        migrated = False
        for key in ["GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "CLAUDE_API_KEY", "NVIDIA_API_KEY"]:
            if key in self.config:
                val = self.config[key]
                if val:
                    keyring.set_password(SERVICE_NAME, key, val)
                del self.config[key]
                migrated = True
                
        if "CUSTOM_PROMPTS" in self.config:
            self.prompts = self.config["CUSTOM_PROMPTS"]
            self.save_prompts(self.prompts)
            del self.config["CUSTOM_PROMPTS"]
            migrated = True
            
        if migrated:
            self.save_config()

    def load(self):
        if self.is_portable:
            return DEFAULT_CONFIG.copy()

        if not os.path.exists(self.config_path):
            self.save(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
        
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(data)
                return merged
        except Exception:
            return DEFAULT_CONFIG.copy()

    def load_prompts(self):
        if self.is_portable:
            return DEFAULT_PROMPTS.copy()

        if not os.path.exists(self.prompts_path):
            self.save_prompts(DEFAULT_PROMPTS)
            return DEFAULT_PROMPTS.copy()
        try:
            with open(self.prompts_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_PROMPTS.copy()

    def save(self, data=None):
        if data is not None:
            self.config = data
        self.save_config()

    def save_config(self):
        if self.is_portable:
            return
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except PermissionError:
            print(f"[WARN] No se pudo guardar config en: {self.config_path}")

    def save_prompts(self, prompts):
        self.prompts = prompts
        if self.is_portable:
            return
        try:
            with open(self.prompts_path, "w", encoding="utf-8") as f:
                json.dump(self.prompts, f, indent=4, ensure_ascii=False)
        except PermissionError:
            print(f"[WARN] No se pudo guardar prompts en: {self.prompts_path}")

    def get(self, key, default=None):
        if key.endswith("_API_KEY"):
            if self.is_portable:
                return self.portable_secrets.get(key, default)
            val = keyring.get_password(SERVICE_NAME, key)
            return val if val is not None else default
        elif key == "CUSTOM_PROMPTS":
            return self.prompts
        return self.config.get(key, default)

    def set(self, key, value):
        if key.endswith("_API_KEY"):
            if self.is_portable:
                self.portable_secrets[key] = value
                return
            if value:
                keyring.set_password(SERVICE_NAME, key, value)
            else:
                try:
                    keyring.delete_password(SERVICE_NAME, key)
                except keyring.errors.PasswordDeleteError:
                    pass
        elif key == "CUSTOM_PROMPTS":
            self.save_prompts(value)
        else:
            self.config[key] = value
            self.save_config()

config_manager = ConfigManager()
