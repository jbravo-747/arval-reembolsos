"""Base de asegurados y de expedientes construida a partir de los documentos analizados (cli.py organizar).

Por cada carpeta de cliente (asegurado) reúne lo que dicen sus documentos: RFC (validado contra el nombre en personas
físicas), aseguradoras, pólizas, correos, personas relacionadas (titular, afectados o dependientes) y sus expedientes
(eventos) con aseguradora, siniestro, póliza, total facturado y faltantes. Lo dudoso va a una lista "Revisar".
Solo identificadores y conteos: nada clínico.
"""
import re
from collections import Counter, defaultdict

from .catalogo import normalizar
from .contenido import prefijos_rfc

EMPRESA = {"SA", "CV", "SC", "SAPI", "AC", "SRL", "SAB", "SOFOM", "CORPORATIVO", "GRUPO", "SERVICIOS", "SERVICIO", "COMERCIAL",
           "INDUSTRIAL", "INDUSTRIAS", "ASOCIACION", "FUNDACION", "BANCO", "ALIMENTOS", "ACADEMIA", "COLEGIO", "INSTITUTO", "CONSTRUCTORA",
           "DISTRIBUIDORA", "INMOBILIARIA", "TRANSPORTES", "CLIENTES"}


NOMBRES_DE_PILA = {"MIGUEL", "ANGEL", "JOSE", "JUAN", "MARIA", "LUIS", "CARLOS", "JORGE", "ANA", "ROSA", "LAURA", "PEDRO", "FRANCISCO",
                   "ANTONIO", "MANUEL", "JESUS", "GUADALUPE", "ALEJANDRO", "FERNANDO", "RICARDO", "EDUARDO", "ROBERTO", "DANIEL",
                   "SERGIO", "MARTHA", "PATRICIA", "ELENA", "CARMEN", "TERESA", "SOFIA", "DIEGO", "PABLO", "DAVID", "JAVIER"}
NO_PERSONA = {"HIJO", "HIJA", "PRIMER", "SEGUNDO", "APELLIDO", "APELLIDOS", "PARTICIPANTE", "AUTORIZA", "AUTORIZAN", "AUTORIZO", "CONSULTA",
              "SE", "NOMBRES", "PATERNO", "MATERNO", "FIRMA", "ESTE", "ESTA", "QUE", "PARA", "CON", "POR", "SU", "EN", "AL", "LE", "LO",
              "QT", "MEDICO", "TRATANTE", "DR", "DRA", "HOSPITAL", "SEGURO", "SEGUROS", "POLIZA", "CERTIFICADO", "COBERTURA", "PLAN"}


def tipo_persona(nombre):
    w = normalizar(nombre).split()
    if set(w) & EMPRESA or len(w) == 1:
        return "Empresa o grupo (revisar)"
    return "Persona física" if len(w) >= 3 else "Persona física (nombre incompleto)"


def es_nombre_de_persona(nombre):
    w = normalizar(nombre).split()
    return 2 <= len(w) <= 5 and not set(w) & NO_PERSONA and all(len(x) >= 2 for x in w)


def poliza_valida(p):
    """Descarta fechas (vigencias) que el lector tomó como número de póliza."""
    return not re.fullmatch(r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}", p) and not re.fullmatch(r"20\d{2}[/\-.]\d{2}[/\-.]\d{2}", p)


def clave_poliza(p):
    return re.sub(r"^0+", "", re.sub(r"[^0-9A-Z]", "", p.upper()))


def _mismo_nombre(a, b):
    """Coinciden si todas las palabras (de 3+ letras) del más corto están en el otro."""
    wa = {x for x in normalizar(a).split() if len(x) >= 3}
    wb = {x for x in normalizar(b).split() if len(x) >= 3}
    corto, largo = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return bool(corto) and len(corto) >= 2 and corto <= largo


