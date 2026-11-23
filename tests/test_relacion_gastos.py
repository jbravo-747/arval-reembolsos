"""Relación de gastos armada por el programa (solo datos sintéticos)."""
from datetime import date

import openpyxl

from reembolsos import relacion_gastos as rg

CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Serie="{serie}" Folio="{folio}" Fecha="{fecha}T10:00:00" Total="{total}" TipoDeComprobante="I">
  <cfdi:Emisor Rfc="XAXX010101000" Nombre="{emisor}" RegimenFiscal="{regimen}"/>
  <cfdi:Receptor Rfc="EJRO800101AAA" Nombre="ROSA EJEMPLO GARZA"/>
  <cfdi:Complemento><tfd:TimbreFiscalDigital UUID="{uuid}"/></cfdi:Complemento>
</cfdi:Comprobante>"""


def _xml(carpeta, nombre, **kw):
    datos = dict(serie="A", folio="100", fecha="2026-10-01", total="1500.00", emisor="FARMACIA EJEMPLO SA DE CV", regimen="601",
                 uuid="11111111-2222-3333-4444-555555555555")
    datos.update(kw)
    (carpeta / nombre).write_text(CFDI.format(**datos), encoding="utf-8")


def _relacion_de_lau(ruta):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["B1"] = "ROSA EJEMPLO GARZA"
    for i, c in enumerate(rg.COLUMNAS):
        ws.cell(2, 2 + i, c)
    ws.cell(3, 2, "DATO CLINICO DE LAU")          # padecimiento
    ws.cell(3, 3, "2026XX0001")                   # reclamación
    ws.cell(3, 4, "FACTURA FARMACIA EJEMPLO")     # concepto
    ws.cell(3, 6, "A 100")                        # factura
    ws.cell(3, 8, 1400)                           # monto distinto al del CFDI
    wb.save(ruta)


def test_concepto_como_lau():
    assert rg.concepto("DR JUAN EJEMPLO", honorarios=True) == "FACTURA HONORARIOS MEDICOS"
    assert rg.concepto("FARMACIA EJEMPLO, S.A. DE C.V.") == "FACTURA FARMACIA EJEMPLO"
    assert rg.clave_factura("A 9805") == rg.clave_factura("a-9805") == "A9805"


def test_arma_relacion_nueva_desde_xml_solicitud_y_finiquito(tmp_path):
    cliente = tmp_path / "SAYER CLIENTES" / "ROSA EJEMPLO GARZA"
    evento = cliente / "2026-10_Expediente 20261005"
    evento.mkdir(parents=True)
    _xml(evento, "f1.xml")
    _xml(evento, "f2.xml", serie="", folio="777", total="800.50", emisor="DRA ANA EJEMPLO", regimen="612", fecha="2026-10-03")
    datos = [
        {"tipo": "solicitud", "reclamacion": "2026XX0001", "fecha": "2026-10-09", "facturas": [{"factura": "A100"}, {"factura": "777"}]},
        {"tipo": "finiquito", "folio": "SIGEJ000123", "fecha": "2026-10-20", "reclamacion": "2026XX0001", "estatus": "Pagado",
         "facturas": [{"factura": "A 100", "pagado": 1200}, {"factura": "777", "pagado": 800.5}]},
    ]
    r = rg.actualizar(cliente, "ROSA EJEMPLO GARZA", datos)
    assert r["filas"] == 2 and r["respaldo"] is None
    nombre, filas, nuestra = rg.leer(r["ruta"])
    assert nuestra and nombre == "ROSA EJEMPLO GARZA"
    f1 = next(f for f in filas if rg.clave_factura(f["FACTURA"]) == "A100")
    assert f1["MONTO"] == 1500 and f1["MONTO PAGADO"] == 1200 and f1["ESTATUS"] == "PAGADA" and f1["FOLIO"] == "SIGEJ000123"
    assert f1["RECLAMACION"] == "2026XX0001" and f1["FECHA DE INGRESO"] == date(2026, 10, 9) and f1["FECHA DE FINIQUITO"] == date(2026, 10, 20)
    assert f1["CONCEPTO"] == "FACTURA FARMACIA EJEMPLO" and f1["PADECIMIENTO"] is None and f1["DESCRIPCION"] is None
    f2 = next(f for f in filas if rg.clave_factura(f["FACTURA"]) == "777")
    assert f2["CONCEPTO"] == "FACTURA HONORARIOS MEDICOS"
    ws = openpyxl.load_workbook(r["ruta"]).worksheets[0]
    assert any(str(ws.cell(row, 14).value).startswith("=") for row in range(3, 5))   # MONTO NO PAGADO con fórmula


def test_respeta_y_respalda_la_relacion_de_lau(tmp_path):
    cliente = tmp_path / "ARVAL CLIENTES" / "ROSA EJEMPLO GARZA"
    cliente.mkdir(parents=True)
    _relacion_de_lau(cliente / rg.NOMBRE_ARCHIVO)
    _xml(cliente, "f1.xml")   # mismo folio A 100, total 1500 (Lau puso 1400)
    _xml(cliente, "f3.xml", folio="300", total="99.90", uuid="99999999-2222-3333-4444-555555555555")
    r = rg.actualizar(cliente, "ROSA EJEMPLO GARZA", [])
    assert r["respaldo"] and (cliente / rg.CARPETA_RESPALDO).exists()
    _, filas, nuestra = rg.leer(r["ruta"])
    assert nuestra and len(filas) == 2
    f1 = next(f for f in filas if rg.clave_factura(f["FACTURA"]) == "A100")
    assert f1["PADECIMIENTO"] == "DATO CLINICO DE LAU" and f1["MONTO"] == 1400   # no pisa lo de Lau
    assert "Revisar monto" in (f1["OBSERVACIONES"] or "")
    # Una segunda pasada sin documentos nuevos no cambia nada ni duplica notas
    r2 = rg.actualizar(cliente, "ROSA EJEMPLO GARZA", [])
    assert r2["cambios"] == 0


def test_relacion_abierta_se_reintenta(tmp_path, monkeypatch):
    cliente = tmp_path / "C" / "ROSA EJEMPLO GARZA"
    cliente.mkdir(parents=True)

    def bloqueado(*a, **k):
        raise PermissionError("abierto en Excel")
    monkeypatch.setattr(rg.Path, "replace", bloqueado)
    try:
        rg.actualizar(cliente, "ROSA EJEMPLO GARZA", [{"tipo": "factura", "factura": "X1", "monto": 10, "fecha": "2026-10-01"}])
        assert False, "debió avisar que está ocupada"
    except rg.RelacionOcupada:
        pass


def test_el_folio_de_la_factura_manda_aunque_llegue_despues(tmp_path):
    cliente = tmp_path / "C" / "ROSA EJEMPLO GARZA"
    cliente.mkdir(parents=True)
    _xml(cliente, "f.xml")
    r = rg.actualizar(cliente, "ROSA EJEMPLO GARZA", [{"tipo": "finiquito", "folio": "S1", "facturas": [{"factura": "A100", "pagado": 10}]}])
    _, filas, _ = rg.leer(r["ruta"])
    assert len(filas) == 1 and filas[0]["FACTURA"] == "A 100" and filas[0]["MONTO PAGADO"] == 10
