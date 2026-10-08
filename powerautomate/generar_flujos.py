"""Genera los paquetes de los flujos 1 (Ingesta) y 2 (Resumen diario) del plan.

Uso:
    python generar_flujos.py <DRIVE_ID> <FILE_ID_CONTROL> [CORREO_RESUMEN]

Sigue los pasos 2.1 a 2.9 (sin el 2.7, clasificación con IA) y 3.1 a 3.2 del plan.
Diferencias respecto al plan, ya probadas en el flujo de inventario:
- La hora local se calcula con addHours(..., -6) en lugar de convertFromUtc.
- Las acciones de Excel llevan el identificador interno del OneDrive y del archivo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generar import conector, definicion, empaquetar  # noqa: E402

OUT = Path(__file__).parent / "salida"
EXCEL = "shared_excelonlinebusiness"
ONEDRIVE = "shared_onedriveforbusiness"
OUTLOOK = "shared_office365"
CONECTORES = {
    OUTLOOK: "Office 365 Outlook",
    EXCEL: "Excel Online (Business)",
    ONEDRIVE: "OneDrive for Business",
}

DRIVE = sys.argv[1]
ARCHIVO = sys.argv[2]
CORREO_RESUMEN = sys.argv[3] if len(sys.argv) > 3 else "soluciones@arval.com.mx"

RECIBIDO = "triggerOutputs()?['body/receivedDateTime']"


# ---------- Ayudantes ----------

def excel(operacion, tabla, extra):
    return conector(EXCEL, operacion, {
        "source": "me", "drive": DRIVE, "file": ARCHIVO, "table": tabla, **extra})


def listar(tabla, filtro):
    return {"type": "OpenApiConnection", "inputs": excel("GetItems", tabla, {"$filter": filtro})}


def fila(columnas):
    return {"type": "OpenApiConnection",
            "inputs": excel("AddRowV2", "tblRegistro", {f"item/{k}": v for k, v in columnas.items()})}


def var(nombre, valor):
    # El editor de Power Automate no deja guardar un "Establecer variable" con valor vacío;
    # trim(' ') produce la cadena vacía y sí pasa la validación.
    if valor == "":
        valor = "@trim(' ')"
    return {"type": "SetVariable", "inputs": {"name": nombre, "value": valor}}


def compose(valor):
    return {"type": "Compose", "inputs": valor}


def condicion(expresion, si, no=None):
    return {"type": "If", "expression": expresion, "actions": si, "else": {"actions": no or {}}}


def encadenar(acciones):
    """Asigna runAfter secuencial a un dict ordenado de acciones (las que no lo tengan)."""
    previa = None
    for nombre, accion in acciones.items():
        if "runAfter" not in accion:
            accion["runAfter"] = {previa: ["Succeeded"]} if previa else {}
        previa = nombre
    return acciones


def norm(expr):
    """Mayúsculas sin acentos, para comparar nombres escritos de distintas formas."""
    e = f"toLower(coalesce({expr}, ''))"
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        e = f"replace({e}, '{a}', '{b}')"
    return f"toUpper({e})"


def asignar_cliente(sufijo, nombre_expr, como):
    """Fija varCliente/varCarpeta/varEstadoBase a partir de un nombre del catálogo."""
    return encadenar({
        f"Set_varCliente_{sufijo}": var("varCliente", f"@trim({nombre_expr})"),
        f"Set_varCarpeta_{sufijo}": var("varCarpeta", "@concat(variables('varRutaBase'), '/Clientes/', variables('varCliente'), '/', substring(variables('varFechaLocal'), 0, 7))"),
        f"Set_varEstadoBase_{sufijo}": var("varEstadoBase", "Revisar"),
        f"Set_varIdentificacion_{sufijo}": var("varIdentificacion", como),
    })


def crear_archivo(bucle, id_accion):
    return {"type": "OpenApiConnection", "inputs": conector(ONEDRIVE, "CreateFile", {
        "folderPath": "@variables('varCarpeta')",
        "name": f"@concat(variables('varPrefijo'), '_', substring(outputs('{id_accion}'), 0, 6), '_', items('{bucle}')?['name'])",
        "body": f"@base64ToBinary(items('{bucle}')?['contentBytes'])",
    })}


def columnas_comunes(bucle, id_accion, crear=None):
    c = {
        "ID": f"@outputs('{id_accion}')",
        "FechaRecepcion": "@variables('varFechaLocal')",
        "HoraRecepcion": "@variables('varHoraLocal')",
        "IdCorreo": "@triggerOutputs()?['body/id']",
        "Remitente": "@variables('varRemitente')",
        "Cliente": "@variables('varCliente')",
        "Asunto": "@triggerOutputs()?['body/subject']",
        "NombreOriginal": f"@items('{bucle}')?['name']",
        "TamanoBytes": f"@string(items('{bucle}')?['size'])",
        "EnResumen": "No",
    }
    if crear:
        c["NombreGuardado"] = f"@body('{crear}')?['Name']"
        c["Ruta"] = f"@body('{crear}')?['Path']"
        c["Enlace"] = f"@body('Enlace_{crear}')?['WebUrl']"
    return c


def crear_enlace(crear):
    """Vínculo de solo lectura para cuentas de la organización al archivo recién creado."""
    return {"type": "OpenApiConnection", "inputs": conector(ONEDRIVE, "CreateShareLink", {
        "id": f"@body('{crear}')?['Id']", "type": "view", "scope": "organization"})}


# ---------- Flujo 1: Ingesta ----------

def variables_iniciales():
    local = f"addHours({RECIBIDO}, -6)"
    lista = [
        ("varCorreoOperadora", "String", "soluciones@arval.com.mx"),
        ("varRutaBase", "String", "/Reembolsos"),
        ("varPermitirMover", "Boolean", False),
        ("varRemitente", "String", "@toLower(triggerOutputs()?['body/from'])"),
        ("varFechaLocal", "String", f"@formatDateTime({local}, 'yyyy-MM-dd')"),
        ("varHoraLocal", "String", f"@formatDateTime({local}, 'HH:mm')"),
        ("varPrefijo", "String", f"@formatDateTime({local}, 'yyyyMMdd_HHmm')"),
        ("varCliente", "String", None),
        ("varCarpeta", "String", None),
        ("varEstadoBase", "String", None),
        ("varAdjuntosProcesados", "Integer", 0),
        ("varDuplicadosExactos", "Integer", 0),
        ("varHayPosible", "Boolean", False),
        ("varBaseDupExactos", "Array", []),
        ("varDupActual", "String", None),
        ("varIdOriginal", "String", None),
        ("varTipo", "String", None),
        ("varConfianza", "String", None),
        ("varMotivo", "String", None),
        ("varIdentificacion", "String", None),
    ]
    acciones = {}
    for nombre, tipo, valor in lista:
        v = {"name": nombre, "type": tipo}
        if valor is not None:
            v["value"] = valor
        acciones[nombre] = {"type": "InitializeVariable", "inputs": {"variables": [v]}}
    return acciones


def identificar_cliente():
    # Solo cuenta como cliente si tiene nombre y su Tipo está vacío o es "Cliente".
    # Otros tipos (Escaner, Aseguradora, Aviso) se identifican por el nombre en el texto o en el CFDI.
    conocido = ("@and(greater(length(body('Buscar_cliente')?['value']), 0), "
                "not(empty(first(body('Buscar_cliente')?['value'])?['NombreCliente'])), "
                "or(empty(first(body('Buscar_cliente')?['value'])?['Tipo']), "
                "equals(toLower(first(body('Buscar_cliente')?['value'])?['Tipo']), 'cliente')))")
    texto = "@" + norm("concat(triggerOutputs()?['body/subject'], ' ', triggerOutputs()?['body/bodyPreview'], ' ', join(body('Nombres_adjuntos'), ' '))")
    coincide_nombre = ("@and(not(empty(item()?['NombreCliente'])), or("
                       f"contains(outputs('Texto_busqueda'), {norm("item()?['NombreCliente']")}), "
                       f"and(not(empty(item()?['Alias'])), contains(outputs('Texto_busqueda'), {norm("item()?['Alias']")}))))")
    remitente_nuevo = ("@and(equals(length(body('Buscar_cliente')?['value']), 0), "
                       "not(endsWith(variables('varRemitente'), '@arval.com.mx')))")
    return {
        "Buscar_cliente": listar("tblClientes", "Correo eq '@{variables('varRemitente')}'"),
        "Catalogo": {"type": "OpenApiConnection", "inputs": excel("GetItems", "tblClientes", {}),
                     "runtimeConfiguration": {"paginationPolicy": {"minimumItemCount": 5000}}},
        "Nombres_adjuntos": {"type": "Select", "inputs": {
            "from": "@coalesce(triggerOutputs()?['body/attachments'], createArray())", "select": "@item()?['name']"}},
        "Texto_busqueda": compose(texto),
        "Cliente_conocido": condicion(
            conocido,
            encadenar({
                "Set_varCliente": var("varCliente", "@trim(first(body('Buscar_cliente')?['value'])?['NombreCliente'])"),
                "Set_varCarpeta": var("varCarpeta", "@concat(variables('varRutaBase'), '/Clientes/', variables('varCliente'), '/', substring(variables('varFechaLocal'), 0, 7))"),
                "Set_varEstadoBase": var("varEstadoBase", "Recibido"),
                "Set_varIdentificacion": var("varIdentificacion", "Cliente identificado por remitente"),
            }),
            encadenar({
                "Set_varCarpeta_desconocido": var("varCarpeta", "@concat(variables('varRutaBase'), '/_Por identificar')"),
                "Set_varEstadoBase_desconocido": var("varEstadoBase", "Cliente desconocido"),
                # Buscar el nombre de algún cliente del catálogo en asunto, vista previa y nombres de archivo.
                "Clientes_en_texto": {"type": "Query", "inputs": {"from": "@body('Catalogo')?['value']", "where": coincide_nombre}},
                "Sel_nombres_texto": {"type": "Select", "inputs": {"from": "@body('Clientes_en_texto')", "select": "@item()?['NombreCliente']"}},
                "Cliente_por_texto": condicion(
                    {"and": [{"equals": ["@length(body('Clientes_en_texto'))", 1]}]},
                    asignar_cliente("texto", "first(body('Clientes_en_texto'))?['NombreCliente']",
                                    "Cliente identificado por nombre en asunto/cuerpo/archivo; verificar"),
                    {"Varios_nombres": condicion(
                        {"and": [{"greater": ["@length(body('Clientes_en_texto'))", 1]}]},
                        {"Set_varIdentificacion_varios": {"runAfter": {}, **var("varIdentificacion",
                            "@concat('Varios clientes posibles en el texto: ', join(body('Sel_nombres_texto'), ', '))")}},
                    )}),
                # Remitente nuevo: se agrega al catálogo sin nombre para que Lau lo complete.
                "Remitente_nuevo": condicion(remitente_nuevo, {
                    "Agregar_a_catalogo": {"runAfter": {}, "type": "OpenApiConnection",
                                           "inputs": excel("AddRowV2", "tblClientes", {
                                               "item/Correo": "@variables('varRemitente')",
                                               "item/NombreCliente": "",
                                               "item/Notas": "@concat('Pendiente de nombre. Primer correo ', variables('varFechaLocal'))"})},
                }),
            }),
        ),
    }


def separar_adjuntos():
    desde = "@triggerOutputs()?['body/attachments']"
    return {
        "Adjuntos_XML": {"type": "Query", "inputs": {
            "from": desde,
            "where": "@and(equals(item()?['isInline'], false), endsWith(toLower(item()?['name']), '.xml'))"}},
        "Adjuntos_otros": {"type": "Query", "inputs": {
            "from": desde,
            # Imágenes: se descartan las menores de 15 KB (firmas). Las incrustadas en el cuerpo
            # solo se conservan si pesan más de 100 KB (fotos de recetas pegadas en el correo).
            # Se ignoran .htm/.html (copias del cuerpo que anexa GNP), .ics y .vcf.
            "where": "@and(not(endsWith(toLower(item()?['name']), '.xml')), not(or(endsWith(toLower(item()?['name']), '.htm'), endsWith(toLower(item()?['name']), '.html'), endsWith(toLower(item()?['name']), '.ics'), endsWith(toLower(item()?['name']), '.vcf'))), or(not(startsWith(toLower(item()?['contentType']), 'image/')), greater(item()?['size'], 15000)), or(equals(item()?['isInline'], false), greater(item()?['size'], 100000)))"}},
        "Set_varAdjuntosProcesados": var("varAdjuntosProcesados", "@add(length(body('Adjuntos_XML')), length(body('Adjuntos_otros')))"),
    }


def bucle_xml():
    b = "Bucle_XML"
    comunes = columnas_comunes(b, "ID_XML")
    comunes_guardado = columnas_comunes(b, "ID_XML", "Crear_archivo_XML")
    comunes_nocfdi = columnas_comunes(b, "ID_XML", "Crear_archivo_noCFDI")

    rama_duplicado = encadenar({
        "Incrementar_dup_XML": {"type": "IncrementVariable", "inputs": {"name": "varDuplicadosExactos", "value": 1}},
        "Anexar_BaseNombre": {"type": "AppendToArrayVariable", "inputs": {"name": "varBaseDupExactos", "value": "@outputs('BaseNombre')"}},
        "Fila_XML_duplicado": fila({**comunes,
            "TipoDocumento": "CFDI", "UUID_CFDI": "@outputs('UUID')", "Duplicado": "Exacto",
            "IdOriginal": "@first(body('Buscar_UUID')?['value'])?['ID']", "Estado": "Descartado - duplicado"}),
    })
    rama_nuevo = encadenar({
        "Crear_archivo_XML": crear_archivo(b, "ID_XML"),
        "Enlace_Crear_archivo_XML": crear_enlace("Crear_archivo_XML"),
        "Fila_XML_nuevo": fila({**comunes_guardado,
            "UUID_CFDI": "@outputs('UUID')", "RFC_Emisor": "@outputs('RFC')", "Emisor": "@outputs('Emisor')",
            "Total": "@outputs('Total')", "FechaCFDI": "@outputs('FechaCFDI')", "Duplicado": "No",
            "Estado": "@variables('varEstadoBase')", "Observaciones": "@variables('varIdentificacion')",
            "TipoDocumento": "@if(not(equals(outputs('TipoComprobante'), 'I')), 'CFDI otro', if(equals(length(outputs('RFC')), 13), 'CFDI recibo de honorarios', 'CFDI factura'))"}),
    })
    rama_cfdi = encadenar({
        "Buscar_UUID": listar("tblRegistro", "UUID_CFDI eq '@{outputs('UUID')}'"),
        "UUID_registrado": condicion(
            {"and": [{"greater": ["@length(body('Buscar_UUID')?['value'])", 0]}]},
            rama_duplicado, rama_nuevo),
    })
    rama_no_cfdi = encadenar({
        "Crear_archivo_noCFDI": crear_archivo(b, "ID_XML"),
        "Enlace_Crear_archivo_noCFDI": crear_enlace("Crear_archivo_noCFDI"),
        "Fila_noCFDI": fila({**comunes_nocfdi, "TipoDocumento": "Otro", "Duplicado": "No",
                             "Estado": "Revisar", "Observaciones": "XML sin timbre fiscal"}),
    })
    acciones = encadenar({
        "ID_XML": compose("@guid()"),
        "TextoXML": compose(f"@base64ToString(items('{b}')?['contentBytes'])"),
        "XML": compose("@xml(substring(outputs('TextoXML'), indexOf(outputs('TextoXML'), '<')))"),
        "UUID": compose("@toUpper(xpath(outputs('XML'), 'string(//*[local-name()=\"TimbreFiscalDigital\"]/@UUID)'))"),
        "RFC": compose("@xpath(outputs('XML'), 'string(//*[local-name()=\"Emisor\"]/@Rfc)')"),
        "Emisor": compose("@xpath(outputs('XML'), 'string(//*[local-name()=\"Emisor\"]/@Nombre)')"),
        "Total": compose("@xpath(outputs('XML'), 'string(/*[local-name()=\"Comprobante\"]/@Total)')"),
        "FechaCFDI": compose("@xpath(outputs('XML'), 'string(/*[local-name()=\"Comprobante\"]/@Fecha)')"),
        "TipoComprobante": compose("@xpath(outputs('XML'), 'string(/*[local-name()=\"Comprobante\"]/@TipoDeComprobante)')"),
        "Receptor": compose("@xpath(outputs('XML'), 'string(//*[local-name()=\"Receptor\"]/@Nombre)')"),
        "RFC_Receptor": compose("@toUpper(xpath(outputs('XML'), 'string(//*[local-name()=\"Receptor\"]/@Rfc)'))"),
        "Clientes_CFDI": {"type": "Query", "inputs": {"from": "@body('Catalogo')?['value']", "where": (
            "@or(and(not(empty(item()?['RFC'])), equals(toUpper(trim(item()?['RFC'])), outputs('RFC_Receptor'))), "
            f"and(not(empty(item()?['NombreCliente'])), contains({norm("outputs('Receptor')")}, {norm("item()?['NombreCliente']")})), "
            f"and(not(empty(item()?['Alias'])), contains({norm("outputs('Receptor')")}, {norm("item()?['Alias']")})))")}},
        "Cliente_por_CFDI": condicion(
            {"and": [{"equals": ["@empty(variables('varCliente'))", True]}, {"equals": ["@length(body('Clientes_CFDI'))", 1]}]},
            asignar_cliente("cfdi", "first(body('Clientes_CFDI'))?['NombreCliente']",
                            "Cliente identificado por el Receptor del CFDI; verificar")),
        "BaseNombre": compose(f"@toLower(substring(items('{b}')?['name'], 0, lastIndexOf(items('{b}')?['name'], '.')))"),
        "Es_CFDI": condicion({"and": [{"not": {"equals": ["@outputs('UUID')", ""]}}]}, rama_cfdi, rama_no_cfdi),
    })
    return {b: {"type": "Foreach", "foreach": "@body('Adjuntos_XML')", "actions": acciones,
                "runtimeConfiguration": {"concurrency": {"repetitions": 1}}}}


def bucle_otros():
    b = "Bucle_otros"
    comunes = columnas_comunes(b, "ID_otro")
    comunes_guardado = columnas_comunes(b, "ID_otro", "Crear_archivo_otro")

    rama_pdf_dup = encadenar({
        "Incrementar_dup_otro": {"type": "IncrementVariable", "inputs": {"name": "varDuplicadosExactos", "value": 1}},
        "Fila_PDF_duplicado": fila({**comunes, "TipoDocumento": "Factura PDF", "Duplicado": "Exacto",
                                    "Estado": "Descartado - duplicado",
                                    "Observaciones": "Representación impresa de CFDI duplicado"}),
    })
    rama_normal = encadenar({
        "Buscar_nombre": listar("tblRegistro", f"NombreOriginal eq '@{{replace(items('{b}')?['name'], '''', '''''')}}'"),
        "Coincidencias": {"type": "Query", "inputs": {
            "from": "@body('Buscar_nombre')?['value']",
            "where": f"@and(equals(item()?['Cliente'], variables('varCliente')), equals(item()?['TamanoBytes'], string(items('{b}')?['size'])))"}},
        "Posible_duplicado": condicion(
            {"and": [{"greater": ["@length(body('Coincidencias'))", 0]}]},
            encadenar({
                "Set_varDupActual_posible": var("varDupActual", "Posible"),
                "Set_varHayPosible": var("varHayPosible", True),
                "Set_varIdOriginal_posible": var("varIdOriginal", "@first(body('Coincidencias'))?['ID']"),
            })),
        "Crear_archivo_otro": crear_archivo(b, "ID_otro"),
        "Enlace_Crear_archivo_otro": crear_enlace("Crear_archivo_otro"),
        "Fila_otro": fila({**comunes_guardado,
            "TipoDocumento": "@variables('varTipo')", "Confianza": "@variables('varConfianza')",
            "Observaciones": "@trim(concat(variables('varMotivo'), ' ', variables('varIdentificacion')))", "Duplicado": "@variables('varDupActual')",
            "IdOriginal": "@variables('varIdOriginal')",
            "Estado": "@if(empty(variables('varCliente')), 'Cliente desconocido', if(or(equals(variables('varEstadoBase'), 'Revisar'), equals(variables('varDupActual'), 'Posible'), equals(variables('varTipo'), 'Sin clasificar'), equals(variables('varConfianza'), 'baja')), 'Revisar', 'Recibido'))"}),
    })
    acciones = encadenar({
        "Reset_varTipo": var("varTipo", "Sin clasificar"),
        "Reset_varConfianza": var("varConfianza", ""),
        "Reset_varMotivo": var("varMotivo", ""),
        "Reset_varDupActual": var("varDupActual", "No"),
        "Reset_varIdOriginal": var("varIdOriginal", ""),
        "ID_otro": compose("@guid()"),
        "BaseNombre_otro": compose(f"@toLower(substring(items('{b}')?['name'], 0, lastIndexOf(items('{b}')?['name'], '.')))"),
        "PDF_de_CFDI_duplicado": condicion(
            {"and": [{"equals": ["@contains(variables('varBaseDupExactos'), outputs('BaseNombre_otro'))", True]}]},
            rama_pdf_dup, rama_normal),
    })
    return {b: {"type": "Foreach", "foreach": "@body('Adjuntos_otros')", "actions": acciones,
                "runtimeConfiguration": {"concurrency": {"repetitions": 1}}}}


def sin_documentos():
    """Si el correo no trajo ningún documento útil (sin adjuntos, o solo firmas/htm), se registra
    una fila por correo para que Lau tenga el registro completo de lo recibido."""
    nombres = "@if(empty(body('Nombres_adjuntos')), '(sin adjuntos)', join(body('Nombres_adjuntos'), ' | '))"
    observ = ("@if(empty(body('Nombres_adjuntos')), 'Correo sin adjuntos', "
              "concat('Adjuntos ignorados (firmas, imágenes pequeñas o htm): ', join(body('Nombres_adjuntos'), ', ')))")
    return {
        "Sin_documentos": condicion(
            {"and": [{"equals": ["@variables('varAdjuntosProcesados')", 0]}]},
            {"Fila_sin_documentos": {"runAfter": {}, **fila({
                "ID": "@guid()",
                "FechaRecepcion": "@variables('varFechaLocal')", "HoraRecepcion": "@variables('varHoraLocal')",
                "IdCorreo": "@triggerOutputs()?['body/id']", "Remitente": "@variables('varRemitente')",
                "Cliente": "@variables('varCliente')", "Asunto": "@triggerOutputs()?['body/subject']",
                "NombreOriginal": nombres, "TamanoBytes": "0",
                "TipoDocumento": "Correo sin documentos", "Duplicado": "No",
                "Estado": "Sin documentos", "Observaciones": "@trim(concat(" + observ[1:] + ", ' ', variables('varIdentificacion')))", "EnResumen": "No",
            })}}),
    }


def mover_correo():
    mover = lambda carpeta: {"type": "OpenApiConnection", "inputs": conector(OUTLOOK, "Move", {
        "messageId": "@triggerOutputs()?['body/id']", "folderPath": carpeta})}
    return {
        "Todo_duplicado": condicion(
            "@and(greater(variables('varAdjuntosProcesados'), 0), equals(variables('varDuplicadosExactos'), variables('varAdjuntosProcesados')))",
            {"Mover_papelera": condicion(
                {"and": [{"equals": ["@variables('varPermitirMover')", True]}]},
                {"Mover_a_eliminados": {"runAfter": {}, **mover("DeletedItems")}})},
            {"Mover_revisar": condicion(
                "@and(variables('varHayPosible'), variables('varPermitirMover'))",
                {"Mover_a_duplicados": {"runAfter": {}, **mover("Duplicados - revisar")}})},
        )
    }


def flujo_ingesta():
    triggers = {
        "Cuando_llega_un_nuevo_correo": {
            "splitOn": "@triggerOutputs()?['body/value']",
            "type": "OpenApiConnectionNotification",
            "inputs": conector(OUTLOOK, "OnNewEmailV3", {
                "folderPath": "Inbox", "importance": "Any",
                "fetchOnlyWithAttachment": False, "includeAttachments": True}),
            "runtimeConfiguration": {"concurrency": {"runs": 1}},
        }
    }
    proceso = encadenar({**identificar_cliente(), **separar_adjuntos(), **bucle_xml(), **bucle_otros(), **sin_documentos(), **mover_correo()})
    acciones = encadenar({
        **variables_iniciales(),
        "Proceso": {"type": "Scope", "actions": proceso},
    })
    acciones["Si_falla"] = {
        "type": "Scope",
        "runAfter": {"Proceso": ["Failed", "TimedOut"]},
        "actions": {"Fila_error": {"runAfter": {}, **fila({
            "ID": "@guid()",
            "FechaRecepcion": "@variables('varFechaLocal')", "HoraRecepcion": "@variables('varHoraLocal')",
            "IdCorreo": "@triggerOutputs()?['body/id']", "Remitente": "@variables('varRemitente')",
            "Cliente": "@variables('varCliente')", "Asunto": "@triggerOutputs()?['body/subject']",
            "Estado": "Error", "EnResumen": "No",
            "Observaciones": "@concat('Falló la ejecución ', workflow()?['run']?['name'], '. Revisar historial del flujo.')",
        })}},
    }
    return definicion(triggers, acciones)


# ---------- Flujo 2: Resumen diario ----------

def flujo_resumen():
    triggers = {
        "Recurrence": {
            "type": "Recurrence",
            "recurrence": {
                "frequency": "Week", "interval": 1,
                "schedule": {"hours": ["8"], "minutes": [0],
                             "weekDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
                "timeZone": "Central Standard Time (Mexico)",
            },
        }
    }
    mapeo = {"Fecha": "@item()?['FechaRecepcion']", "Hora": "@item()?['HoraRecepcion']",
             "Cliente": "@item()?['Cliente']", "Tipo": "@item()?['TipoDocumento']",
             "Archivo": "@item()?['NombreOriginal']", "Estado": "@item()?['Estado']",
             "Notas": "@item()?['Observaciones']"}
    filtro = lambda where: {"type": "Query", "inputs": {"from": "@body('Pendientes')?['value']", "where": where}}
    sel = lambda origen: {"type": "Select", "inputs": {"from": f"@body('{origen}')", "select": mapeo}}
    tabla = lambda origen: {"type": "Table", "inputs": {"from": f"@body('{origen}')", "format": "HTML"}}
    cuerpo = (
        "<p><b>Nuevos:</b> @{length(body('Nuevos'))} &nbsp; <b>Por revisar:</b> @{length(body('Por_revisar'))} "
        "&nbsp; <b>Descartados por duplicado:</b> @{length(body('Descartados'))} "
        "&nbsp; <b>Correos sin documentos:</b> @{length(body('Sin_documentos'))}</p>"
        "<h3>Por revisar</h3>@{body('Tabla_revisar')}"
        "<h3>Nuevos</h3>@{body('Tabla_nuevos')}"
        "<h3>Descartados (están en Elementos eliminados si hay que recuperarlos)</h3>@{body('Tabla_descartados')}"
        "<h3>Correos sin documentos (avisos, respuestas, firmas)</h3>@{body('Tabla_sin_documentos')}"
        "<p>El registro completo está en Reembolsos/Control_Reembolsos.xlsx</p>"
    )
    acciones = encadenar({
        "Pendientes": {**listar("tblRegistro", "EnResumen eq 'No'"),
                       "runtimeConfiguration": {"paginationPolicy": {"minimumItemCount": 5000}}},
        "Nuevos": filtro("@equals(item()?['Estado'], 'Recibido')"),
        "Por_revisar": filtro("@or(equals(item()?['Estado'], 'Revisar'), equals(item()?['Estado'], 'Cliente desconocido'), equals(item()?['Estado'], 'Error'))"),
        "Descartados": filtro("@equals(item()?['Estado'], 'Descartado - duplicado')"),
        "Sin_documentos": filtro("@equals(item()?['Estado'], 'Sin documentos')"),
        "Sel_nuevos": sel("Nuevos"), "Sel_revisar": sel("Por_revisar"), "Sel_descartados": sel("Descartados"),
        "Sel_sin_documentos": sel("Sin_documentos"),
        "Tabla_nuevos": tabla("Sel_nuevos"), "Tabla_revisar": tabla("Sel_revisar"), "Tabla_descartados": tabla("Sel_descartados"),
        "Tabla_sin_documentos": tabla("Sel_sin_documentos"),
        "Enviar_resumen": {"type": "OpenApiConnection", "inputs": conector(OUTLOOK, "SendEmailV2", {
            "emailMessage/To": CORREO_RESUMEN,
            "emailMessage/Subject": "@concat('Reembolsos: ', length(body('Pendientes')?['value']), ' registros desde el último resumen')",
            "emailMessage/Body": cuerpo,
            "emailMessage/Importance": "Normal"})},
        "Marcar_enviados": {"type": "Foreach", "foreach": "@body('Pendientes')?['value']",
                            "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
                            "actions": {"Actualizar_fila": {"runAfter": {}, "type": "OpenApiConnection",
                                        "inputs": excel("PatchItem", "tblRegistro", {
                                            "idColumn": "ID", "id": "@items('Marcar_enviados')?['ID']",
                                            "item/EnResumen": "Sí"})}}},
    })
    return definicion(triggers, acciones)


if __name__ == "__main__":
    empaquetar("Reembolsos - 1 Ingesta", flujo_ingesta(), OUT / "Reembolsos_1_Ingesta.zip", CONECTORES)
    empaquetar("Reembolsos - 2 Resumen diario", flujo_resumen(), OUT / "Reembolsos_2_Resumen_diario.zip",
               {OUTLOOK: CONECTORES[OUTLOOK], EXCEL: CONECTORES[EXCEL]})
    for f in sorted(OUT.glob("*.zip")):
        print(f.name, f.stat().st_size)
