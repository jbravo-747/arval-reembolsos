"""Paquetes del Embudo de expedientes: lo que Lau clasifica en el artifact llega como ARVAL_EMBUDO_<lote>.zip (archivos +
manifiesto.json) a Descargas, y aquí se acomoda en la carpeta Arval sincronizada con OneDrive:
  <Cartera>/<Cliente>/<AAAA-MM_Evento>/<AAAAMMDD>_<TIPO>_<nn>.ext   (evento abierto a 10 días o menos, o uno nuevo)
  <Grupo>/_Póliza de grupo/<AAAAMMDD>_<TIPO>_<nn>.ext               (documento de la póliza de grupo completa)
  _Por identificar/<nombre original>                                (sin asegurado)
Nunca sobrescribe ni borra nada en Arval. Cada archivo colocado se anota en Arval/_Embudo/registro.jsonl (solo metadatos).
Después arma o completa la RELACION DE GASTOS.xlsx de cada asegurado tocado (ver relacion_gastos.py).
"""
import hashlib
import json
import zipfile
from datetime import date, datetime
from pathlib import Path

from . import destino, relacion_gastos
from .catalogo import normalizar
from .organizacion import TIPO_CORTO, limpiar
from .puente import POR_IDENTIFICAR, _siguiente_nombre, carpeta_evento

PATRON_PAQUETE = "ARVAL_EMBUDO_*.zip"
CARPETA_REGISTRO = "_Embudo"
POLIZA_GRUPO = "_Póliza de grupo"   # dentro de la carpeta del grupo (SAYER CLIENTES, BANCO DE ALIMENTOS)


def _fecha(texto, respaldo):
    try:
        return date.fromisoformat(str(texto or "")[:10])
    except ValueError:
        return respaldo


