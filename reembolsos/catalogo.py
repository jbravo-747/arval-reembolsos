"""Catálogo de clientes (hoja Clientes de Control_Reembolsos.xlsx) y comparación de nombres.

Columnas usadas: Correo, NombreCliente, Tipo (vacío o Cliente = cliente; Escaner/Aseguradora/Aviso/Ignorar = no),
Alias (otra forma del nombre), RFC.
"""
import re
import unicodedata

TIPOS_NO_CLIENTE = {"escaner", "aseguradora", "aviso", "ignorar"}
ETIQUETAS_NOMBRE = ("ASEGURADO", "PACIENTE", "NOMBRE DEL ASEGURADO", "NOMBRE DEL PACIENTE", "NOMBRE", "RECEPTOR",
                    "TITULAR", "BENEFICIARIO")


def normalizar(texto):
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^A-Za-z0-9 ]+", " ", t.upper())
    return re.sub(r"\s+", " ", t).strip()


class Cliente:
    def __init__(self, fila):
        self.correo = str(fila.get("Correo") or "").strip().lower()
        self.nombre = re.sub(r"\s+", " ", str(fila.get("NombreCliente") or "")).strip()
        self.tipo = str(fila.get("Tipo") or "").strip().lower()
        self.alias = str(fila.get("Alias") or "").strip()
        self.rfc = str(fila.get("RFC") or "").strip().upper()
        self.claves = {c for c in (normalizar(self.nombre), normalizar(self.alias)) if len(c) >= 6}

    @property
    def es_cliente(self):
        return bool(self.nombre) and self.tipo not in TIPOS_NO_CLIENTE

    @property
    def ignorar(self):
        return self.tipo in ("aviso", "ignorar")


class Catalogo:
    def __init__(self, filas):
        self.todos = [Cliente(f) for f in filas]
        self.clientes = [c for c in self.todos if c.es_cliente]
        self.por_correo = {c.correo: c for c in self.todos if c.correo}

    def por_remitente(self, correo):
        c = self.por_correo.get(str(correo or "").lower())
        return c if c and c.es_cliente else None

    def remitente_ignorado(self, correo):
        c = self.por_correo.get(str(correo or "").lower())
        return bool(c and c.ignorar)

    def coincidencias(self, texto):
        """Lista de (cliente, 'exacta'|'parcial') encontrados en el texto."""
        t = normalizar(texto)
        hallados = []
        for c in self.clientes:
            if any(k in t for k in c.claves) or (c.rfc and c.rfc in t):
                hallados.append((c, "exacta"))
                continue
            palabras = [p for p in normalizar(c.nombre).split() if len(p) >= 3]
            if palabras and all(re.search(rf"\b{re.escape(p)}\b", t) for p in palabras):
                hallados.append((c, "parcial"))
        return hallados

    def resolver(self, texto):
        """Devuelve (nombre, confianza) o (None, motivo)."""
        h = self.coincidencias(texto)
        exactas = [c.nombre for c, k in h if k == "exacta"]
        if len(exactas) == 1:
            return exactas[0], "exacta"
        if len(exactas) > 1:
            return None, "varios: " + " | ".join(exactas)
        if len(h) == 1:
            return h[0][0].nombre, "parcial"
        if h:
            return None, "varios parciales: " + " | ".join(c.nombre for c, _ in h)
        return None, "sin coincidencia"


def candidatos_en_texto(texto, maximo=3):
    """Nombres que siguen a etiquetas como ASEGURADO: o NOMBRE: en un documento leído.
    Sirve para proponer altas al catálogo; no decide nada por sí solo."""
    t = normalizar(texto)
    vistos = []
    for etiqueta in ETIQUETAS_NOMBRE:
        for m in re.finditer(rf"\b{etiqueta}\b[: ]+((?:[A-Z]{{2,}} ?){{2,5}})", t):
            cand = m.group(1).strip()
            cand = re.sub(r"\b(RFC|CURP|FECHA|DOMICILIO|POLIZA|NO|NUM|FOLIO)\b.*$", "", cand).strip()
            if 2 <= len(cand.split()) <= 5 and cand not in vistos:
                vistos.append(cand)
            if len(vistos) >= maximo:
                return vistos
    return vistos
