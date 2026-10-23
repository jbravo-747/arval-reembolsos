"""Organización de los expedientes que Lau ya armó a mano, a partir de una copia local de la carpeta.

Estructura que se espera (la que Lau usa en SINIESTROS):  <Cartera>/<Cliente>/<Evento>/<subcarpetas...>/<archivo>
Los archivos sueltos en la carpeta del cliente quedan "sin evento".

Para cada archivo deduce cartera, cliente, evento, tipo de documento y fecha, y propone la ruta y el nombre estándar.
No mueve ni renombra nada: escribe un plan para que Lau lo revise y un resumen para el panel (solo metadatos).
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from . import clasificacion as cl
from . import contenido
from .catalogo import Catalogo, normalizar
from .expedientes import ETIQUETAS, REQUISITOS

TIPO_POR_PALABRA = [("receta", "Receta"), ("informe", "Informe médico"), ("estudio", "Estudio o resultado"), ("resultado", "Estudio o resultado"),
                    ("factura", "Factura PDF"), ("recibo", "Factura PDF"), ("ine", "Identificación"), ("curp", "Identificación"),
                    ("identificaci", "Identificación"), ("poliza", "Operación de seguro (no reembolso)"), ("endoso", "Operación de seguro (no reembolso)")]
TIPO_CORTO = {"CFDI factura": "CFDI", "CFDI recibo de honorarios": "CFDI-HON", "CFDI otro": "CFDI-OTRO", "Factura PDF": "FACTURA",
              "Receta": "RECETA", "Informe médico": "INFORME", "Estudio o resultado": "ESTUDIO", "Identificación": "ID",
              "Operación de seguro (no reembolso)": "SEGURO", "Formato de reclamación": "RECLAMACION",
              "Comprobante de pago": "PAGO", "Finiquito o dictamen": "FINIQUITO", "Otro": "DOC"}
ANALISIS_VERSION = 3   # sube cuando cambia cómo se analiza un archivo: la caché de otra versión se vuelve a calcular
EXT_DICOM = {".dcm"}
SIN_EVENTO = "_Sin evento"
CARPETA_DICOM = "Imagenes DICOM"


def tipo_por_nombre(texto):
    n = normalizar(texto)
    for palabra, tipo in TIPO_POR_PALABRA:
        if re.search(rf"\b{palabra.upper()}", n):
            return tipo
    return ""


def fecha_en_nombre(nombre):
    """AAAAMMDD, AAAA-MM-DD o DD-MM-AAAA en el nombre; None si no hay una fecha válida."""
    for patron, orden in ((r"(20\d{2})[-_. ]?(\d{2})[-_. ]?(\d{2})", "amd"), (r"(\d{2})[-_. ](\d{2})[-_. ](20\d{2})", "dma")):
        for m in re.finditer(patron, nombre):
            a, b, c = m.groups()
            anio, mes, dia = (a, b, c) if orden == "amd" else (c, b, a)
            try:
                return datetime(int(anio), int(mes), int(dia)).date()
            except ValueError:
                continue
    return None


def limpiar(texto, maximo=60):
    """Nombre seguro para OneDrive: sin caracteres prohibidos ni espacios repetidos."""
    t = re.sub(r'[\\/:*?"<>|#%]+', " ", str(texto or ""))
    return re.sub(r"\s+", " ", t).strip(" .")[:maximo].strip() or "SIN NOMBRE"


def etiqueta_evento(nombre_carpeta, fecha):
    """Carpeta de evento estándar: AAAA-MM_<nombre que Lau le dio> (si ya empieza con fecha, se respeta)."""
    limpio = limpiar(nombre_carpeta)
    if re.match(r"^20\d{2}-\d{2}", limpio) or not fecha:
        return limpio
    return f"{fecha:%Y-%m}_{limpio}"


def _sha1(ruta):
    h = hashlib.sha1()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def recorrer(raiz):
    """(partes relativas, Path) de cada archivo bajo raiz, en orden estable."""
    raiz = Path(raiz)
    return [(p.relative_to(raiz).parts, p) for p in sorted(raiz.rglob("*")) if p.is_file()]


def _cargar_cache(ruta):
    """Caché JSONL: una línea por archivo ya analizado (la última línea de cada ruta gana)."""
    cache = {}
    if ruta and Path(ruta).exists():
        for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(linea)
                cache[d["ruta"]] = d
            except (ValueError, KeyError):
                continue   # una línea cortada por una interrupción se descarta
    return cache


def _texto(p, ext, paginas_max, usar_ocr):
    """(texto, método) del archivo: capa de texto, Office o, si no hay, OCR de Windows."""
    texto, metodo = "", ""
    if ext == ".pdf":
        texto, metodo = cl.texto_pdf(p, paginas_max), "texto PDF"
    elif ext in cl.EXT_OFICINA:
        texto, metodo = cl.texto_markitdown(p), "texto (MarkItDown)"
    if not texto.strip() and usar_ocr and (ext == ".pdf" or ext in cl.EXT_IMAGEN):
        texto, metodo = contenido.ocr(p, min(paginas_max, 2)), "OCR"
    return texto, metodo if texto.strip() else ""


def _analizar_archivo(partes, p, catalogo, leer, paginas_max, usar_ocr=True):
    st = p.stat()
    cartera = partes[0] if len(partes) >= 3 else ""
    cliente = partes[1] if len(partes) >= 3 else ""
    evento = partes[2] if len(partes) >= 4 else ""
    subruta = "/".join(partes[3:-1]) if len(partes) >= 5 else ""
    ext = p.suffix.lower()
    info = {"ruta": "/".join(partes), "nombre": p.name, "cartera": cartera, "cliente": cliente, "evento": evento,
            "subcarpeta": subruta, "ext": ext, "tamano": st.st_size, "mtime": int(st.st_mtime), "dicom": ext in EXT_DICOM,
            "metodo": "", "senal_tipo": "", "cliente_contenido": None, "conflicto": False, "requiere_lectura": False, "sha1": None,
            "version": ANALISIS_VERSION}
    tipo, f_doc, f_contenido = None, None, None
    if info["dicom"]:
        info["metodo"], tipo = "imagen DICOM: no se lee", "Estudio o resultado"
    elif leer and ext == ".xml":
        nombre, rfc, total, fecha = cl.receptor_cfdi(p)
        info["metodo"] = "Receptor CFDI" if (nombre or rfc) else "XML sin CFDI"
        if nombre or rfc:
            tipo = "CFDI factura"
            info["datos"] = {"cfdi": cl.datos_cfdi(p)}
            c, como = catalogo.resolver(f"{nombre} {rfc}")
            if c and como == "exacta":
                info["cliente_contenido"] = c
        try:
            f_doc = datetime.fromisoformat(fecha[:10]).date() if fecha else None
        except ValueError:
            f_doc = None
    elif leer and ext not in cl.EXT_IGNORAR:
        try:
            texto, metodo = _texto(p, ext, paginas_max, usar_ocr)
        except Exception as e:  # noqa: BLE001  un archivo dañado no detiene el bloque
            texto, metodo = "", f"error al leer: {type(e).__name__}"
        if texto.strip():
            info["metodo"] = metodo
            tipo, info["senal_tipo"] = contenido.tipo_por_texto(texto)
            f_contenido = contenido.fecha_por_texto(texto)
            c, como = catalogo.resolver(texto)
            if c and como == "exacta":
                info["cliente_contenido"] = c
            info["datos"] = contenido.identificadores(texto)   # RFC, póliza, siniestro, aseguradora, personas, correos
        else:
            info["metodo"] = metodo or ("sin texto: requiere lectura del agente" if ext == ".pdf" or ext in cl.EXT_IMAGEN else "formato no leído")
            info["requiere_lectura"] = ext == ".pdf" or ext in cl.EXT_IMAGEN
        del texto   # el contenido no sale de esta función
    info["conflicto"] = bool(cliente and info["cliente_contenido"] and info["cliente_contenido"] != cliente)
    if not tipo:
        tipo = tipo_por_nombre(p.name) or tipo_por_nombre(subruta) or tipo_por_nombre(evento)
        info["senal_tipo"] = "nombre" if tipo else ""
    info["tipo"] = tipo or "Otro"
    f_nombre = fecha_en_nombre(p.name)
    fecha = f_doc or f_contenido or f_nombre or datetime.fromtimestamp(st.st_mtime).date()
    info["fecha"] = str(fecha)
    info["fecha_origen"] = "documento" if f_doc else "contenido" if f_contenido else "nombre" if f_nombre else "modificación"
    return info


def analizar(raiz, leer=True, paginas_max=3, cache=None, bitacora=None, progreso=None, usar_ocr=True):
    """Analiza la copia local y devuelve {"archivos": [...], "resumen": {...}, "expedientes": [...]}.

    Trabaja por bloques (un cliente a la vez). Con cache (ruta a un .jsonl) guarda cada archivo en cuanto lo analiza
    y en la siguiente corrida salta lo que ya está (misma ruta, tamaño y fecha): si se corta, se retoma donde quedó.
    bitacora (ruta a un .txt) recibe una línea con la hora por cada bloque terminado; progreso (ruta a un .json)
    se reescribe en cada bloque con los conteos que el panel muestra en "Avance de la organización"."""
    raiz = Path(raiz)
    entradas = recorrer(raiz)
    clientes_carpeta = sorted({partes[1] for partes, _ in entradas if len(partes) >= 3})
    catalogo = Catalogo([{"NombreCliente": c} for c in clientes_carpeta])
    previo = _cargar_cache(cache)
    fh = open(cache, "a", encoding="utf-8") if cache else None

    def anotar(texto):
        if bitacora:
            with open(bitacora, "a", encoding="utf-8") as b:
                b.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {texto}\n")

    bloques = defaultdict(list)
    for partes, p in entradas:
        bloques["/".join(partes[:2]) if len(partes) >= 3 else "(fuera de estructura)"].append((partes, p))
    anotar(f"inicio: {len(entradas)} archivos en {len(bloques)} bloques; {len(previo)} ya en caché")
    por_ruta = {}
    avance = {"estado": "corriendo", "inicio": datetime.now().isoformat(timespec="seconds"), "bloques_total": len(bloques),
              "bloques_hechos": 0, "archivos_total": len(entradas), "archivos_hechos": 0, "analizados_esta_corrida": 0,
              "desde_cache": 0, "errores_lectura": 0, "ultimo_bloque": "", "etapa": "leyendo archivos"}

    def publicar_avance(**cambios):
        if progreso:
            avance.update(cambios, hora=datetime.now().isoformat(timespec="seconds"))
            Path(progreso).write_text(json.dumps(avance, ensure_ascii=False, indent=1), encoding="utf-8")

    publicar_avance()
    try:
        for n, (bloque, lista) in enumerate(sorted(bloques.items()), 1):
            nuevos = 0
            for partes, p in lista:
                ruta = "/".join(partes)
                st = p.stat()
                c = previo.get(ruta)
                if c and c.get("tamano") == st.st_size and c.get("mtime") == int(st.st_mtime) and c.get("version") == ANALISIS_VERSION:
                    por_ruta[ruta] = c
                    avance["desde_cache"] += 1
                    continue
                info = _analizar_archivo(partes, p, catalogo, leer, paginas_max, usar_ocr)
                por_ruta[ruta] = info
                nuevos += 1
                avance["errores_lectura"] += info["metodo"].startswith("error al leer")
                if nuevos % 25 == 0:   # en clientes grandes, avisar también dentro del bloque
                    publicar_avance(ultimo_bloque=f"{bloque.split('/')[-1]} ({nuevos} de {len(lista)})")
                if fh:
                    fh.write(json.dumps(info, ensure_ascii=False) + "\n"); fh.flush()
            if nuevos:
                anotar(f"bloque {n}/{len(bloques)}: {len(lista)} archivos, {nuevos} analizados")
            avance["analizados_esta_corrida"] += nuevos
            publicar_avance(bloques_hechos=n, archivos_hechos=avance["archivos_hechos"] + len(lista), ultimo_bloque=bloque.split("/")[-1])

        # Duplicados: mismo tamaño y mismo contenido (la huella también queda en la caché)
        publicar_avance(etapa="buscando duplicados")
        por_tamano = defaultdict(list)
        for partes, p in entradas:
            por_tamano[por_ruta["/".join(partes)]["tamano"]].append((partes, p))
        for grupo in por_tamano.values():
            if len(grupo) < 2:
                continue
            for partes, p in grupo:
                info = por_ruta["/".join(partes)]
                if not info.get("sha1"):
                    info["sha1"] = _sha1(p)
                    if fh:
                        fh.write(json.dumps(info, ensure_ascii=False) + "\n"); fh.flush()
        anotar("análisis de archivos y duplicados terminado")
        publicar_avance(etapa="armando la propuesta")
    except BaseException as e:
        publicar_avance(estado="detenido", etapa=f"se detuvo: {type(e).__name__}")
        raise
    finally:
        if fh:
            fh.close()

    archivos, primero = [], {}
    for partes, _ in entradas:
        info = dict(por_ruta["/".join(partes)])
        info["tipo"] = contenido.tipo_vigente(info["tipo"], info.get("senal_tipo"))
        info["duplicado_de"] = None
        if info.get("sha1"):
            if info["sha1"] in primero:
                info["duplicado_de"] = primero[info["sha1"]]
            else:
                primero[info["sha1"]] = info["ruta"]
        archivos.append(info)

    _proponer(archivos)
    return {"archivos": archivos, "resumen": _resumir(archivos), "expedientes": _expedientes(archivos)}


def _proponer(archivos):
    """Ruta y nombre estándar: <Cartera>/<Cliente>/<AAAA-MM_Evento>/<AAAAMMDD>_<TIPO>_<nn>.<ext>"""
    fecha_evento = {}
    for a in archivos:
        k = (a["cartera"], a["cliente"], a["evento"])
        fecha_evento[k] = min(fecha_evento.get(k, a["fecha"]), a["fecha"])
    usados = Counter()
    for a in archivos:
        if not a["cliente"]:
            a["ruta_propuesta"] = None
            continue
        f_ev = datetime.fromisoformat(fecha_evento[(a["cartera"], a["cliente"], a["evento"])]).date()
        evento = etiqueta_evento(a["evento"], f_ev) if a["evento"] else SIN_EVENTO
        carpeta = f"{limpiar(a['cartera'])}/{limpiar(a['cliente'])}/{evento}"
        if a["dicom"]:
            a["ruta_propuesta"] = f"{carpeta}/{CARPETA_DICOM}/{a['subcarpeta'] + '/' if a['subcarpeta'] else ''}{a['nombre']}"
            continue
        base = f"{a['fecha'].replace('-', '')}_{TIPO_CORTO.get(a['tipo'], 'DOC')}"
        usados[(carpeta, base)] += 1
        a["ruta_propuesta"] = f"{carpeta}/{base}_{usados[(carpeta, base)]:02d}{a['ext']}"


def construir_semilla(analisis, raiz, destino, solo_carpetas=False):
    """Crea en destino la estructura estándar (Cartera/Cliente/Evento) y copia cada archivo con su nombre propuesto.
    Nunca toca la carpeta original. Los duplicados no se copian; lo que no tiene cliente va a _Por identificar.
    Se puede repetir: un archivo que ya existe con el mismo tamaño se salta. Devuelve los conteos."""
    import csv
    import shutil
    raiz, destino = Path(raiz).resolve(), Path(destino).resolve()
    if destino == raiz or raiz in destino.parents:
        raise ValueError("el destino no puede estar dentro de la carpeta original")
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "_Por identificar").mkdir(exist_ok=True)
    conteo = Counter()
    filas = []
    for a in analisis["archivos"]:
        if a["duplicado_de"]:
            filas.append([a["ruta"], "", "duplicado de " + a["duplicado_de"]]); conteo["duplicados omitidos"] += 1
            continue
        nueva = a["ruta_propuesta"] or f"_Por identificar/{limpiar(a['nombre'], 120)}"
        final = destino / nueva
        final.parent.mkdir(parents=True, exist_ok=True)
        if solo_carpetas:
            filas.append([a["ruta"], nueva, "solo carpeta"])
            continue
        if final.exists() and final.stat().st_size == a["tamano"]:
            filas.append([a["ruta"], nueva, "ya estaba"]); conteo["ya estaban"] += 1
            continue
        shutil.copy2(raiz / a["ruta"], final)
        filas.append([a["ruta"], nueva, "copiado"]); conteo["copiados" if a["ruta_propuesta"] else "a _Por identificar"] += 1
    with (destino / "_indice_semilla.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow(["RutaOriginal", "RutaNueva", "Resultado"]); w.writerows(filas)
    conteo["carpetas"] = sum(1 for p in destino.rglob("*") if p.is_dir())
    return dict(conteo)


def catalogo_semilla(analisis):
    """Filas para la hoja Clientes: una por cliente encontrado, con su cartera."""
    vistos = {}
    for a in analisis["archivos"]:
        if a["cliente"]:
            vistos.setdefault((a["cartera"], a["cliente"]), None)
    return [{"NombreCliente": re.sub(r"\s+", " ", c).strip(), "Cartera": k, "Correo": "", "RFC": "", "Alias": "", "Tipo": ""}
            for k, c in sorted(vistos)]


def _expedientes(archivos):
    grupos = defaultdict(list)
    for a in archivos:
        if a["cliente"] and not a["duplicado_de"]:
            grupos[(a["cartera"], a["cliente"], a["evento"] or SIN_EVENTO)].append(a)
    salida = []
    for (cartera, cliente, evento), docs in grupos.items():
        tipos = {d["tipo"] for d in docs}
        faltantes = [ETIQUETAS[k] for k, aceptados in REQUISITOS.items() if not tipos & set(aceptados)]
        fechas = sorted(d["fecha"] for d in docs)
        salida.append({"cartera": cartera, "cliente": cliente, "evento": evento, "documentos": len(docs),
                       "inicio": fechas[0], "ultimo": fechas[-1], "tipos": sorted(tipos), "faltantes": faltantes,
                       "dicom": sum(1 for d in docs if d["dicom"]), "por_leer": sum(1 for d in docs if d["requiere_lectura"]),
                       "conflictos": sum(1 for d in docs if d["conflicto"])})
    salida.sort(key=lambda e: (e["cartera"], e["cliente"], e["inicio"]))
    return salida


def _resumir(archivos):
    con_cliente = [a for a in archivos if a["cliente"]]
    clientes = {(a["cartera"], a["cliente"]) for a in con_cliente}
    eventos = {(a["cartera"], a["cliente"], a["evento"]) for a in con_cliente if a["evento"]}
    clientes_sin_evento = {(a["cartera"], a["cliente"]) for a in con_cliente if not a["evento"]}
    por_cartera = defaultdict(lambda: {"clientes": set(), "eventos": set(), "archivos": 0})
    for a in con_cliente:
        c = por_cartera[a["cartera"]]
        c["clientes"].add(a["cliente"])
        c["archivos"] += 1
        if a["evento"]:
            c["eventos"].add((a["cliente"], a["evento"]))
    return {
        "archivos": len(archivos), "mb": round(sum(a["tamano"] for a in archivos) / 1048576),
        "clientes": len(clientes), "eventos": len(eventos), "clientes_con_archivos_sueltos": len(clientes_sin_evento),
        "fuera_de_estructura": len(archivos) - len(con_cliente),
        "renombres_propuestos": sum(1 for a in archivos if a["ruta_propuesta"] and not a["dicom"]),
        "dicom": sum(1 for a in archivos if a["dicom"]), "requieren_lectura": sum(1 for a in archivos if a["requiere_lectura"]),
        "conflictos": sum(1 for a in archivos if a["conflicto"]), "duplicados": sum(1 for a in archivos if a["duplicado_de"]),
        "fecha_por": dict(Counter(a["fecha_origen"] for a in archivos)),
        "tipos": dict(Counter(a["tipo"] for a in archivos).most_common()),
        "extensiones": dict(Counter(a["ext"] or "(sin)" for a in archivos).most_common(8)),
        "carteras": [{"cartera": k, "clientes": len(v["clientes"]), "eventos": len(v["eventos"]), "archivos": v["archivos"]}
                     for k, v in sorted(por_cartera.items())],
    }
