"""El agente del clasificador (embudo/agente.py): instalar sin tocar el registro real de Windows ni arrancar procesos."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "embudo"))
import agente  # noqa: E402

from reembolsos.destino import MARCA, DestinoIncorrecto  # noqa: E402


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(agente, "CASA", tmp_path / "casa")
    monkeypatch.setattr(agente, "CONFIG", tmp_path / "casa" / "config.json")
    monkeypatch.setattr(agente, "BITACORA", tmp_path / "casa" / "agente.log")
    monkeypatch.setattr(agente, "quitar_version_anterior", lambda: None)
    monkeypatch.setattr(agente, "iniciar_vigilante", lambda exe: None)
    monkeypatch.setattr(agente, "carpeta_escritorio", lambda: tmp_path / "escritorio")
    import winreg

    class Clave:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass
    monkeypatch.setattr(winreg, "CreateKey", lambda *a: Clave())
    monkeypatch.setattr(winreg, "SetValueEx", lambda *a: None)
    (tmp_path / "escritorio").mkdir()
    (tmp_path / "Descargas").mkdir()
    return tmp_path


def test_instalar_en_la_carpeta_con_marca(entorno):
    arval = entorno / "Arval"
    (arval / MARCA).mkdir(parents=True)
    cfg = agente.instalar(arval, entorno / "Descargas")
    assert cfg["arval"] == str(arval)
    assert (arval / "_Embudo").is_dir()
    assert agente.leer_config(agente.CONFIG)["descargas"] == str(entorno / "Descargas")
    assert (entorno / "escritorio" / "Clasificador de archivos.url").exists()


def test_instalar_rechaza_carpeta_sin_marca(entorno):
    arval = entorno / "Arval"
    arval.mkdir()
    with pytest.raises(DestinoIncorrecto):
        agente.instalar(arval, entorno / "Descargas")
    assert not (arval / "_Embudo").exists()


def test_detecta_las_carpetas_de_descarga_de_cada_navegador(tmp_path, monkeypatch):
    import json
    local, d_edge, d_win = tmp_path / "local", tmp_path / "D_Descargas", tmp_path / "Downloads"
    d_edge.mkdir(); d_win.mkdir()
    perfil = local / "Microsoft" / "Edge" / "User Data" / "Profile 1"
    perfil.mkdir(parents=True)
    (perfil / "Preferences").write_text(json.dumps({"download": {"default_directory": str(d_edge)}}), encoding="utf-8")
    sin_carpeta = local / "Google" / "Chrome" / "User Data" / "Default"
    sin_carpeta.mkdir(parents=True)
    (sin_carpeta / "Preferences").write_text(json.dumps({"download": {}}), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setattr(agente, "carpeta_descargas", lambda: d_win)
    assert agente.carpetas_descarga() == [d_win, d_edge]
    assert agente.carpetas_descarga(str(d_edge)) == [d_win, d_edge]   # la extra repetida no se duplica
