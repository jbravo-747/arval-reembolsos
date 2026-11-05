"""Puente local: lleva lo que Power Automate guarda en /Reembolsos a la estructura estándar de /Arval.

Trabaja sobre las dos carpetas sincronizadas con OneDrive en esta PC (no necesita credenciales de Graph):
  entrada  = /Reembolsos de soluciones@ (Power Automate: _Por identificar y Clientes/<cliente>/<aaaa-mm>, Control_Reembolsos.xlsx)
  destino  = /Arval de soluciones@ (<Cartera>/<Cliente>/<AAAA-MM_Evento>/<AAAAMMDD>_<TIPO>_<nn>.ext)

Para cada archivo nuevo: lee el contenido (texto u OCR), decide tipo, fecha y cliente, busca el evento abierto del cliente
(documentos a 10 días o menos) o abre uno nuevo, y lo COPIA con el nombre estándar. Nunca borra ni mueve el original.
Lo que no tiene cliente va a /Arval/_Por identificar y queda como pendiente en el panel. Reanudable: lo procesado queda
en un estado JSONL y no se repite.
"""
import json
import re
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from . import clasificacion as cl
from . import contenido
from .catalogo import Catalogo, normalizar
from .expedientes import VENTANA_DIAS
from .organizacion import TIPO_CORTO, _texto, fecha_en_nombre, limpiar, tipo_por_nombre

POR_IDENTIFICAR = "_Por identificar"
MIN_IMAGEN = 15 * 1024          # imágenes más chicas suelen ser firmas o logos del correo
IGNORAR_EXT = cl.EXT_IGNORAR | {".zip"}


def _fecha_recepcion(nombre):
    """Power Automate nombra AAAAMMDD_HHMM_<hash>_<original>: la fecha de llegada del correo."""
    m = re.match(r"(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})_", nombre)
    if not m:
        return None, ""
    try:
        return date(int(m[1]), int(m[2]), int(m[3])), f"{m[4]}:{m[5]}"
    except ValueError:
        return None, ""


def catalogo_destino(destino, extra=None):
    """Clientes y su cartera según las carpetas de /Arval (<Cartera>/<Cliente>), más filas extra [{NombreCliente, Cartera}]."""
    destino = Path(destino)
    filas = []
    for cartera in sorted(p for p in destino.iterdir() if p.is_dir() and not p.name.startswith("_")) if destino.exists() else []:
        for cliente in sorted(p for p in cartera.iterdir() if p.is_dir()):
            filas.append({"NombreCliente": cliente.name, "Cartera": cartera.name})
    vistos = {normalizar(f["NombreCliente"]) for f in filas}
    for f in extra or []:
        if normalizar(f.get("NombreCliente")) not in vistos:
            filas.append(f)
            vistos.add(normalizar(f.get("NombreCliente")))
    return Catalogo(filas)


TIPOS_REMITENTE_NO_CLIENTE = {"aseguradora", "escaner", "aviso", "ignorar"}
NO_REEMBOLSO = ("NOMINA", "RECIBOS DE NOMINA")   # remitentes internos cuyos documentos no son reembolsos


