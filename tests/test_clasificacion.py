from pathlib import Path

from reembolsos import clasificacion as cl
from reembolsos.catalogo import Catalogo
from reembolsos.resumen import agrupar, correo

CAT = Catalogo([{"Correo": "", "NombreCliente": "Ana María Pérez López", "Tipo": "", "Alias": "", "RFC": "PELA800101AB1"}])

CFDI = """<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Total="1500.00" Fecha="2026-10-01T10:00:00">
<cfdi:Emisor Rfc="FAR010101AAA" Nombre="FARMACIA X"/><cfdi:Receptor Rfc="PELA800101AB1" Nombre="ANA MARIA PEREZ LOPEZ"/></cfdi:Comprobante>"""


def test_preanalisis_cfdi(tmp_path: Path):
    f = tmp_path / "20261001_1000_abc123_f.xml"
    f.write_text(CFDI, encoding="utf-8")
    pre = cl.preanalisis(f, CAT)
    assert pre["metodo"] == "Receptor CFDI"
    assert pre["cliente"] == "Ana María Pérez López" and pre["confianza"] == "Alta"
    assert pre["rfc"] == "PELA800101AB1" and pre["total"] == "1500.00"


def test_preanalisis_ignorado(tmp_path: Path):
    f = tmp_path / "x.htm"
    f.write_text("<p>hola</p>")
    assert cl.preanalisis(f, CAT)["ignorar"]


def test_combinar_escala():
    pre_alta = {"cliente": "Ana María Pérez López", "confianza": "Alta", "motivo": "exacta", "candidatos": [], "metodo": "Receptor CFDI"}
    r = cl.combinar(pre_alta, None)
    assert (r["confianza"], r["prioridad"], r["estado"]) == ("Alta", 3, "Recibido")

    pre_nada = {"cliente": None, "confianza": None, "motivo": "", "candidatos": [], "metodo": "escaneado"}
    r = cl.combinar(pre_nada, {"cliente": "Ana María Pérez López", "identificado_por": "nombre completo", "tipo_documento": "Receta"})
    assert (r["confianza"], r["prioridad"], r["estado"]) == ("Media", 2, "Revisar")

    r = cl.combinar(pre_nada, {"cliente": None, "identificado_por": "no identificado", "candidato_cliente": "MARTHA GOMEZ"})
    assert (r["confianza"], r["prioridad"], r["estado"]) == ("Ninguna", 1, "Cliente desconocido")
    assert r["candidatos"] == ["MARTHA GOMEZ"]

    r = cl.combinar(pre_nada, {"cliente": None, "identificado_por": "no identificado"})
    assert (r["prioridad"], r["estado"]) == (3, "Cliente desconocido")

    r = cl.combinar(pre_nada, {"tipo_documento": "Operación de seguro (no reembolso)"})
    assert r["estado"] == "No es reembolso" and r["prioridad"] == 3


def test_mes_de():
    assert cl.mes_de("20261001_1715_abc_x.pdf") == "2026-10"


def test_resumen_agrupa_y_ordena():
    filas = [
        {"Prioridad": "3", "Estado": "Recibido", "Cliente": "A", "NombreOriginal": "a.pdf", "EnResumen": "No", "FechaRecepcion": "2026-10-08", "HoraRecepcion": "09:00"},
        {"Prioridad": "1", "Estado": "Cliente desconocido", "Cliente": "", "NombreOriginal": "b.pdf", "EnResumen": "No", "FechaRecepcion": "2026-10-08", "HoraRecepcion": "10:00"},
        {"Prioridad": "2", "Estado": "Revisar", "Cliente": "B", "NombreOriginal": "c.pdf", "EnResumen": "Sí", "FechaRecepcion": "2026-10-07", "HoraRecepcion": "10:00"},
    ]
    pendientes, grupos = agrupar(filas)
    assert [p["NombreOriginal"] for p in pendientes] == ["b.pdf", "a.pdf"]
    assert len(grupos["Prioridad 1: decidir hoy"]) == 1
    asunto, html, _ = correo(filas, "08/10/2026")
    assert "1 por decidir" in asunto and "<table" in html
