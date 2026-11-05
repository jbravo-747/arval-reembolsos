"""Destino único de los expedientes: la carpeta Arval en la raíz del OneDrive de soluciones@ (compartida con Lau).

Todo lo que construye expedientes en una copia local sincronizada (el agente del clasificador, `cli.py puente`) escribe
solo si la carpeta trae la marca _DESTINO_OFICIAL_ARVAL, creada a mano en OneDrive web y bajada por la sincronización.
Así una carpeta "Arval" propia, una copia vieja o una carpeta local sin sincronizar nunca reciben expedientes.
"""
from pathlib import Path

RUTA_WEB = "/personal/soluciones_arval_com_mx/Documents/Arval"
ENLACE = "https://arvalcommx-my.sharepoint.com/:f:/g/personal/soluciones_arval_com_mx/IgC160Bttn7QS6FnLfr_SWC4AQtmAUX8Ughq1bnaKRAIlkE?e=eDheHa"
MARCA = "_DESTINO_OFICIAL_ARVAL"


class DestinoIncorrecto(Exception):
    pass


def es_oficial(carpeta):
    return bool(carpeta) and (Path(carpeta) / MARCA).is_dir()


def exigir(carpeta):
    if not es_oficial(carpeta):
        raise DestinoIncorrecto(f"{carpeta} no es la carpeta Arval de soluciones@ sincronizada: le falta la marca {MARCA}. "
                                f"Abre {ENLACE}, revisa que la marca exista y sincroniza esa carpeta en esta PC.")
