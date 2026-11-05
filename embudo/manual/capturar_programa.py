"""Capturas de la ventana de ArvalClasificador.exe para el manual, con rutas y estados de ejemplo (sin tocar nada real).

Abre la ventana del agente con las comprobaciones simuladas, la fotografía con Pillow y la cierra.
Uso: python -I capturar_programa.py   -> img/programa_antes.png, img/programa_listo.png
"""
import ctypes
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent)); sys.path.insert(0, str(AQUI.parent.parent))
ctypes.windll.shcore.SetProcessDpiAwareness(2)   # coordenadas reales de pantalla para la captura

import tkinter as tk  # noqa: E402

from PIL import ImageGrab  # noqa: E402

import agente  # noqa: E402

ARVAL = r"C:\Users\ltorres\OneDrive - ERNESTO ANTONIO ARVIZU VARELA\Arval"
DESCARGAS = [Path(r"C:\Users\ltorres\Downloads")]
CUENTA = r"ltorres@arval.com.mx · C:\Users\ltorres\OneDrive - ERNESTO ANTONIO ARVIZU VARELA"


def preparar(listo):
    agente.candidatas_arval = lambda: [Path(ARVAL)]
    agente.carpetas_descarga = lambda extra=None: DESCARGAS
    agente.destino.es_oficial = lambda p: True
    agente.leer_config = lambda ruta=None: {"configurado": "2026-11-05T12:32:00"} if listo else {}
    agente.ver_instrucciones = lambda raiz: None
    base = [(True, "OneDrive con la cuenta de trabajo", CUENTA), (True, "Carpeta Arval en esta computadora", ARVAL),
            (True, "Es la Arval de soluciones@", "Trae _DESTINO_OFICIAL_ARVAL"), (True, "Permiso para guardar en Arval", "Se pudo escribir"),
            (True, "Carpetas de descargas que vigila", str(DESCARGAS[0]))]
    resto = ([(True, "Configurado y arranca con Windows", "Configurado el 2026-11-05 12:32"), (True, "Vigilando Descargas ahora", "Activo")] if listo
             else [(None, "Configurado y arranca con Windows", "Aún no: pulsa «Guardar e iniciar» (paso 4)"), (None, "Vigilando Descargas ahora", "Se activa al guardar")])
    agente.comprobaciones = lambda arval, descargas=None: base + resto


def capturar(nombre, listo):
    preparar(listo)
    original = tk.Tk.mainloop

    def foto(self, n=0):
        def tomar():
            self.geometry("820x960")   # con la escala de pantalla, la ventana normal no muestra todo para la foto
            self.update()
            if listo:   # el mensaje verde que aparece después de «Guardar e iniciar»
                for w in self.winfo_children()[0].winfo_children():
                    if isinstance(w, tk.ttk.Label) and str(w.cget("text")).startswith("Estado:"):
                        w.config(foreground="#2e7d4f", text="Listo. El agente vigila las descargas de esta PC y guarda en " + ARVAL +
                                 ". Ya puedes cerrar esta ventana; seguirá trabajando en segundo plano y arrancará solo al encender la computadora.")
                self.update()
            x, y = self.winfo_rootx(), self.winfo_rooty()
            ImageGrab.grab((x, y, x + self.winfo_width(), y + self.winfo_height()), all_screens=True).save(AQUI / "img" / f"{nombre}.png")
            self.destroy()
        self.attributes("-topmost", True)
        self.after(1500, tomar)
        original(self, n)
    tk.Tk.mainloop = foto
    try:
        agente.ventana()
    finally:
        tk.Tk.mainloop = original
    print(nombre, (AQUI / "img" / f"{nombre}.png").stat().st_size)


if __name__ == "__main__":
    import tkinter.ttk  # noqa: F401
    (AQUI / "img").mkdir(exist_ok=True)
    capturar("programa_antes", False)
    capturar("programa_listo", True)
