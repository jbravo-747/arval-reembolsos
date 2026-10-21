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
    assert wb.sheetnames == ["Asegurados", "Personas", "Polizas", "Expedientes", "Reclamaciones", "Revisar"]
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


def test_limpieza_de_polizas_personas_y_tipos():
    assert not ag.poliza_valida("21/12/2023") and ag.poliza_valida("49874068")
    assert ag.clave_poliza("00000049874068") == ag.clave_poliza("49874068")
    assert not ag.es_nombre_de_persona("PARTICIPANTE SE AUTORIZA") and not ag.es_nombre_de_persona("HIJO PRIMER APELLIDO ARCINIEGA")
    assert ag.es_nombre_de_persona("MARIA PEREZ GARCIA")
    assert ag.tipo_persona("EDUARDO ARCINEAGA") == "Persona física (nombre incompleto)" and ag.tipo_persona("TECNOVIDRIO").startswith("Empresa")


def test_carga_de_la_revision_y_semilla(tmp_path):
    ruta = tmp_path / "b.xlsx"
    ag.a_excel(ag.construir(ARCHIVOS, EXPEDIENTES), ruta)
    revisados = ag.leer_hoja(ruta, "Asegurados")
    assert ag.filas_catalogo(revisados, "2026-10-21") == []                 # nada aprobado todavía
    semilla = ag.filas_catalogo(revisados, "2026-10-21", semilla=True)
    juan = [f for f in semilla if f["NombreCliente"] == "JUAN PEREZ LOPEZ"][0]
    assert juan["RFC"] == "PELJ800101AB1" and juan["Cartera"] == "CARTERA UNO" and "semilla sin revisar" in juan["Notas"]
    docs = ag.buscador(ruta, semilla=True)
    assert {d["nombre"] for d in docs} == {"JUAN PEREZ LOPEZ", "TECNOVIDRIO"} and not any(d["revisado"] for d in docs)


def test_posible_misma_persona():
    base = {"cartera": "C", "evento": "", "tipo": "Otro", "fecha": "2026-01-01", "fecha_origen": "contenido", "duplicado_de": None, "datos": {}}
    docs = [{**base, "cliente": n} for n in ("FRANCISCO DE LA CRUZ", "FRANCISCO DE LA CRUZ SALAZAR", "MIRIAM OLIVER BUCIO", "MYRIAM OLIVER BUCIO", "ANA LEYVA")]
    r = [x for x in ag.construir(docs, [])["revisar"] if x["Qué revisar"] == "posible misma persona en dos carpetas"]
    assert {(x["Cliente"], x["Detalle"]) for x in r} == {("FRANCISCO DE LA CRUZ", "C / FRANCISCO DE LA CRUZ SALAZAR"), ("MIRIAM OLIVER BUCIO", "C / MYRIAM OLIVER BUCIO")}


def test_nombre_legitimo_y_misma_persona_confirmada():
    base = {"cartera": "C", "evento": "", "tipo": "Otro", "fecha": "2026-01-01", "fecha_origen": "contenido", "duplicado_de": None}
    legit = {"cfdi": {"receptor": "MARIA TERESA COLIN ALVAREZ", "rfc_receptor": "COAT800101AB1"}}
    docs = [{**base, "cliente": "TERESA COLIN", "datos": legit}, {**base, "cliente": "MARIA TERESA COLIN ALVAREZ", "datos": legit}]
    assert ag.nombre_legitimo("TERESA COLIN", [docs[0]]) == ("MARIA TERESA COLIN ALVAREZ", "CFDI (3)")
    h = ag.construir(docs, [])
    assert {a["Nombre en catálogo"] for a in h["asegurados"]} == {"MARIA TERESA COLIN ALVAREZ"}
    assert any(r["Qué revisar"].startswith("misma persona en dos carpetas (confirmado") for r in h["revisar"])


def test_relaciones_de_lau_se_leen_sin_datos_clinicos_y_se_corroboran(tmp_path):
    import openpyxl
    from reembolsos import relaciones as rl
    d = tmp_path / "C" / "JUAN PEREZ LOPEZ" / "REEMBOLSO 1"
    d.mkdir(parents=True)
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["PADECIMIENTO", "RECLAMACION", "CONCEPTO", "DESCRIPCIÓN", "FACTURA", "FECHA DE DOCUMENTO", "MONTO", "FECHA DE INGRESO", "FOLIO", "ESTATUS"])
    ws.append(["dato clínico", "R-1", "FACTURA FARMACIA SAN PABLO", "dato clínico", "A123", "2026-03-10", 700, "2026-03-15", "F-99", "PAGADA"])
    ws.append(["dato clínico", "R-1", "FACTURA HONORARIOS MEDICOS", "dato clínico", "B9", "2026-03-11", 1500, "2026-03-15", "F-99", "EN PROCESO"])
    wb.save(d / "relacion.xlsx")
    filas = rl.leer_relaciones(tmp_path)
    assert len(filas) == 2 and not any("clínico" in str(v) for f in filas for v in f.values())
    assert filas[0]["estatus"] == "Pagado" and filas[0]["categoria"] == "Farmacia" and filas[1]["estatus"] == "En proceso"
    indice = {("C", "JUAN PEREZ LOPEZ"): [{"ruta": "x.xml", "folio": "A123", "total": 700.0, "fecha": "2026-03-10", "evento": "REEMBOLSO 1"},
                                          {"ruta": "y.pdf", "folio": "", "total": 1500.0, "fecha": "2026-03-12", "evento": "REEMBOLSO 1"}]}
    rl.corroborar(filas, indice)
    assert [f["corroboracion"] for f in filas] == ["confirmada por folio", "confirmada por monto y fecha"]
    h = ag.agregar_reclamaciones(ag.construir(ARCHIVOS, EXPEDIENTES), [{**f, "cartera": "CARTERA UNO"} for f in filas])
    juan = [a for a in h["asegurados"] if a["Cliente"] == "JUAN PEREZ LOPEZ"][0]
    assert juan["Facturas en relación"] == 2 and juan["Confirmadas con documento"] == 2 and juan["Monto reclamado"] == 2200.0
    assert h["expedientes"][0]["Reclamación (Lau)"] == "R-1" and list(juan)[-1] == "Notas de Lau"
