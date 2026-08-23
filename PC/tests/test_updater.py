"""Tests del sistema de actualización (sin acceso real a la red)."""
import pytest

from core import updater


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _release(tag, assets):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/Ragdoll-Git/FMoodle/releases/tag/{tag}",
        "assets": [
            {"name": n, "browser_download_url": f"https://x/{tag}/{n}"}
            for n in assets
        ],
    }


@pytest.mark.parametrize("text,expected", [
    ("FMoodle-v3.6.3", (3, 6, 3)),
    ("v3.6", (3, 6, 0)),
    ("3.7.1", (3, 7, 1)),
    ("sin-numero", (0, 0, 0)),
])
def test_parse_version(text, expected):
    assert updater.parse_version(text) == expected


def test_check_detecta_nueva_version(monkeypatch):
    monkeypatch.delenv("FMOODLE_PORTABLE", raising=False)  # modo instalado
    payload = _release("FMoodle-v3.6.3",
                       ["FMoodle_Installer.exe", "FMoodle_Portable.exe"])
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _FakeResp(payload))

    info = updater.check_for_update(current="3.6.2")
    assert info["available"] is True
    assert info["asset"] == "FMoodle_Installer.exe"
    assert info["download_url"].endswith("FMoodle_Installer.exe")


def test_check_al_dia(monkeypatch):
    monkeypatch.delenv("FMOODLE_PORTABLE", raising=False)
    payload = _release("FMoodle-v3.6.2", ["FMoodle_Installer.exe"])
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _FakeResp(payload))

    info = updater.check_for_update(current="3.6.2")
    assert info["available"] is False


def test_check_selecciona_asset_portable(monkeypatch):
    monkeypatch.setenv("FMOODLE_PORTABLE", "1")  # modo portable
    payload = _release("FMoodle-v3.6.3",
                       ["FMoodle_Installer.exe", "FMoodle_Portable.exe"])
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _FakeResp(payload))

    info = updater.check_for_update(current="3.6.2")
    assert info["asset"] == "FMoodle_Portable.exe"
    assert info["download_url"].endswith("FMoodle_Portable.exe")


def test_check_asset_faltante_lanza_error(monkeypatch):
    monkeypatch.delenv("FMOODLE_PORTABLE", raising=False)
    payload = _release("FMoodle-v3.6.3", ["FMoodle_Extension.zip"])  # sin installer
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _FakeResp(payload))

    with pytest.raises(ValueError):
        updater.check_for_update(current="3.6.2")


def test_apply_update_bloqueado_en_desarrollo(monkeypatch):
    # En modo no compilado (python crudo) NO debe intentar reemplazar nada.
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    with pytest.raises(RuntimeError):
        updater.apply_update("cualquier_cosa.exe")


def test_apply_portable_genera_bat_correcto(monkeypatch, tmp_path):
    # Simula app compilada en modo portable; captura el .bat sin ejecutarlo.
    current_exe = tmp_path / "FMoodle_Portable.exe"
    current_exe.write_text("viejo")
    new_exe = tmp_path / "FMoodle_update_xyz.exe"
    new_exe.write_text("nuevo")

    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setenv("FMOODLE_PORTABLE", "1")
    monkeypatch.setattr(updater.sys, "executable", str(current_exe))
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))

    captured = {}
    monkeypatch.setattr(updater.subprocess, "Popen",
                        lambda *a, **k: captured.update(args=a, kwargs=k))

    assert updater.apply_update(str(new_exe)) is True

    bat = (tmp_path / "fmoodle_update.bat").read_text(encoding="utf-8")
    assert str(current_exe) in bat       # reemplaza el exe actual
    assert str(new_exe) in bat           # con el nuevo descargado
    assert "start" in bat                # y lo relanza
    assert "moveloop" in bat             # tiene retry para el move
    assert captured, "debe lanzar el .bat de forma desacoplada"
    # Solo CREATE_NO_WINDOW (no DETACHED_PROCESS, son mutuamente excluyentes).
    flags = captured["kwargs"].get("creationflags", 0)
    assert flags != 0
    assert not (flags & 0x00000008), "no debe usar DETACHED_PROCESS"


def test_portable_target_writable_true(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.sys, "executable", str(tmp_path / "FMoodle_Portable.exe"))
    assert updater.portable_target_writable() is True


def test_apply_portable_sin_permisos_avisa(monkeypatch, tmp_path):
    # Si la carpeta del portable no es escribible, NO debe intentar el swap.
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setenv("FMOODLE_PORTABLE", "1")
    monkeypatch.setattr(updater.sys, "executable", str(tmp_path / "FMoodle_Portable.exe"))
    monkeypatch.setattr(updater, "portable_target_writable", lambda: False)

    spawned = {}
    monkeypatch.setattr(updater.subprocess, "Popen",
                        lambda *a, **k: spawned.update(called=True))

    with pytest.raises(PermissionError):
        updater.apply_update(str(tmp_path / "nuevo.exe"))
    assert not spawned, "no debe lanzar el .bat si no hay permisos"


def test_apply_installer_lanza_ejecutable(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.delenv("FMOODLE_PORTABLE", raising=False)
    installer = tmp_path / "FMoodle_Installer.exe"
    installer.write_text("instalador")

    called = {}
    monkeypatch.setattr(updater.os, "startfile",
                        lambda p: called.setdefault("path", p), raising=False)

    assert updater.apply_update(str(installer)) is True
    assert called["path"] == str(installer)
