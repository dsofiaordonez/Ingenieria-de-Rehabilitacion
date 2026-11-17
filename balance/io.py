"""Lectura de CSV crudos de ForceDecks (coma decimal, 1000 Hz, dos plataformas)."""
import csv
import io
import re
import numpy as np

# Índices de columnas del export: Time, Z Left, COPX L, COPY L, Z Right, COPX R, COPY R
_COLS = (0, 1, 2, 3, 4, 5, 6)


def _f(s):
    return float(s.replace(",", ".")) if s else 0.0


def parse_forcedecks(data, target_hz=100):
    """Parsea bytes/str de un CSV ForceDecks y devuelve dict con señales remuestreadas.

    Retorna: t, zl, zr, xl, yl, xr, yr (np.ndarray a target_hz), fs, athlete_id, recorded.
    El remuestreo es un promedio por bloques (filtro pasa-bajos + decimación).
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", errors="replace")
    data = data.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(data))
    meta, rows = {}, []
    header_seen = False
    for row in reader:
        if not row:
            continue
        if not header_seen:
            if row[0] == "Time":
                header_seen = True
                continue
            meta[row[0]] = row[1] if len(row) > 1 else ""
            continue
        if len(row) < 7:
            continue
        try:
            rows.append([_f(row[i]) for i in _COLS])
        except ValueError:
            continue
    if not rows:
        raise ValueError("No se encontraron datos de fuerza en el archivo (¿es un export crudo de ForceDecks?)")
    a = np.asarray(rows, dtype=float)
    fs = float(meta.get("Frequency", "1000").replace(",", ".") or 1000)
    k = max(1, int(round(fs / target_hz)))
    n = (len(a) // k) * k
    b = a[:n].reshape(-1, k, a.shape[1]).mean(axis=1)
    return {
        "t": b[:, 0] - b[0, 0],
        "zl": b[:, 1], "xl": b[:, 2], "yl": b[:, 3],
        "zr": b[:, 4], "xr": b[:, 5], "yr": b[:, 6],
        "fs": fs / k,
        "athlete_id": meta.get("AthleteId", ""),
        "recorded": meta.get("Recording Date", ""),
    }


def classify_test(filename):
    """Devuelve (test_key, paciente) a partir del nombre de archivo exportado por ForceDecks.

    test_key ∈ QS_EO, QS_EC, SLS_EO, SLS_EC, STS, GIRO, CMJ o None.
    """
    name = filename.rsplit("/", 1)[-1]
    low = name.lower()
    patient = re.split(r"-(?=\d{4}[._]\d{2}[._]\d{2})|-(?:quiet|single|sit|countermovement|cmj)", low, maxsplit=1)[0]
    patient = re.sub(r"[_]+", " ", patient).strip()
    closed = bool(re.search(r"clos|cerr", low))
    if low.endswith("_giro.csv") or "giro" in low:
        key = "GIRO"
    elif "countermovement" in low or "cmj" in low:
        key = "CMJ"
    elif "single" in low and "leg" in low:
        key = "SLS_EC" if closed else "SLS_EO"
    elif "quiet" in low:
        key = "QS_EC" if closed else "QS_EO"
    elif re.search(r"sit[\s_-]*to|satd", low):
        key = "STS"
    else:
        key = None
    return key, patient