DOMINIOS_INSTITUCIONALES = ("gnp.", "arval.", "mapfre.", "axa.", "metlife.", "segurosatlas.", "atlas.", "allianz.", "bupa.", "inbursa.",
                            "banorte.", "zurich.", "hdi.", "chubb.", "qualitas.", "sura.", "mnyl.", "planseguro.", "gs.com")


def _comunes(archivos, campo, minimo=3):
    """Valores (correos o nombres) que aparecen en documentos de `minimo` o más clientes: institucionales o médicos."""
    clientes = defaultdict(set)
    for a in archivos:
        if a.get("cliente") and not a.get("duplicado_de"):
            datos = a.get("datos") or {}
            for v in datos.get(campo, []):
                clientes[v if campo == "correos" else v[1]].add(a["cliente"])
    return {v for v, cs in clientes.items() if len(cs) >= minimo}


def correo_del_cliente(correo, cliente):
    usuario = re.sub(r"[^a-z]", " ", correo.split("@")[0].lower())
    return any(len(w) >= 4 and w.lower() in usuario for w in normalizar(cliente).split())


def _top(contador, n=5):
    return " | ".join(f"{k} ({v})" for k, v in contador.most_common(n))


def clasificar_conflictos(archivos, min_carpetas=5):
    """Cuando el contenido nombra a otro cliente: {(cartera, cliente, otro): (categoría, documentos)}.
    contratante o agente = nombre de empresa o que aparece en muchas carpetas; genérico = menos de 3 palabras;
    familiar o titular = otro cliente persona física que aparece varias veces; posible error = casos aislados."""
    carpetas_por_otro = defaultdict(set)
    pares = Counter()
    for a in archivos:
        if a.get("conflicto") and a.get("cliente_contenido") and not a.get("duplicado_de"):
            carpetas_por_otro[a["cliente_contenido"]].add((a["cartera"], a["cliente"]))
            pares[(a["cartera"], a["cliente"], a["cliente_contenido"])] += 1
    salida = {}
    for (cartera, cliente, otro), n in pares.items():
        palabras = set(normalizar(otro).split())
        if palabras <= NOMBRES_DE_PILA:
            cat = "genérico"
        elif len(carpetas_por_otro[otro]) >= min_carpetas or palabras & EMPRESA:
            cat = "contratante o agente"
        elif len(palabras) < 3:
            cat = "genérico"
        elif n >= 3:
            cat = "familiar o titular"
        else:
            cat = "posible error"
        salida[(cartera, cliente, otro)] = (cat, n)
    return salida


def nombre_legitimo(cliente, docs, minimo=2):
    """Nombre completo del asegurado tal como aparece en documentos oficiales de su carpeta: receptor del CFDI (vale 3) y
    titular/asegurado/afectado en formatos de la aseguradora (vale 1). Debe ser compatible con el nombre de la carpeta.
    Devuelve (nombre, fuente) o ("", "") si no hay evidencia suficiente."""
    puntos, fuentes = Counter(), defaultdict(set)
    for d in docs:
        datos = d.get("datos") or {}
        rec = (datos.get("cfdi") or {}).get("receptor", "")
        if rec and _mismo_nombre(rec, cliente):
            puntos[normalizar(rec)] += 3
            fuentes[normalizar(rec)].add("CFDI")
        for _rol, nombre in datos.get("personas", []):
            if es_nombre_de_persona(nombre) and _mismo_nombre(nombre, cliente):
                puntos[normalizar(nombre)] += 1
                fuentes[normalizar(nombre)].add("formatos de la aseguradora")
    if not puntos:
        return "", ""
    mejor = max(puntos, key=lambda n: (puntos[n], len(n.split())))
    if puntos[mejor] < minimo:
        return "", ""
    return mejor, f"{' y '.join(sorted(fuentes[mejor]))} ({puntos[mejor]})"


