"""Puente local /Reembolsos (Power Automate) -> /Arval (estructura estándar), con datos sintéticos."""
import json
import os
import time
from datetime import date

import pytest

from reembolsos import puente as pt

CFDI = """<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Total="700.00" Fecha="2026-10-10T10:00:00">
<cfdi:Emisor Rfc="FAR010101AAA" Nombre="FARMACIA"/><cfdi:Receptor Rfc="PELA800101AB1" Nombre="ANA MARIA PEREZ LOPEZ"/></cfdi:Comprobante>"""
HOY = date(2026, 10, 15)


@pytest.fixture
def carpetas(tmp_path):
    entrada, destino = tmp_path / "Reembolsos", tmp_path / "Arval"
    # /Arval ya tiene un expediente de Ana con una receta del 8 de octubre
    ev = destino / "CARTERA UNO" / "ANA MARIA PEREZ LOPEZ" / "2026-10_REEMBOLSO 1"
    ev.mkdir(parents=True)
    (ev / "20261008_RECETA_01.pdf").write_bytes(b"x")
    (destino / "CARTERA UNO" / "CARLOS RUIZ SOTO").mkdir(parents=True)
    # Power Automate: CFDI de Ana sin remitente conocido, un archivo de Carlos por remitente, una firma y un PDF ilegible
    (entrada / "_Por identificar").mkdir(parents=True)
    (entrada / "_Por identificar" / "20261012_0930_aaa111_factura.xml").write_text(CFDI, encoding="utf-8")
    (entrada / "_Por identificar" / "20261012_0930_aaa111_image001.png").write_bytes(b"png")
    (entrada / "_Por identificar" / "20261013_1100_bbb222_escaneo.pdf").write_bytes(b"%PDF-1.4 roto")
    c = entrada / "Clientes" / "Carlos Ruiz Soto" / "2026-10"
    c.mkdir(parents=True)
    (c / "20261014_0800_ccc333_receta carlos.pdf").write_bytes(b"%PDF-1.4 roto")
    return entrada, destino


def test_propone_no_copia_y_decide_destinos(carpetas, tmp_path):
    entrada, destino = carpetas
    antes = sorted(p.name for p in destino.rglob("*"))
    panel = pt.correr(entrada, destino, tmp_path / "trabajo", "propone", usar_ocr=False, hoy=HOY)
    assert sorted(p.name for p in destino.rglob("*")) == antes
    por = {p["id"]: p for p in panel["pendientes"]}
    cfdi = por["20261012_0930_aaa111_factura.xml"]
    assert cfdi["cliente"] == "ANA MARIA PEREZ LOPEZ" and cfdi["tipo"] == "CFDI factura"
    assert cfdi["destino"] == "CARTERA UNO/ANA MARIA PEREZ LOPEZ/2026-10_REEMBOLSO 1/20261010_CFDI_01.xml"   # se suma al evento abierto
    carlos = por["20261014_0800_ccc333_receta carlos.pdf"]
    assert carlos["cliente"] == "CARLOS RUIZ SOTO" and carlos["destino"].startswith("CARTERA UNO/CARLOS RUIZ SOTO/2026-10_Reembolso 20261014/")
    assert carlos["tipo"] == "Receta"
    assert por["20261013_1100_bbb222_escaneo.pdf"]["destino"].startswith("_Por identificar/")
    assert "20261012_0930_aaa111_image001.png" not in por and panel["conteo"]["ignorado"] == 1


def test_aplica_copia_sin_tocar_entrada_y_no_repite(carpetas, tmp_path):
    entrada, destino = carpetas
    antes = sorted(str(p) for p in entrada.rglob("*"))
    trabajo = tmp_path / "trabajo"
    pt.correr(entrada, destino, trabajo, "aplica", usar_ocr=False, hoy=HOY)
    assert sorted(str(p) for p in entrada.rglob("*")) == antes
    assert (destino / "CARTERA UNO" / "ANA MARIA PEREZ LOPEZ" / "2026-10_REEMBOLSO 1" / "20261010_CFDI_01.xml").exists()
    assert (destino / "_Por identificar" / "20261013_1100_bbb222_escaneo.pdf").exists()
    otra = pt.correr(entrada, destino, trabajo, "aplica", usar_ocr=False, hoy=HOY)
    assert otra["conteo"] == {"ya procesados": 4}


def test_confirmacion_de_lau_reubica_lo_que_no_tenia_cliente(carpetas, tmp_path):
    entrada, destino = carpetas
    trabajo = tmp_path / "trabajo"
    pt.correr(entrada, destino, trabajo, "aplica", usar_ocr=False, hoy=HOY)
    conf = [{"archivo": "20261013_1100_bbb222_escaneo.pdf", "cliente": "CARLOS RUIZ SOTO"}]
    panel = pt.correr(entrada, destino, trabajo, "aplica", usar_ocr=False, confirmaciones=conf, hoy=HOY)
    assert panel["conteo"]["clasificado"] == 1
    assert any(p.name.startswith("20261013_DOC_") for p in (destino / "CARTERA UNO" / "CARLOS RUIZ SOTO").rglob("*"))


def test_resumen_del_dia(carpetas, tmp_path):
    entrada, destino = carpetas
    trabajo = tmp_path / "trabajo"
    pt.correr(entrada, destino, trabajo, "aplica", usar_ocr=False, hoy=HOY)
    r = pt.resumen_dia(trabajo, destino, date.today())
    assert r["conteos"]["Documentos clasificados hoy"] == 2 and r["conteos"]["Sin cliente (por identificar)"] == 1
    assert r["conteos"]["Eventos nuevos hoy"] == 1
    ana = [e for e in r["expedientes_abiertos"] if e["cliente"] == "ANA MARIA PEREZ LOPEZ"][0]
    assert "receta" not in ana["faltantes"] and "CFDI (XML)" not in ana["faltantes"]
