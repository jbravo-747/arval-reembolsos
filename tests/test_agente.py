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
