"""Indexar expedientes hechos a mano: descubre clientes por carpeta y documentos por contenido; en aplica registra."""
import json

import cli
from tests.test_cli_apply import GraphFalso, _cfg

CFDI = """<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Total="700.00" Fecha="2026-09-15T10:00:00">
<cfdi:Emisor Rfc="FAR010101AAA" Nombre="FARMACIA"/><cfdi:Receptor Rfc="PELA800101AB1" Nombre="ANA MARIA PEREZ LOPEZ"/></cfdi:Comprobante>"""


class GraphHistorico(GraphFalso):
    ARBOL = {
        "/Expedientes Lau": [{"id": "d1", "name": "Ana Maria Perez Lopez", "folder": {}}, {"id": "d2", "name": "Carlos Nuevo Cliente", "folder": {}}],
        "/Expedientes Lau/Ana Maria Perez Lopez": [{"id": "f1", "name": "factura.xml", "size": 500, "file": {}, "createdDateTime": "2026-09-15T10:00:00Z", "webUrl": "https://x/f1"},
                                                   {"id": "f2", "name": "receta foto.jpg", "size": 90000, "file": {}, "createdDateTime": "2026-09-16T10:00:00Z", "webUrl": "https://x/f2"}],
        "/Expedientes Lau/Carlos Nuevo Cliente": [{"id": "f3", "name": "Informe medico.pdf", "size": 1000, "file": {}, "createdDateTime": "2026-09-20T10:00:00Z", "webUrl": "https://x/f3"}],
    }

    def drive_de(self, usuario):
        return "drive-lau"

    def listar(self, ruta, drive=None):
        return self.ARBOL.get(ruta, [])

    listar_recursivo = cli.Graph.listar_recursivo

    def descargar_de(self, drive, item_id, destino):
        from pathlib import Path
        Path(destino).write_text(CFDI if item_id == "f1" else "%PDF-1.4 escaneado", encoding="utf-8")


def test_indexar_descubre_clientes_y_documentos(tmp_path, monkeypatch):
    falso = {}
    monkeypatch.setattr(cli, "Graph", lambda cfg: falso.setdefault("g", GraphHistorico(cfg)))
    cfg = _cfg(tmp_path, "propone")
    cfg.trabajo.mkdir()
    cli.indexar(cfg, "/Expedientes Lau", "lau@x.com")
    idx = json.loads((cfg.trabajo / "indexacion.json").read_text(encoding="utf-8"))
    assert idx["resumen"]["archivos"] == 3 and idx["resumen"]["carpetas"] == 2
    por = {a["nombre"]: a for a in idx["archivos"]}
    assert por["factura.xml"]["cliente"] == "Ana María Pérez López" and por["factura.xml"]["tipo"] == "CFDI factura" and por["factura.xml"]["confianza"] == "Alta"
    assert por["receta foto.jpg"]["requiere_lectura"] and por["receta foto.jpg"]["cliente"] == "Ana María Pérez López"
    assert por["Informe medico.pdf"]["cliente"] is None and por["Informe medico.pdf"]["tipo"] == "Informe médico"
    sugerido = (cfg.trabajo / "catalogo_sugerido.csv").read_text(encoding="utf-8-sig")
    assert "Carlos Nuevo Cliente" in sugerido
    assert falso["g"].escrituras == []


def test_indexar_aplica_registra_solo_con_cliente(tmp_path, monkeypatch):
    falso = {}
    monkeypatch.setattr(cli, "Graph", lambda cfg: falso.setdefault("g", GraphHistorico(cfg)))
    cfg = _cfg(tmp_path, "aplica")
    cfg.trabajo.mkdir()
    cli.indexar(cfg, "/Expedientes Lau", "lau@x.com")
    filas = [e[1][3] for e in falso["g"].escrituras if e[0] == "add"]
    assert len(filas) == 2 and all(f["Estado"] == "Histórico" and f["Cliente"] == "Ana María Pérez López" for f in filas)
    assert all(f["IdCorreo"].startswith("historico:") and f["EnResumen"] == "Sí" for f in filas)
