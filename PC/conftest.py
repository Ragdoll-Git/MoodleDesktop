import os
import sys

# Permite importar los paquetes de la app (core/ui/utils) que viven en PC/,
# sin importar desde qué directorio se invoque pytest.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Al importar utils.config se crea un ConfigManager a nivel de módulo. En modo
# instalado eso escribiría en el APPDATA real del usuario. Forzamos modo
# portable por defecto durante los tests para no tocar el sistema; cada test
# que necesite el modo instalado lo sobreescribe con monkeypatch.
os.environ.setdefault("MOODLE_DESKTOP_PORTABLE", "1")
