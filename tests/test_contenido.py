"""Tipo y fecha por contenido (textos sintéticos)."""
from datetime import date

from reembolsos.contenido import fecha_por_texto, tipo_por_texto

HOY = date(2026, 10, 15)


def test_tipo_por_texto():
    assert tipo_por_texto("Folio fiscal: ABC  Uso del CFDI: G01  Subtotal  IVA") == ("Factura PDF", "FOLIO FISCAL")
    assert tipo_por_texto("RX  Tomar 1 tableta cada 8 horas  Cédula profesional 123")[0] == "Receta"
    assert tipo_por_texto("RESUMEN CLÍNICO  Padecimiento actual ...  Diagnóstico")[0] == "Informe médico"
    assert tipo_por_texto("Biometría hemática  Resultado  Valores de referencia")[0] == "Estudio o resultado"
    assert tipo_por_texto("AVISO DE ACCIDENTE O ENFERMEDAD  Número de siniestro")[0] == "Formato de reclamación"
    assert tipo_por_texto("Instituto Nacional Electoral  Credencial para votar")[0] == "Identificación"
    assert tipo_por_texto("hola, nos vemos el martes") == (None, "")


def test_fecha_por_texto():
    assert fecha_por_texto("Fecha de nacimiento: 01/02/1980   Fecha: 15/03/2026", HOY) == date(2026, 3, 15)
    assert fecha_por_texto("Guadalajara, Jal. a 5 de marzo de 2025", HOY) == date(2025, 3, 5)
    assert fecha_por_texto("Fecha de emisión 2026-03-15T10:00:00", HOY) == date(2026, 3, 15)
    assert fecha_por_texto("Consulta 15-MAR-2026", HOY) == date(2026, 3, 15)
    assert fecha_por_texto("Vigente al 01/01/2030", HOY) is None          # fechas futuras no cuentan
    assert fecha_por_texto("sin fechas", HOY) is None


def test_identificadores_y_prefijos_rfc():
    from reembolsos.contenido import identificadores, prefijos_rfc
    d = identificadores("GNP Seguros  Póliza No. 12345678  Número de siniestro: S-2026-001234  Asegurado titular: JUAN PEREZ LOPEZ "
                        "RFC PELJ800101AB1  Afectado: MARIA PEREZ GARCIA Parentesco hija  correo juan.perez@ejemplo.com  XAXX010101000")
    assert d["rfcs"] == ["PELJ800101AB1"] and d["polizas"] == ["12345678"] and d["siniestros"] == ["S-2026-001234"]
    assert d["aseguradora"] == "GNP" and ["titular", "JUAN PEREZ LOPEZ"] in d["personas"] and ["afectado", "MARIA PEREZ GARCIA"] in d["personas"]
    assert d["correos"] == ["juan.perez@ejemplo.com"]
    assert "PELJ" in prefijos_rfc("JUAN PEREZ LOPEZ") and "PELJ" in prefijos_rfc("PEREZ LOPEZ JUAN")
