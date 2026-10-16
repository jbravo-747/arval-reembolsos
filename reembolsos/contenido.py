"""Tipo de documento y fecha a partir del contenido (capa de texto, Office u OCR de Windows).

El texto se usa en memoria y se descarta: solo salen el tipo, la fecha y la señal que los decidió (una palabra clave,
nunca contenido clínico).
"""
import re
import unicodedata
from datetime import date

from .catalogo import normalizar

# (tipo, señales fuertes = 3 puntos, señales débiles = 1 punto). Gana el tipo con más puntos si llega a MINIMO.
REGLAS = [
    ("Factura PDF", ["FOLIO FISCAL", "COMPROBANTE FISCAL DIGITAL", "SELLO DIGITAL DEL CFDI", "USO DEL CFDI", "USO CFDI", "REGIMEN FISCAL",
                     "CADENA ORIGINAL", "UUID"], ["FACTURA", "SUBTOTAL", "IVA", "RFC EMISOR", "RFC RECEPTOR", "CFDI"]),
    ("Receta", ["RECETA MEDICA", "RECETA"], ["RX", "INDICACIONES", "TOMAR", "CADA 8 HORAS", "CADA 12 HORAS", "CADA 24 HORAS", "TABLETA",
                                             "CAPSULA", "VIA ORAL", "CEDULA PROFESIONAL", "DOSIS"]),
    ("Informe médico", ["INFORME MEDICO", "RESUMEN CLINICO", "HISTORIA CLINICA", "NOTA MEDICA", "NOTA DE EGRESO", "NOTA DE INGRESO",
                        "NOTA POSTOPERATORIA", "NOTA QUIRURGICA", "HOJA QUIRURGICA", "PADECIMIENTO ACTUAL", "EXPLORACION FISICA"],
     ["DIAGNOSTICO", "TRATAMIENTO", "ANTECEDENTES", "EVOLUCION", "PRONOSTICO"]),
    ("Estudio o resultado", ["VALORES DE REFERENCIA", "BIOMETRIA HEMATICA", "QUIMICA SANGUINEA", "EXAMEN GENERAL DE ORINA", "ULTRASONIDO",
                             "TOMOGRAFIA", "RESONANCIA MAGNETICA", "RADIOGRAFIA", "RAYOS X", "ELECTROCARDIOGRAMA", "ESTUDIO HISTOPATOLOGICO",
                             "LABORATORIO CLINICO"], ["RESULTADO", "RESULTADOS", "INTERPRETACION", "HALLAZGOS", "LABORATORIO", "ESTUDIO", "MUESTRA"]),
    ("Identificación", ["INSTITUTO NACIONAL ELECTORAL", "CREDENCIAL PARA VOTAR", "CLAVE DE ELECTOR", "PASAPORTE",
                        "CLAVE UNICA DE REGISTRO DE POBLACION"], ["CURP", "NACIONALIDAD"]),
    ("Formato de reclamación", ["AVISO DE ACCIDENTE", "AVISO DE ENFERMEDAD", "SOLICITUD DE REEMBOLSO", "FORMATO DE RECLAMACION",
                                "RECLAMACION DE GASTOS", "PROGRAMACION DE CIRUGIA", "PROGRAMACION DE SERVICIOS"],
     ["REEMBOLSO", "RECLAMACION", "NUMERO DE SINIESTRO", "ASEGURADO TITULAR", "FIRMA DEL ASEGURADO"]),
    ("Comprobante de pago", ["COMPROBANTE DE PAGO", "COMPROBANTE DE TRANSFERENCIA", "SPEI", "VOUCHER"],
     ["TRANSFERENCIA", "CLAVE DE RASTREO", "AUTORIZACION", "TARJETA", "PAGO"]),
    ("Operación de seguro (no reembolso)", ["CARATULA DE POLIZA", "ENDOSO", "FINIQUITO", "CONDICIONES GENERALES", "CARTA DE PAGO",
                                            "RENOVACION DE POLIZA", "DICTAMEN"], ["POLIZA", "PRIMA", "VIGENCIA", "SUMA ASEGURADA", "DEDUCIBLE"]),
]
MINIMO = 3
MESES = {"ENERO": 1, "ENE": 1, "FEBRERO": 2, "FEB": 2, "MARZO": 3, "MAR": 3, "ABRIL": 4, "ABR": 4, "MAYO": 5, "MAY": 5, "JUNIO": 6, "JUN": 6,
         "JULIO": 7, "JUL": 7, "AGOSTO": 8, "AGO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "SEPT": 9, "SEP": 9, "OCTUBRE": 10, "OCT": 10,
         "NOVIEMBRE": 11, "NOV": 11, "DICIEMBRE": 12, "DIC": 12}
