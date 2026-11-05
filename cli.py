"""Herramienta de línea de comandos de las rutinas de reembolsos.

  python cli.py selftest                 comprueba credenciales, OneDrive y el Excel (criterio de salida de F0)
  python cli.py pull [--todos]           descarga los documentos pendientes y arma trabajo/trabajo.json
  python cli.py apply [--modo propone|aplica]
                                         combina trabajo/decisiones.json con el análisis previo, aplica las
                                         confirmaciones y altas de Lau (trabajo/confirmaciones.json, trabajo/altas.json);
                                         en modo aplica mueve archivos, actualiza el Excel y el catálogo;
                                         siempre escribe trabajo/panel_snapshot.json
  python cli.py resumen --preparar       arma trabajo/resumen_datos.json para que el agente escriba la narrativa
  python cli.py resumen [--modo ...]     arma el resumen (con trabajo/narrativa.txt si existe); en modo aplica lo envía
  python cli.py borradores [--modo ...]  deja en el buzón borradores pidiendo documentos faltantes (modo aplica)
  python cli.py organizar --local <carpeta>
                                         analiza la copia local de los expedientes de Lau y propone la estructura estándar
  python cli.py semilla --local <carpeta> --destino <carpeta nueva> [--solo-carpetas]
                                         arma la estructura estándar con copias renombradas, lista para sincronizar a OneDrive
  python cli.py puente --entrada <Reembolsos> --destino <Arval> [--modo aplica]
                                         lleva lo nuevo que dejó Power Automate a la estructura estándar de /Arval
  python cli.py asegurados               base de asegurados y expedientes (Excel) a partir del análisis de organizar
  python cli.py cargar-asegurados [--excel X] [--semilla-sin-revisar]
                                         catálogo (hoja Clientes con Cartera y RFC) y buscador del panel desde la base revisada
  python cli.py latido <rutina> <resultado> [detalle]
  python cli.py decisiones-locales       (respaldo) OCR de Windows en lugar del agente; solo en un equipo Windows

El modo viene de --modo o de la variable MODO (por defecto "propone": no escribe nada en Microsoft 365).
"""
import argparse
import json
import os
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from reembolsos import clasificacion as cl
from reembolsos import expedientes as ex
from reembolsos.catalogo import Catalogo, normalizar
from reembolsos.config import cargar
from reembolsos.graph import Graph, GraphError
from reembolsos.resumen import correo as armar_correo

MEXICO = timezone(timedelta(hours=-6))


def ahora():
    return datetime.now(MEXICO)


def _leer_json(ruta, defecto):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8") or "null") or defecto
    except FileNotFoundError:
        return defecto


def _escribir_json(ruta, datos):
    Path(ruta).write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def _control(g, cfg):
    return g.item_por_ruta(f"{cfg.ruta_base}/{cfg.archivo_control}")["id"]


def _registros(g, archivo_id):
    enc, filas = g.tabla_filas(archivo_id, "tblRegistro")
    return enc, filas, [dict(zip(enc, f["values"]), _index=f["index"]) for f in filas]


# ---------- selftest ----------
def selftest(cfg):
    g = Graph(cfg)
    print("token: ok")
    print("drive:", g.drive)
    print("carpeta base:", [c["name"] for c in g.listar(cfg.ruta_base)])
    archivo_id = _control(g, cfg)
    enc, filas, _ = _registros(g, archivo_id)
    print(f"tblRegistro: {len(filas)} filas; columnas: {enc}")
    faltan = [c for c in ("Confianza", "Prioridad", "Enlace") if c not in enc]
    print("columnas que faltan en tblRegistro:", faltan or "ninguna")
    enc_c, _ = g.tabla_filas(archivo_id, "tblClientes")
    print("tblClientes columnas:", enc_c, "| faltan:", [c for c in ("Tipo", "Alias", "RFC") if c not in enc_c] or "ninguna")
    try:
        g.tabla_filas(archivo_id, "tblMonitor")
        print("tblMonitor: ok")
    except GraphError:
        print("tblMonitor: no existe (crear hoja Monitor con tabla tblMonitor: Rutina, Fecha, Hora, Resultado, Detalle)")
    print("modo:", cfg.modo)


# ---------- pull ----------
def pull(cfg, todos=False):
    g = Graph(cfg)
    archivo_id = _control(g, cfg)
    catalogo = Catalogo(g.tabla_como_dicts(archivo_id, "tblClientes"))
    enc, filas, registros = _registros(g, archivo_id)
    pendientes = [r for r in registros if r.get("NombreGuardado") and (
        r.get("Estado") == "Cliente desconocido" or (todos and r.get("Estado") == "Revisar"))]
    carpeta = cfg.trabajo / "archivos"
    carpeta.mkdir(parents=True, exist_ok=True)
    existentes = {i["name"]: i for i in g.listar(cfg.por_identificar)}
    items = []
    for r in pendientes:
        nombre = r["NombreGuardado"]
        item = existentes.get(nombre)
        if not item:
            continue  # ya no está en _Por identificar (lo movieron a mano)
        if catalogo.remitente_ignorado(r.get("Remitente")):
            items.append(_item(r, item, None, {"metodo": "remitente marcado como Aviso/Ignorar", "cliente": None, "confianza": None,
                                                 "motivo": "remitente ignorado", "candidatos": [], "rfc": "", "total": "",
                                                 "fecha_doc": "", "texto_disponible": True, "ignorar": True}, False))
            continue
        destino = carpeta / nombre
        if not destino.exists():
            g.descargar(item["id"], destino)
        pre = cl.preanalisis(destino, catalogo, cfg.paginas_max)
        requiere = not pre["texto_disponible"] and not pre["ignorar"] and pre["metodo"] != "formato no leído"
        items.append(_item(r, item, str(destino), pre, requiere))
    trabajo = {"generado": ahora().isoformat(timespec="seconds"), "modo": cfg.modo,
               "catalogo": [c.nombre for c in catalogo.clientes],
               "catalogo_detalle": [{"nombre": c.nombre, "rfc": c.rfc, "correo": c.correo} for c in catalogo.clientes],
               "tipos_documento": cl.TIPOS_DOCUMENTO, "items": items}
    _escribir_json(cfg.trabajo / "trabajo.json", trabajo)
    if not (cfg.trabajo / "decisiones.json").exists():
        _escribir_json(cfg.trabajo / "decisiones.json", {})
    n_leer = sum(1 for i in items if i["requiere_lectura"])
    print(f"pendientes: {len(items)} | con análisis previo: {len(items) - n_leer} | requieren lectura del agente: {n_leer}")
    print(f"archivo de trabajo: {cfg.trabajo / 'trabajo.json'}")


