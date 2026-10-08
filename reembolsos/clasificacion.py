"""Reglas de clasificación: escala de confianza, prioridad y estado; lectura previa de XML y PDF con texto.

La lectura de documentos escaneados e imágenes la hace el agente de Claude (ve el archivo con su herramienta
Read) y deja su decisión en trabajo/decisiones.json. Este módulo combina esa decisión con el análisis previo.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .catalogo import candidatos_en_texto

TIPOS_DOCUMENTO = ["CFDI factura", "CFDI recibo de honorarios", "CFDI otro", "Factura PDF", "Receta",
                   "Informe médico", "Estudio o resultado", "Identificación", "Operación de seguro (no reembolso)",
                   "Correo sin documentos", "Otro"]
CONFIANZAS = ["Alta", "Media", "Baja", "Ninguna"]
EXT_IMAGEN = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
EXT_IGNORAR = {".htm", ".html", ".ini", ".ics", ".vcf"}


def receptor_cfdi(ruta):
    """(nombre, rfc, total, fecha) del Receptor/Comprobante de un CFDI; vacíos si no es CFDI."""
    try:
        raiz = ET.parse(ruta).getroot()
    except ET.ParseError:
        return "", "", "", ""
    nombre = rfc = ""
    for el in raiz.iter():
        if el.tag.split("}")[-1] == "Receptor":
            nombre, rfc = el.get("Nombre", ""), el.get("Rfc", "").upper()
            break
    return nombre, rfc, raiz.get("Total", ""), raiz.get("Fecha", "")


def texto_pdf(ruta, paginas_max=3):
    """Capa de texto de un PDF (vacía si es escaneado o si PyMuPDF no está instalado)."""
    try:
        import pymupdf
    except ImportError:
        return ""
    try:
        doc = pymupdf.open(ruta)
        partes = [p.get_text() for p in list(doc)[:paginas_max]]
        doc.close()
        return " ".join(partes)
    except Exception:  # noqa: BLE001
        return ""


def preanalisis(ruta_local, catalogo, paginas_max=3):
    """Lo que se puede decidir sin ver el documento: por XML o por capa de texto."""
    ruta = Path(ruta_local)
    ext = ruta.suffix.lower()
    pre = {"metodo": "", "cliente": None, "confianza": None, "motivo": "", "candidatos": [], "rfc": "", "total": "",
           "fecha_doc": "", "texto_disponible": False, "ignorar": ext in EXT_IGNORAR}
    if pre["ignorar"]:
        pre["metodo"] = "ignorado por extensión"
        return pre
    texto = ""
    if ext == ".xml":
        nombre, rfc, total, fecha = receptor_cfdi(ruta)
        pre.update(rfc=rfc, total=total, fecha_doc=fecha, metodo="Receptor CFDI")
        texto = f"{nombre} {rfc}"
    elif ext == ".pdf":
        texto = texto_pdf(ruta, paginas_max)
        pre["metodo"] = "texto PDF" if texto.strip() else "escaneado: requiere lectura del agente"
    elif ext in EXT_IMAGEN:
        pre["metodo"] = "imagen: requiere lectura del agente"
    else:
        pre["metodo"] = "formato no leído"
    if texto.strip():
        pre["texto_disponible"] = True
        cliente, como = catalogo.resolver(texto)
        pre["cliente"], pre["confianza"] = cliente, ("Alta" if como == "exacta" else "Baja" if como == "parcial" else None)
        pre["motivo"] = como
        pre["candidatos"] = candidatos_en_texto(texto)
    return pre


def combinar(pre, decision):
    """Une el análisis previo con la decisión del agente y fija confianza, prioridad y estado.

    decision (del agente, puede ser None o parcial):
      cliente: nombre exacto del catálogo o null
      tipo_documento: uno de TIPOS_DOCUMENTO
      identificado_por: "nombre y RFC" | "nombre completo" | "nombre parcial" | "no identificado"
      candidato_cliente: nombre leído que no está en el catálogo (o null)
      rfc, total, fecha_doc, motivo
    """
    d = decision or {}
    cliente = pre.get("cliente") or d.get("cliente")
    tipo = d.get("tipo_documento") or ("CFDI factura" if pre.get("metodo") == "Receptor CFDI" and cliente else "Otro")
    if pre.get("confianza") == "Alta":
        confianza = "Alta"
    elif cliente and d.get("identificado_por") in ("nombre y RFC",):
        confianza = "Alta"
    elif cliente and (d.get("identificado_por") == "nombre completo" or pre.get("confianza") is None):
        confianza = "Media"
    elif cliente:
        confianza = "Baja"
    else:
        confianza = "Ninguna"
    candidatos = list(dict.fromkeys(([d["candidato_cliente"]] if d.get("candidato_cliente") else []) + pre.get("candidatos", [])))
    if tipo == "Operación de seguro (no reembolso)":
        prioridad, estado = 3, "No es reembolso"
    elif confianza == "Alta":
        prioridad, estado = 3, "Recibido"
    elif confianza == "Media":
        prioridad, estado = 2, "Revisar"
    elif confianza == "Baja":
        prioridad, estado = 1, "Revisar"
    elif candidatos:
        prioridad, estado = 1, "Cliente desconocido"
    else:
        prioridad, estado = 3, "Cliente desconocido"
    motivo = "; ".join(x for x in (pre.get("motivo"), d.get("motivo")) if x)
    return {"cliente": cliente, "tipo_documento": tipo, "confianza": confianza, "prioridad": prioridad,
            "estado": estado, "candidatos": candidatos, "rfc": d.get("rfc") or pre.get("rfc", ""),
            "total": d.get("total") or pre.get("total", ""), "fecha_doc": d.get("fecha_doc") or pre.get("fecha_doc", ""),
            "motivo": motivo, "metodo": pre.get("metodo", "")}


def observacion(resultado, origen="Claude"):
    partes = [f"Clasificado por {origen}: {resultado['metodo']}" if resultado.get("metodo") else f"Clasificado por {origen}"]
    if resultado.get("cliente"):
        partes.append(f"cliente por {resultado['confianza'].lower()} confianza")
    if resultado.get("candidatos"):
        partes.append("candidato: " + " | ".join(resultado["candidatos"][:2]))
    if resultado.get("motivo"):
        partes.append(resultado["motivo"])
    return "; ".join(partes)[:250]


def mes_de(nombre_guardado):
    m = re.match(r"(\d{4})(\d{2})\d{2}_", nombre_guardado or "")
    return f"{m.group(1)}-{m.group(2)}" if m else ""
