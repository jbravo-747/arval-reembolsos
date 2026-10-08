"""Configuración de las rutinas. Todo viene de variables de entorno (ver .env.example).

En la nube de Claude las variables se definen en el entorno de la rutina; nunca se guardan en el repositorio.
"""
import os
from dataclasses import dataclass
from pathlib import Path


def _env(nombre, defecto=None, obligatorio=False):
    valor = os.environ.get(nombre, defecto)
    if obligatorio and not valor:
        raise SystemExit(f"Falta la variable de entorno {nombre}")
    return valor


@dataclass(frozen=True)
class Config:
    tenant_id: str
    client_id: str
    client_secret: str
    usuario: str                 # buzón y OneDrive que usan las rutinas, p. ej. soluciones@arval.com.mx
    correo_lau: str              # destinatario del resumen diario
    ruta_base: str               # carpeta raíz en OneDrive, p. ej. /Reembolsos
    archivo_control: str         # nombre del Excel de control dentro de ruta_base
    modo: str                    # "propone" (no mueve ni escribe en Excel) o "aplica"
    trabajo: Path                # carpeta local temporal de la corrida
    paginas_max: int             # páginas de PDF que se leen por documento
    onedrive_web: str            # prefijo web de OneDrive para abrir carpetas desde el panel

    @property
    def por_identificar(self):
        return f"{self.ruta_base}/_Por identificar"

    @property
    def clientes(self):
        return f"{self.ruta_base}/Clientes"

    def url_carpeta(self, ruta):
        """URL para abrir una carpeta de OneDrive (ruta como /Reembolsos/Clientes/<cliente>/<mes>) en el navegador."""
        from urllib.parse import quote
        return self.onedrive_web + quote(ruta, safe="")


def cargar():
    return Config(
        tenant_id=_env("M365_TENANT_ID", obligatorio=True),
        client_id=_env("M365_CLIENT_ID", obligatorio=True),
        client_secret=_env("M365_CLIENT_SECRET", obligatorio=True),
        usuario=_env("M365_USUARIO", "soluciones@arval.com.mx"),
        correo_lau=_env("CORREO_RESUMEN", "ltorres@arval.com.mx"),
        ruta_base=_env("RUTA_BASE", "/Reembolsos"),
        archivo_control=_env("ARCHIVO_CONTROL", "Control_Reembolsos.xlsx"),
        modo=_env("MODO", "propone"),
        trabajo=Path(_env("CARPETA_TRABAJO", "trabajo")),
        paginas_max=int(_env("PAGINAS_MAX", "3")),
        onedrive_web=_env("ONEDRIVE_WEB_BASE",
                          "https://arvalcommx-my.sharepoint.com/my?id=%2Fpersonal%2Fsoluciones%5Farval%5Fcom%5Fmx%2FDocuments"),
    )
