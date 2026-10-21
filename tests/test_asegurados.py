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
    assert juan["Correo probable"] == "juan@ejemplo.com" and juan["Otros correos en sus documentos"] == "" and juan["Expedientes"] == 1 and juan["Con faltantes"] == 1
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


def test_conflictos_se_clasifican():
    base = {"cartera": "C", "evento": "", "tipo": "Otro", "fecha": "2026-01-01", "fecha_origen": "contenido", "duplicado_de": None, "datos": {},
            "conflicto": True}
    docs = [{**base, "cliente": f"EMPLEADO NUMERO {i}", "cliente_contenido": "SAYER LACK"} for i in range(5)]
    docs += [{**base, "cliente": "ANA MARIA PEREZ LOPEZ", "cliente_contenido": "JUAN PEREZ LOPEZ"} for _ in range(3)]
    docs += [{**base, "cliente": "LUIS SOTO RUIZ", "cliente_contenido": "PEDRO DIAZ MORA"}]
    docs += [{**base, "cliente": "LUIS SOTO RUIZ", "cliente_contenido": "MIGUEL ANGEL"}]
    c = ag.clasificar_conflictos(docs)
    assert c[("C", "EMPLEADO NUMERO 0", "SAYER LACK")][0] == "contratante o agente"
    assert c[("C", "ANA MARIA PEREZ LOPEZ", "JUAN PEREZ LOPEZ")] == ("familiar o titular", 3)
    assert c[("C", "LUIS SOTO RUIZ", "PEDRO DIAZ MORA")][0] == "posible error"
    assert c[("C", "LUIS SOTO RUIZ", "MIGUEL ANGEL")][0] == "genérico"
    h = ag.construir(docs, [])
    assert any(p["Persona"] == "JUAN PEREZ LOPEZ" for p in h["personas"]) and any("PEDRO DIAZ MORA" in r["Detalle"] for r in h["revisar"])


def test_correo_del_cliente():
    assert ag.correo_del_cliente("hilda.reyna80@gmail.com", "HILDA REYNA INES ROLDAN")
    assert not ag.correo_del_cliente("contacto@laboratorio.com", "HILDA REYNA INES ROLDAN")
