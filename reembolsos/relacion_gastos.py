"""RELACION DE GASTOS.xlsx de cada asegurado, armada por el programa con el mismo formato que Lau llevaba a mano.

Fila 1: nombre del asegurado (B1:O1). Fila 2: encabezados. Una fila por factura:
  PADECIMIENTO · RECLAMACION · CONCEPTO · DESCRIPCION · FACTURA · FECHA DE DOCUMENTO · MONTO · FECHA DE INGRESO ·
  FOLIO · ESTATUS · FECHA DE FINIQUITO · MONTO PAGADO · MONTO NO PAGADO · OBSERVACIONES

Fuentes (solo metadatos, nada clínico):
  - factura:   CFDI XML (lo lee este módulo) o datos que el clasificador leyó de la factura en PDF; incluye la descripción
               de los conceptos facturados (columna DESCRIPCION), que solo se escribe aquí, en el expediente del asegurado
  - solicitud: número de reclamación, fecha de ingreso y facturas incluidas
  - finiquito: folio, fecha, reclamación, estatus y lo pagado por factura
PADECIMIENTO nunca se llena desde los documentos: es dato clínico y queda para Lau.

Reglas: nunca pisa una celda que ya tiene valor (si el documento dice otra cosa lo anota en OBSERVACIONES); si la relación
existente no la hizo el programa, guarda antes una copia en «_Respaldo relación»; si el archivo está abierto (bloqueado),
lanza RelacionOcupada para reintentar después.
"""
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

NOMBRE_ARCHIVO = "RELACION DE GASTOS.xlsx"
CARPETA_RESPALDO = "_Respaldo relación"
MARCA = "arval-relacion-v1"
COLUMNAS = ["PADECIMIENTO", "RECLAMACION", "CONCEPTO", "DESCRIPCION", "FACTURA", "FECHA DE DOCUMENTO", "MONTO",
            "FECHA DE INGRESO", "FOLIO", "ESTATUS", "FECHA DE FINIQUITO", "MONTO PAGADO", "MONTO NO PAGADO", "OBSERVACIONES"]
FECHAS = {"FECHA DE DOCUMENTO", "FECHA DE INGRESO", "FECHA DE FINIQUITO"}
MONTOS = {"MONTO", "MONTO PAGADO", "MONTO NO PAGADO"}
CLINICAS = {"PADECIMIENTO"}
FORMATO_MONEDA = '_-"$"* #,##0.00_-;\\-"$"* #,##0.00_-;_-"$"* "-"??_-;_-@_-'
REGIMEN_HONORARIOS = {"612", "625"}   # personas físicas con actividad profesional


class RelacionOcupada(Exception):
    """El Excel está abierto o bloqueado: reintentar más tarde."""


def _n(s):
    s = unicodedata.normalize("NFKD", str(s if s is not None else ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c)).upper()).strip()


def clave_factura(s):
    """«A 9805», «A9805» y «a-9805» son la misma factura; «01 2623» = «012623»."""
    return re.sub(r"[^0-9A-Z]", "", _n(s))


def _digitos(s):
    return re.sub(r"^0+", "", re.sub(r"\D", "", str(s or "")))


