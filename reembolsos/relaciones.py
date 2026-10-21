"""Relaciones de reclamaciones que Lau llevaba a mano en Excel, corroboradas contra las facturas de los expedientes.

Formato típico (hoja con encabezados): PADECIMIENTO · RECLAMACION · CONCEPTO · DESCRIPCION · FACTURA · FECHA DE DOCUMENTO ·
MONTO · FECHA DE INGRESO · FOLIO · ESTATUS [· FECHA DE FINIQUITO]. Se leen todas las columnas MENOS padecimiento y
descripción (datos clínicos): esas nunca salen de aquí.

Cada fila se cruza con el índice de facturas (CFDI XML y facturas PDF con capa de texto: folio, total, fecha, UUID) del
mismo cliente: por folio, o por monto (±1 peso) y fecha (±7 días). Queda "confirmada" o "sin documento".
"""
import json
import re
import unicodedata
import warnings
from datetime import date, datetime
from pathlib import Path

from . import clasificacion as cl

CLINICAS = ("PADECIMIENTO", "DESCRIPCION", "DIAGNOSTICO")
ESTATUS = [("PAGO PARCIAL", "Pago parcial"), ("PARCIAL", "Pago parcial"), ("PAGAD", "Pagado"), ("LIQUIDAD", "Pagado"),
           ("REPROCESO", "En reproceso"), ("PROCESO", "En proceso"), ("RECHAZ", "Rechazado"), ("IMPROCEDENTE", "Rechazado"),
           ("FUERA DE TIEMPO", "Fuera de tiempo"), ("PENDIENTE", "Pendiente")]
CATEGORIAS = [("HONORARIO", "Honorarios médicos"), ("FARMACIA", "Farmacia"), ("MEDICAMENTO", "Farmacia"), ("LABORATORIO", "Laboratorio o estudios"),
              ("CHOPO", "Laboratorio o estudios"), ("SALUD DIGNA", "Laboratorio o estudios"), ("ESTUDIO", "Laboratorio o estudios"),
              ("HOSPITAL", "Hospital"), ("CONSULTA", "Honorarios médicos"), ("TERAPIA", "Terapia o rehabilitación"),
              ("REHABILITA", "Terapia o rehabilitación"), ("OPTICA", "Óptica"), ("LENTE", "Óptica")]


def _n(s):
    s = unicodedata.normalize("NFKD", str(s if s is not None else ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c)).upper()).strip()


