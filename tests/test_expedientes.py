from datetime import date

from reembolsos import expedientes as ex
from reembolsos.catalogo import Cliente


def _r(cliente, fecha, tipo, estado="Recibido", total=""):
    return {"Cliente": cliente, "FechaRecepcion": fecha, "TipoDocumento": tipo, "Estado": estado,
            "NombreOriginal": f"{tipo}.pdf", "Total": total, "Enlace": ""}


def test_expediente_completo_e_incompleto():
    regs = [
        _r("Ana", "2026-10-01", "CFDI factura", total="1500"), _r("Ana", "2026-10-02", "Factura PDF"), _r("Ana", "2026-10-03", "Receta"),
        _r("Luis", "2026-10-05", "Factura PDF"),
        _r("Ana", "2026-10-25", "Informe médico"),  # nuevo evento de Ana, fuera de la ventana
    ]
    exps = ex.agrupar(regs, hoy=date(2026, 10, 8))
    por = {(e["cliente"], e["inicio"]): e for e in exps}
    ana1 = por[("Ana", "2026-10-01")]
    assert ana1["estado"] == "completo" and ana1["documentos"] == 3 and ana1["total_facturado"] == 1500.0
    assert ana1["faltantes"] == ["informe médico"]
    luis = por[("Luis", "2026-10-05")]
    assert luis["estado"] == "incompleto" and "receta" in luis["faltantes"] and luis["dias_sin_movimiento"] == 3
    assert exps[0]["estado"] == "incompleto"  # los incompletos van primero


def test_en_revision_cuando_hay_documentos_por_confirmar():
    regs = [_r("Ana", "2026-10-01", "CFDI factura"), _r("Ana", "2026-10-01", "Receta", estado="Revisar")]
    assert ex.agrupar(regs, hoy=date(2026, 10, 8))[0]["estado"] == "en revisión"


def test_sin_cliente_o_descartados_no_forman_expediente():
    regs = [_r("", "2026-10-01", "Receta"), _r("Ana", "2026-10-01", "CFDI factura", estado="Descartado - duplicado")]
    assert ex.agrupar(regs, hoy=date(2026, 10, 8)) == []


def test_alertas_documento():
    cliente = Cliente({"NombreCliente": "Ana", "RFC": "PELA800101AB1"})
    res = {"rfc": "XAXX010101000", "fecha_doc": "2026-08-01", "tipo_documento": "CFDI factura", "total": ""}
    avisos = ex.alertas_documento(res, cliente, "2026-10-08")
    assert any("RFC" in a for a in avisos) and any("antigüedad" in a for a in avisos) and any("sin total" in a for a in avisos)
    assert ex.alertas_documento({"rfc": "PELA800101AB1", "fecha_doc": "2026-10-07", "tipo_documento": "Receta"}, cliente, "2026-10-08") == []


def test_borrador_solicitud():
    e = {"cliente": "Ana", "ultimo": "2026-10-05", "faltantes": ["receta", "informe médico"]}
    html = ex.texto_solicitud_faltantes(e)
    assert "receta y informe médico" in html and "Ana" in html


def test_expediente_sin_reembolso_no_exige_nada_y_la_poliza_cuenta():
    from reembolsos.expedientes import agrupar
    registros = [
        {"Cliente": "ANA RUIZ", "FechaRecepcion": "2026-11-01", "TipoDocumento": "Operación de seguro (no reembolso)", "Estado": "No es reembolso"},
        {"Cliente": "ANA RUIZ", "FechaRecepcion": "2026-11-02", "TipoDocumento": "Identificación", "Estado": "Recibido"},
        {"Cliente": "LUIS SOTO", "FechaRecepcion": "2026-11-01", "TipoDocumento": "Operación de seguro (no reembolso)", "Estado": "No es reembolso"},
        {"Cliente": "LUIS SOTO", "FechaRecepcion": "2026-11-03", "TipoDocumento": "Receta", "Estado": "Recibido"},
    ]
    exps = {e["cliente"]: e for e in agrupar(registros, date(2026, 11, 5))}
    assert exps["ANA RUIZ"]["estado"] == "sin reembolso" and exps["ANA RUIZ"]["faltantes"] == [] and exps["ANA RUIZ"]["documentos"] == 2
    # con un documento de reembolso ya se exige lo demás; la póliza sigue dentro del mismo expediente
    assert exps["LUIS SOTO"]["estado"] == "incompleto" and exps["LUIS SOTO"]["documentos"] == 2
