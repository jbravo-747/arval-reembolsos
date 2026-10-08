from reembolsos.catalogo import Catalogo, candidatos_en_texto, normalizar

FILAS = [
    {"Correo": "ana@example.com", "NombreCliente": "Ana María Pérez López", "Tipo": "", "Alias": "ANA M PEREZ", "RFC": "PELA800101AB1"},
    {"Correo": "escaner@example.com", "NombreCliente": "Escaner Oficina", "Tipo": "Escaner", "Alias": "", "RFC": ""},
    {"Correo": "avisos@example.com", "NombreCliente": "Avisos Aseguradora", "Tipo": "Aviso", "Alias": "", "RFC": ""},
    {"Correo": "jose@example.com", "NombreCliente": "José Luis Ramírez", "Tipo": "Cliente", "Alias": "", "RFC": ""},
]


def test_normalizar_quita_acentos_y_mayusculas():
    assert normalizar("  Ana María  Pérez-López ") == "ANA MARIA PEREZ LOPEZ"


def test_remitente_conocido_solo_si_es_cliente():
    c = Catalogo(FILAS)
    assert c.por_remitente("ANA@example.com").nombre == "Ana María Pérez López"
    assert c.por_remitente("escaner@example.com") is None
    assert c.remitente_ignorado("avisos@example.com")


def test_resolver_exacta_por_nombre_alias_y_rfc():
    c = Catalogo(FILAS)
    assert c.resolver("Factura a nombre de ANA MARIA PEREZ LOPEZ") == ("Ana María Pérez López", "exacta")
    assert c.resolver("Receptor: Ana M Perez")[1] == "exacta"
    assert c.resolver("RFC PELA800101AB1 total 500") == ("Ana María Pérez López", "exacta")


def test_resolver_parcial_y_sin_coincidencia():
    c = Catalogo(FILAS)
    assert c.resolver("Paciente: Ramírez, José Luis") == ("José Luis Ramírez", "parcial")
    assert c.resolver("sin nadie conocido")[0] is None


def test_no_clientes_no_participan():
    c = Catalogo(FILAS)
    assert c.resolver("ESCANER OFICINA")[0] is None


def test_candidatos_en_texto():
    cands = candidatos_en_texto("Póliza 123 ASEGURADO: MARTHA ELENA GOMEZ RUIZ RFC GORM900101 Fecha 2026")
    assert cands == ["MARTHA ELENA GOMEZ RUIZ"]
