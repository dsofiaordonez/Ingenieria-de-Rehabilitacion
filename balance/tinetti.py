"""Escala de Tinetti (subescala de equilibrio, máx. 16) leída desde el Word de evaluación.

El Word lista, por paciente, todas las opciones de cada ítem; la opción puntuada está RESALTADA.
"""
import io
import re
import unicodedata

ITEMS = [  # (clave, etiqueta, máximo)
    ("sentado", "Equilibrio sentado", 1),
    ("levantarse", "Levantarse", 2),
    ("intentos", "Intentos para levantarse", 2),
    ("bip_inmediata", "Bipedestación inmediata (5 s)", 2),
    ("bipedestacion", "Bipedestación", 2),
    ("empujar", "Empujar", 2),
    ("ojos_cerrados", "Ojos cerrados", 1),
    ("vuelta_pasos", "Vuelta 360° – continuidad de pasos", 1),
    ("vuelta_estab", "Vuelta 360° – estabilidad", 1),
    ("sentarse", "Sentarse", 2),
]
MAX_TOTAL = sum(m for _, _, m in ITEMS)  # 16

def _header_key(low):
    """Reconoce el encabezado de ítem por palabra clave (el Word tiene formatos irregulares)."""
    low = low.strip(" -•:")
    if low.startswith("ojos"):
        return "ojos_cerrados"
    if low.startswith("empuj"):
        return "empujar"
    if "inmediata" in low:
        return "bip_inmediata"
    if "bipedest" in low:
        return "bipedestacion"
    if "intento" in low:
        return "intentos"
    if "levantarse" in low:
        return "levantarse"
    if "vuelta" in low:
        return "vuelta"
    if "sentarse" in low:
        return "sentarse"
    if "sentado" in low:
        return "sentado"
    return None


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]+", " ", s).split()


def _highlighted(par):
    return any(r.font.highlight_color is not None and r.text.strip() for r in par.runs)


def parse_tinetti_docx(data):
    """Devuelve lista de pacientes: {name, items{clave:puntos|None}, total, missing[], max_available}."""
    from docx import Document  # import perezoso: solo se necesita para esta función

    doc = Document(io.BytesIO(data))
    patients, cur, section = [], None, None
    for par in doc.paragraphs:
        text = par.text.strip()
        if not text:
            continue
        m = re.match(r"^paciente\s*\d*\s*[:：]?\s*(.*)$", re.sub(r"\s+", " ", text), re.I)
        if m and text.lower().startswith("paciente"):
            cur = {"name": re.sub(r"^\d+\s*[:：]?\s*", "", m.group(1)).strip(" :"), "items": {k: None for k, _, _ in ITEMS}}
            patients.append(cur)
            section = None
            continue
        if cur is None:
            continue
        low = text.lower()
        om = re.match(r"^([0-2])\s*=", text)
        if not om and len(low) < 200:
            hdr = _header_key(low)
            if hdr:
                section = hdr
                continue
        if om and section and _highlighted(par):
            score = int(om.group(1))
            key = section
            if section == "vuelta":
                key = "vuelta_pasos" if "paso" in low else "vuelta_estab"
            cur["items"][key] = score
    maxd = {k: m for k, _, m in ITEMS}
    for p in patients:
        got = {k: v for k, v in p["items"].items() if v is not None}
        p["missing"] = [k for k in p["items"] if p["items"][k] is None]
        p["total"] = sum(got.values())
        p["max_available"] = sum(maxd[k] for k in got)
        p["complete"] = not p["missing"]
    return patients
