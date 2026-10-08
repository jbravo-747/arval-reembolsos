"""Prueba de humo de pull + apply con un Graph simulado (sin red). Modo propone: no debe escribir nada."""
import json
from pathlib import Path

import cli
from reembolsos.config import Config

CFDI = """<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Total="900.00" Fecha="2026-10-01T10:00:00">
<cfdi:Emisor Rfc="FAR010101AAA" Nombre="FARMACIA"/><cfdi:Receptor Rfc="PELA800101AB1" Nombre="ANA MARIA PEREZ LOPEZ"/></cfdi:Comprobante>"""


class GraphFalso:
    def __init__(self, cfg):
        self.cfg = cfg
        self.escrituras = []
        self.enc = ["ID", "FechaRecepcion", "HoraRecepcion", "Remitente", "Cliente", "Asunto", "NombreOriginal", "NombreGuardado",
                    "Ruta", "TipoDocumento", "Total", "Estado", "Confianza", "Prioridad", "Observaciones", "EnResumen", "Enlace"]
        self.filas = [
            {"index": 0, "values": ["1", "2026-10-08", "09:00", "x@y.com", "", "factura", "f.xml", "20261008_0900_aaa_f.xml", "", "", "", "Cliente desconocido", "", "", "", "No", ""]},
            {"index": 1, "values": ["2", "2026-10-08", "09:01", "x@y.com", "", "receta", "r.pdf", "20261008_0901_bbb_r.pdf", "", "", "", "Cliente desconocido", "", "", "", "No", ""]},
        ]

    def item_por_ruta(self, ruta):
        return {"id": "control"}

    def tabla_filas(self, archivo_id, tabla):
        if tabla == "tblClientes":
            return ["Correo", "NombreCliente", "Tipo", "Alias", "RFC", "Notas"], [{"index": 0, "values": ["ana@x.com", "Ana María Pérez López", "", "", "PELA800101AB1", ""]}]
        if tabla == "tblRegistro":
            return self.enc, self.filas
        raise cli.GraphError("GET", tabla, 404, "no existe")

    def tabla_como_dicts(self, archivo_id, tabla):
        enc, filas = self.tabla_filas(archivo_id, tabla)
        return [dict(zip(enc, f["values"]), _index=f["index"]) for f in filas]

    def listar(self, ruta):
        return [{"id": "i1", "name": "20261008_0900_aaa_f.xml"}, {"id": "i2", "name": "20261008_0901_bbb_r.pdf"}]

    def descargar(self, item_id, destino):
        Path(destino).write_text(CFDI if str(destino).endswith(".xml") else "%PDF-1.4 escaneado", encoding="utf-8")

    def mover(self, *a, **k):
        self.escrituras.append(("mover", a))

    def tabla_actualizar_fila(self, *a, **k):
        self.escrituras.append(("patch", a))

    def tabla_agregar_fila(self, *a, **k):
        self.escrituras.append(("add", a))

    def subir_pequeno(self, *a, **k):
        self.escrituras.append(("subir", a))


def _cfg(tmp_path, modo):
    return Config(tenant_id="t", client_id="c", client_secret="s", usuario="u@x.com", correo_lau="l@x.com", ruta_base="/Reembolsos",
                  archivo_control="Control.xlsx", modo=modo, trabajo=tmp_path / "trabajo", paginas_max=1)


def test_pull_y_apply_propone_no_escribe(tmp_path, monkeypatch):
    falso = {}
    monkeypatch.setattr(cli, "Graph", lambda cfg: falso.setdefault("g", GraphFalso(cfg)))
    cfg = _cfg(tmp_path, "propone")
    cfg.trabajo.mkdir()
    cli.pull(cfg)
    trabajo = json.loads((cfg.trabajo / "trabajo.json").read_text(encoding="utf-8"))
    assert len(trabajo["items"]) == 2
    xml, pdf = trabajo["items"]
    assert xml["preanalisis"]["cliente"] == "Ana María Pérez López" and not xml["requiere_lectura"]
    assert pdf["requiere_lectura"]
    # decisión del agente para el PDF escaneado
    (cfg.trabajo / "decisiones.json").write_text(json.dumps({pdf["nombre_guardado"]: {
        "cliente": "Ana María Pérez López", "tipo_documento": "Receta", "identificado_por": "nombre completo", "motivo": "nombre en la receta"}}), encoding="utf-8")
    cli.apply(cfg)
    snap = json.loads((cfg.trabajo / "panel_snapshot.json").read_text(encoding="utf-8"))
    assert snap["kpis"]["analizados"] == 2 and snap["kpis"]["movidos"] == 0
    estados = {p["id"]: (p["estado"], p["prioridad"]) for p in snap["pendientes"]}
    assert estados[xml["nombre_guardado"]] == ("Recibido", 3)
    assert estados[pdf["nombre_guardado"]] == ("Revisar", 2)
    assert snap["expedientes"] and snap["expedientes"][0]["cliente"] == "Ana María Pérez López"
    assert falso["g"].escrituras == []


def test_apply_aplica_mueve_y_actualiza(tmp_path, monkeypatch):
    falso = {}
    monkeypatch.setattr(cli, "Graph", lambda cfg: falso.setdefault("g", GraphFalso(cfg)))
    cfg = _cfg(tmp_path, "aplica")
    cfg.trabajo.mkdir()
    cli.pull(cfg)
    (cfg.trabajo / "confirmaciones.json").write_text(json.dumps([{"archivo": "20261008_0901_bbb_r.pdf", "cliente": "Ana María Pérez López"}]), encoding="utf-8")
    (cfg.trabajo / "altas.json").write_text(json.dumps([{"nombre": "Nuevo Cliente Prueba", "correo": "n@x.com", "rfc": "NCP900101XX1"}]), encoding="utf-8")
    cli.apply(cfg)
    tipos = [e[0] for e in falso["g"].escrituras]
    assert tipos.count("mover") == 2 and tipos.count("patch") == 2 and tipos.count("add") == 1 and "subir" in tipos
    mover_args = [e[1] for e in falso["g"].escrituras if e[0] == "mover"]
    assert all(a[1].startswith("/Reembolsos/Clientes/Ana María Pérez López/2026-10") for a in mover_args)
