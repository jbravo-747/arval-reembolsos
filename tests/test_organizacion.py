"""Organizar la copia local de expedientes y construir la semilla con la estructura estándar (datos sintéticos)."""
import csv
import json
import os

import pytest

import cli
from reembolsos import organizacion as org
from tests.test_cli_apply import _cfg

CFDI = """<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Total="700.00" Fecha="2026-03-15T10:00:00">
<cfdi:Emisor Rfc="FAR010101AAA" Nombre="FARMACIA"/><cfdi:Receptor Rfc="PELA800101AB1" Nombre="{nombre}"/></cfdi:Comprobante>"""


@pytest.fixture
def arbol(tmp_path):
    raiz = tmp_path / "SINIESTROS"
    ev = raiz / "CARTERA UNO" / "ANA MARIA PEREZ LOPEZ" / "REEMBOLSO 1"
    (ev / "FACTURAS").mkdir(parents=True)
    (ev / "FACTURAS" / "f1.xml").write_text(CFDI.format(nombre="ANA MARIA PEREZ LOPEZ"), encoding="utf-8")
    (ev / "receta 2026-03-10.pdf").write_bytes(b"%PDF-1.4 escaneado")
    (ev / "copia receta.pdf").write_bytes(b"%PDF-1.4 escaneado")          # duplicado exacto de la receta
    (ev / "TAC").mkdir()
    (ev / "TAC" / "IM0001.dcm").write_bytes(b"DICM")
    suelto = raiz / "CARTERA UNO" / "CARLOS RUIZ SOTO"
    suelto.mkdir(parents=True)
    (suelto / "factura.xml").write_text(CFDI.format(nombre="ANA MARIA PEREZ LOPEZ").replace("700.00", "800.00"), encoding="utf-8")  # contenido de otro cliente
    (suelto / "foto.jpg").write_bytes(b"jpg")
    (raiz / "suelto en raiz.pdf").write_bytes(b"%PDF-1.4 x")
    return raiz


def test_analizar_deduce_estructura_tipos_y_propuesta(arbol):
    a = org.analizar(arbol)
    por = {x["nombre"]: x for x in a["archivos"]}
    f1 = por["f1.xml"]
    assert (f1["cartera"], f1["cliente"], f1["evento"], f1["tipo"]) == ("CARTERA UNO", "ANA MARIA PEREZ LOPEZ", "REEMBOLSO 1", "CFDI factura")
    assert f1["fecha"] == "2026-03-15" and f1["fecha_origen"] == "documento"
    assert f1["ruta_propuesta"].startswith("CARTERA UNO/ANA MARIA PEREZ LOPEZ/2026-03_REEMBOLSO 1/20260315_CFDI_01")
    receta = por["receta 2026-03-10.pdf"]
    assert receta["tipo"] == "Receta" and receta["fecha_origen"] == "nombre" and receta["requiere_lectura"]
    assert por["receta 2026-03-10.pdf"]["duplicado_de"] == por["copia receta.pdf"]["ruta"]   # se queda el primero en orden
    assert por["IM0001.dcm"]["dicom"] and por["IM0001.dcm"]["ruta_propuesta"].endswith("/Imagenes DICOM/TAC/IM0001.dcm")
    assert por["factura.xml"]["conflicto"] and por["factura.xml"]["evento"] == ""
    assert "/_Sin evento/" in por["factura.xml"]["ruta_propuesta"]
    assert por["suelto en raiz.pdf"]["ruta_propuesta"] is None
    r = a["resumen"]
    assert (r["clientes"], r["eventos"], r["dicom"], r["duplicados"], r["conflictos"], r["fuera_de_estructura"]) == (2, 1, 1, 1, 1, 1)
    ana = [e for e in a["expedientes"] if e["cliente"] == "ANA MARIA PEREZ LOPEZ"][0]
    assert ana["documentos"] == 3 and "factura en PDF" in ana["faltantes"] and "receta" not in ana["faltantes"]


def test_semilla_copia_sin_tocar_el_original(arbol, tmp_path):
    a = org.analizar(arbol)
    antes = sorted(p.name for p in arbol.rglob("*"))
    destino = tmp_path / "Estandar"
    conteo = org.construir_semilla(a, arbol, destino)
    assert sorted(p.name for p in arbol.rglob("*")) == antes
    assert conteo["copiados"] == 5 and conteo["duplicados omitidos"] == 1 and conteo["a _Por identificar"] == 1
    assert (destino / "_Por identificar" / "suelto en raiz.pdf").exists()
    with (destino / "_indice_semilla.csv").open(encoding="utf-8-sig") as fh:
        assert len(list(csv.reader(fh))) == 8
    assert org.construir_semilla(a, arbol, destino)["ya estaban"] == 6   # repetir no duplica
    with pytest.raises(ValueError):
        org.construir_semilla(a, arbol, arbol / "dentro")


def test_cli_organizar_y_semilla_sin_credenciales(arbol, tmp_path, monkeypatch):
    for v in ("M365_TENANT_ID", "M365_CLIENT_ID", "M365_CLIENT_SECRET"):
        monkeypatch.delenv(v, raising=False)
    cfg = _cfg(tmp_path, "propone")
    cfg.trabajo.mkdir()
    cli.organizar(cfg, str(arbol))
    resumen = json.loads((cfg.trabajo / "organizacion_resumen.json").read_text(encoding="utf-8"))
    assert resumen["etapa"] == "propuesta" and resumen["clientes"] == 2 and resumen["expedientes_total"] == 2
    with (cfg.trabajo / "catalogo_semilla.csv").open(encoding="utf-8-sig") as fh:
        assert [r["NombreCliente"] for r in csv.DictReader(fh)] == ["ANA MARIA PEREZ LOPEZ", "CARLOS RUIZ SOTO"]
    cli.semilla(cfg, str(arbol), str(tmp_path / "Estandar"), solo_carpetas=True)
    resumen = json.loads((cfg.trabajo / "organizacion_resumen.json").read_text(encoding="utf-8"))
    assert resumen["etapa"] == "solo carpetas" and (tmp_path / "Estandar" / "CARTERA UNO" / "CARLOS RUIZ SOTO" / "_Sin evento").is_dir()
    assert not any(p.is_file() for p in (tmp_path / "Estandar" / "CARTERA UNO").rglob("*"))
    assert os.environ.get("M365_CLIENT_ID") is None


def test_analizar_reanuda_desde_la_cache(arbol, tmp_path, monkeypatch):
    cache, bitacora = tmp_path / "cache.jsonl", tmp_path / "bitacora.txt"
    primero = org.analizar(arbol, cache=cache, bitacora=bitacora)
    with cache.open("a", encoding="utf-8") as fh:
        fh.write('{"ruta": "cortada por una interrupc')          # última línea incompleta
    monkeypatch.setattr(org.cl, "preanalisis", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debía releer")))
    segundo = org.analizar(arbol, cache=cache, bitacora=bitacora)
    assert segundo["resumen"] == primero["resumen"]
    assert [a["ruta_propuesta"] for a in segundo["archivos"]] == [a["ruta_propuesta"] for a in primero["archivos"]]
    assert "bloque" in bitacora.read_text(encoding="utf-8")


def test_analizar_escribe_avance(arbol, tmp_path):
    progreso = tmp_path / "progreso.json"
    org.analizar(arbol, progreso=progreso)
    p = json.loads(progreso.read_text(encoding="utf-8"))
    assert p["bloques_hechos"] == p["bloques_total"] == 3 and p["archivos_hechos"] == p["archivos_total"] == 7
    assert p["estado"] == "corriendo" and p["etapa"] == "armando la propuesta"
