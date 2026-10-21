"""Base de asegurados a partir de documentos analizados (datos sintéticos)."""
from reembolsos import asegurados as ag


def _doc(cliente, evento, datos, tipo="Factura PDF", fecha="2026-03-10"):
    return {"cartera": "CARTERA UNO", "cliente": cliente, "evento": evento, "tipo": tipo, "fecha": fecha, "fecha_origen": "contenido",
            "duplicado_de": None, "datos": datos}


ARCHIVOS = [
    _doc("JUAN PEREZ LOPEZ", "REEMBOLSO 1", {"rfcs": ["PELJ800101AB1", "FAR010101AAA"], "aseguradora": "GNP", "polizas": ["12345678"],
                                             "siniestros": ["S-1001"], "personas": [["titular", "JUAN PEREZ LOPEZ"], ["afectado", "MARIA PEREZ GARCIA"]],
                                             "correos": ["juan@ejemplo.com"]}),
    _doc("JUAN PEREZ LOPEZ", "REEMBOLSO 1", {"rfcs": ["PELJ800101AB1"], "aseguradora": "GNP", "polizas": ["12345678"], "siniestros": [],
                                             "personas": [["afectado", "MARIA PEREZ GARCIA"]], "correos": []}),
    _doc("JUAN PEREZ LOPEZ", "REEMBOLSO 1", {"cfdi": {"receptor": "JUAN PEREZ LOPEZ", "rfc_receptor": "PELJ800101AB1", "total": "700.00"}}, tipo="CFDI factura"),
    _doc("TECNOVIDRIO", "", {"rfcs": ["TEC990101AB1"], "aseguradora": "AXA", "polizas": [], "siniestros": [], "personas": [], "correos": []}),
]
EXPEDIENTES = [{"cartera": "CARTERA UNO", "cliente": "JUAN PEREZ LOPEZ", "evento": "REEMBOLSO 1", "inicio": "2026-03-01", "ultimo": "2026-03-10",
                "documentos": 3, "tipos": ["CFDI factura", "Factura PDF"], "faltantes": ["receta"], "conflictos": 0, "por_leer": 0}]


def test_construye_asegurados_personas_polizas_y_expedientes():
    h = ag.construir(ARCHIVOS, EXPEDIENTES)
    juan = [a for a in h["asegurados"] if a["Cliente"] == "JUAN PEREZ LOPEZ"][0]
    assert juan["Tipo"] == "Persona física" and juan["RFC"] == "PELJ800101AB1" and juan["Confianza RFC"].startswith("alta")
    assert juan["Aseguradora principal"] == "GNP" and juan["Pólizas"] == "12345678" and juan["Titular es el cliente"] == "sí"
    assert juan["Correos encontrados"] == "juan@ejemplo.com" and juan["Expedientes"] == 1 and juan["Con faltantes"] == 1
    assert [p["Persona"] for p in h["personas"]] == ["MARIA PEREZ GARCIA"]
    assert h["polizas"][0]["Aseguradora"] == "GNP"
    exp = h["expedientes"][0]
    assert exp["Aseguradora"] == "GNP" and exp["Siniestro(s)"] == "S-1001" and exp["Total CFDI"] == 700.0
    tec = [a for a in h["asegurados"] if a["Cliente"] == "TECNOVIDRIO"][0]
    assert tec["Tipo"].startswith("Empresa") and tec["RFC"] == ""
    assert any(r["Cliente"] == "TECNOVIDRIO" for r in h["revisar"])


def test_excel(tmp_path):
    import openpyxl
    ag.a_excel(ag.construir(ARCHIVOS, EXPEDIENTES), tmp_path / "b.xlsx")
    wb = openpyxl.load_workbook(tmp_path / "b.xlsx")
    assert wb.sheetnames == ["Asegurados", "Personas", "Polizas", "Expedientes", "Revisar"]
    assert "tblAsegurados" in wb["Asegurados"].tables
