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