def _item(r, item, ruta_local, pre, requiere):
    return {"id": r.get("ID"), "index": r["_index"], "nombre_guardado": r["NombreGuardado"], "nombre_original": r.get("NombreOriginal"),
            "remitente": r.get("Remitente"), "asunto": r.get("Asunto"), "fecha": r.get("FechaRecepcion"), "hora": r.get("HoraRecepcion"),
            "item_id": item["id"], "ruta_local": ruta_local, "preanalisis": pre, "requiere_lectura": requiere}


# ---------- apply ----------
def apply(cfg):
    g = Graph(cfg)
    archivo_id = _control(g, cfg)
    trabajo = _leer_json(cfg.trabajo / "trabajo.json", None)
    if not trabajo:
        sys.exit("falta trabajo/trabajo.json: ejecuta pull primero")
    decisiones = _leer_json(cfg.trabajo / "decisiones.json", {})
    confirmaciones = _leer_json(cfg.trabajo / "confirmaciones.json", [])   # [{archivo, cliente}] confirmadas por Lau en el panel
    altas = _leer_json(cfg.trabajo / "altas.json", [])                     # [{nombre, correo, rfc, alias}] aprobadas por Lau
    # Los expedientes se construyen en Arval; sin la marca de destino no se escribe nada (ver reembolsos/destino.py)
    from reembolsos.destino import DestinoIncorrecto
    from reembolsos.destino_graph import ArvalGraph
    arval = ArvalGraph(g, cfg.ruta_arval)
    if cfg.modo == "aplica":
        try:
            arval.verificar()
        except DestinoIncorrecto as e:
            (cfg.trabajo / "errores.txt").write_text(str(e), encoding="utf-8")
            sys.exit(str(e))
    enc, filas, registros = _registros(g, archivo_id)
    por_index = {f["index"]: f["values"] for f in filas}
    catalogo = Catalogo(g.tabla_como_dicts(archivo_id, "tblClientes"))
    errores, nuevos = [], 0

    # 1) Altas al catálogo aprobadas por Lau (solo en modo aplica)
    if altas and cfg.modo == "aplica":
        enc_c, _ = g.tabla_filas(archivo_id, "tblClientes")
        existentes = {normalizar(c.nombre) for c in catalogo.todos}
        for a in altas:
            nombre = str(a.get("nombre") or "").strip().title() if a.get("nombre", "").isupper() else str(a.get("nombre") or "").strip()
            if not nombre or normalizar(nombre) in existentes:
                continue
            try:
                g.tabla_agregar_fila(archivo_id, "tblClientes", enc_c, {
                    "Correo": a.get("correo", ""), "NombreCliente": nombre, "Tipo": "", "Alias": a.get("alias", ""),
                    "RFC": str(a.get("rfc") or "").upper(), "Notas": f"Alta aprobada en el panel {ahora():%Y-%m-%d}"})
                existentes.add(normalizar(nombre)); nuevos += 1
            except GraphError as e:
                errores.append(f"alta {nombre}: {e}")
        if nuevos:
            catalogo = Catalogo(g.tabla_como_dicts(archivo_id, "tblClientes"))
    nombres = {c.nombre for c in catalogo.clientes}
    por_nombre = {c.nombre: c for c in catalogo.clientes}

    # 2) Confirmaciones de Lau tienen prioridad sobre lo que decidió el agente
    for c in confirmaciones:
        if c.get("archivo") and c.get("cliente") in nombres:
            decisiones[c["archivo"]] = {"cliente": c["cliente"], "identificado_por": "nombre y RFC",
                                        "tipo_documento": (decisiones.get(c["archivo"]) or {}).get("tipo_documento"),
                                        "motivo": "confirmado por Lau en el panel"}

    resultados, movidos = [], 0
    for it in trabajo["items"]:
        d = decisiones.get(it["nombre_guardado"]) or decisiones.get(str(it["id"])) or {}
        if d.get("cliente") and d["cliente"] not in nombres:
            d["candidato_cliente"], d["cliente"] = d["cliente"], None
        res = cl.combinar(it["preanalisis"], d)
        res["alertas"] = ex.alertas_documento(res, por_nombre.get(res["cliente"]), it["fecha"])
        res.update(nombre_guardado=it["nombre_guardado"], id=it["id"], remitente=it["remitente"], asunto=it["asunto"],
                   fecha=it["fecha"], hora=it["hora"], item_id=it["item_id"])
        resultados.append(res)
        if cfg.modo != "aplica":
            continue
        try:
            obs = cl.observacion(res)
            if res["alertas"]:
                obs = (obs + "; AVISO: " + "; ".join(res["alertas"]))[:250]
            cambios = {"Estado": res["estado"], "Observaciones": obs, "TipoDocumento": res["tipo_documento"]}
            if "Confianza" in enc:
                cambios["Confianza"] = res["confianza"]
            if "Prioridad" in enc:
                cambios["Prioridad"] = str(res["prioridad"])
            if res["total"] and "Total" in enc:
                cambios["Total"] = res["total"]
            if res["cliente"]:
                f_rec = _fecha_iso(it["fecha"]) or ahora().date()
                cartera = getattr(por_nombre.get(res["cliente"]), "cartera", "")
                carpeta, nombre, _ = arval.destino(res["cliente"], cartera, f_rec, _fecha_iso(res.get("fecha_doc")) or f_rec,
                                                   res["tipo_documento"], Path(it["nombre_guardado"]).suffix.lower())
                g.mover(it["item_id"], carpeta, nombre)
                res["ruta_arval"] = f"{carpeta}/{nombre}"
                cambios["Cliente"] = res["cliente"]
                cambios["Ruta"] = res["ruta_arval"]
                movidos += 1
            if it["index"] in por_index:
                g.tabla_actualizar_fila(archivo_id, "tblRegistro", it["index"], enc, cambios, por_index[it["index"]])
        except GraphError as e:
            errores.append(f"{it['nombre_guardado'][:40]}: {e}")

    # 3) Expedientes con el registro actualizado (en modo propone se simula con los resultados de esta corrida)
    registros_vista = _registros_con_resultados(registros, resultados) if cfg.modo != "aplica" else _registros(g, archivo_id)[2]
    expedientes = ex.agrupar(registros_vista, ahora().date())
    snapshot = _snapshot(cfg, resultados, movidos, errores, expedientes, nuevos, arval)
    _escribir_json(cfg.trabajo / "panel_snapshot.json", snapshot)
    if cfg.modo == "aplica":
        try:
            g.subir_pequeno(f"{cfg.ruta_base}/_OCR/panel_snapshot.json", json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
        except GraphError as e:
            errores.append(f"snapshot: {e}")
    if errores:
        (cfg.trabajo / "errores.txt").write_text("\n".join(errores), encoding="utf-8")
    print(f"modo {cfg.modo}: {len(resultados)} analizados, {movidos} movidos, {nuevos} altas al catálogo, "
          f"{sum(1 for r in resultados if r['prioridad'] == 1)} de prioridad 1, {len(errores)} errores")
    for e in errores:
        print("  ", e)
    print("panel_snapshot.json listo para publicar en la base de datos del panel")


def _registros_con_resultados(registros, resultados):
    por_nombre = {r["nombre_guardado"]: r for r in resultados}
    vista = []
    for r in registros:
        res = por_nombre.get(r.get("NombreGuardado"))
        if res:
            r = {**r, "Cliente": res["cliente"] or r.get("Cliente"), "TipoDocumento": res["tipo_documento"], "Estado": res["estado"],
                 "Total": res["total"] or r.get("Total")}
        vista.append(r)
    return vista


def _bitacora(cfg, resultados, movidos, errores, altas):
    """Eventos de esta corrida para la bitácora del panel (solo metadatos)."""
    hora = ahora().isoformat(timespec="seconds")
    eventos = [{"hora": hora, "rutina": "clasificador", "evento": "corrida",
                "detalle": f"{len(resultados)} analizados, {movidos} movidos, {altas} altas, {len(errores)} errores (modo {cfg.modo})"}]
    for r in resultados:
        if r["cliente"]:
            eventos.append({"hora": hora, "rutina": "clasificador", "evento": "movido" if cfg.modo == "aplica" else "propuesto",
                            "detalle": f"{r['nombre_guardado'][:60]} → {r['cliente']} ({r['tipo_documento']}, confianza {r['confianza'].lower()})"})
        elif r["prioridad"] == 1:
            eventos.append({"hora": hora, "rutina": "clasificador", "evento": "prioridad 1",
                            "detalle": f"{r['nombre_guardado'][:60]}: {r['motivo'] or 'sin cliente'}"})
    eventos += [{"hora": hora, "rutina": "clasificador", "evento": "error", "detalle": e[:160]} for e in errores]
    return eventos[:60]


def _fecha_iso(texto):
    try:
        return date.fromisoformat(str(texto or "")[:10])
    except ValueError:
        return None


def _snapshot(cfg, resultados, movidos, errores, expedientes, altas=0, arval=None):
    def url_cliente(cliente):   # carpeta del cliente en Arval si ya se conoce; si no, la raíz de Arval
        return cfg.url_carpeta((arval.ruta_conocida(cliente) if arval else None) or cfg.ruta_arval)

    por_prioridad = {1: 0, 2: 0, 3: 0}
    for r in resultados:
        por_prioridad[r["prioridad"]] += 1
    candidatos = {}
    for r in resultados:
        for c in r["candidatos"]:
            candidatos.setdefault(c, []).append(r["nombre_guardado"])
    return {
        "generado": ahora().isoformat(timespec="seconds"), "modo": cfg.modo,
        "kpis": {"analizados": len(resultados), "movidos": movidos, "errores": len(errores), "altas": altas,
                 "prioridad1": por_prioridad[1], "prioridad2": por_prioridad[2], "prioridad3": por_prioridad[3],
                 "expedientes_incompletos": sum(1 for e in expedientes if e["estado"] == "incompleto"),
                 "expedientes_completos": sum(1 for e in expedientes if e["estado"] == "completo")},
        "pendientes": [{"id": r["nombre_guardado"], "cliente": r["cliente"], "tipo": r["tipo_documento"], "confianza": r["confianza"],
                        "prioridad": r["prioridad"], "estado": r["estado"], "candidatos": r["candidatos"], "motivo": r["motivo"],
                        "alertas": r["alertas"], "remitente": r["remitente"], "asunto": r["asunto"], "fecha": r["fecha"], "hora": r["hora"],
                        "carpeta_url": cfg.url_carpeta(r["ruta_arval"].rsplit("/", 1)[0]) if r.get("ruta_arval")
                                       else url_cliente(r["cliente"]) if r["cliente"] else cfg.url_carpeta(cfg.por_identificar)}
                       for r in resultados],
        "candidatos": [{"nombre": c, "archivos": a} for c, a in candidatos.items()],
        "expedientes": [{**e, "carpeta_url": url_cliente(e["cliente"])} for e in expedientes],
        "bitacora": _bitacora(cfg, resultados, movidos, errores, altas),
        "latido": {"rutina": "clasificador", "hora": ahora().isoformat(timespec="seconds"),
                   "resultado": "error" if errores else "ok", "detalle": f"{len(resultados)} analizados, {movidos} movidos"},
    }


# ---------- resumen ----------
def resumen(cfg, preparar=False):
    g = Graph(cfg)
    archivo_id = _control(g, cfg)
    enc, filas, registros = _registros(g, archivo_id)
    expedientes = ex.agrupar(registros, ahora().date())
    fecha = ahora().strftime("%d/%m/%Y")
    cfg.trabajo.mkdir(parents=True, exist_ok=True)
    if preparar:
        from reembolsos.resumen import agrupar
        pendientes, grupos = agrupar(registros)
        datos = {"fecha": fecha, "conteos": {k: len(v) for k, v in grupos.items()},
                 "expedientes_abiertos": [{"cliente": e["cliente"], "estado": e["estado"], "faltantes": e["faltantes"],
                                           "dias_sin_movimiento": e["dias_sin_movimiento"]} for e in expedientes if e["estado"] != "completo"],
                 "prioridad1": [{"cliente": p.get("Cliente"), "tipo": p.get("TipoDocumento"), "motivo": p.get("Observaciones")}
                                for p in pendientes if str(p.get("Prioridad") or "")[:1] == "1"][:15]}
        _escribir_json(cfg.trabajo / "resumen_datos.json", datos)
        print("trabajo/resumen_datos.json listo; escribe trabajo/narrativa.txt (3 a 5 líneas) y vuelve a ejecutar resumen")
        return
    narrativa = (cfg.trabajo / "narrativa.txt").read_text(encoding="utf-8") if (cfg.trabajo / "narrativa.txt").exists() else ""
    asunto, html, pendientes = armar_correo(registros, fecha, narrativa, expedientes, os.environ.get("PANEL_URL", ""))
    (cfg.trabajo / "resumen.html").write_text(html, encoding="utf-8")
    from reembolsos.resumen import agrupar
    _, grupos = agrupar(registros)
    _escribir_json(cfg.trabajo / "resumen_panel.json", {
        "hora": ahora().isoformat(timespec="seconds"), "fecha": fecha, "asunto": asunto, "narrativa": narrativa.strip(),
        "enviado": cfg.modo == "aplica", "conteos": {k: len(v) for k, v in grupos.items()},
        "expedientes_abiertos": [{"cliente": e["cliente"], "estado": e["estado"], "faltantes": e["faltantes"],
                                  "dias_sin_movimiento": e["dias_sin_movimiento"]} for e in expedientes if e["estado"] != "completo"][:20]})
    print("asunto:", asunto, "| registros:", len(pendientes), "| trabajo/resumen_panel.json listo para el panel")
    if cfg.modo != "aplica":
        print("modo propone: el correo quedó en trabajo/resumen.html, no se envió")
        return
    g.enviar_correo(cfg.correo_lau, asunto, html)
    por_index = {f["index"]: f["values"] for f in filas}
    for r in pendientes:
        g.tabla_actualizar_fila(archivo_id, "tblRegistro", r["_index"], enc, {"EnResumen": "Sí"}, por_index[r["_index"]])
    print(f"enviado a {cfg.correo_lau}; {len(pendientes)} filas marcadas EnResumen = Sí")


# ---------- borradores ----------
def borradores(cfg, dias_min=2):
    """Para cada expediente incompleto sin movimiento en dias_min días, deja un borrador al cliente (si hay correo)."""
    g = Graph(cfg)
    archivo_id = _control(g, cfg)
    _, _, registros = _registros(g, archivo_id)
    catalogo = Catalogo(g.tabla_como_dicts(archivo_id, "tblClientes"))
    correos = {c.nombre: c.correo for c in catalogo.clientes if c.correo}
    carpeta = cfg.trabajo / "borradores"
    carpeta.mkdir(parents=True, exist_ok=True)
    hechos = 0
    for e in ex.agrupar(registros, ahora().date()):
        if e["estado"] != "incompleto" or e["dias_sin_movimiento"] < dias_min:
            continue
        html = ex.texto_solicitud_faltantes(e)
        asunto = "Reembolso: documentos faltantes"
        destino = correos.get(e["cliente"])
        (carpeta / f"{normalizar(e['cliente']).replace(' ', '_')}.html").write_text(html, encoding="utf-8")
        if cfg.modo == "aplica" and destino:
            g.crear_borrador(destino, asunto, html)
            hechos += 1
    print(f"borradores preparados en {carpeta}; {hechos} dejados en el buzón" + ("" if cfg.modo == "aplica" else " (modo propone: ninguno)"))


# ---------- entradas desde el panel (archivos que Lau suelta: WhatsApp, escáner, etc.) ----------
def ingresar(cfg):
    """Lee trabajo/entradas.json ([{id, nombre, ruta_local, cliente, por, hora}]) y mete cada archivo al circuito:
    lo sube a OneDrive con el nombre estándar y agrega su fila en tblRegistro. Si trae cliente, lo deja listo para
    que apply lo confirme (confirmaciones.json). Escribe trabajo/entradas_resultado.json con el resultado por entrada."""
    import hashlib
    entradas = _leer_json(cfg.trabajo / "entradas.json", [])
    if not entradas:
        print("sin entradas"); return
    g = Graph(cfg)
    archivo_id = _control(g, cfg)
    enc, _, _ = _registros(g, archivo_id)
    catalogo = Catalogo(g.tabla_como_dicts(archivo_id, "tblClientes"))
    nombres = {c.nombre for c in catalogo.clientes}
    confirmaciones = _leer_json(cfg.trabajo / "confirmaciones.json", [])
    resultados = []
    for e in entradas:
        ruta = Path(e.get("ruta_local") or "")
        if not ruta.exists():
            resultados.append({"id": e["id"], "estado": "error", "detalle": "archivo no descargado"}); continue
        t = ahora()
        hash6 = hashlib.sha1(ruta.read_bytes()).hexdigest()[:6]
        nombre_limpio = re.sub(r"[\\/:*?\"<>|]+", "_", e.get("nombre") or ruta.name).strip() or ruta.name
        guardado = f"{t:%Y%m%d_%H%M}_{hash6}_{nombre_limpio}"
        cliente = e.get("cliente") if e.get("cliente") in nombres else None
        fila = {"ID": str(uuid.uuid4()), "FechaRecepcion": t.strftime("%Y-%m-%d"), "HoraRecepcion": t.strftime("%H:%M"),
                "IdCorreo": f"panel:{e['id']}", "Remitente": f"panel:{e.get('por') or 'desconocido'}", "Cliente": "",
                "Asunto": e.get("asunto") or "Entrada manual desde el panel (WhatsApp u otro)", "NombreOriginal": nombre_limpio,
                "TamanoBytes": str(ruta.stat().st_size), "NombreGuardado": guardado, "Ruta": f"{cfg.por_identificar}/{guardado}",
                "TipoDocumento": "", "Duplicado": "No", "Estado": "Cliente desconocido", "EnResumen": "No",
                "Observaciones": "Entrada manual desde el panel" + (f"; cliente indicado por Lau: {cliente}" if cliente else "")}
        if cfg.modo != "aplica":
            resultados.append({"id": e["id"], "estado": "propuesto", "nombre_guardado": guardado, "cliente": cliente}); continue
        try:
            item = g.subir_archivo(f"{cfg.por_identificar}/{guardado}", ruta)
            try:
                fila["Enlace"] = g.enlace_lectura(item["id"])
            except GraphError:
                pass
            g.tabla_agregar_fila(archivo_id, "tblRegistro", enc, fila)
            if cliente:
                confirmaciones.append({"archivo": guardado, "cliente": cliente})
            resultados.append({"id": e["id"], "estado": "ingresado", "nombre_guardado": guardado, "cliente": cliente})
        except GraphError as ex:
            resultados.append({"id": e["id"], "estado": "error", "detalle": str(ex)[:200]})
    _escribir_json(cfg.trabajo / "confirmaciones.json", confirmaciones)
    _escribir_json(cfg.trabajo / "entradas_resultado.json", resultados)
    print(f"entradas: {len(entradas)} | ingresadas: {sum(1 for r in resultados if r['estado'] == 'ingresado')} | "
          f"propuestas: {sum(1 for r in resultados if r['estado'] == 'propuesto')} | errores: {sum(1 for r in resultados if r['estado'] == 'error')}")


# ---------- indexar expedientes hechos a mano ----------
def _tipo_por_nombre(nombre):
    from reembolsos.organizacion import tipo_por_nombre
    return tipo_por_nombre(nombre)


def indexar(cfg, ruta, usuario=None, max_mb=25):
    """Recorre una carpeta de expedientes hechos a mano (p. ej. el OneDrive de Lau), descubre clientes por el nombre de
    cada subcarpeta y documentos por su contenido, y escribe trabajo/indexacion.json y trabajo/catalogo_sugerido.csv.
    En modo aplica registra cada archivo en tblRegistro con estado 'Histórico' (no mueve ni renombra nada)."""
    import csv
    g = Graph(cfg)
    drive = g.drive_de(usuario) if usuario else None
    archivo_id = _control(g, cfg)
    catalogo = Catalogo(g.tabla_como_dicts(archivo_id, "tblClientes"))
    enc, _, registros = _registros(g, archivo_id)
    ya = {str(r.get("IdCorreo") or "") for r in registros}
    archivos = g.listar_recursivo(ruta, drive)
    base = ruta.rstrip("/")
    carpeta_local = cfg.trabajo / "historico"
    carpeta_local.mkdir(parents=True, exist_ok=True)
    por_carpeta, filas = {}, []
    for rel, it in archivos:
        resto = rel[len(base) + 1:]
        partes = resto.split("/")
        carpeta = partes[0] if len(partes) > 1 else ""
        nombre = it["name"]
        ext = Path(nombre).suffix.lower()
        cliente_carpeta, como = catalogo.resolver(carpeta) if carpeta else (None, "")
        pre = {"metodo": "sin analizar", "cliente": None, "rfc": "", "total": "", "fecha_doc": "", "texto_disponible": False, "candidatos": []}
        if ext not in cl.EXT_IMAGEN and ext not in cl.EXT_IGNORAR and it.get("size", 0) <= max_mb * 1024 * 1024:
            destino = carpeta_local / f"{it['id'][-8:]}_{nombre}"
            try:
                if not destino.exists():
                    g.descargar_de(drive or g.drive, it["id"], destino)
                pre = cl.preanalisis(destino, catalogo, cfg.paginas_max)
            except GraphError as e:
                pre["metodo"] = f"error: {str(e)[:60]}"
        elif ext in cl.EXT_IMAGEN:
            pre["metodo"] = "imagen: requiere lectura del agente"
        cliente = cliente_carpeta or pre.get("cliente")
        conflicto = bool(cliente_carpeta and pre.get("cliente") and cliente_carpeta != pre["cliente"])
        tipo = ("CFDI factura" if pre.get("metodo") == "Receptor CFDI" else _tipo_por_nombre(nombre)) or "Documento histórico"
        fila = {"ruta": rel, "nombre": nombre, "carpeta": carpeta, "subcarpeta": "/".join(partes[1:-1]), "tamano": it.get("size", 0),
                "fecha": str(it.get("createdDateTime") or "")[:10], "item_id": it["id"], "enlace": it.get("webUrl", ""),
                "cliente": cliente, "cliente_por": "carpeta" if cliente_carpeta else ("contenido" if pre.get("cliente") else ""),
                "confianza": "Alta" if cliente_carpeta and como == "exacta" else ("Media" if cliente else "Ninguna"),
                "conflicto": conflicto, "tipo": tipo, "metodo": pre.get("metodo"), "rfc": pre.get("rfc", ""), "total": pre.get("total", ""),
                "fecha_doc": pre.get("fecha_doc", ""), "candidatos": pre.get("candidatos", []),
                "requiere_lectura": ext in cl.EXT_IMAGEN or pre.get("metodo", "").startswith("escaneado"), "ya_indexado": f"historico:{it['id']}" in ya}
        filas.append(fila)
        c = por_carpeta.setdefault(carpeta, {"carpeta": carpeta, "cliente_catalogo": cliente_carpeta, "archivos": 0, "tipos": set(), "candidato": None})
        c["archivos"] += 1
        c["tipos"].add(tipo)
    sugeridos = []
    for c in por_carpeta.values():
        c["tipos"] = sorted(c["tipos"])
        if c["carpeta"] and not c["cliente_catalogo"]:
            c["candidato"] = re.sub(r"\s+", " ", c["carpeta"]).strip()
            sugeridos.append(c["candidato"])
    indexacion = {"generado": ahora().isoformat(timespec="seconds"), "ruta": ruta, "usuario": usuario or cfg.usuario, "modo": cfg.modo,
                  "resumen": {"archivos": len(filas), "carpetas": len(por_carpeta), "con_cliente": sum(1 for f in filas if f["cliente"]),
                              "conflictos": sum(1 for f in filas if f["conflicto"]), "requieren_lectura": sum(1 for f in filas if f["requiere_lectura"]),
                              "carpetas_sin_catalogo": len(sugeridos), "ya_indexados": sum(1 for f in filas if f["ya_indexado"])},
                  "carpetas": sorted(por_carpeta.values(), key=lambda c: c["carpeta"]), "archivos": filas}
    _escribir_json(cfg.trabajo / "indexacion.json", indexacion)
    with (cfg.trabajo / "catalogo_sugerido.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow(["NombreCliente", "Correo", "RFC", "Alias", "Tipo", "Origen"])
        for s in sugeridos:
            w.writerow([s, "", "", "", "", f"carpeta en {ruta}"])
    registradas = 0
    if cfg.modo == "aplica":
        for f in filas:
            if f["ya_indexado"] or not f["cliente"]:
                continue
            g.tabla_agregar_fila(archivo_id, "tblRegistro", enc, {
                "ID": str(uuid.uuid4()), "FechaRecepcion": f["fecha"], "HoraRecepcion": "00:00", "IdCorreo": f"historico:{f['item_id']}",
                "Remitente": f"historico:{usuario or cfg.usuario}", "Cliente": f["cliente"], "Asunto": f"Expediente manual: {f['carpeta']}",
                "NombreOriginal": f["nombre"], "TamanoBytes": str(f["tamano"]), "NombreGuardado": f["nombre"], "Ruta": f["ruta"],
                "TipoDocumento": f["tipo"], "RFC_Emisor": "", "Total": f["total"], "FechaCFDI": f["fecha_doc"], "Duplicado": "No",
                "Estado": "Histórico", "Confianza": f["confianza"], "Prioridad": "3", "EnResumen": "Sí", "Enlace": f["enlace"],
                "Observaciones": f"Indexado de expediente manual ({f['cliente_por']}); {f['metodo']}" + ("; AVISO: carpeta y contenido no coinciden" if f["conflicto"] else "")})
            registradas += 1
    r = indexacion["resumen"]
    print(f"archivos: {r['archivos']} en {r['carpetas']} carpetas | con cliente: {r['con_cliente']} | conflictos: {r['conflictos']} | "
          f"requieren lectura: {r['requieren_lectura']} | carpetas sin catálogo: {r['carpetas_sin_catalogo']} | registradas: {registradas} (modo {cfg.modo})")
    print(f"detalle: {cfg.trabajo / 'indexacion.json'} | catálogo sugerido: {cfg.trabajo / 'catalogo_sugerido.csv'}")


# ---------- organizar la copia local de los expedientes de Lau y construir la semilla ----------
def organizar(cfg, local, leer=True, usar_ocr=True):
    """Analiza la copia local (<Cartera>/<Cliente>/<Evento>/...) y propone la estructura estándar. No toca nada.
    Escribe trabajo/organizacion.json (detalle), organizacion_plan.csv (para que Lau revise), catalogo_semilla.csv
    y organizacion_resumen.json (lo que el panel muestra en "Lo que se hizo").
    Es reanudable: lo ya analizado queda en trabajo/organizacion_cache.jsonl y el avance en organizacion_bitacora.txt."""
    import csv
    from reembolsos import organizacion as org
    analisis = org.analizar(local, leer, cfg.paginas_max, cache=cfg.trabajo / "organizacion_cache.jsonl",
                            bitacora=cfg.trabajo / "organizacion_bitacora.txt", progreso=cfg.trabajo / "organizacion_progreso.json", usar_ocr=usar_ocr)
    _escribir_json(cfg.trabajo / "organizacion.json", {"generado": ahora().isoformat(timespec="seconds"), "raiz": str(local), **analisis})
    with (cfg.trabajo / "organizacion_plan.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["RutaActual", "RutaPropuesta", "Tipo", "Fecha", "FechaPor", "Metodo", "Conflicto", "DuplicadoDe"])
        for a in analisis["archivos"]:
            w.writerow([a["ruta"], a["ruta_propuesta"] or "", a["tipo"], a["fecha"], a["fecha_origen"], a["metodo"],
                        a["cliente_contenido"] if a["conflicto"] else "", a["duplicado_de"] or ""])
    with (cfg.trabajo / "catalogo_semilla.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        filas = org.catalogo_semilla(analisis)
        w = csv.DictWriter(fh, fieldnames=["NombreCliente", "Cartera", "Correo", "RFC", "Alias", "Tipo"]); w.writeheader(); w.writerows(filas)
    _escribir_json(cfg.trabajo / "organizacion_resumen.json", _resumen_organizacion(analisis, "propuesta"))
    progreso = _leer_json(cfg.trabajo / "organizacion_progreso.json", {})
    _escribir_json(cfg.trabajo / "organizacion_progreso.json", {**progreso, "estado": "terminado", "etapa": "propuesta lista",
                                                               "hora": ahora().isoformat(timespec="seconds")})
    r = analisis["resumen"]
    print(f"archivos: {r['archivos']} ({r['mb']} MB) | clientes: {r['clientes']} | eventos: {r['eventos']} | "
          f"renombres propuestos: {r['renombres_propuestos']} | DICOM: {r['dicom']} | por leer: {r['requieren_lectura']} | "
          f"conflictos: {r['conflictos']} | duplicados: {r['duplicados']}")
    print(f"plan para Lau: {cfg.trabajo / 'organizacion_plan.csv'} | resumen para el panel: {cfg.trabajo / 'organizacion_resumen.json'}")


def semilla(cfg, local, destino, solo_carpetas=False):
    """Construye en destino la estructura estándar con copias renombradas, usando el análisis de organizar."""
    from reembolsos import organizacion as org
    analisis = _leer_json(cfg.trabajo / "organizacion.json", None)
    if not analisis or Path(analisis["raiz"]).resolve() != Path(local).resolve():
        sys.exit("ejecuta primero: python cli.py organizar --local <misma carpeta>")
    conteo = org.construir_semilla(analisis, local, destino, solo_carpetas)
    resumen = _resumen_organizacion(analisis, "solo carpetas" if solo_carpetas else "semilla construida")
    resumen.update(destino=str(destino), semilla=conteo)
    _escribir_json(cfg.trabajo / "organizacion_resumen.json", resumen)
    print("semilla:", ", ".join(f"{k}: {v}" for k, v in conteo.items()), f"| índice: {Path(destino) / '_indice_semilla.csv'}")


def puente(cfg, entrada, destino, usar_ocr=True):
    """Lleva lo nuevo de /Reembolsos (Power Automate) a /Arval con la estructura estándar. Ver reembolsos/puente.py.
    Aplica las confirmaciones de Lau (trabajo/confirmaciones.json) y usa el catálogo semilla para conocer la cartera.
    Escribe trabajo/puente_panel.json (pendientes, bitácora, latido) y trabajo/puente_resumen.json (resumen del día)."""
    import csv
    from reembolsos import destino as dst, puente as pt
    if cfg.modo == "aplica":
        try:
            dst.exigir(destino)
        except dst.DestinoIncorrecto as e:
            sys.exit(str(e))
    extra = []
    if (cfg.trabajo / "catalogo_semilla.csv").exists():
        with (cfg.trabajo / "catalogo_semilla.csv").open(encoding="utf-8-sig") as fh:
            extra = list(csv.DictReader(fh))
    panel = pt.correr(entrada, destino, cfg.trabajo, cfg.modo, usar_ocr, extra, _leer_json(cfg.trabajo / "confirmaciones.json", []))
    _escribir_json(cfg.trabajo / "puente_resumen.json", pt.resumen_dia(cfg.trabajo, destino))
    print(f"puente (modo {cfg.modo}):", ", ".join(f"{k}: {v}" for k, v in panel["conteo"].items()) or "sin archivos")
    print(f"para el panel: {cfg.trabajo / 'puente_panel.json'} | resumen del día: {cfg.trabajo / 'puente_resumen.json'}")


def asegurados(cfg):
    """Base de asegurados y de expedientes a partir de trabajo/organizacion.json (correr organizar antes).
    Escribe trabajo/Base_Asegurados.xlsx (para revisión de Lau) y trabajo/asegurados_resumen.json (conteos para el panel)."""
    from reembolsos import asegurados as ag
    analisis = _leer_json(cfg.trabajo / "organizacion.json", None)
    if not analisis:
        sys.exit("falta trabajo/organizacion.json: ejecuta organizar primero")
    hojas = ag.construir(analisis["archivos"], analisis["expedientes"])
    from reembolsos import relaciones as rl
    filas = rl.leer_relaciones(analisis["raiz"])                                   # relaciones de reclamaciones de Lau
    indice = rl.indice_facturas(analisis["raiz"], analisis["archivos"], cfg.trabajo / "facturas_cache.jsonl")
    ag.agregar_reclamaciones(hojas, rl.corroborar(filas, indice))
    ag.a_excel(hojas, cfg.trabajo / "Base_Asegurados.xlsx")
    res = {"hora": ahora().isoformat(timespec="seconds"), **ag.resumen(hojas)}
    _escribir_json(cfg.trabajo / "asegurados_resumen.json", res)
    print("base de asegurados:", ", ".join(f"{k}: {v}" for k, v in res.items() if not isinstance(v, dict)))
    print(f"Excel para Lau: {cfg.trabajo / 'Base_Asegurados.xlsx'}")


def cargar_asegurados(cfg, excel, semilla=False):
    """Carga la base revisada por Lau (columna Aprobado = sí; con --semilla, todos marcados "sin revisar"):
    trabajo/Clientes_para_catalogo.xlsx (filas para la hoja Clientes con Cartera y RFC) y trabajo/buscador_lista.json
    (documento buscador/lista del panel). En modo aplica con credenciales de Graph agrega las
    filas nuevas a tblClientes (no repite nombres que ya están)."""
    import openpyxl
    from openpyxl.worksheet.table import Table
    from reembolsos import asegurados as ag
    excel = Path(excel)
    filas = ag.filas_catalogo(ag.leer_hoja(excel, "Asegurados"), ahora().strftime("%Y-%m-%d"), semilla)
    enc = ["Correo", "NombreCliente", "Notas", "Tipo", "Alias", "RFC", "Cartera"]
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Clientes"
    ws.append(enc)
    for f in filas:
        ws.append([f[k] for k in enc])
    ws.add_table(Table(displayName="tblClientesNuevos", ref=f"A1:G{max(len(filas), 1) + 1}"))
    wb.save(cfg.trabajo / "Clientes_para_catalogo.xlsx")
    docs = ag.buscador(excel, semilla)
    # El buscador del panel lee un solo documento buscador/lista: {"asegurados": [...]}
    _escribir_json(cfg.trabajo / "buscador_lista.json", {"asegurados": docs})
    print(f"catálogo: {len(filas)} filas en {cfg.trabajo / 'Clientes_para_catalogo.xlsx'} | buscador: {len(docs)} asegurados"
          + (" (semilla sin revisar)" if semilla else ""))
    if cfg.modo == "aplica" and cfg.client_id:
        g = Graph(cfg)
        archivo_id = _control(g, cfg)
        enc_c, _ = g.tabla_filas(archivo_id, "tblClientes")
        existentes = {normalizar(c.get("NombreCliente")) + "|" + str(c.get("Correo") or "").lower()
                      for c in g.tabla_como_dicts(archivo_id, "tblClientes")}
        nuevas = 0
        for f in filas:
            if normalizar(f["NombreCliente"]) + "|" + f["Correo"] in existentes:
                continue
            g.tabla_agregar_fila(archivo_id, "tblClientes", enc_c, f)
            nuevas += 1
        print(f"tblClientes: {nuevas} filas agregadas" + ("" if "Cartera" in enc_c else " (la tabla no tiene columna Cartera: agrégala)"))
    else:
        print("sin escribir en Microsoft 365 (modo propone o sin credenciales): pega Clientes_para_catalogo.xlsx en la hoja Clientes")


def _resumen_organizacion(analisis, etapa):
    """Documento organizacion/ultimo del panel: solo metadatos (carpetas, tipos y conteos), nunca contenido."""
    return {"hora": ahora().isoformat(timespec="seconds"), "etapa": etapa, **analisis["resumen"],
            "expedientes": analisis["expedientes"][:400], "expedientes_total": len(analisis["expedientes"])}


# ---------- latido ----------
def latido(cfg, rutina, resultado, detalle=""):
    g = Graph(cfg)
    archivo_id = _control(g, cfg)
    try:
        enc, _ = g.tabla_filas(archivo_id, "tblMonitor")
    except GraphError:
        print("tblMonitor no existe; latido omitido")
        return
    t = ahora()
    g.tabla_agregar_fila(archivo_id, "tblMonitor", enc, {"Rutina": rutina, "Fecha": t.strftime("%Y-%m-%d"), "Hora": t.strftime("%H:%M"),
                                                          "Resultado": resultado, "Detalle": detalle[:200]})
    print("latido registrado")


# ---------- respaldo local con OCR de Windows ----------
def decisiones_locales(cfg):
    trabajo = _leer_json(cfg.trabajo / "trabajo.json", None)
    if not trabajo:
        sys.exit("falta trabajo/trabajo.json: ejecuta pull primero")
    try:
        import pymupdf
        import winocr
        from PIL import Image
    except ImportError as e:
        raise SystemExit(f"Solo en Windows con pymupdf, winocr y pillow instalados: {e}")
    from reembolsos.catalogo import candidatos_en_texto
    catalogo = Catalogo([{"NombreCliente": n} for n in trabajo["catalogo"]])
    decisiones = _leer_json(cfg.trabajo / "decisiones.json", {})
    for it in trabajo["items"]:
        if not it["requiere_lectura"] or not it["ruta_local"]:
            continue
        ruta = Path(it["ruta_local"])
        try:
            if ruta.suffix.lower() == ".pdf":
                doc = pymupdf.open(ruta)
                pixs = [p.get_pixmap(dpi=200) for p in list(doc)[:cfg.paginas_max]]
                texto = " ".join(winocr.recognize_pil_sync(Image.frombytes("RGB", (px.width, px.height), px.samples), "es-MX").get("text", "") for px in pixs)
            else:
                texto = winocr.recognize_pil_sync(Image.open(ruta).convert("RGB"), "es-MX").get("text", "")
        except Exception as e:  # noqa: BLE001
            decisiones[it["nombre_guardado"]] = {"motivo": f"OCR local falló: {type(e).__name__}"}
            continue
        cliente, como = catalogo.resolver(texto)
        decisiones[it["nombre_guardado"]] = {
            "cliente": cliente if como in ("exacta", "parcial") else None,
            "identificado_por": "nombre completo" if como == "exacta" else "nombre parcial" if como == "parcial" else "no identificado",
            "candidato_cliente": (candidatos_en_texto(texto) or [None])[0], "motivo": f"OCR local: {como}"}
    _escribir_json(cfg.trabajo / "decisiones.json", decisiones)
    print(f"decisiones locales: {len(decisiones)}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("comando", choices=["selftest", "pull", "apply", "resumen", "borradores", "ingresar", "indexar", "organizar", "semilla", "puente", "asegurados", "cargar-asegurados",
                                       "latido", "decisiones-locales"])
    p.add_argument("args", nargs="*")
    p.add_argument("--modo", choices=["propone", "aplica"])
    p.add_argument("--todos", action="store_true")
    p.add_argument("--preparar", action="store_true")
    p.add_argument("--ruta", help="indexar: carpeta de OneDrive con los expedientes hechos a mano, p. ej. /Reembolsos Lau")
    p.add_argument("--usuario", help="indexar: dueño del OneDrive si no es la cuenta de servicio, p. ej. ltorres@arval.com.mx")
    p.add_argument("--local", help="organizar/semilla: copia local de los expedientes, p. ej. D:\\Arval\\Expedientes\\SINIESTROS")
    p.add_argument("--entrada", help="puente: carpeta /Reembolsos sincronizada (Power Automate)")
    p.add_argument("--destino", help="semilla/puente: carpeta /Arval sincronizada, o carpeta nueva donde se arma la estructura estándar (fuera de --local)")
    p.add_argument("--sin-leer", action="store_true", help="organizar: no abre PDF ni XML (solo nombres y carpetas)")
    p.add_argument("--excel", help="cargar-asegurados: Base_Asegurados.xlsx revisado por Lau")
    p.add_argument("--semilla-sin-revisar", action="store_true", help="cargar-asegurados: carga todos, marcados sin revisar")
    p.add_argument("--sin-ocr", action="store_true", help="organizar: no pasa OCR a escaneos ni fotos (más rápido)")
    p.add_argument("--solo-carpetas", action="store_true", help="semilla: crea las carpetas sin copiar archivos")
    a = p.parse_args()
    cfg = cargar(credenciales=a.comando not in ("organizar", "semilla", "puente", "asegurados", "cargar-asegurados"))
    if a.modo:
        cfg = cfg.__class__(**{**cfg.__dict__, "modo": a.modo})
    cfg.trabajo.mkdir(parents=True, exist_ok=True)
    if a.comando == "selftest":
        selftest(cfg)
    elif a.comando == "pull":
        pull(cfg, a.todos)
    elif a.comando == "apply":
        apply(cfg)
    elif a.comando == "resumen":
        resumen(cfg, a.preparar)
    elif a.comando == "borradores":
        borradores(cfg)
    elif a.comando == "ingresar":
        ingresar(cfg)
    elif a.comando == "indexar":
        if not a.ruta:
            sys.exit("uso: indexar --ruta '/carpeta de expedientes' [--usuario correo@arval.com.mx]")
        indexar(cfg, a.ruta, a.usuario)
    elif a.comando == "organizar":
        if not a.local:
            sys.exit("uso: organizar --local <carpeta> [--sin-leer]")
        organizar(cfg, a.local, not a.sin_leer, not a.sin_ocr)
    elif a.comando == "semilla":
        if not a.local or not a.destino:
            sys.exit("uso: semilla --local <carpeta original> --destino <carpeta nueva> [--solo-carpetas]")
        semilla(cfg, a.local, a.destino, a.solo_carpetas)
    elif a.comando == "cargar-asegurados":
        cargar_asegurados(cfg, a.excel or cfg.trabajo / "Base_Asegurados.xlsx", a.semilla_sin_revisar)
    elif a.comando == "asegurados":
        asegurados(cfg)
    elif a.comando == "puente":
        if not a.entrada or not a.destino:
            sys.exit("uso: puente --entrada <Reembolsos sincronizado> --destino <Arval sincronizado> [--modo aplica] [--sin-ocr]")
        puente(cfg, a.entrada, a.destino, not a.sin_ocr)
    elif a.comando == "latido":
        if len(a.args) < 2:
            sys.exit("uso: latido <rutina> <resultado> [detalle]")
        latido(cfg, a.args[0], a.args[1], " ".join(a.args[2:]))
    elif a.comando == "decisiones-locales":
        decisiones_locales(cfg)


if __name__ == "__main__":
    main()