_MESES_RE = "|".join(sorted(MESES, key=len, reverse=True))
_PAL = {}


def _patron(frase):
    if frase not in _PAL:
        _PAL[frase] = re.compile(r"\b" + re.escape(frase) + r"\b")
    return _PAL[frase]


def tipo_por_texto(texto):
    """(tipo, señal) según palabras clave; (None, "") si nada llega al mínimo."""
    t = normalizar(texto)
    mejor, puntos_mejor, senal = None, 0, ""
    for tipo, fuertes, debiles in REGLAS:
        hallados_f = [f for f in fuertes if _patron(f).search(t)]
        hallados_d = [d for d in debiles if _patron(d).search(t)]
        puntos = 3 * len(hallados_f) + len(hallados_d)
        if puntos > puntos_mejor:
            mejor, puntos_mejor, senal = tipo, puntos, (hallados_f or hallados_d)[0]
    return (mejor, senal) if puntos_mejor >= MINIMO else (None, "")


def _mayus(texto):
    """Mayúsculas sin acentos, conservando la puntuación de las fechas (/ - .)."""
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"[\s,]+", " ", s)


def _valida(a, m, d, hoy):
    try:
        f = date(a, m, d)
    except ValueError:
        return None
    return f if date(2010, 1, 1) <= f <= hoy else None


def fechas_en_texto(texto, hoy=None):
    """Lista ordenada de (posición, fecha): dd/mm/aaaa, aaaa-mm-dd, '15 de marzo de 2026', '15-MAR-2026', 'MAR 15 2026'."""
    hoy = hoy or date.today()
    t = _mayus(texto)
    salida = []
    for m in re.finditer(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b", t):
        a = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        f = _valida(a, int(m[2]), int(m[1]), hoy)
        if f:
            salida.append((m.start(), f))
    for m in re.finditer(r"\b(20\d{2})[-/](\d{2})[-/](\d{2})", t):
        f = _valida(int(m[1]), int(m[2]), int(m[3]), hoy)
        if f:
            salida.append((m.start(), f))
    for m in re.finditer(r"\b(\d{1,2})(?: DE |[ /.\-])(" + _MESES_RE + r")\.?(?: DEL? |[ /.\-])(\d{4})\b", t):
        f = _valida(int(m[3]), MESES[m[2]], int(m[1]), hoy)
        if f:
            salida.append((m.start(), f))
    for m in re.finditer(r"\b(" + _MESES_RE + r")\.? (\d{1,2}) (\d{4})\b", t):
        f = _valida(int(m[3]), MESES[m[1]], int(m[2]), hoy)
        if f:
            salida.append((m.start(), f))
    return sorted(salida)


def fecha_por_texto(texto, hoy=None):
    """Fecha del documento: la que sigue a 'FECHA' (sin ser de nacimiento); si no hay, la más reciente encontrada."""
    hoy = hoy or date.today()
    t = _mayus(texto)
    for m in re.finditer(r"\bFECHA\b", t):
        contexto = t[m.start(): m.end() + 30]
        if "NACIMIENTO" in contexto or re.search(r"\bNAC\b", contexto):
            continue
        cerca = fechas_en_texto(t[m.end(): m.end() + 45], hoy)
        if cerca:
            return cerca[0][1]
    todas = [f for _, f in fechas_en_texto(t, hoy)]
    return max(todas) if todas else None


def ocr(ruta, paginas_max=2, idioma="es-MX", dpi=200):
    """Texto por OCR de Windows (winocr) de las primeras páginas de un PDF o de una imagen. Vacío si no hay OCR."""
    try:
        import winocr
        from PIL import Image
    except ImportError:
        return ""
    ruta = str(ruta)
    if ruta.lower().endswith(".pdf"):
        import pymupdf
        doc = pymupdf.open(ruta)
        imagenes = []
        for pagina in list(doc)[:paginas_max]:
            px = pagina.get_pixmap(dpi=dpi)
            imagenes.append(Image.frombytes("RGB", (px.width, px.height), px.samples))
        doc.close()
    else:
        imagenes = [Image.open(ruta).convert("RGB")]
    return " ".join(winocr.recognize_pil_sync(im, idioma).get("text", "") for im in imagenes)
