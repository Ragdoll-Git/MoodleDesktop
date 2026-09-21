import os
import sys
import winreg

APP_NAME = "MoodleDesktop"

def get_executable_path():
    # Si estamos compilados con PyInstaller, sys.executable es el .exe
    if getattr(sys, 'frozen', False):
        return sys.executable
    # Si estamos en python crudo, es la llamada a python con main.py
    return f'"{sys.executable}" "{os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))}"'

def is_in_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return value == get_executable_path()
    except WindowsError:
        return False

def set_startup(enable: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, get_executable_path())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except WindowsError as e:
        print(f"Error modificando el registro de inicio: {e}")
