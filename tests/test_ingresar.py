"""Entradas desde el panel: ingresar sube a _Por identificar, crea la fila y deja la confirmación si Lau indicó cliente."""
import json

import cli
from tests.test_cli_apply import GraphFalso, _cfg


class GraphEntradas(GraphFalso):
    def subir_archivo(self, ruta_onedrive, ruta_local):
        self.escrituras.append(("subir_archivo", ruta_onedrive))
        return {"id": "nuevo-item"}

    def enlace_lectura(self, item_id):
        return "https://ejemplo/enlace"


def _preparar(tmp_path, monkeypatch, modo):
    falso = {}
    monkeypatch.setattr(cli, "Graph", lambda cfg: falso.setdefault("g", GraphEntradas(cfg)))
    cfg = _cfg(tmp_path, modo)
    cfg.trabajo.mkdir()
    (cfg.trabajo / "foto.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 100)
    (cfg.trabajo / "entradas.json").write_text(json.dumps([
        {"id": "e1", "nombre": "foto whatsapp.jpg", "ruta_local": str(cfg.trabajo / "foto.jpg"), "cliente": "Ana María Pérez López", "por": "u_1", "hora": "2026-10-08T10:00:00"},
        {"id": "e2", "nombre": "receta.pdf", "ruta_local": str(cfg.trabajo / "no_existe.pdf"), "cliente": None, "por": "u_1", "hora": "2026-10-08T10:01:00"},
    ]), encoding="utf-8")
    return cfg, falso


def test_ingresar_aplica(tmp_path, monkeypatch):
    cfg, falso = _preparar(tmp_path, monkeypatch, "aplica")
    cli.ingresar(cfg)
    res = {r["id"]: r for r in json.loads((cfg.trabajo / "entradas_resultado.json").read_text(encoding="utf-8"))}
    assert res["e1"]["estado"] == "ingresado" and res["e1"]["nombre_guardado"].endswith("_foto whatsapp.jpg")
    assert res["e2"]["estado"] == "error"
    tipos = [e[0] for e in falso["g"].escrituras]
    assert tipos.count("subir_archivo") == 1 and tipos.count("add") == 1
    fila = [e for e in falso["g"].escrituras if e[0] == "add"][0][1][3]
    assert fila["Estado"] == "Cliente desconocido" and fila["Ruta"].startswith("/Reembolsos/_Por identificar/") and fila["Enlace"]
    conf = json.loads((cfg.trabajo / "confirmaciones.json").read_text(encoding="utf-8"))
    assert conf == [{"archivo": res["e1"]["nombre_guardado"], "cliente": "Ana María Pérez López"}]


def test_ingresar_propone_no_escribe(tmp_path, monkeypatch):
    cfg, falso = _preparar(tmp_path, monkeypatch, "propone")
    cli.ingresar(cfg)
    res = {r["id"]: r for r in json.loads((cfg.trabajo / "entradas_resultado.json").read_text(encoding="utf-8"))}
    assert res["e1"]["estado"] == "propuesto" and falso["g"].escrituras == []
