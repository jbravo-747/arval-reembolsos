import json
import zipfile
from datetime import date

import pytest

from reembolsos.destino import MARCA, DestinoIncorrecto
from reembolsos.embudo import colocar_paquete


def _paquete(tmp_path, archivos):
    ruta = tmp_path / "ARVAL_EMBUDO_20261030-101500.zip"
    with zipfile.ZipFile(ruta, "w") as zf:
        manifiesto = {"formato": "arval-embudo", "version": 1, "lote": "20261030-101500", "archivos": []}
        for i, a in enumerate(archivos, 1):
            interno = f"archivos/{i:03d}_{a['nombre']}"
            zf.writestr(interno, b"contenido sintetico %d" % i)
            manifiesto["archivos"].append({"id": f"h{i}", "archivo": interno, "fecha_recepcion": "2026-10-30", **a})
        zf.writestr("manifiesto.json", json.dumps(manifiesto))
    return ruta


def test_coloca_en_evento_abierto_y_por_identificar(tmp_path):
    arval = tmp_path / "Arval"
    evento = arval / "ARVAL CLIENTES" / "JUAN PEREZ LOPEZ" / "2026-10_Reembolso 20261025"
    evento.mkdir(parents=True)
    (arval / MARCA).mkdir()
    (evento / "20261025_FACTURA_01.pdf").write_bytes(b"x")
    zip_ruta = _paquete(tmp_path, [
        {"nombre": "factura.pdf", "cliente": "Juan Pérez López", "cartera": "ARVAL CLIENTES", "tipo": "Factura PDF", "fecha_doc": "2026-10-25"},
        {"nombre": "receta.jpg", "cliente": "JUAN PEREZ LOPEZ", "cartera": "ARVAL CLIENTES", "tipo": "Receta", "fecha_doc": ""},
        {"nombre": "foto.jpg", "cliente": None, "tipo": "Otro"},
    ])
    r = colocar_paquete(zip_ruta, arval, hoy=date(2026, 10, 30))
    assert [x["resultado"] for x in r] == ["colocado"] * 3
    assert r[0]["destino"] == "ARVAL CLIENTES/JUAN PEREZ LOPEZ/2026-10_Reembolso 20261025/20261025_FACTURA_02.pdf"
    assert r[1]["destino"] == "ARVAL CLIENTES/JUAN PEREZ LOPEZ/2026-10_Reembolso 20261025/20261030_RECETA_01.jpg"
    assert r[2]["destino"] == "_Por identificar/foto.jpg"
    assert (evento / "20261025_FACTURA_01.pdf").read_bytes() == b"x"   # no pisa lo que ya estaba
    assert len((arval / "_Embudo" / "registro.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_cliente_nuevo_abre_evento_y_no_sobrescribe(tmp_path):
    arval = tmp_path / "Arval"
    (arval / MARCA).mkdir(parents=True)
    datos = {"nombre": "a.pdf", "cliente": "ANA RUIZ", "cartera": "SAYER CLIENTES", "tipo": "Receta", "fecha_doc": "2026-10-29"}
    colocar_paquete(_paquete(tmp_path, [datos]), arval)
    r = colocar_paquete(_paquete(tmp_path, [datos]), arval, hoy=date(2026, 10, 30))
    assert r[0]["destino"] == "SAYER CLIENTES/ANA RUIZ/2026-10_Reembolso 20261030/20261029_RECETA_02.pdf"


def test_no_escribe_en_una_carpeta_sin_marca(tmp_path):
    arval = tmp_path / "Arval"
    arval.mkdir()
    zip_ruta = _paquete(tmp_path, [{"nombre": "a.pdf", "cliente": None, "tipo": "Otro"}])
    with pytest.raises(DestinoIncorrecto):
        colocar_paquete(zip_ruta, arval)
    assert list(arval.iterdir()) == []
