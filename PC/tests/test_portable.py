"""Tests del modo Portable (Zero-Knowledge).

La versión portable debe poder ejecutarse sin permisos de administrador. Lo que
lo hace posible es que NO realiza ninguna operación privilegiada ni que deje
rastros: no escribe archivos de configuración en disco y no toca el Almacén de
Credenciales de Windows (keyring). Todo vive en memoria RAM y se pierde al
cerrar la app.

Estos tests verifican ese contrato y, por contraste, comprueban que en modo
instalado sí se persisten datos (para asegurar que el test del portable es
significativo y no pasa "por casualidad").
"""
import pytest

import utils.config as cfgmod
from utils.config import ConfigManager


def _explode(*_args, **_kwargs):
    raise AssertionError(
        "Se accedió al Almacén de Credenciales (keyring) en modo portable"
    )


def test_portable_no_escribe_disco_ni_keyring(tmp_path, monkeypatch):
    monkeypatch.setenv("MOODLE_DESKTOP_PORTABLE", "1")

    # Cualquier uso de keyring en modo portable debe hacer fallar el test.
    monkeypatch.setattr(cfgmod.keyring, "set_password", _explode)
    monkeypatch.setattr(cfgmod.keyring, "get_password", _explode)
    monkeypatch.setattr(cfgmod.keyring, "delete_password", _explode)

    # APPDATA apunta a una carpeta temporal vacía: el modo portable no debe
    # crear nada dentro de ella.
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))

    cfg_file = tmp_path / "config.json"
    prompts_file = tmp_path / "prompts.json"
    cm = ConfigManager(config_path=str(cfg_file), prompts_path=str(prompts_file))

    assert cm.is_portable is True

    # Operaciones que en modo instalado escribirían a disco / keyring:
    cm.set("GEMINI_API_KEY", "super-secreto")   # iría al keyring
    cm.set("preferredProvider", "claude")        # iría a config.json
    cm.save_config()
    cm.save_prompts([{"title": "x", "text": "y"}])

    # 1) La API key y la config viven solo en RAM y son recuperables.
    assert cm.get("GEMINI_API_KEY") == "super-secreto"
    assert cm.portable_secrets["GEMINI_API_KEY"] == "super-secreto"
    assert cm.get("preferredProvider") == "claude"

    # 2) No se creó ningún archivo de configuración en disco.
    assert not cfg_file.exists()
    assert not prompts_file.exists()

    # 3) No se tocó APPDATA (ni se creó la carpeta del servicio).
    assert not (appdata / "MoodleDesktop").exists()
    assert list(appdata.iterdir()) == []


def test_instalado_si_persiste(tmp_path, monkeypatch):
    """Contraste: en modo instalado las mismas operaciones SÍ escriben en disco
    y usan keyring. Garantiza que las aserciones del test portable importan."""
    monkeypatch.delenv("MOODLE_DESKTOP_PORTABLE", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    # keyring falso en memoria (no tocamos el Credential Manager real).
    store = {}
    monkeypatch.setattr(cfgmod.keyring, "set_password",
                        lambda s, k, v: store.__setitem__((s, k), v))
    monkeypatch.setattr(cfgmod.keyring, "get_password",
                        lambda s, k: store.get((s, k)))
    monkeypatch.setattr(cfgmod.keyring, "delete_password",
                        lambda s, k: store.pop((s, k), None))

    cm = ConfigManager(config_path="config.json", prompts_path="prompts.json")
    assert cm.is_portable is False

    base = tmp_path / "MoodleDesktop"
    # La inicialización ya escribió los archivos por defecto en disco.
    assert (base / "config.json").exists()
    assert (base / "prompts.json").exists()

    # La API key va al keyring (no a RAM).
    cm.set("GEMINI_API_KEY", "clave")
    assert store[("MoodleDesktop", "GEMINI_API_KEY")] == "clave"
    assert cm.get("GEMINI_API_KEY") == "clave"