def construir(archivos, expedientes):
    """archivos y expedientes de organizar (organizacion.json). Devuelve dict de hojas: asegurados, personas, polizas,
    expedientes, revisar (listas de dicts)."""
    por_cliente = defaultdict(list)
    for a in archivos:
        if a.get("cliente") and not a.get("duplicado_de"):
            por_cliente[(a["cartera"], a["cliente"])].append(a)

    asegurados, personas, polizas, revisar = [], [], [], []
    legitimo_de = {}
    conflictos = clasificar_conflictos(archivos)
    correos_comunes, personas_comunes = _comunes(archivos, "correos"), _comunes(archivos, "personas")
    for (cartera, cliente, otro), (cat, n) in sorted(conflictos.items()):
        if cat == "familiar o titular":
            personas.append({"Cartera": cartera, "Cliente": cliente, "Persona": otro,
                             "Relación probable": "Otro cliente: posible familiar o titular", "Documentos": n})
        elif cat == "posible error":
            revisar.append({"Cartera": cartera, "Cliente": cliente, "Qué revisar": "documento que menciona a otro cliente",
                            "Detalle": f"{otro}: {n} documento(s)"})
    for (cartera, cliente), docs in sorted(por_cliente.items()):
        tipo = tipo_persona(cliente)
        rfcs, rfcs_receptor, aseguradoras, pol, correos, gente = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
        pol_aseg = defaultdict(Counter)
        for d in docs:
            datos = d.get("datos") or {}
            cfdi = datos.get("cfdi") or {}
            if cfdi.get("rfc_receptor"):
                rfcs_receptor[cfdi["rfc_receptor"]] += 1
                if _mismo_nombre(cfdi.get("receptor", ""), cliente):
                    rfcs_receptor[cfdi["rfc_receptor"]] += 5     # el receptor se llama como el cliente: señal fuerte
            for r in datos.get("rfcs", []):
                rfcs[r] += 1
            if datos.get("aseguradora"):
                aseguradoras[datos["aseguradora"]] += 1
            for p in {clave_poliza(x): x for x in datos.get("polizas", []) if poliza_valida(x)}:
                pol[p] += 1
                if datos.get("aseguradora"):
                    pol_aseg[p][datos["aseguradora"]] += 1
            for c in datos.get("correos", []):
                if c not in correos_comunes and not any(dom in c.split("@")[-1] for dom in DOMINIOS_INSTITUCIONALES):
                    correos[c] += 1
            for rol, nombre in datos.get("personas", []):
                if nombre not in personas_comunes and es_nombre_de_persona(nombre):
                    gente[(rol, nombre)] += 1

        # RFC del asegurado
        rfc, rfc_conf = "", ""
        if tipo.startswith("Persona física"):
            prefijos = prefijos_rfc(cliente)
            validos = Counter({r: n + rfcs_receptor.get(r, 0) for r, n in (rfcs + rfcs_receptor).items() if len(r) == 13 and r[:4] in prefijos})
            if validos:
                rfc, rfc_conf = validos.most_common(1)[0][0], "alta (coincide con el nombre)"
            else:
                casi = Counter({r: n for r, n in (rfcs + rfcs_receptor).items()
                                if len(r) == 13 and n >= 2 and any(sum(x == y for x, y in zip(r[:4], pf)) >= 3 for pf in prefijos)})
                if casi:
                    rfc, rfc_conf = casi.most_common(1)[0][0], "media (coincide en 3 de 4 letras: revisar)"
        if not rfc and rfcs_receptor:
            r, n = rfcs_receptor.most_common(1)[0]
            if n >= 5:
                rfc, rfc_conf = r, "media (receptor del CFDI con el mismo nombre)"
        if not rfc:
            revisar.append({"Cartera": cartera, "Cliente": cliente, "Qué revisar": "RFC no encontrado o no coincide con el nombre",
                            "Detalle": _top(rfcs + rfcs_receptor, 3)})

        # Personas relacionadas: el propio asegurado se reconoce; los demás son titulares o dependientes posibles
        titular_es_cliente = any(_mismo_nombre(n, cliente) for (rol, n) in gente if rol in ("titular", "asegurado"))
        vistos = set()
        for (rol, nombre), n in gente.most_common():
            clave = normalizar(nombre)
            if clave in vistos:
                continue
            vistos.add(clave)
            es_cliente = _mismo_nombre(nombre, cliente)
            if es_cliente or n < 2:          # una sola aparición suele ser ruido de lectura
                continue
            personas.append({"Cartera": cartera, "Cliente": cliente, "Persona": nombre,
                             "Relación probable": {"titular": "Titular de la póliza", "contratante": "Contratante",
                                                   "afectado": "Afectado o dependiente", "asegurado": "Asegurado"}[rol],
                             "Documentos": n})

        for p, n in pol.most_common(5):
            if n >= 2:
                polizas.append({"Cartera": cartera, "Cliente": cliente, "Póliza": p,
                                "Aseguradora": pol_aseg[p].most_common(1)[0][0] if pol_aseg[p] else "", "Documentos": n})

        legit, fuente = nombre_legitimo(cliente, docs)
        legitimo_de[(cartera, cliente)] = legit
        eventos = [e for e in expedientes if e["cartera"] == cartera and e["cliente"] == cliente]
        fechas = sorted(d["fecha"] for d in docs if d.get("fecha_origen") in ("documento", "contenido", "nombre"))
        asegurados.append({
            "Aprobado": "", "Nombre en catálogo": legit or cliente, "Nombre legítimo": legit, "Fuente del nombre": fuente,
            "Cartera": cartera, "Cliente": cliente, "Tipo": tipo, "RFC": rfc, "Confianza RFC": rfc_conf,
            "Aseguradora principal": aseguradoras.most_common(1)[0][0] if aseguradoras else "",
            "Aseguradoras": _top(aseguradoras, 3), "Pólizas": " | ".join(p for p, n in pol.most_common(3) if n >= 2),
            "Correo probable": " | ".join(c for c, _ in correos.most_common() if correo_del_cliente(c, cliente))[:120],
            "Otros correos en sus documentos": " | ".join(c for c, _ in correos.most_common(3) if not correo_del_cliente(c, cliente)),
            "Titular es el cliente": "sí" if titular_es_cliente else "no se encontró",
            "Contratante o agente": " | ".join(f"{o} ({n})" for (c1, c2, o), (cat, n) in sorted(conflictos.items(), key=lambda x: -x[1][1])
                                               if (c1, c2) == (cartera, cliente) and cat == "contratante o agente")[:120],
            "Personas relacionadas": sum(1 for p in personas if p["Cliente"] == cliente and p["Cartera"] == cartera),
            "Expedientes": len(eventos), "Con faltantes": sum(1 for e in eventos if e["faltantes"]),
            "Documentos": len(docs), "Primer documento": fechas[0] if fechas else "", "Último documento": fechas[-1] if fechas else "",
            "Notas de Lau": "",
        })

    # Posible misma persona en dos carpetas: las palabras de un nombre están contenidas en el otro, o difieren en una letra
    nombres = sorted({(c, cl) for c, cl in por_cliente})
    for i, (c1, n1) in enumerate(nombres):
        for c2, n2 in nombres[i + 1:]:
            w1, w2 = normalizar(n1).split(), normalizar(n2).split()
            contenido = len(w1) >= 2 and len(w2) >= 2 and (set(w1) <= set(w2) or set(w2) <= set(w1))
            casi = len(w1) == len(w2) >= 3 and sum(a != b for a, b in zip(w1, w2)) == 1 and                 sum(x != y for a, b in zip(w1, w2) if a != b for x, y in zip(a, b)) + abs(sum(len(a) - len(b) for a, b in zip(w1, w2))) <= 2
            l1, l2 = legitimo_de.get((c1, n1)), legitimo_de.get((c2, n2))
            if l1 and l1 == l2:
                revisar.append({"Cartera": c1, "Cliente": n1, "Qué revisar": "misma persona en dos carpetas (confirmado por documentos)",
                                "Detalle": f"{c2} / {n2} · nombre legítimo: {l1}"})
            elif (contenido or casi) and not set(w1) <= NOMBRES_DE_PILA and not set(w2) <= NOMBRES_DE_PILA:
                revisar.append({"Cartera": c1, "Cliente": n1, "Qué revisar": "posible misma persona en dos carpetas",
                                "Detalle": f"{c2} / {n2}"})

    filas_exp = []
    por_evento = defaultdict(list)
    for (cartera, cliente), docs in por_cliente.items():
        for d in docs:
            por_evento[(cartera, cliente, d.get("evento") or "_Sin evento")].append(d)
    for e in expedientes:
        docs = por_evento.get((e["cartera"], e["cliente"], e["evento"]), [])
        aseg, sin, pol, total = Counter(), Counter(), Counter(), 0.0
        for d in docs:
            datos = d.get("datos") or {}
            if datos.get("aseguradora"):
                aseg[datos["aseguradora"]] += 1
            sin.update(datos.get("siniestros", []))
            pol.update({clave_poliza(x) for x in datos.get("polizas", []) if poliza_valida(x)})
            try:
                total += float(str((datos.get("cfdi") or {}).get("total") or 0).replace(",", ""))
            except ValueError:
                pass
        filas_exp.append({"Cartera": e["cartera"], "Cliente": e["cliente"], "Evento": e["evento"], "Inicio": e["inicio"], "Último": e["ultimo"],
                          "Documentos": e["documentos"], "Tipos": ", ".join(e["tipos"]), "Faltantes": ", ".join(e["faltantes"]),
                          "Resuelto por la aseguradora": "sí (finiquito o dictamen)" if "Finiquito o dictamen" in e["tipos"] else "",
                          "Aseguradora": aseg.most_common(1)[0][0] if aseg else "", "Siniestro(s)": " | ".join(s for s, _ in sin.most_common(3)),
                          "Póliza(s)": " | ".join(p for p, _ in pol.most_common(2)), "Total CFDI": round(total, 2) if total else "",
                          "Por leer": e.get("por_leer", 0), "Conflictos": e.get("conflictos", 0)})
    return {"asegurados": asegurados, "personas": personas, "polizas": polizas, "expedientes": filas_exp, "revisar": revisar}