def remitentes_catalogo(ruta_xlsx):
    """{correo: {"nombre", "tipo"}} de tblClientes (solo lectura). Vacío si no se puede abrir."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(ruta_xlsx, read_only=False, data_only=True)
    except Exception:  # noqa: BLE001
        return {}
    for ws in wb.worksheets:
        for tabla in ws.tables.values():
            if tabla.name != "tblClientes":
                continue
            filas = list(ws[tabla.ref])
            enc = [str(c.value or "") for c in filas[0]]
            salida = {}
            for fila in filas[1:]:
                d = dict(zip(enc, (c.value for c in fila)))
                correo = str(d.get("Correo") or "").strip().lower()
                if correo:
                    salida[correo] = {"nombre": str(d.get("NombreCliente") or "").strip(), "tipo": str(d.get("Tipo") or "").strip().lower()}
            return salida
    return {}


def registro_excel(ruta_xlsx):
    """{NombreGuardado: {remitente, asunto, fecha, hora}} leído de tblRegistro (solo lectura). Vacío si no se puede abrir."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(ruta_xlsx, read_only=False, data_only=True)
    except Exception:  # noqa: BLE001  el Excel puede estar bloqueado mientras OneDrive sincroniza
        return {}
    for ws in wb.worksheets:
        for tabla in ws.tables.values():
            if tabla.name != "tblRegistro":
                continue
            filas = list(ws[tabla.ref])
            enc = [str(c.value or "") for c in filas[0]]
            salida = {}
            for fila in filas[1:]:
                d = dict(zip(enc, (c.value for c in fila)))
                if d.get("NombreGuardado"):
                    salida[str(d["NombreGuardado"])] = {"remitente": str(d.get("Remitente") or "").strip().lower(), "asunto": str(d.get("Asunto") or ""),
                                                        "cliente": str(d.get("Cliente") or ""),
                                                        "fecha": str(d.get("FechaRecepcion") or ""), "hora": str(d.get("HoraRecepcion") or "")}
            return salida
    return {}


def _fechas_evento(carpeta):
    """Fechas AAAAMMDD de los archivos estándar dentro de una carpeta de evento."""
    fechas = []
    for p in carpeta.rglob("*"):
        m = re.match(r"(20\d{2})(\d{2})(\d{2})_", p.name)
        if p.is_file() and m:
            try:
                fechas.append(date(int(m[1]), int(m[2]), int(m[3])))
            except ValueError:
                pass
    return fechas


def llegadas_por_evento(estado):
    """{ruta relativa del evento: [fechas de llegada]} de lo que el puente ya guardó (la fecha del correo, no la del documento)."""
    salida = {}
    for r in estado.values():
        if r.get("resultado") == "clasificado" and r.get("destino") and r.get("fecha_recepcion"):
            try:
                f = date.fromisoformat(str(r["fecha_recepcion"])[:10])
            except ValueError:
                continue
            salida.setdefault(Path(r["destino"]).parent.as_posix(), []).append(f)
    return salida


def _fechas_de(ev, destino, llegadas):
    """Fechas de movimiento de un evento: las llegadas registradas por el puente o, en expedientes históricos,
    las fechas de los documentos (AAAAMMDD del nombre estándar)."""
    rel = ev.relative_to(destino).as_posix() if destino else ""
    return list((llegadas or {}).get(rel, [])) or _fechas_evento(ev)


def carpeta_evento(carpeta_cliente, fecha, en_corrida=None, destino=None, llegadas=None):
    """Evento abierto del cliente (movimiento a VENTANA_DIAS o menos) o uno nuevo AAAA-MM_Expediente AAAAMMDD.
    en_corrida: {nombre de evento: [fechas]} ya asignados en esta corrida (aún no copiados en modo propone)."""
    fechas = {}
    if carpeta_cliente.exists():
        for ev in carpeta_cliente.iterdir():
            if ev.is_dir() and not ev.name.startswith("_"):
                fechas[ev.name] = _fechas_de(ev, destino, llegadas)
    for nombre, lista in (en_corrida or {}).items():
        fechas.setdefault(nombre, []).extend(lista)
    return elegir_evento(fechas, fecha)


def elegir_evento(fechas, fecha):
    """{nombre de evento: [fechas]} -> (evento con movimiento a VENTANA_DIAS o menos de fecha, False) o (uno nuevo
    AAAA-MM_Expediente AAAAMMDD, True). El evento es del expediente, haya o no reembolso. La usan el puente (carpetas locales) y la rutina en la nube (Graph)."""
    candidatos = []
    for nombre, lista in fechas.items():
        dist = min((abs((f - fecha).days) for f in lista), default=None)
        if dist is not None and dist <= VENTANA_DIAS:
            candidatos.append((dist, nombre))
    if candidatos:
        return min(candidatos)[1], False
    return f"{fecha:%Y-%m}_Expediente {fecha:%Y%m%d}", True