def _fecha(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _monto(v):
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = re.sub(r"[^\d.,-]", "", str(v or ""))
    if not s:
        return None
    s = s.replace(",", "") if s.count(".") <= 1 else s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def solo_digitos(s):
    return re.sub(r"^0+", "", re.sub(r"\D", "", str(s or "")))


def estatus_normal(s):
    t = _n(s)
    return next((nombre for clave, nombre in ESTATUS if clave in t), "Sin estatus" if not t or t in ("ESTATUS", "STATUS") else "Otro")


def categoria(concepto):
    t = _n(concepto)
    return next((nombre for clave, nombre in CATEGORIAS if clave in t), "Otro")


def leer_relaciones(raiz):
    """Filas de todas las relaciones de reclamaciones bajo raiz (Cartera/Cliente/...)."""
    import openpyxl
    raiz = Path(raiz)
    salida = []
    for p in sorted(raiz.rglob("*.xlsx")):
        partes = p.relative_to(raiz).parts
        cartera, cliente = (partes[0], partes[1]) if len(partes) >= 3 else ("", "")
        evento = partes[2] if len(partes) >= 4 else ""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        except Exception:  # noqa: BLE001
            continue
        for ws in wb.worksheets:
            idx = None
            for fila in ws.iter_rows(values_only=True):
                vals = [_n(v) for v in fila]
                if idx is None:
                    if "FACTURA" in vals and "MONTO" in vals and any(v.startswith("RECLAMACION") for v in vals):
                        idx = {}
                        for i, v in enumerate(vals):
                            if v and not v.startswith(CLINICAS):
                                idx.setdefault(v, i)
                    continue

                def campo(*claves):
                    for clave in claves:
                        for c, i in idx.items():
                            if c.startswith(clave) and i < len(fila):
                                return fila[i]
                    return None
                factura, monto = campo("FACTURA"), _monto(campo("MONTO"))
                if not factura and monto is None:
                    continue
                if _n(factura) == "FACTURA":
                    continue   # encabezado repetido
                salida.append({
                    "cartera": cartera, "cliente": cliente, "evento": evento, "archivo": "/".join(partes), "hoja": ws.title,
                    "reclamacion": _n(campo("RECLAMACION"))[:40], "concepto": _n(campo("CONCEPTO"))[:60],
                    "categoria": categoria(campo("CONCEPTO")), "factura": _n(factura)[:40],
                    "fecha_documento": str(_fecha(campo("FECHA DE DOCUMENTO", "FECHA DOCUMENTO")) or ""),
                    "monto": monto, "fecha_ingreso": str(_fecha(campo("FECHA DE INGRESO", "FECHA INGRESO")) or ""),
                    "folio": _n(campo("FOLIO"))[:30], "estatus": estatus_normal(campo("ESTATUS", "STATUS")),
                    "fecha_finiquito": str(_fecha(campo("FECHA DE FINIQUITO", "F/ FINIQUITO")) or ""),
                })
    return salida


# ---------- índice de facturas de los expedientes ----------
_RE_FOLIO = re.compile(r"\b(?:FOLIO|NO\.? ?DE ?FACTURA|FACTURA)\b ?(?:FISCAL)?[:#\s]*([A-Z]{0,4}[- ]?\d{1,12})\b")
_RE_TOTAL = re.compile(r"\bTOTAL\b[^0-9$]{0,25}\$? ?([\d,]+\.\d{2})")


def datos_factura(ruta, metodo):
    """Folio, total, fecha y UUID de una factura (XML o PDF con capa de texto). {} si no se encuentra nada."""
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".xml":
        import xml.etree.ElementTree as ET
        try:
            raiz = ET.parse(ruta).getroot()
        except ET.ParseError:
            return {}
        d = {"folio": (raiz.get("Serie", "") + raiz.get("Folio", "")), "total": _monto(raiz.get("Total")),
             "fecha": raiz.get("Fecha", "")[:10]}
        for el in raiz.iter():
            if el.tag.split("}")[-1] == "TimbreFiscalDigital":
                d["uuid"] = el.get("UUID", "").upper()
        return d
    if metodo == "texto PDF":
        texto = _n(cl.texto_pdf(ruta, 2))
    elif metodo == "OCR":
        from .contenido import ocr
        texto = _n(ocr(ruta, 2))
    else:
        return {}
    if not texto:
        return {}
    folio = _RE_FOLIO.search(texto)
    totales = [_monto(m) for m in _RE_TOTAL.findall(texto)]
    from .contenido import fecha_por_texto
    uuid = re.search(r"\b[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\b", texto)
    return {"folio": folio[1].replace(" ", "") if folio else "", "total": max([t for t in totales if t], default=None),
            "fecha": str(fecha_por_texto(texto) or ""), "uuid": uuid[0] if uuid else ""}


INDICE_VERSION = 2   # 2: también facturas escaneadas (OCR)


def indice_facturas(raiz, archivos, cache):
    """{(cartera, cliente): [factura]} de los documentos tipo factura/CFDI. Reanudable: cache JSONL por ruta."""
    raiz, cache = Path(raiz), Path(cache)
    previo = {}
    if cache.exists():
        for linea in cache.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(linea)
                previo[d["ruta"]] = d
            except (ValueError, KeyError):
                continue
    indice = {}
    with cache.open("a", encoding="utf-8") as fh:
        for a in archivos:
            if not a.get("cliente") or a.get("duplicado_de") or a["tipo"] not in ("Factura PDF", "CFDI factura"):
                continue
            d = previo.get(a["ruta"])
            if d is None or d.get("v") != INDICE_VERSION:
                try:
                    d = {"ruta": a["ruta"], "v": INDICE_VERSION, **datos_factura(raiz / a["ruta"], a.get("metodo"))}
                except Exception:  # noqa: BLE001
                    d = {"ruta": a["ruta"], "v": INDICE_VERSION}
                fh.write(json.dumps(d, ensure_ascii=False) + "\n"); fh.flush()
            indice.setdefault((a["cartera"], a["cliente"]), []).append({**d, "evento": a.get("evento") or ""})
    return indice


def corroborar(filas, indice, tolerancia=1.0, dias=7):
    """Agrega a cada fila: corroboracion ('confirmada por folio' | 'confirmada por monto y fecha' | 'sin documento'),
    documento y evento del documento encontrado."""
    for f in filas:
        facturas = indice.get((f["cartera"], f["cliente"]), [])
        folio = solo_digitos(f["factura"])
        hallada, como = None, ""
        if folio and len(folio) >= 2:
            hallada = next((x for x in facturas if solo_digitos(x.get("folio")) == folio
                            and (f["monto"] is None or x.get("total") is None or abs(x["total"] - f["monto"]) <= max(tolerancia, f["monto"] * 0.01))), None)
            como = "confirmada por folio" if hallada else ""
        if not hallada and f["monto"]:
            fd = _fecha(f["fecha_documento"])
            for x in facturas:
                fx = _fecha(x.get("fecha"))
                if x.get("total") is not None and abs(x["total"] - f["monto"]) <= tolerancia and (not fd or not fx or abs((fd - fx).days) <= dias):
                    hallada, como = x, "confirmada por monto y fecha"
                    break
        if not hallada and len(folio) >= 3:
            hallada = next((x for x in facturas if solo_digitos(x.get("folio")) and len(solo_digitos(x.get("folio"))) >= 3 and
                            (solo_digitos(x.get("folio")).endswith(folio) or folio.endswith(solo_digitos(x.get("folio"))))), None)
            como = "probable: folio parcial (revisar)" if hallada else ""
        if not hallada and f["monto"]:
            hallada = next((x for x in facturas if x.get("total") is not None and abs(x["total"] - f["monto"]) <= tolerancia), None)
            como = "probable: mismo monto, otra fecha (revisar)" if hallada else ""
        f["corroboracion"] = como or "sin documento"
        f["documento"] = hallada["ruta"] if hallada else ""
        f["evento_documento"] = hallada.get("evento", "") if hallada else ""
    return filas
