"""Confirma en el historial del clasificador lo que el agente ya acomodó en Arval.

Lee Arval/_Embudo/registro.jsonl (lo escribe ArvalClasificador.exe al colocar cada archivo) y escribe la lista de
actualizaciones para la colección «entradas» del artifact: estado «colocado» y la ruta exacta («destino») para que el
historial abra el archivo en OneDrive. La aplica una sesión de Claude o la rutina con ArtifactData (update, por id).
Uso: python -I registro_a_entradas.py "<Arval sincronizada>/_Embudo/registro.jsonl" salida.json
"""
import json
import sys


def actualizaciones(lineas):
    salida = {}
    for linea in lineas:
        try:
            r = json.loads(linea)
        except ValueError:
            continue
        if r.get("id") and r.get("resultado") == "colocado" and r.get("destino"):
            salida[r["id"]] = {"estado": "colocado", "destino": r["destino"], "colocado_hora": r.get("hora", "")}   # el último gana
    return [{"id": k, **v} for k, v in salida.items()]


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as fh:
        datos = actualizaciones(fh)
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=1)
    print(len(datos), "confirmados")
