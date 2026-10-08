"""Genera el flujo 3 "Reembolsos - 3 Registro desde OCR local" y el archivo movidos.json.

Uso:
    python generar_flujo3.py <DRIVE_ID> <FILE_ID_CONTROL>

El flujo (instantáneo, se ejecuta a mano) lee /Reembolsos/_OCR/movidos.json en OneDrive, y por cada
entrada {archivo, cliente, ruta} busca la fila de tblRegistro cuyo NombreGuardado coincida y le pone
Cliente, Ruta, Estado = Revisar y una observación. Se usa después de mover archivos con el OCR local.
movidos.json se construye a partir de OCR_movidos.csv (última corrida).
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generar import conector, definicion, empaquetar  # noqa: E402

AQUI = Path(__file__).parent / "salida"
EXCEL = "shared_excelonlinebusiness"
ONEDRIVE = "shared_onedriveforbusiness"
DRIVE, ARCHIVO = sys.argv[1], sys.argv[2]
RUTA_JSON = "/Reembolsos/_OCR/movidos.json"


def excel(operacion, extra):
    return conector(EXCEL, operacion, {"source": "me", "drive": DRIVE, "file": ARCHIVO, "table": "tblRegistro", **extra})


def flujo():
    triggers = {"manual": {"type": "Request", "kind": "Button",
                           "inputs": {"schema": {"type": "object", "properties": {}, "required": []}}}}
    acciones = {
        "Contenido": {"runAfter": {}, "type": "OpenApiConnection",
                      "inputs": conector(ONEDRIVE, "GetFileContentByPath", {"path": RUTA_JSON, "inferContentType": True})},
        "Lista": {"runAfter": {"Contenido": ["Succeeded"]}, "type": "Compose",
                  "inputs": "@if(empty(body('Contenido')?['$content']), body('Contenido'), json(base64ToString(body('Contenido')?['$content'])))"},
        "Bucle": {
            "runAfter": {"Lista": ["Succeeded"]}, "type": "Foreach", "foreach": "@outputs('Lista')",
            "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
            "actions": {
                "Buscar_fila": {"runAfter": {}, "type": "OpenApiConnection",
                                "inputs": excel("GetItems", {"$filter": "NombreGuardado eq '@{replace(items('Bucle')?['archivo'], '''', '''''')}'"})},
                "Existe": {
                    "runAfter": {"Buscar_fila": ["Succeeded"]}, "type": "If",
                    "expression": {"and": [{"greater": ["@length(body('Buscar_fila')?['value'])", 0]}]},
                    "actions": {"Actualizar": {"runAfter": {}, "type": "OpenApiConnection", "inputs": excel("PatchItem", {
                        "idColumn": "ID", "id": "@first(body('Buscar_fila')?['value'])?['ID']",
                        "item/Cliente": "@items('Bucle')?['cliente']",
                        "item/Ruta": "@items('Bucle')?['ruta']",
                        "item/Estado": "Revisar",
                        "item/Observaciones": "@trim(concat(coalesce(first(body('Buscar_fila')?['value'])?['Observaciones'], ''), ' Cliente identificado por OCR local; verificar'))",
                    })}},
                    "else": {"actions": {}},
                },
            },
        },
    }
    return definicion(triggers, acciones)


def movidos_json():
    origen = AQUI / "OCR_movidos.csv"
    if not origen.exists():
        return origen, 0
    filas = list(csv.reader(origen.open(encoding="utf-8-sig")))
    ultimo = {}
    for f in filas:
        if len(f) >= 4:
            ultimo[f[1]] = {"archivo": f[1], "cliente": f[2], "ruta": f[3]}
    salida = AQUI / "movidos.json"
    salida.write_text(json.dumps(list(ultimo.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    return salida, len(ultimo)


if __name__ == "__main__":
    empaquetar("Reembolsos - 3 Registro desde OCR local", flujo(), AQUI / "Reembolsos_3_Registro_OCR.zip",
               {ONEDRIVE: "OneDrive for Business", EXCEL: "Excel Online (Business)"})
    salida, n = movidos_json()
    print("paquete: Reembolsos_3_Registro_OCR.zip |", salida.name, "con", n, "entradas")
