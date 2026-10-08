"""Cliente mínimo de Microsoft Graph para OneDrive, Excel y correo (permisos de aplicación).

Permisos necesarios en el registro de aplicación de Entra ID:
  Files.ReadWrite.All (o Sites.Selected acotado), Mail.Send (con política de acceso al buzón de soluciones@).
Documentación: https://learn.microsoft.com/graph/api/overview
"""
import time
import urllib.parse

import requests

GRAPH = "https://graph.microsoft.com/v1.0"


class Graph:
    def __init__(self, cfg):
        self.cfg = cfg
        self._token = None
        self._expira = 0
        self._drive_id = None
        self.sesion = requests.Session()

    # ---------- autenticación ----------
    def token(self):
        if self._token and time.time() < self._expira - 60:
            return self._token
        r = requests.post(
            f"https://login.microsoftonline.com/{self.cfg.tenant_id}/oauth2/v2.0/token",
            data={"client_id": self.cfg.client_id, "client_secret": self.cfg.client_secret,
                  "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"},
            timeout=30)
        r.raise_for_status()
        j = r.json()
        self._token, self._expira = j["access_token"], time.time() + int(j.get("expires_in", 3600))
        return self._token

    def _req(self, metodo, url, **kw):
        if not url.startswith("http"):
            url = GRAPH + url
        kw.setdefault("timeout", 120)
        headers = {"Authorization": f"Bearer {self.token()}", **kw.pop("headers", {})}
        for intento in range(5):
            r = self.sesion.request(metodo, url, headers=headers, **kw)
            if r.status_code in (429, 503, 504):
                time.sleep(int(r.headers.get("Retry-After", 2 ** intento)))
                continue
            if r.status_code >= 400:
                raise GraphError(metodo, url, r.status_code, r.text[:500])
            return r
        raise GraphError(metodo, url, r.status_code, "reintentos agotados")

    def get(self, url, **kw):
        return self._req("GET", url, **kw).json()

    def get_all(self, url, **kw):
        """Sigue @odata.nextLink y devuelve todos los elementos de value."""
        items = []
        while url:
            j = self.get(url, **kw)
            items.extend(j.get("value", []))
            url = j.get("@odata.nextLink")
            kw = {}
        return items

    # ---------- OneDrive ----------
    @property
    def drive(self):
        if not self._drive_id:
            self._drive_id = self.get(f"/users/{self.cfg.usuario}/drive")["id"]
        return self._drive_id

    def drive_de(self, usuario):
        """Id del OneDrive de otro usuario del tenant (requiere permiso de aplicación sobre sus archivos)."""
        return self.get(f"/users/{usuario}/drive")["id"]

    def _ruta(self, ruta, drive=None):
        return f"/drives/{drive or self.drive}/root:{urllib.parse.quote(ruta)}"

    def item_por_ruta(self, ruta, drive=None):
        return self.get(self._ruta(ruta, drive))

    def listar(self, ruta, drive=None):
        return self.get_all(self._ruta(ruta, drive) + ":/children?$top=200&$select=id,name,size,file,folder,createdDateTime,lastModifiedDateTime,webUrl,parentReference")

    def listar_recursivo(self, ruta, drive=None, max_items=5000):
        """Recorre una carpeta y sus subcarpetas; devuelve (ruta_relativa, item) para cada archivo."""
        salida, pendientes = [], [ruta]
        while pendientes and len(salida) < max_items:
            actual = pendientes.pop(0)
            for it in self.listar(actual, drive):
                rel = f"{actual}/{it['name']}"
                if "folder" in it:
                    pendientes.append(rel)
                else:
                    salida.append((rel, it))
        return salida

    def descargar_de(self, drive, item_id, destino):
        r = self._req("GET", f"/drives/{drive}/items/{item_id}/content", stream=True)
        with open(destino, "wb") as fh:
            for trozo in r.iter_content(1 << 16):
                fh.write(trozo)
        return destino

    def descargar(self, item_id, destino):
        r = self._req("GET", f"/drives/{self.drive}/items/{item_id}/content", stream=True)
        with open(destino, "wb") as fh:
            for trozo in r.iter_content(1 << 16):
                fh.write(trozo)
        return destino

    def asegurar_carpeta(self, ruta):
        """Crea la carpeta (y sus padres) si no existe; devuelve el item."""
        try:
            return self.item_por_ruta(ruta)
        except GraphError as e:
            if e.status != 404:
                raise
        padre, nombre = ruta.rsplit("/", 1)
        padre_item = self.asegurar_carpeta(padre) if padre else self.get(f"/drives/{self.drive}/root")
        return self._req("POST", f"/drives/{self.drive}/items/{padre_item['id']}/children",
                         json={"name": nombre, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}).json()

    def mover(self, item_id, carpeta_destino, nombre=None):
        destino = self.asegurar_carpeta(carpeta_destino)
        cuerpo = {"parentReference": {"id": destino["id"]}}
        if nombre:
            cuerpo["name"] = nombre
        return self._req("PATCH", f"/drives/{self.drive}/items/{item_id}", json=cuerpo).json()

    def subir_pequeno(self, ruta, contenido: bytes, content_type="application/json"):
        """Sube o reemplaza un archivo de menos de 4 MB."""
        return self._req("PUT", self._ruta(ruta) + ":/content", data=contenido,
                         headers={"Content-Type": content_type}).json()

    def subir_archivo(self, ruta_onedrive, ruta_local):
        """Sube un archivo de cualquier tamaño (sesión de carga por bloques de 5 MB si pasa de 4 MB). No sobrescribe."""
        datos = open(ruta_local, "rb").read()
        if len(datos) < 4 * 1024 * 1024:
            return self._req("PUT", self._ruta(ruta_onedrive) + ":/content?@microsoft.graph.conflictBehavior=fail",
                             data=datos, headers={"Content-Type": "application/octet-stream"}).json()
        sesion = self._req("POST", self._ruta(ruta_onedrive) + ":/createUploadSession",
                           json={"item": {"@microsoft.graph.conflictBehavior": "fail"}}).json()
        url, bloque, pos, resp = sesion["uploadUrl"], 5 * 1024 * 1024, 0, None
        while pos < len(datos):
            trozo = datos[pos:pos + bloque]
            resp = self.sesion.put(url, data=trozo, headers={"Content-Length": str(len(trozo)),
                                                             "Content-Range": f"bytes {pos}-{pos + len(trozo) - 1}/{len(datos)}"}, timeout=300)
            if resp.status_code >= 400:
                raise GraphError("PUT", url, resp.status_code, resp.text[:300])
            pos += len(trozo)
        return resp.json()

    def enlace_lectura(self, item_id):
        j = self._req("POST", f"/drives/{self.drive}/items/{item_id}/createLink",
                      json={"type": "view", "scope": "organization"}).json()
        return j["link"]["webUrl"]

    # ---------- Excel (tablas) ----------
    def _wb(self, archivo_id):
        return f"/drives/{self.drive}/items/{archivo_id}/workbook"

    def tabla_filas(self, archivo_id, tabla):
        """Devuelve (encabezados, filas) donde cada fila es {"index": n, "values": [...]}."""
        enc = self.get(f"{self._wb(archivo_id)}/tables/{tabla}/headerRowRange?$select=values")["values"][0]
        filas = self.get_all(f"{self._wb(archivo_id)}/tables/{tabla}/rows?$select=index,values")
        return [str(e).strip() for e in enc], [{"index": f["index"], "values": f["values"][0]} for f in filas]

    def tabla_como_dicts(self, archivo_id, tabla):
        enc, filas = self.tabla_filas(archivo_id, tabla)
        return [dict(zip(enc, f["values"]), _index=f["index"]) for f in filas]

    def tabla_actualizar_fila(self, archivo_id, tabla, index, encabezados, cambios: dict, valores_actuales):
        valores = list(valores_actuales)
        for k, v in cambios.items():
            valores[encabezados.index(k)] = v
        return self._req("PATCH", f"{self._wb(archivo_id)}/tables/{tabla}/rows/itemAt(index={index})",
                         json={"values": [valores]}).json()

    def tabla_agregar_fila(self, archivo_id, tabla, encabezados, fila: dict):
        valores = [fila.get(e, "") for e in encabezados]
        return self._req("POST", f"{self._wb(archivo_id)}/tables/{tabla}/rows", json={"values": [valores]}).json()

    # ---------- Correo ----------
    def crear_borrador(self, para, asunto, html):
        """Deja un borrador en el buzón (no lo envía): la operadora lo revisa y decide."""
        cuerpo = {"subject": asunto, "body": {"contentType": "HTML", "content": html},
                  "toRecipients": [{"emailAddress": {"address": para}}], "isDraft": True}
        return self._req("POST", f"/users/{self.cfg.usuario}/messages", json=cuerpo).json()

    def enviar_correo(self, para, asunto, html):
        destinatarios = [para] if isinstance(para, str) else list(para)
        cuerpo = {"message": {"subject": asunto, "body": {"contentType": "HTML", "content": html},
                              "toRecipients": [{"emailAddress": {"address": d}} for d in destinatarios]},
                  "saveToSentItems": True}
        self._req("POST", f"/users/{self.cfg.usuario}/sendMail", json=cuerpo)


class GraphError(Exception):
    def __init__(self, metodo, url, status, texto):
        super().__init__(f"{metodo} {url} -> {status}: {texto}")
        self.status = status
