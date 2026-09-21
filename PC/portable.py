import os

# Establecemos la bandera de portable antes de que cualquier módulo se cargue
os.environ["MOODLE_DESKTOP_PORTABLE"] = "1"

# Importamos main que levantará la aplicación normalmente
import main

if __name__ == "__main__":
    controller = main.MainController()
    controller.run()
