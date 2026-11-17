"""Score de equilibrio (0–100) y análisis aparte del giro.

Score principal = dominios que corresponden a ítems evaluados en Tinetti con plataforma:
bipodal ojos abiertos, bipodal ojos cerrados y sentarse–pararse.
El giro 360° se analiza aparte (`turn_analysis`) y el empuje se registra a mano (no usó plataformas).
"""
import json
import math
import os

_REF_PATH = os.path.join(os.path.dirname(__file__), "reference.json")


def load_reference(path=None):
    with open(path or _REF_PATH, encoding="utf-8") as f:
        return json.load(f)


def sub_score(name, value, ref):
    """Mapea un valor al rango 0–100 con las anclas good/poor de la métrica."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    m = ref["metrics"][name]
    good, poor = m["good"], m["poor"]
    v = float(value)
    if m.get("log"):
        v, good, poor = math.log(max(v, 1e-9)), math.log(good), math.log(poor)
    s = (v - poor) / (good - poor)
    return round(100 * min(1.0, max(0.0, s)), 1)


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _item(ref, name, value):
    m = ref["metrics"][name]
    return {"metric": name, "label": m["label"], "unit": m["unit"], "value": value, "score": sub_score(name, value, ref)}


def domain_scores(tests, ref):
    out = {}
    for key, dom in (("QS_EO", "bipodal_ojos_abiertos"), ("QS_EC", "bipodal_ojos_cerrados")):
        q = tests.get(key)
        if q:
            items = [_item(ref, "qs_vel", q["vel_mm_s"]), _item(ref, "qs_area", q["area95_mm2"])]
            out[dom] = {"items": items, "score": _mean([i["score"] for i in items])}
    s = tests.get("STS")
    if s and s.get("cycle_s") is not None:
        items = [_item(ref, "sts_cycle", s["cycle_s"]), _item(ref, "sts_cv", s.get("cycle_cv_pct"))]
        out["sentarse_pararse"] = {"items": items, "score": _mean([i["score"] for i in items])}
    return out


def band_for(score, ref):
    for b in ref["bands"]:
        if score >= b["min"]:
            return b
    return ref["bands"][-1]


def flags(tests):
    """Observaciones automáticas (no puntúan)."""
    f = []
    qo, qc = tests.get("QS_EO"), tests.get("QS_EC")
    if qo and qc and qo["vel_mm_s"] > 0:
        r = qc["vel_mm_s"] / qo["vel_mm_s"]
        if r >= 1.5:
            f.append(f"Cociente de Romberg alto ({r:.2f}): marcada dependencia visual.")
    for q, name in ((qo, "ojos abiertos"), (qc, "ojos cerrados")):
        if q and q.get("load_asym_pct", 0) >= 15:
            f.append(f"Asimetría de carga bipodal de {q['load_asym_pct']:.0f} % ({name}).")
            break
    s = tests.get("STS")
    if s and (s.get("load_asym_pct") or 0) >= 20:
        f.append(f"Asimetría de carga al pararse de {s['load_asym_pct']:.0f} %.")
    return f


def turn_analysis(g, ref=None):
    """Análisis aparte del giro de 360° (no entra al score principal)."""
    if not g:
        return None
    ref = ref or load_reference()
    items = [_item(ref, "turn_time", g["turn_s"]), _item(ref, "turn_steps", g["steps"])]
    sc = _mean([i["score"] for i in items])
    b = band_for(sc, ref) if sc is not None else None
    return {"score": None if sc is None else round(sc, 1),
            "band": {"label": b["label"], "color": b["color"]} if b else None,
            "items": items, "turn_s": g["turn_s"], "steps": g["steps"], "step_s": g.get("step_s"),
            "single_support_pct": g.get("single_support_pct")}


def balance_score(tests, ref=None):
    """Combina dominios disponibles con pesos renormalizados (sin giro ni monopodal)."""
    ref = ref or load_reference()
    doms = domain_scores(tests, ref)
    giro = turn_analysis(tests.get("GIRO"), ref)
    num = den = 0.0
    for k, d in doms.items():
        if d["score"] is None:
            continue
        w = ref["domains"][k]["weight"]
        d["weight"], d["label"] = w, ref["domains"][k]["label"]
        num += w * d["score"]
        den += w
    if den == 0:
        return {"score": None, "domains": doms, "coverage_pct": 0, "flags": [], "band": None, "giro": giro}
    total = round(num / den, 1)
    b = band_for(total, ref)
    cov = round(100 * den / sum(v["weight"] for v in ref["domains"].values()))
    missing = [ref["domains"][k]["label"] for k in ref["domains"] if k not in doms]
    return {"score": total, "band": {"label": b["label"], "color": b["color"]}, "domains": doms,
            "coverage_pct": cov, "missing_domains": missing, "flags": flags(tests), "giro": giro}