def carpeta_cliente(arval, cliente, cartera):
    """Carpeta existente del cliente en cualquier cartera (la cartera pudo renombrarse) o la de su cartera indicada."""
    buscado = normalizar(cliente)
    for c in sorted(p for p in arval.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for p in c.iterdir():
            if p.is_dir() and not p.name.startswith("_") and normalizar(p.name) == buscado:
                return p
    return arval / limpiar(cartera or "_Sin cartera") / limpiar(cliente)


def _libre(carpeta, nombre):
    """Nombre que no pisa nada: archivo.pdf, archivo (2).pdf, ..."""
    base, ext = Path(nombre).stem, Path(nombre).suffix
    final, n = carpeta / nombre, 2
    while final.exists():
        final, n = carpeta / f"{base} ({n}){ext}", n + 1
    return final


def leer_manifiesto(zf):
    m = json.loads(zf.read("manifiesto.json").decode("utf-8"))
    if m.get("formato") != "arval-embudo" or not isinstance(m.get("archivos"), list):
        raise ValueError("manifiesto que no es del embudo")
    return m


def _ya_esta(raiz, datos):
    """Ruta de un archivo idéntico (mismo contenido) dentro de raiz, o None. Compara primero el tamaño: es barato."""
    raiz = Path(raiz)
    if not raiz.is_dir():
        return None
    huella = None
    for p in raiz.rglob("*"):
        try:
            if p.is_file() and p.stat().st_size == len(datos):
                huella = huella or hashlib.sha256(datos).digest()
                if hashlib.sha256(p.read_bytes()).digest() == huella:
                    return p
        except OSError:
            continue
    return None


def colocar_paquete(zip_ruta, arval, hoy=None):
    """Acomoda cada archivo del paquete en Arval. Devuelve [{id, nombre, resultado, destino}] (resultado: colocado | error)."""
    arval, hoy = Path(arval), hoy or date.today()
    destino.exigir(arval)
    registro = arval / CARPETA_REGISTRO / "registro.jsonl"
    registro.parent.mkdir(parents=True, exist_ok=True)
    resultados, eventos, reservados = [], {}, set()
    relaciones = {}   # carpeta del asegurado -> {nombre, datos}: su RELACION DE GASTOS se arma al final
    with zipfile.ZipFile(zip_ruta) as zf:
        m = leer_manifiesto(zf)
        miembros = set(zf.namelist())
        for a in m["archivos"]:
            r = {"id": a.get("id"), "nombre": a.get("nombre"), "cliente": a.get("cliente"), "tipo": a.get("tipo"), "lote": m.get("lote")}
            try:
                if a.get("archivo") not in miembros:
                    raise ValueError("falta en el paquete")
                ext = Path(a.get("nombre") or a["archivo"]).suffix.lower()
                f_rec = _fecha(a.get("fecha_recepcion"), hoy)
                if a.get("nivel") == "grupo" and a.get("grupo"):
                    carpeta = arval / limpiar(a["grupo"]) / POLIZA_GRUPO
                    base = f"{_fecha(a.get('fecha_doc'), f_rec):%Y%m%d}_{TIPO_CORTO.get(a.get('tipo'), 'DOC')}"
                    final = carpeta / _siguiente_nombre(carpeta, base, ext, reservados)
                elif a.get("cliente"):
                    cc = carpeta_cliente(arval, a["cliente"], a.get("cartera"))
                    en_corrida = eventos.setdefault(cc, {})
                    evento, nuevo = carpeta_evento(cc, f_rec, en_corrida, arval, None)
                    en_corrida.setdefault(evento, []).append(f_rec)
                    carpeta = cc / evento
                    base = f"{_fecha(a.get('fecha_doc'), f_rec):%Y%m%d}_{TIPO_CORTO.get(a.get('tipo'), 'DOC')}"
                    final = carpeta / _siguiente_nombre(carpeta, base, ext, reservados)
                    r["evento_nuevo"] = nuevo
                    rel = relaciones.setdefault(cc, {"nombre": a.get("asegurado") or a["cliente"], "datos": []})
                    if isinstance(a.get("relacion"), dict):
                        rel["datos"].append(a["relacion"])
                else:
                    carpeta = arval / POR_IDENTIFICAR
                    final = _libre(carpeta, limpiar(a.get("nombre") or Path(a["archivo"]).name, 150))
                datos = zf.read(a["archivo"])
                # El mismo archivo ya guardado antes (se volvió a soltar): no se duplica, se reporta dónde está
                raiz_busqueda = carpeta.parent if a.get("cliente") and a.get("nivel") != "grupo" else carpeta
                previo = _ya_esta(raiz_busqueda, datos)
                if previo:
                    r.update(resultado="colocado", duplicado=True, destino=previo.relative_to(arval).as_posix())
                    r["hora"] = datetime.now().isoformat(timespec="seconds")
                    resultados.append(r)
                    continue
                final.parent.mkdir(parents=True, exist_ok=True)
                with open(final, "xb") as dst:   # "x": nunca sobrescribe
                    dst.write(datos)
                r.update(resultado="colocado", destino=final.relative_to(arval).as_posix())
            except (OSError, ValueError, KeyError) as e:
                r.update(resultado="error", detalle=f"{type(e).__name__}: {e}"[:200])
            r["hora"] = datetime.now().isoformat(timespec="seconds")
            resultados.append(r)
    with registro.open("a", encoding="utf-8") as fh:
        for r in resultados:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for cc, rel in relaciones.items():
        actualizar_relacion(arval, cc, rel["nombre"], rel["datos"])
    reintentar_relaciones(arval)
    return resultados


def _anotar(arval, dato):
    with (Path(arval) / CARPETA_REGISTRO / "registro.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({**dato, "hora": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")


def _nombre_seguro(texto):
    return "".join(c if c.isalnum() else "_" for c in texto)[:120]


def actualizar_relacion(arval, carpeta_cliente, nombre, datos):
    """Arma o completa la RELACION DE GASTOS del asegurado. Si el Excel está abierto, queda pendiente para reintentar."""
    arval = Path(arval)
    rel_carpeta = Path(carpeta_cliente).relative_to(arval).as_posix()
    try:
        r = relacion_gastos.actualizar(carpeta_cliente, nombre, list(datos))
        if r["ruta"]:
            _anotar(arval, {"relacion": rel_carpeta, "resultado": "actualizada" if r["cambios"] else "sin cambios",
                            "filas": r["filas"], "respaldo": bool(r["respaldo"])})
        return True
    except relacion_gastos.RelacionOcupada:
        pend = arval / CARPETA_REGISTRO / "relaciones_pendientes"
        pend.mkdir(parents=True, exist_ok=True)
        archivo = pend / (_nombre_seguro(rel_carpeta) + ".json")
        previos = json.loads(archivo.read_text(encoding="utf-8")).get("datos", []) if archivo.exists() else []
        archivo.write_text(json.dumps({"carpeta": rel_carpeta, "nombre": nombre, "datos": previos + list(datos)}, ensure_ascii=False),
                           encoding="utf-8")
        _anotar(arval, {"relacion": rel_carpeta, "resultado": "pendiente (archivo abierto)"})
    except Exception as e:   # noqa: BLE001 — la relación nunca debe impedir acomodar los documentos
        _anotar(arval, {"relacion": rel_carpeta, "resultado": "error", "detalle": f"{type(e).__name__}: {e}"[:200]})
    return False


def reintentar_relaciones(arval):
    """Reintenta las relaciones que quedaron pendientes porque el Excel estaba abierto."""
    pend = Path(arval) / CARPETA_REGISTRO / "relaciones_pendientes"
    if not pend.exists():
        return
    for archivo in sorted(pend.glob("*.json")):
        try:
            p = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        archivo.unlink()
        actualizar_relacion(arval, Path(arval) / p["carpeta"], p["nombre"], p.get("datos", []))