def resumen(hojas):
    a = hojas["asegurados"]
    return {"asegurados": len(a), "personas_fisicas": sum(1 for x in a if x["Tipo"].startswith("Persona física")),
            "con_rfc": sum(1 for x in a if x["RFC"]), "rfc_alta": sum(1 for x in a if x["Confianza RFC"].startswith("alta")),
            "con_aseguradora": sum(1 for x in a if x["Aseguradora principal"]), "con_poliza": sum(1 for x in a if x["Pólizas"]),
            "con_correo": sum(1 for x in a if x["Correo probable"]), "personas_relacionadas": len(hojas["personas"]),
            "polizas": len(hojas["polizas"]), "expedientes": len(hojas["expedientes"]), "por_revisar": len(hojas["revisar"]),
            "aseguradoras": dict(Counter(x["Aseguradora principal"] for x in a if x["Aseguradora principal"]).most_common()),
            "con_nombre_legitimo": sum(1 for x in a if x.get("Nombre legítimo")),
            "facturas_en_relaciones": len(hojas.get("reclamaciones", [])),
            "facturas_confirmadas": sum(1 for r in hojas.get("reclamaciones", []) if r["Corroboración"].startswith("confirmada")),
            "facturas_probables": sum(1 for r in hojas.get("reclamaciones", []) if r["Corroboración"].startswith("probable"))}


