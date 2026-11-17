"""Pipeline: archivo CSV -> métricas; y ensamblado de pruebas de un paciente."""
import numpy as np

from .io import classify_test, parse_forcedecks
from .metrics import quiet_stand, single_leg, sit_stand, turn

TEST_LABELS = {
    "QS_EO": "Bipodal ojos abiertos", "QS_EC": "Bipodal ojos cerrados",
    "SLS_EO": "Un pie ojos abiertos", "SLS_EC": "Un pie ojos cerrados",
    "STS": "Sentarse–pararse", "GIRO": "Giro 360°", "CMJ": "Salto (no puntúa)",
}


def _estimate_bw(d, key):
    tot = np.clip(d["zl"], 0, None) + np.clip(d["zr"], 0, None)
    p90 = float(np.percentile(tot, 90))
    return p90 if key.startswith("SLS") else p90 * 0.92


def analyze_file(filename, data, bw_map=None, plate_sep_mm=400.0):
    """Analiza un CSV. bw_map: {athlete_id: peso_en_N} (de Quiet Stand o del peso registrado)."""
    key, label = classify_test(filename)
    if key is None:
        raise ValueError("No reconozco el tipo de prueba por el nombre del archivo")
    out = {"test": key, "test_label": TEST_LABELS[key], "label": label}
    if key == "CMJ":
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
    if key.startswith("SLS"):
        m = single_leg(d, bw)
        m["eyes"] = "EC" if key == "SLS_EC" else "EO"
    elif key == "STS":
        m = sit_stand(d, bw)
    else:
        m = turn(d, bw)
    out["metrics"] = m
    return out


def assemble_tests(results):
    """Lista de resultados de analyze_file (un paciente) -> dict `tests` para balance_score."""
    tests = {"SLS": []}
    for r in results:
        k, m = r["test"], r.get("metrics")
        if not m:
            continue
        if k.startswith("SLS"):
            tests["SLS"].append(m)
        else:
            tests[k] = m
    if not tests["SLS"]:
        del tests["SLS"]
    return tests
