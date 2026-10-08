"""Resumen diario para Lau: toma las filas con EnResumen = No, las ordena por prioridad y arma el correo."""
import html
from collections import Counter

COLUMNAS = ["Prioridad", "Cliente", "TipoDocumento", "NombreOriginal", "Estado", "Confianza", "Observaciones"]


def _prio(fila):
    try:
        return int(str(fila.get("Prioridad") or "3")[:1])
    except ValueError:
        return 3


def agrupar(filas):
    pendientes = [f for f in filas if str(f.get("EnResumen") or "No").strip().lower() != "sí"
                  and str(f.get("EnResumen") or "No").strip().lower() != "si"]
    pendientes.sort(key=lambda f: (_prio(f), str(f.get("FechaRecepcion") or ""), str(f.get("HoraRecepcion") or "")))
    grupos = {
        "Prioridad 1: decidir hoy": [f for f in pendientes if _prio(f) == 1],
        "Prioridad 2: confirmar cliente": [f for f in pendientes if _prio(f) == 2],
        "Recibidos sin pendientes": [f for f in pendientes if _prio(f) == 3 and f.get("Estado") == "Recibido"],
        "Descartados por duplicado": [f for f in pendientes if f.get("Estado") == "Descartado - duplicado"],
        "Correos sin documentos": [f for f in pendientes if f.get("Estado") == "Sin documentos"],
        "No son reembolsos": [f for f in pendientes if f.get("Estado") == "No es reembolso"],
        "Errores": [f for f in pendientes if f.get("Estado") == "Error"],
    }
    return pendientes, grupos


def tabla_html(filas):
    if not filas:
        return "<p><i>Nada.</i></p>"
    enc = "".join(f"<th style='text-align:left;padding:4px 8px'>{c}</th>" for c in COLUMNAS)
    cuerpo = ""
    for f in filas:
        celdas = []
        for c in COLUMNAS:
            v = html.escape(str(f.get(c) or ""))
            if c == "NombreOriginal" and f.get("Enlace"):
                v = f"<a href='{html.escape(str(f['Enlace']))}'>{v}</a>"
            celdas.append(f"<td style='padding:4px 8px;border-top:1px solid #ddd'>{v}</td>")
        cuerpo += "<tr>" + "".join(celdas) + "</tr>"
    return f"<table style='border-collapse:collapse;font-family:Segoe UI,Arial;font-size:13px'><tr>{enc}</tr>{cuerpo}</table>"


def tabla_expedientes(expedientes):
    if not expedientes:
        return "<p><i>Sin expedientes abiertos.</i></p>"
    filas = ""
    for e in expedientes:
        faltan = ", ".join(e["faltantes"]) or "nada"
        filas += (f"<tr><td style='padding:4px 8px;border-top:1px solid #ddd'>{html.escape(e['cliente'])}</td>"
                  f"<td style='padding:4px 8px;border-top:1px solid #ddd'>{e['estado']}</td>"
                  f"<td style='padding:4px 8px;border-top:1px solid #ddd'>{e['documentos']}</td>"
                  f"<td style='padding:4px 8px;border-top:1px solid #ddd'>{html.escape(faltan)}</td>"
                  f"<td style='padding:4px 8px;border-top:1px solid #ddd'>{e['dias_sin_movimiento']}</td></tr>")
    enc = "".join(f"<th style='text-align:left;padding:4px 8px'>{c}</th>" for c in ("Cliente", "Expediente", "Docs", "Falta", "Días sin movimiento"))
    return f"<table style='border-collapse:collapse;font-family:Segoe UI,Arial;font-size:13px'><tr>{enc}</tr>{filas}</table>"


def correo(filas, fecha, narrativa="", expedientes=None, panel_url=""):
    pendientes, grupos = agrupar(filas)
    conteo = Counter(_prio(f) for f in pendientes)
    clientes = Counter(f.get("Cliente") or "(sin cliente)" for f in pendientes if _prio(f) <= 2)
    partes = []
    if narrativa:
        partes.append("<div style='font-family:Segoe UI,Arial;font-size:14px;border-left:4px solid #2f6fed;padding:6px 12px;margin-bottom:12px'>"
                      + "".join(f"<p>{html.escape(p)}</p>" for p in narrativa.strip().split("\n") if p.strip()) + "</div>")
    partes.append(f"<p>Resumen de reembolsos al {fecha}. <b>{len(pendientes)}</b> registros nuevos desde el último resumen: "
                  f"<b>{conteo.get(1, 0)}</b> de prioridad 1, <b>{conteo.get(2, 0)}</b> de prioridad 2, {conteo.get(3, 0)} informativos.</p>")
    if clientes:
        partes.append("<p>Clientes con pendientes: " + ", ".join(f"{html.escape(c)} ({n})" for c, n in clientes.most_common(8)) + "</p>")
    abiertos = [e for e in (expedientes or []) if e["estado"] != "completo"]
    if abiertos:
        partes.append(f"<h3 style='font-family:Segoe UI,Arial'>Expedientes con faltantes ({len(abiertos)})</h3>{tabla_expedientes(abiertos)}")
    for titulo, lista in grupos.items():
        if lista:
            partes.append(f"<h3 style='font-family:Segoe UI,Arial'>{titulo} ({len(lista)})</h3>{tabla_html(lista)}")
    pie = "Registro completo: Reembolsos/Control_Reembolsos.xlsx."
    if panel_url:
        pie += f" <a href='{html.escape(panel_url)}'>Abrir el panel de reembolsos</a>."
    partes.append(f"<p style='color:#666'>{pie}</p>")
    asunto = f"Reembolsos {fecha}: {conteo.get(1, 0)} por decidir, {conteo.get(2, 0)} por confirmar, {len(abiertos)} expedientes con faltantes"
    return asunto, "".join(partes), pendientes
