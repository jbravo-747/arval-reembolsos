"""Almacén en listas de SharePoint (base de datos compartida del equipo) con la misma interfaz que las tablas de Excel.

Uso previsto (fase posterior, ver docs/base_datos_equipo.md): cuando la operación pase de una persona a un equipo,
las tablas tblClientes, tblRegistro y tblMonitor se migran a listas de SharePoint en un sitio del equipo. Este módulo
expone las tres operaciones que usa cli.py (leer filas, agregar fila, actualizar fila) sobre Microsoft Graph.

Permisos de aplicación adicionales: Sites.ReadWrite.All (o Sites.Selected concedido al sitio del equipo).
"""


class Listas:
    def __init__(self, graph, sitio_hostname, sitio_ruta):
        """sitio_hostname: arvalcommx.sharepoint.com; sitio_ruta: /sites/Reembolsos"""
        self.g = graph
        self.site_id = graph.get(f"/sites/{sitio_hostname}:{sitio_ruta}")["id"]
        self._listas = {}

    def _lista(self, nombre):
        if nombre not in self._listas:
            self._listas[nombre] = self.g.get(f"/sites/{self.site_id}/lists/{nombre}")["id"]
        return self._listas[nombre]

    def filas(self, nombre):
        """Devuelve (encabezados, filas) como tabla_filas de Excel: cada fila {"index": id de la lista, "values": [...]}."""
        items = self.g.get_all(f"/sites/{self.site_id}/lists/{self._lista(nombre)}/items?$expand=fields&$top=500")
        columnas = [c["name"] for c in self.g.get_all(f"/sites/{self.site_id}/lists/{self._lista(nombre)}/columns")
                    if not c.get("readOnly") and not c.get("hidden")]
        filas = [{"index": it["id"], "values": [it["fields"].get(c, "") for c in columnas]} for it in items]
        return columnas, filas

    def como_dicts(self, nombre):
        enc, filas = self.filas(nombre)
        return [dict(zip(enc, f["values"]), _index=f["index"]) for f in filas]

    def agregar(self, nombre, fila: dict):
        return self.g._req("POST", f"/sites/{self.site_id}/lists/{self._lista(nombre)}/items", json={"fields": fila}).json()

    def actualizar(self, nombre, item_id, cambios: dict):
        return self.g._req("PATCH", f"/sites/{self.site_id}/lists/{self._lista(nombre)}/items/{item_id}/fields", json=cambios).json()
