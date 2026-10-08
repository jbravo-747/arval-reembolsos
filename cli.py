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
  python cli.py latido <rutina> <resultado> [detalle]
  python cli.py decisiones-locales       (respaldo) OCR de Windows en lugar del agente; solo en un equipo Windows

El modo viene de --modo o de la variable MODO (por defecto "propone": no escribe nada en Microsoft 365).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
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
                carpeta = f"{cfg.clientes}/{res['cliente']}/{cl.mes_de(it['nombre_guardado'])}"
                g.mover(it["item_id"], carpeta)
                cambios["Cliente"] = res["cliente"]
                cambios["Ruta"] = f"{carpeta}/{it['nombre_guardado']}"
                movidos += 1
            if it["index"] in por_index:
                g.tabla_actualizar_fila(archivo_id, "tblRegistro", it["index"], enc, cambios, por_index[it["index"]])
        except GraphError as e:
            errores.append(f"{it['nombre_guardado'][:40]}: {e}")

    # 3) Expedientes con el registro actualizado (en modo propone se simula con los resultados de esta corrida)
    registros_vista = _registros_con_resultados(registros, resultados) if cfg.modo != "aplica" else _registros(g, archivo_id)[2]
    expedientes = ex.agrupar(registros_vista, ahora().date())
    snapshot = _snapshot(cfg, resultados, movidos, errores, expedientes, nuevos)
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


def _snapshot(cfg, resultados, movidos, errores, expedientes, altas=0):
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
                        "carpeta_url": cfg.url_carpeta(f"{cfg.clientes}/{r['cliente']}/{cl.mes_de(r['nombre_guardado'])}" if r["cliente"] and cfg.modo == "aplica"
                                                       else cfg.por_identificar)}
                       for r in resultados],
        "candidatos": [{"nombre": c, "archivos": a} for c, a in candidatos.items()],
        "expedientes": [{**e, "carpeta_url": cfg.url_carpeta(f"{cfg.clientes}/{e['cliente']}/{e['inicio'][:7]}")} for e in expedientes],
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
    print("asunto:", asunto, "| registros:", len(pendientes))
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
    p.add_argument("comando", choices=["selftest", "pull", "apply", "resumen", "borradores", "latido", "decisiones-locales"])
    p.add_argument("args", nargs="*")
    p.add_argument("--modo", choices=["propone", "aplica"])
    p.add_argument("--todos", action="store_true")
    p.add_argument("--preparar", action="store_true")
    a = p.parse_args()
    cfg = cargar()
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
    elif a.comando == "latido":
        if len(a.args) < 2:
            sys.exit("uso: latido <rutina> <resultado> [detalle]")
        latido(cfg, a.args[0], a.args[1], " ".join(a.args[2:]))
    elif a.comando == "decisiones-locales":
        decisiones_locales(cfg)


if __name__ == "__main__":
    main()