def a_excel(hojas, ruta):
    """Excel para que Lau revise: una hoja por tabla, con formato de tabla y filtros."""
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    nombres = {"asegurados": "Asegurados", "personas": "Personas", "polizas": "Polizas", "expedientes": "Expedientes",
               "reclamaciones": "Reclamaciones", "revisar": "Revisar"}
    for clave, titulo in nombres.items():
        filas = hojas.get(clave, [])
        ws = wb.create_sheet(titulo)
        if not filas:
            ws.append(["Sin datos"])
            continue
        enc = list(filas[0].keys())
        ws.append(enc)
        for f in filas:
            ws.append([f.get(k, "") for k in enc])
        ws.add_table(Table(displayName="tbl" + titulo, ref=f"A1:{get_column_letter(len(enc))}{len(filas) + 1}",
                           tableStyleInfo=TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)))
        for i, k in enumerate(enc, 1):
            ancho = max([len(str(k))] + [len(str(f.get(k, ""))) for f in filas[:300]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(10, ancho + 2), 60)
        ws.freeze_panes = "B2"
        if clave == "asegurados":
            from openpyxl.worksheet.datavalidation import DataValidation
            dv = DataValidation(type="list", formula1='"sí,no"', allow_blank=True,
                                promptTitle="Revisión", prompt="sí = entra al catálogo; no = se descarta. Puedes corregir Nombre en catálogo, RFC y Correo probable.")
            ws.add_data_validation(dv)
            dv.add(f"A2:A{len(filas) + 1}")
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
    wb.save(ruta)


# ---------- carga después de la revisión de Lau ----------
def leer_hoja(ruta, hoja):
    import openpyxl
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    if hoja not in wb.sheetnames:
        return []
    filas = list(wb[hoja].iter_rows(values_only=True))
    if not filas or filas[0][0] == "Sin datos":
        return []
    enc = [str(c or "") for c in filas[0]]
    return [{k: ("" if v is None else v) for k, v in zip(enc, f)} for f in filas[1:] if any(v not in (None, "") for v in f)]


def aprobado(fila):
    return normalizar(fila.get("Aprobado", "")) in ("SI", "S", "OK", "X")


def filas_catalogo(asegurados_revisados, fecha, semilla=False):
    """Filas para tblClientes (Correo, NombreCliente, Notas, Tipo, Alias, RFC, Cartera): una por correo del asegurado aprobado;
    sin correo, una fila con el correo vacío (el catálogo también se usa para reconocer el nombre en los documentos)."""
    salida = []
    for a in asegurados_revisados:
        if not (aprobado(a) or semilla):
            continue
        nombre = re.sub(r"\s+", " ", str(a.get("Nombre en catálogo") or a.get("Cliente") or "")).strip()
        correos = [c.strip().lower() for c in str(a.get("Correo probable") or "").split("|") if "@" in c] or [""]
        for c in correos:
            salida.append({"Correo": c, "NombreCliente": nombre, "Notas": f"Alta desde la base de asegurados {fecha}" + ("; semilla sin revisar" if semilla and not aprobado(a) else "") +
                           (f"; {a['Notas de Lau']}" if a.get("Notas de Lau") else ""), "Tipo": "", "Alias": "",
                           "RFC": str(a.get("RFC") or "").strip().upper(), "Cartera": str(a.get("Cartera") or "")})
    return salida


def buscador(ruta_excel, semilla=False):
    """Documentos del buscador del panel (uno por asegurado aprobado; con semilla, todos, marcados sin revisar)
    con sus personas, pólizas y expedientes recientes."""
    aseg = [a for a in leer_hoja(ruta_excel, "Asegurados") if aprobado(a) or semilla]
    personas, polizas, exps = defaultdict(list), defaultdict(list), defaultdict(list)
    for p in leer_hoja(ruta_excel, "Personas"):
        personas[(p["Cartera"], p["Cliente"])].append({"nombre": p["Persona"], "relacion": p["Relación probable"]})
    for p in leer_hoja(ruta_excel, "Polizas"):
        polizas[(p["Cartera"], p["Cliente"])].append({"poliza": str(p["Póliza"]), "aseguradora": p["Aseguradora"]})
    for e in leer_hoja(ruta_excel, "Expedientes"):
        exps[(e["Cartera"], e["Cliente"])].append({"evento": e["Evento"], "ultimo": str(e["Último"]), "faltantes": e["Faltantes"],
                                                   "resuelto": bool(e.get("Resuelto por la aseguradora")), "aseguradora": e["Aseguradora"],
                                                   "siniestro": str(e.get("Siniestro(s)") or "")})
    docs = []
    for a in aseg:
        k = (a["Cartera"], a["Cliente"])
        ex = sorted(exps[k], key=lambda e: e["ultimo"], reverse=True)
        docs.append({"nombre": str(a.get("Nombre en catálogo") or a["Cliente"]), "carpeta": a["Cliente"], "cartera": a["Cartera"],
                     "tipo": a["Tipo"], "rfc": str(a.get("RFC") or ""), "aseguradora": a.get("Aseguradora principal", ""),
                     "correo": str(a.get("Correo probable") or ""), "contratante": str(a.get("Contratante o agente") or ""),
                     "polizas": polizas[k][:5], "personas": personas[k][:10], "expedientes": len(ex),
                     "con_faltantes": sum(1 for e in ex if e["faltantes"]), "recientes": ex[:5], "revisado": aprobado(a),
                     "nombre_legitimo": str(a.get("Nombre legítimo") or ""), "reclamaciones": a.get("Reclamaciones (Lau)") or 0,
                     "facturas_relacion": a.get("Facturas en relación") or 0, "facturas_confirmadas": a.get("Confirmadas con documento") or 0,
                     "estatus_relacion": str(a.get("Estatus (relación)") or "")})
    return docs


def agregar_reclamaciones(hojas, filas):
    """Suma las relaciones de reclamaciones de Lau (ya corroboradas) a la base: hoja Reclamaciones, columnas por
    asegurado y por expediente. Nunca incluye padecimiento ni descripción."""
    hojas["reclamaciones"] = [{"Cartera": f["cartera"], "Cliente": f["cliente"], "Reclamación": f["reclamacion"], "Concepto": f["concepto"],
                               "Categoría": f["categoria"], "Factura": f["factura"], "Fecha documento": f["fecha_documento"],
                               "Monto": f["monto"], "Fecha de ingreso": f["fecha_ingreso"], "Folio aseguradora": f["folio"],
                               "Estatus": f["estatus"], "Fecha de finiquito": f["fecha_finiquito"], "Corroboración": f["corroboracion"],
                               "Documento": f["documento"], "Evento del documento": f["evento_documento"] or f["evento"],
                               "Archivo de Lau": f["archivo"]} for f in filas]
    por = defaultdict(list)
    for f in filas:
        por[(f["cartera"], f["cliente"])].append(f)
    for a in hojas["asegurados"]:
        fs = por.get((a["Cartera"], a["Cliente"]), [])
        a["Reclamaciones (Lau)"] = len({f["reclamacion"] for f in fs if f["reclamacion"]})
        a["Facturas en relación"] = len(fs)
        a["Confirmadas con documento"] = sum(1 for f in fs if f["corroboracion"].startswith("confirmada"))
        a["Probables (revisar)"] = sum(1 for f in fs if f["corroboracion"].startswith("probable"))
        a["Monto reclamado"] = round(sum(f["monto"] or 0 for f in fs), 2) if fs else ""
        est = Counter(f["estatus"] for f in fs)
        a["Estatus (relación)"] = " | ".join(f"{k} {v}" for k, v in est.most_common(3))
        notas = a.pop("Notas de Lau", "")
        a["Notas de Lau"] = notas
    por_evento = defaultdict(set)
    for f in filas:
        ev = f["evento_documento"] or f["evento"]
        if ev and f["reclamacion"]:
            por_evento[(f["cartera"], f["cliente"], ev)].add(f["reclamacion"])
    for e in hojas["expedientes"]:
        e["Reclamación (Lau)"] = " | ".join(sorted(por_evento.get((e["Cartera"], e["Cliente"], e["Evento"]), [])))
    return hojas
