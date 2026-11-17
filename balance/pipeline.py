"""Pipeline: archivo CSV -> métricas; y ensamblado de pruebas de un paciente."""
import numpy as np

from .io import classify_test, parse_forcedecks
from .metrics import quiet_stand, sit_stand, turn

TEST_LABELS = {
    "QS_EO": "Bipodal ojos abiertos", "QS_EC": "Bipodal ojos cerrados",
    "SLS_EO": "Un pie (no puntúa)", "SLS_EC": "Un pie (no puntúa)",
    "STS": "Sentarse–pararse", "GIRO": "Giro 360°", "CMJ": "Salto (no puntúa)",
}


def _estimate_bw(d, key):
    tot = np.clip(d["zl"], 0, None) + np.clip(d["zr"], 0, None)
    return float(np.percentile(tot, 90)) * 0.92


def analyze_file(filename, data, bw_map=None, plate_sep_mm=400.0):
    """Analiza un CSV. bw_map: {athlete_id: peso_en_N} (de Quiet Stand o del peso registrado)."""
    key, label = classify_test(filename)
    if key is None:
        raise ValueError("No reconozco el tipo de prueba por el nombre del archivo")
    out = {"test": key, "test_label": TEST_LABELS[key], "label": label}
    if key in ("CMJ", "SLS_EO", "SLS_EC"):  # no puntúan (no evaluados en Tinetti / no relacionados)
        out["ignored"] = True
        return out
    d = parse_forcedecks(data)
    out["athlete_id"], out["recorded"] = d["athlete_id"], d["recorded"]
    if key in ("QS_EO", "QS_EC"):
        m = quiet_stand(d, plate_sep_mm)
        out["metrics"], out["bw_n"], out["bw_source"] = m, m["bw_n"], "quiet_stand"
        return out
    bw = (bw_map or {}).get(d["athlete_id"])
    src = "quiet_stand/peso registrado"
    if not bw:
        bw, src = _estimate_bw(d, key), "estimado (sin Quiet Stand ni peso)"
    out["bw_n"], out["bw_source"] = round(float(bw), 1), src
    if key == "STS":
        m = sit_stand(d, bw)
    else:
        m = turn(d, bw)
    out["metrics"] = m
    return out


def assemble_tests(results):
    """Lista de resultados de analyze_file (un paciente) -> dict `tests` para balance_score."""
    tests = {}
    for r in results:
        if r.get("metrics"):
            tests[r["test"]] = r["metrics"]
    return tests