def _siguiente_nombre(carpeta, base, ext, reservados):
    n = 1
    while (carpeta / f"{base}_{n:02d}{ext}").exists() or (carpeta / f"{base}_{n:02d}{ext}") in reservados:
        n += 1
    reservados.add(carpeta / f"{base}_{n:02d}{ext}")
    return f"{base}_{n:02d}{ext}"


def expandir_zips(archivos, entrada, trabajo, registro):
    """[(Path, ruta relativa)] donde cada ZIP se cambia por sus archivos: se extraen (solo el nombre, nunca las rutas del
    ZIP) en trabajo/zips/<zip>/ con el prefijo de Power Automate del ZIP, para clasificarlos uno por uno. El remitente y
    el asunto del ZIP pasan a cada archivo. Un ZIP dañado queda como archivo normal (se ignora)."""
    import zipfile
    salida = []
    for p in archivos:
        rel = p.relative_to(entrada).as_posix()
        if p.suffix.lower() != ".zip":
            salida.append((p, rel))
            continue
        try:
            z = zipfile.ZipFile(p)
        except zipfile.BadZipFile:
            salida.append((p, rel))
            continue
        m = re.match(r"(20\d{6}_\d{4}_[0-9a-f]+_)", p.name)
        prefijo = m[1] if m else ""
        carpeta = Path(trabajo) / "zips" / p.stem
        usados = Counter()
        with z:
            for info in z.infolist():
                nombre = Path(info.filename.replace("\\", "/")).name
                if info.is_dir() or not nombre or nombre.startswith((".", "__MACOSX")) or "__MACOSX" in info.filename:
                    continue
                usados[nombre] += 1
                base = limpiar(nombre, 150) if usados[nombre] == 1 else f"{usados[nombre]}_{limpiar(nombre, 140)}"
                destino = carpeta / (prefijo + base)
                if not destino.exists():
                    carpeta.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(destino, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                if p.name in registro:
                    registro[destino.name] = registro[p.name]
                salida.append((destino, f"{rel}/{base}"))
    return salida


def _cargar_estado(ruta):
    estado = {}
    if Path(ruta).exists():
        for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(linea)
                estado[d["origen"]] = d
            except (ValueError, KeyError):
                continue
    return estado


def correr(entrada, destino, trabajo, modo="propone", usar_ocr=True, extra_catalogo=None, confirmaciones=None, hoy=None):
    """Procesa lo nuevo de entrada. Devuelve el resumen de la corrida (también queda en trabajo/puente_panel.json)."""
    entrada, destino, trabajo = Path(entrada), Path(destino), Path(trabajo)
    trabajo.mkdir(parents=True, exist_ok=True)
    estado_ruta = trabajo / "puente_estado.jsonl"
    estado = _cargar_estado(estado_ruta)
    catalogo = catalogo_destino(destino, extra_catalogo)
    cartera_de = {c.nombre: c.cartera for c in catalogo.clientes}
    registro = registro_excel(entrada / "Control_Reembolsos.xlsx")
    remitentes = remitentes_catalogo(entrada / "Control_Reembolsos.xlsx")
    for meta in registro.values():   # el remitente que después se dio de alta con nombre identifica también sus correos anteriores
        if meta.get("cliente") and meta.get("remitente") and not (remitentes.get(meta["remitente"]) or {}).get("nombre"):
            remitentes[meta["remitente"]] = {"nombre": meta["cliente"], "tipo": ""}
    confirmadas = {c["archivo"]: c["cliente"] for c in (confirmaciones or []) if c.get("archivo") and c.get("cliente")}
    hoy = hoy or date.today()

    archivos = []
    for sub in (POR_IDENTIFICAR, "Clientes"):
        base = entrada / sub
        if base.exists():
            archivos += sorted(p for p in base.rglob("*") if p.is_file())
    archivos = expandir_zips(archivos, entrada, trabajo, registro)
    conteo, resultados = Counter(), []
    corrida = {"reservados": set(), "eventos": {}, "llegadas": llegadas_por_evento(estado)}   # lo asignado en esta corrida
    with estado_ruta.open("a", encoding="utf-8") as fh:
        for p, rel in archivos:
            st = p.stat()
            previo = estado.get(rel)
            confirmado = confirmadas.get(p.name)
            hecho = previo and previo.get("tamano") == st.st_size and previo.get("modo") in (modo, "aplica")
            if hecho and not (confirmado and previo.get("resultado") == "por identificar"):
                conteo["ya procesados"] += 1
                continue
            r = _procesar(p, rel, st, entrada, destino, catalogo, cartera_de, registro, confirmado, modo, usar_ocr, hoy, corrida, remitentes)
            r["modo"] = modo
            conteo[r["resultado"]] += 1
            resultados.append(r)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n"); fh.flush()
    panel = _panel(resultados, conteo, modo)
    (trabajo / "puente_panel.json").write_text(json.dumps(panel, ensure_ascii=False, indent=1), encoding="utf-8")
    with (trabajo / "puente_bitacora.txt").open("a", encoding="utf-8") as b:
        b.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | modo {modo} | " + ", ".join(f"{k}: {v}" for k, v in conteo.items()) + "\n")
    return panel


def _procesar(p, rel, st, entrada, destino, catalogo, cartera_de, registro, confirmado, modo, usar_ocr, hoy, corrida, remitentes=None):
    ext = p.suffix.lower()
    meta = registro.get(p.name, {})
    f_rec, hora = _fecha_recepcion(p.name)
    r = {"origen": rel, "nombre": p.name, "tamano": st.st_size, "remitente": meta.get("remitente", ""), "asunto": meta.get("asunto", ""),
         "fecha_recepcion": str(f_rec or meta.get("fecha") or ""), "hora": hora or meta.get("hora", ""), "hora_proceso": datetime.now().isoformat(timespec="seconds")}
    if ext in IGNORAR_EXT or (ext in cl.EXT_IMAGEN and st.st_size < MIN_IMAGEN):
        return {**r, "resultado": "ignorado", "motivo": "firma, logo o formato sin documento"}
    rem = (remitentes or {}).get(r["remitente"]) or {}
    partes0 = Path(rel).parts
    carpeta_pa = partes0[1] if partes0[0] == "Clientes" and len(partes0) >= 3 else ""
    if any(x in normalizar(rem.get("nombre") or carpeta_pa) for x in NO_REEMBOLSO):
        return {**r, "resultado": "ignorado", "motivo": "remitente interno: no es reembolso"}
    # Cliente: confirmado por Lau en el panel > carpeta donde lo dejó Power Automate (remitente conocido) > contenido
    partes = Path(rel).parts
    cliente_pa = partes[1] if partes[0] == "Clientes" and len(partes) >= 3 else None
    texto, metodo = "", ""
    try:
        if ext == ".xml":
            nombre, rfc, _total, fecha = cl.receptor_cfdi(p)
            texto, metodo = f"{nombre} {rfc} FECHA {fecha[:10]}", "Receptor CFDI"
        else:
            texto, metodo = _texto(p, ext, 3, usar_ocr)
    except Exception as e:  # noqa: BLE001
        metodo = f"error al leer: {type(e).__name__}"
    tipo, senal = ("CFDI factura", "Receptor CFDI") if metodo == "Receptor CFDI" else contenido.tipo_por_texto(texto)
    tipo = tipo or tipo_por_nombre(p.name) or "Otro"
    f_doc = contenido.fecha_por_texto(texto, hoy) if texto else None
    c_texto, como = catalogo.resolver(texto) if texto.strip() else (None, "sin texto")
    candidatos = cl.candidatos_en_texto(texto) if texto.strip() else []
    del texto   # el contenido no sale de esta función
    cliente, por = None, ""
    nombre_rem = rem.get("nombre") if rem.get("tipo") not in TIPOS_REMITENTE_NO_CLIENTE else ""
    if confirmado:
        cliente, por = confirmado, "confirmado en el panel"
    elif nombre_rem:
        c, _ = catalogo.resolver(nombre_rem)
        cliente, por = (c or nombre_rem.upper()), "remitente del catálogo"
    elif cliente_pa:
        c, _ = catalogo.resolver(cliente_pa)
        cliente, por = (c or cliente_pa), "remitente (Power Automate)"
    elif c_texto and como == "exacta":
        cliente, por = c_texto, "nombre en el documento"
    fecha_nombre = f_doc or fecha_en_nombre(p.name[14:]) or f_rec or hoy
    r.update(tipo=tipo, senal_tipo=senal, metodo=metodo, fecha_doc=str(f_doc or ""), cliente=cliente, cliente_por=por,
             candidatos=[] if cliente else candidatos[:3], motivo=como if not cliente else por)   # candidatos solo si falta cliente
    if not cliente:
        destino_rel = f"{POR_IDENTIFICAR}/{limpiar(p.name, 150)}"
        r.update(resultado="por identificar", destino=destino_rel, prioridad=1 if candidatos or c_texto else 3)
    else:
        cartera = cartera_de.get(cliente) or "_Sin cartera"
        carpeta_cliente = destino / limpiar(cartera) / limpiar(cliente)
        f_evento = f_rec or fecha_nombre
        en_corrida = corrida["eventos"].setdefault(carpeta_cliente, {})
        evento, nuevo = carpeta_evento(carpeta_cliente, f_evento, en_corrida, destino, corrida["llegadas"])
        en_corrida.setdefault(evento, []).append(f_evento)
        carpeta = carpeta_cliente / evento
        nombre = _siguiente_nombre(carpeta, f"{fecha_nombre:%Y%m%d}_{TIPO_CORTO.get(tipo, 'DOC')}", ext, corrida["reservados"])
        destino_rel = (carpeta / nombre).relative_to(destino).as_posix()
        r.update(resultado="clasificado", destino=destino_rel, cartera=cartera, evento=evento, evento_nuevo=nuevo, prioridad=3 if por != "nombre en el documento" else 2)
    if modo == "aplica":
        final = destino / destino_rel
        final.parent.mkdir(parents=True, exist_ok=True)
        if not final.exists():
            shutil.copy2(p, final)
    return r


TIPO_DE_CORTO = {v: k for k, v in TIPO_CORTO.items()}


def expedientes_destino(destino, hoy=None, llegadas=None):
    """Expedientes según las carpetas de /Arval: por evento, tipos presentes (por el nombre estándar) y faltantes."""
    from .expedientes import ETIQUETAS, REQUISITOS, TIPOS_REEMBOLSO
    destino, hoy = Path(destino), hoy or date.today()
    salida = []
    if not destino.exists():
        return salida
    for cartera in (p for p in destino.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for cliente in (p for p in cartera.iterdir() if p.is_dir()):
            for ev in (p for p in cliente.iterdir() if p.is_dir()):
                tipos = set()
                for f in ev.rglob("*"):
                    m = re.match(r"20\d{6}_([A-Z\-]+)_\d+", f.name)
                    if f.is_file() and m:
                        tipos.add(TIPO_DE_CORTO.get(m[1], "Otro"))
                fechas = _fechas_de(ev, destino, llegadas)
                if not fechas:
                    continue
                # Sin documentos de reembolso el expediente no tiene faltantes: se construye en paralelo al reembolso
                faltantes = [ETIQUETAS[k] for k, aceptados in REQUISITOS.items() if not tipos & set(aceptados)] if tipos & TIPOS_REEMBOLSO else []
                salida.append({"cartera": cartera.name, "cliente": cliente.name, "evento": ev.name, "tipos": sorted(tipos),
                               "faltantes": faltantes, "estado": "incompleto" if faltantes else "completo" if tipos & TIPOS_REEMBOLSO else "sin reembolso",
                               "ultimo": str(max(fechas)), "dias_sin_movimiento": (hoy - max(fechas)).days})
    return sorted(salida, key=lambda e: (e["estado"] != "incompleto", -e["dias_sin_movimiento"]))


def resumen_dia(trabajo, destino, dia=None):
    """Qué hizo el puente en el día y qué hay que atender (documento resumen/ultimo del panel, sin narrativa)."""
    dia = dia or date.today()
    estado = _cargar_estado(Path(trabajo) / "puente_estado.jsonl")
    del_dia = [r for r in estado.values() if str(r.get("hora_proceso", "")).startswith(str(dia)) and r.get("resultado") != "ignorado"]
    clasificados = [r for r in del_dia if r["resultado"] == "clasificado"]
    sin_cliente = [r for r in estado.values() if r.get("resultado") == "por identificar"]
    abiertos = [e for e in expedientes_destino(destino, dia, llegadas_por_evento(estado)) if e["estado"] == "incompleto"]
    conteos = {"Documentos clasificados hoy": len(clasificados), "Eventos nuevos hoy": sum(1 for r in clasificados if r.get("evento_nuevo")),
               "Sin cliente (por identificar)": len(sin_cliente), "Expedientes con faltantes": len(abiertos)}
    asunto = (f"Reembolsos {dia:%d/%m/%Y}: {len(clasificados)} clasificados, {len(sin_cliente)} sin cliente, "
              f"{len(abiertos)} expedientes con faltantes")
    return {"hora": datetime.now().astimezone().isoformat(timespec="seconds"), "fecha": f"{dia:%d/%m/%Y}", "asunto": asunto, "narrativa": "",
            "enviado": False, "conteos": conteos,
            "hecho": [{"cliente": r.get("cliente"), "tipo": r.get("tipo"), "evento": r.get("evento"), "nuevo": bool(r.get("evento_nuevo"))} for r in clasificados][:60],
            "por_identificar": [{"archivo": r["nombre"], "remitente": r.get("remitente", ""), "candidatos": r.get("candidatos", [])} for r in sin_cliente][:60],
            "expedientes_abiertos": abiertos[:30]}


def _panel(resultados, conteo, modo):
    """Documentos para el panel: pendientes (lo que Lau debe ver) y eventos de bitácora. Solo metadatos."""
    hora = datetime.now().astimezone().isoformat(timespec="seconds")
    utiles = [r for r in resultados if r["resultado"] != "ignorado"]
    pendientes = [{"id": r["nombre"], "cliente": r.get("cliente"), "tipo": r.get("tipo"), "prioridad": r.get("prioridad", 3),
                   "confianza": {"confirmado en el panel": "Alta", "remitente del catálogo": "Alta", "remitente (Power Automate)": "Alta", "nombre en el documento": "Media"}.get(r.get("cliente_por"), "Ninguna"),
                   "estado": "Recibido" if r["resultado"] == "clasificado" else "Cliente desconocido", "candidatos": r.get("candidatos", []),
                   "motivo": r.get("motivo", ""), "alertas": [], "remitente": r["remitente"], "asunto": r["asunto"],
                   "fecha": r["fecha_recepcion"], "hora": r["hora"], "destino": r.get("destino", "")} for r in utiles]
    bitacora = [{"hora": hora, "rutina": "puente", "evento": "corrida", "detalle": f"modo {modo}: " + ", ".join(f"{k} {v}" for k, v in conteo.items())}]
    for r in utiles[:50]:
        bitacora.append({"hora": hora, "rutina": "puente", "evento": ("movido" if modo == "aplica" else "propuesto") if r["resultado"] == "clasificado" else "prioridad 1",
                         "detalle": f"{r['nombre'][:60]} → {r.get('destino', '')[:90]}"})
    return {"hora": hora, "modo": modo, "conteo": dict(conteo), "pendientes": pendientes, "bitacora": bitacora,
            "latido": {"rutina": "puente", "hora": hora, "resultado": "ok", "detalle": ", ".join(f"{k} {v}" for k, v in conteo.items()),
                       "kpis": {"analizados": len(utiles), "movidos": sum(1 for r in utiles if r["resultado"] == "clasificado") if modo == "aplica" else 0}}}