def a_fecha(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 20000 < v < 80000:   # número de serie de Excel
        return date.fromordinal(date(1899, 12, 30).toordinal() + int(v))
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def a_monto(v):
    if isinstance(v, bool):
        return None
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


def concepto(emisor, honorarios=False):
    """Como lo escribe Lau: «FACTURA HONORARIOS MEDICOS» para médicos, «FACTURA <EMISOR>» para lo demás."""
    if honorarios:
        return "FACTURA HONORARIOS MEDICOS"
    e = _n(emisor)
    e = re.sub(r"[,.]", " ", e)
    e = re.sub(r"\b(S ?A ?B?|S DE R ?L|S ?C|S ?A ?P ?I|A ?C)( DE C ?V)?\b\s*$", "", e)
    e = re.sub(r"\bDE C ?V\b|\bSA DE CV\b", "", e)
    e = re.sub(r"\s+", " ", e).strip()
    return f"FACTURA {e}" if e else "FACTURA"


def estatus(s):
    t = _n(s)
    if not t:
        return ""
    if "PARCIAL" in t:
        return "PAGO PARCIAL"
    if "PAGAD" in t or "LIQUIDAD" in t:
        return "PAGADA"
    if "RECHAZ" in t or "IMPROCEDENTE" in t or "NO PROCEDE" in t:
        return "RECHAZADA"
    if "PROCESO" in t:
        return "EN PROCESO"
    return t[:30]


# ---------- CFDI ----------
def leer_cfdi(ruta):
    """Factura de un CFDI (XML): {tipo, factura, fecha, monto, concepto, uuid, rfc_receptor} o None si no es CFDI de ingreso."""
    try:
        raiz = ET.parse(ruta).getroot()
    except (ET.ParseError, OSError):
        return None
    if not raiz.tag.endswith("Comprobante") or raiz.get("TipoDeComprobante", "I") != "I":
        return None
    def uno(nombre):
        return next((e for e in raiz.iter() if e.tag.endswith("}" + nombre) or e.tag == nombre), None)
    em, rec, tfd = uno("Emisor"), uno("Receptor"), uno("TimbreFiscalDigital")
    serie, folio = (raiz.get("Serie") or "").strip(), (raiz.get("Folio") or "").strip()
    conceptos = []
    for e in raiz.iter():
        if (e.tag.endswith("}Concepto") or e.tag == "Concepto") and (e.get("Descripcion") or "").strip():
            d = re.sub(r"\s+", " ", e.get("Descripcion")).strip()
            if d not in conceptos:
                conceptos.append(d)
    uuid = (tfd.get("UUID") if tfd is not None else "") or ""
    factura = f"{serie} {folio}".strip() or uuid[-8:].upper()
    return {"tipo": "factura", "factura": factura, "fecha": (raiz.get("Fecha") or "")[:10], "monto": a_monto(raiz.get("Total")),
            "concepto": concepto(em.get("Nombre") if em is not None else "", (em.get("RegimenFiscal") if em is not None else "") in REGIMEN_HONORARIOS),
            "descripcion": descripcion(conceptos), "uuid": uuid.upper(), "rfc_receptor": (rec.get("Rfc") if rec is not None else "") or ""}


def descripcion(conceptos, largo=250):
    """Conceptos de la factura en una celda: «CONSULTA MEDICA; MEDICAMENTO X» (sin repetir, con tope de largo)."""
    if isinstance(conceptos, str):
        conceptos = [conceptos]
    texto = "; ".join(c.strip() for c in conceptos if c and str(c).strip())
    return texto if len(texto) <= largo else texto[:largo - 1].rstrip("; ") + "…"


def escanear_xml(carpeta):
    """Facturas de todos los CFDI de la carpeta del asegurado (con subcarpetas)."""
    datos = []
    for p in sorted(Path(carpeta).rglob("*.xml")):
        if CARPETA_RESPALDO in p.parts:
            continue
        d = leer_cfdi(p)
        if d:
            datos.append(d)
    return datos


# ---------- Excel ----------
def _fila_vacia():
    return {c: None for c in COLUMNAS}


def leer(ruta):
    """(nombre, filas, hecha_por_programa) de una relación existente; columnas ubicadas por su encabezado."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(ruta, data_only=True)
    except PermissionError as e:
        raise RelacionOcupada(str(e)) from e
    ws = wb.worksheets[0]
    nuestra = (wb.properties.keywords or "") == MARCA
    fila_enc, mapa = None, {}
    for r in range(1, min(ws.max_row, 8) + 1):
        vals = {c: _n(ws.cell(r, c).value) for c in range(1, ws.max_column + 1)}
        if "FACTURA" in vals.values() or ("FACTURA" in " ".join(vals.values()) and "MONTO" in " ".join(vals.values())):
            fila_enc = r
            for c, v in vals.items():
                v = v.strip()
                if v in COLUMNAS and v not in mapa:
                    mapa[v] = c
                elif v.startswith("FOLIO") and "FOLIO" not in mapa:
                    mapa["FOLIO"] = c
            break
    if not fila_enc:
        return "", [], nuestra
    nombre = next((str(ws.cell(r, c).value).strip() for r in range(1, fila_enc) for c in range(1, ws.max_column + 1)
                   if ws.cell(r, c).value not in (None, "")), "")
    filas = []
    for r in range(fila_enc + 1, ws.max_row + 1):
        f = _fila_vacia()
        for col, c in mapa.items():
            v = ws.cell(r, c).value
            if col in FECHAS:
                v = a_fecha(v) or (v if v not in ("", None) else None)
            elif col in MONTOS:
                v = a_monto(v) if v not in ("", None) else None
            elif v is not None:
                v = str(v).strip() or None
            f[col] = v
        if any(f[c] not in (None, "") for c in COLUMNAS):
            filas.append(f)
    return nombre, filas, nuestra


def escribir(ruta, nombre, filas):
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"
    wb.properties.keywords = MARCA
    wb.properties.creator = "Arval Clasificador"
    fina = Side(style="thin", color="999999")
    borde = Border(left=fina, right=fina, top=fina, bottom=fina)
    ws.cell(1, 2, nombre).font = Font(bold=True, size=13)
    ws.merge_cells(start_row=1, start_column=2, end_row=1, end_column=1 + len(COLUMNAS))
    ws.cell(1, 2).alignment = Alignment(horizontal="center")
    for i, col in enumerate(COLUMNAS):
        c = ws.cell(2, 2 + i, col)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9E1F2")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = borde
    for k, f in enumerate(filas):
        r = 3 + k
        for i, col in enumerate(COLUMNAS):
            letra = get_column_letter(2 + i)
            v = f.get(col)
            if col == "MONTO NO PAGADO" and f.get("MONTO") is not None and f.get("MONTO PAGADO") is not None:
                v = f"={get_column_letter(2 + COLUMNAS.index('MONTO'))}{r}-{get_column_letter(2 + COLUMNAS.index('MONTO PAGADO'))}{r}"
            c = ws[f"{letra}{r}"]
            c.value = v
            c.border = borde
            if col in FECHAS:
                c.number_format = "dd/mm/yyyy"
            elif col in MONTOS:
                c.number_format = FORMATO_MONEDA
    anchos = {"PADECIMIENTO": 22, "RECLAMACION": 18, "CONCEPTO": 34, "DESCRIPCION": 26, "FACTURA": 14, "FECHA DE DOCUMENTO": 13,
              "MONTO": 14, "FECHA DE INGRESO": 13, "FOLIO": 22, "ESTATUS": 13, "FECHA DE FINIQUITO": 13, "MONTO PAGADO": 14,
              "MONTO NO PAGADO": 14, "OBSERVACIONES": 40}
    ws.column_dimensions["A"].width = 2
    for i, col in enumerate(COLUMNAS):
        ws.column_dimensions[get_column_letter(2 + i)].width = anchos[col]
    ws.row_dimensions[2].height = 30
    ws.freeze_panes = "B3"
    tmp = Path(ruta).with_name("~" + Path(ruta).name + ".tmp")
    wb.save(tmp)
    try:
        tmp.replace(ruta)
    except PermissionError as e:
        tmp.unlink(missing_ok=True)
        raise RelacionOcupada(str(e)) from e


# ---------- Combinar documentos con la relación ----------
def _igual(col, a, b):
    if col in FECHAS:
        return a_fecha(a) == a_fecha(b)
    if col in MONTOS:
        x, y = a_monto(a), a_monto(b)
        return x is not None and y is not None and abs(x - y) <= 0.5
    if col == "FACTURA":
        return clave_factura(a) == clave_factura(b)
    if col == "ESTATUS":
        return estatus(a) == estatus(b)
    return _n(a) == _n(b)


def _poner(fila, col, valor):
    """Llena solo celdas vacías; si ya hay otro valor, lo anota en OBSERVACIONES. Nunca escribe columnas clínicas."""
    if col in CLINICAS or valor in (None, ""):
        return False
    if col in FECHAS:
        valor = a_fecha(valor)
        if not valor:
            return False
    elif col in MONTOS:
        valor = a_monto(valor)
        if valor is None:
            return False
    else:
        valor = str(valor).strip()
    actual = fila.get(col)
    if actual in (None, ""):
        fila[col] = valor
        return True
    if not _igual(col, actual, valor):
        texto = valor.strftime("%d/%m/%Y") if isinstance(valor, date) else (f"{valor:,.2f}" if isinstance(valor, float) else valor)
        nota = f"Revisar {col.lower()}: el documento dice {texto}"
        obs = fila.get("OBSERVACIONES") or ""
        if nota not in obs:
            fila["OBSERVACIONES"] = f"{obs} · {nota}".strip(" ·")
            return True
    return False


def _buscar(filas, factura, monto=None, fecha=None):
    k = clave_factura(factura)
    if k:
        for f in filas:
            if f.get("FACTURA") and clave_factura(f["FACTURA"]) == k:
                return f
        d = _digitos(factura)
        mismos = [f for f in filas if f.get("FACTURA") and d and _digitos(f["FACTURA"]) == d]
        if len(mismos) == 1:
            return mismos[0]
        return None
    if monto is not None:   # sin folio: por monto y fecha cercana
        m = a_monto(monto)
        cand = [f for f in filas if f.get("MONTO") is not None and m is not None and abs(f["MONTO"] - m) <= 1
                and (not fecha or not f.get("FECHA DE DOCUMENTO") or abs((a_fecha(f["FECHA DE DOCUMENTO"]) - a_fecha(fecha)).days) <= 7)]
        if len(cand) == 1:
            return cand[0]
    return None


def combinar(filas, datos):
    """Aplica los datos de los documentos a las filas. Devuelve el número de celdas llenadas o anotadas."""
    cambios = 0
    def fila_de(factura, monto=None, fecha=None):
        f = _buscar(filas, factura, monto, fecha)
        if f is None and (factura or monto is not None):
            f = _fila_vacia()
            filas.append(f)
        return f
    orden = {"factura": 0, "solicitud": 1, "finiquito": 2}   # la factura manda en el folio y el monto; luego solicitud y finiquito
    for d in sorted(datos, key=lambda x: orden.get(x.get("tipo"), 3)):
        tipo = d.get("tipo")
        if tipo == "factura":
            f = fila_de(d.get("factura"), d.get("monto"), d.get("fecha"))
            if f is None:
                continue
            for col, k in (("FACTURA", "factura"), ("FECHA DE DOCUMENTO", "fecha"), ("MONTO", "monto"), ("CONCEPTO", "concepto"),
                           ("DESCRIPCION", "descripcion")):
                cambios += _poner(f, col, d.get(k))
        elif tipo in ("finiquito", "solicitud"):
            for x in d.get("facturas") or []:
                f = fila_de(x.get("factura"), x.get("monto"), x.get("fecha"))
                if f is None:
                    continue
                cambios += _poner(f, "FACTURA", x.get("factura"))
                cambios += _poner(f, "MONTO", x.get("monto"))
                cambios += _poner(f, "RECLAMACION", d.get("reclamacion"))
                if tipo == "solicitud":
                    cambios += _poner(f, "FECHA DE INGRESO", d.get("fecha"))
                else:
                    cambios += _poner(f, "FOLIO", d.get("folio"))
                    cambios += _poner(f, "FECHA DE FINIQUITO", d.get("fecha"))
                    cambios += _poner(f, "ESTATUS", estatus(x.get("estatus") or d.get("estatus")))
                    cambios += _poner(f, "MONTO PAGADO", x.get("pagado"))
    return cambios


def _orden(f):
    return (a_fecha(f.get("FECHA DE DOCUMENTO")) or date.max, clave_factura(f.get("FACTURA")))


def actualizar(carpeta_cliente, nombre, datos, escanear=True, hoy=None):
    """Arma o completa <carpeta_cliente>/RELACION DE GASTOS.xlsx. Devuelve {ruta, filas, cambios, respaldo}."""
    carpeta = Path(carpeta_cliente)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / NOMBRE_ARCHIVO
    nombre_previo, filas, nuestra, respaldo = "", [], True, None
    if ruta.exists():
        nombre_previo, filas, nuestra = leer(ruta)
    datos = (escanear_xml(carpeta) if escanear else []) + list(datos or [])
    previas = len(filas)
    cambios = combinar(filas, datos)
    if ruta.exists() and not cambios:
        return {"ruta": str(ruta), "filas": len(filas), "cambios": 0, "respaldo": None}
    if not filas:
        return {"ruta": None, "filas": 0, "cambios": 0, "respaldo": None}
    if ruta.exists() and not nuestra:   # relación hecha a mano por Lau: copia antes de reescribirla
        dest = carpeta / CARPETA_RESPALDO
        dest.mkdir(exist_ok=True)
        respaldo = dest / f"RELACION DE GASTOS (original {(hoy or datetime.now()):%Y%m%d-%H%M}).xlsx"
        if not respaldo.exists():
            shutil.copy2(ruta, respaldo)
    nuevas = sorted(filas[previas:], key=_orden)
    filas = filas[:previas] + nuevas
    escribir(ruta, nombre_previo or nombre, filas)
    return {"ruta": str(ruta), "filas": len(filas), "cambios": cambios, "respaldo": str(respaldo) if respaldo else None}
