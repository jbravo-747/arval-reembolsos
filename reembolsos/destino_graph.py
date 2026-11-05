"""La rutina en la nube construye los expedientes en la carpeta Arval de soluciones@ por Microsoft Graph, con la misma
estructura que el puente y el clasificador: <Cartera>/<Cliente>/<AAAA-MM_Evento>/<AAAAMMDD>_<TIPO>_<nn>.ext.

Antes de mover nada se comprueba la marca _DESTINO_OFICIAL_ARVAL (reembolsos/destino.py). Lo que se lee de Arval
(carteras, clientes, eventos, nombres) se guarda en memoria durante la corrida para no repetir llamadas.
"""
import re
from datetime import date

from .catalogo import normalizar
from .destino import MARCA, DestinoIncorrecto
from .graph import GraphError
from .organizacion import TIPO_CORTO, limpiar
from .puente import elegir_evento


def _fecha_nombre(nombre):
    m = re.match(r"(20\d{2})(\d{2})(\d{2})_", nombre)
    try:
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None
    except ValueError:
        return None


class ArvalGraph:
    def __init__(self, g, raiz):
        self.g, self.raiz = g, raiz.rstrip("/")
        self._clientes = None   # nombre normalizado -> ruta de la carpeta del cliente
        self._eventos = {}      # ruta del cliente -> {evento: [fechas]}
        self._nombres = {}      # ruta del evento -> nombres de archivo ya usados

    def verificar(self):
        try:
            self.g.item_por_ruta(f"{self.raiz}/{MARCA}")
        except GraphError as e:
            if e.status != 404:
                raise
            raise DestinoIncorrecto(f"{self.raiz} no tiene la marca {MARCA}: no se mueve nada hasta que exista en la carpeta "
                                    "Arval de soluciones@") from None

    def _hijos(self, ruta):
        try:
            return self.g.listar(ruta)
        except GraphError as e:
            if e.status == 404:
                return []
            raise

    def carpeta_cliente(self, cliente, cartera=""):
        """Carpeta existente del cliente en cualquier cartera, o <cartera indicada o _Sin cartera>/<cliente>."""
        if self._clientes is None:
            self._clientes = {}
            for c in self._hijos(self.raiz):
                if "folder" in c and not c["name"].startswith("_"):
                    for p in self._hijos(f"{self.raiz}/{c['name']}"):
                        if "folder" in p:
                            self._clientes.setdefault(normalizar(p["name"]), f"{self.raiz}/{c['name']}/{p['name']}")
        clave = normalizar(cliente)
        if clave not in self._clientes:
            self._clientes[clave] = f"{self.raiz}/{limpiar(cartera or '_Sin cartera')}/{limpiar(cliente)}"
        return self._clientes[clave]

    def ruta_conocida(self, cliente):
        return (self._clientes or {}).get(normalizar(cliente))

    def _fechas_eventos(self, ruta_cliente):
        if ruta_cliente not in self._eventos:
            eventos = {}
            for e in self._hijos(ruta_cliente):
                if "folder" in e and not e["name"].startswith("_"):
                    nombres = {x["name"] for x in self._hijos(f"{ruta_cliente}/{e['name']}")}
                    self._nombres[f"{ruta_cliente}/{e['name']}"] = nombres
                    eventos[e["name"]] = [f for f in map(_fecha_nombre, nombres) if f]
            self._eventos[ruta_cliente] = eventos
        return self._eventos[ruta_cliente]

    def destino(self, cliente, cartera, fecha_evento, fecha_doc, tipo, ext):
        """(carpeta del evento, nombre estándar, evento_nuevo) para un documento; reserva el nombre en esta corrida."""
        rc = self.carpeta_cliente(cliente, cartera)
        eventos = self._fechas_eventos(rc)
        evento, nuevo = elegir_evento(eventos, fecha_evento)
        eventos.setdefault(evento, []).append(fecha_evento)
        carpeta = f"{rc}/{evento}"
        usados = self._nombres.setdefault(carpeta, set())
        base, n = f"{fecha_doc:%Y%m%d}_{TIPO_CORTO.get(tipo, 'DOC')}", 1
        while any(u.lower() == f"{base}_{n:02d}{ext}".lower() for u in usados):
            n += 1
        nombre = f"{base}_{n:02d}{ext}"
        usados.add(nombre)
        return carpeta, nombre, nuevo
