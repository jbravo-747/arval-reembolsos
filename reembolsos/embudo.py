"""Paquetes del Embudo de expedientes: lo que Lau clasifica en el artifact llega como ARVAL_EMBUDO_<lote>.zip (archivos +
manifiesto.json) a Descargas, y aquí se acomoda en la carpeta Arval sincronizada con OneDrive:
  <Cartera>/<Cliente>/<AAAA-MM_Evento>/<AAAAMMDD>_<TIPO>_<nn>.ext   (evento abierto a 10 días o menos, o uno nuevo)
  _Por identificar/<nombre original>                                (sin asegurado)
Nunca sobrescribe ni borra nada en Arval. Cada archivo colocado se anota en Arval/_Embudo/registro.jsonl (solo metadatos).
"""
import json
import zipfile
from datetime import date, datetime
from pathlib import Path

from . import destino
from .catalogo import normalizar
from .organizacion import TIPO_CORTO, limpiar
from .puente import POR_IDENTIFICAR, _siguiente_nombre, carpeta_evento

PATRON_PAQUETE = "ARVAL_EMBUDO_*.zip"
CARPETA_REGISTRO = "_Embudo"


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
            if p.is_dir() and normalizar(p.name) == buscado:
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


def colocar_paquete(zip_ruta, arval, hoy=None):
    """Acomoda cada archivo del paquete en Arval. Devuelve [{id, nombre, resultado, destino}] (resultado: colocado | error)."""
    arval, hoy = Path(arval), hoy or date.today()
    destino.exigir(arval)
    registro = arval / CARPETA_REGISTRO / "registro.jsonl"
    registro.parent.mkdir(parents=True, exist_ok=True)
    resultados, eventos, reservados = [], {}, set()
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
                if a.get("cliente"):
                    cc = carpeta_cliente(arval, a["cliente"], a.get("cartera"))
                    en_corrida = eventos.setdefault(cc, {})
                    evento, nuevo = carpeta_evento(cc, f_rec, en_corrida, arval, None)
                    en_corrida.setdefault(evento, []).append(f_rec)
                    carpeta = cc / evento
                    base = f"{_fecha(a.get('fecha_doc'), f_rec):%Y%m%d}_{TIPO_CORTO.get(a.get('tipo'), 'DOC')}"
                    final = carpeta / _siguiente_nombre(carpeta, base, ext, reservados)
                    r["evento_nuevo"] = nuevo
                else:
                    carpeta = arval / POR_IDENTIFICAR
                    final = _libre(carpeta, limpiar(a.get("nombre") or Path(a["archivo"]).name, 150))
                final.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(a["archivo"]) as src, open(final, "xb") as dst:   # "x": nunca sobrescribe
                    while bloque := src.read(1 << 20):
                        dst.write(bloque)
                r.update(resultado="colocado", destino=final.relative_to(arval).as_posix())
            except (OSError, ValueError, KeyError) as e:
                r.update(resultado="error", detalle=f"{type(e).__name__}: {e}"[:200])
            r["hora"] = datetime.now().isoformat(timespec="seconds")
            resultados.append(r)
    with registro.open("a", encoding="utf-8") as fh:
        for r in resultados:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return resultados
