"""Expedientes: agrupa los documentos registrados por cliente y evento, y dice qué falta.

Un expediente de reembolso completo suele llevar: factura (CFDI XML + representación PDF), receta o indicación
médica, e informe médico. Dos documentos del mismo cliente pertenecen al mismo evento si llegan con menos de
VENTANA_DIAS de diferencia.
"""
from collections import defaultdict
from datetime import date, datetime

VENTANA_DIAS = 10
REQUISITOS = {
    "factura_xml": ("CFDI factura", "CFDI recibo de honorarios"),
    "factura_pdf": ("Factura PDF",),
    "receta": ("Receta",),
    "informe": ("Informe médico", "Estudio o resultado"),
}
ETIQUETAS = {"factura_xml": "CFDI (XML)", "factura_pdf": "factura en PDF", "receta": "receta", "informe": "informe médico"}


def _fecha(valor):
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def agrupar(registros, hoy=None):
    """registros: dicts con Cliente, FechaRecepcion, TipoDocumento, Estado, NombreOriginal, Total, Enlace.
    Devuelve una lista de expedientes ordenada por prioridad de seguimiento."""
    hoy = hoy or date.today()
    por_cliente = defaultdict(list)
    for r in registros:
        c = str(r.get("Cliente") or "").strip()
        if not c or r.get("Estado") in ("Descartado - duplicado", "Sin documentos", "No es reembolso", "Error"):
            continue
        f = _fecha(r.get("FechaRecepcion"))
        if f:
            por_cliente[c].append((f, r))
    expedientes = []
    for cliente, docs in por_cliente.items():
        docs.sort(key=lambda x: x[0])
        grupo, inicio = [], None
        for f, r in docs + [(None, None)]:
            if f is None or (inicio and (f - inicio).days > VENTANA_DIAS):
                if grupo:
                    expedientes.append(_resumir(cliente, grupo, hoy))
                grupo, inicio = [], f
            if r is not None:
                if inicio is None:
                    inicio = f
                grupo.append((f, r))
    orden = {"incompleto": 0, "en revisión": 1, "completo": 2}
    expedientes.sort(key=lambda e: (orden[e["estado"]], -e["dias_sin_movimiento"]))
    return expedientes


def _resumir(cliente, grupo, hoy):
    tipos = [str(r.get("TipoDocumento") or "") for _, r in grupo]
    presentes = {k for k, aceptados in REQUISITOS.items() if any(t in aceptados for t in tipos)}
    faltantes = [ETIQUETAS[k] for k in REQUISITOS if k not in presentes]
    # Un recibo de honorarios o una receta sin informe puede ser legítimo: solo exigimos factura y receta o informe.
    esencial_ok = ("factura_xml" in presentes or "factura_pdf" in presentes) and ("receta" in presentes or "informe" in presentes)
    por_revisar = any(r.get("Estado") in ("Revisar", "Cliente desconocido") for _, r in grupo)
    estado = "en revisión" if por_revisar else ("completo" if esencial_ok else "incompleto")
    ultima = max(f for f, _ in grupo)
    total = 0.0
    for _, r in grupo:
        try:
            total += float(str(r.get("Total") or "0").replace(",", ""))
        except ValueError:
            pass
    return {
        "cliente": cliente, "inicio": str(grupo[0][0]), "ultimo": str(ultima), "documentos": len(grupo),
        "tipos": sorted(set(t for t in tipos if t)), "faltantes": faltantes, "estado": estado,
        "dias_sin_movimiento": (hoy - ultima).days, "total_facturado": round(total, 2),
        "archivos": [{"nombre": r.get("NombreOriginal"), "tipo": r.get("TipoDocumento"), "enlace": r.get("Enlace"),
                      "estado": r.get("Estado")} for _, r in grupo],
    }


def alertas_documento(res, cliente_catalogo=None, fecha_recepcion=None, dias_max=30):
    """Avisos de calidad sobre un documento ya clasificado (no son errores, son cosas que Lau debe saber)."""
    avisos = []
    rfc_doc = (res.get("rfc") or "").upper()
    if cliente_catalogo is not None and cliente_catalogo.rfc and rfc_doc and rfc_doc != cliente_catalogo.rfc:
        avisos.append(f"RFC del documento ({rfc_doc}) distinto al RFC del cliente en el catálogo")
    f_doc, f_rec = _fecha(res.get("fecha_doc")), _fecha(fecha_recepcion)
    if f_doc and f_rec and (f_rec - f_doc).days > dias_max:
        avisos.append(f"documento con {(f_rec - f_doc).days} días de antigüedad al recibirse")
    if res.get("tipo_documento") in ("CFDI factura", "CFDI recibo de honorarios") and not res.get("total"):
        avisos.append("CFDI sin total legible")
    return avisos


def texto_solicitud_faltantes(expediente, nombre_operadora="Laura Torres"):
    """Borrador de correo al cliente pidiendo lo que falta. Sin datos clínicos: solo tipos de documento."""
    faltan = " y ".join(expediente["faltantes"]) if expediente["faltantes"] else "ningún documento"
    return (
        f"<p>Estimado(a) {expediente['cliente']},</p>"
        f"<p>Recibimos su documentación para el trámite de reembolso (último envío el {expediente['ultimo']}). "
        f"Para poder presentarlo ante la aseguradora nos falta: <b>{faltan}</b>.</p>"
        "<p>¿Podría enviarlo respondiendo a este correo? Si ya lo envió, indíquenos la fecha y lo buscamos.</p>"
        f"<p>Gracias,<br>{nombre_operadora}<br>Arval México</p>"
    )
