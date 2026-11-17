"""Score de equilibrio (0–100) a partir de las métricas de plataforma de fuerza."""
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
    """tests: {'QS_EO':{..}, 'QS_EC':{..}, 'SLS':[{..,'eyes':'EO'|'EC'}], 'STS':{..}, 'GIRO':{..}}"""
    out = {}
    for key, dom in (("QS_EO", "bipodal_ojos_abiertos"), ("QS_EC", "bipodal_ojos_cerrados")):
        q = tests.get(key)
        if q:
            items = [_item(ref, "qs_vel", q["vel_mm_s"]), _item(ref, "qs_area", q["area95_mm2"])]
            out[dom] = {"items": items, "score": _mean([i["score"] for i in items])}
    sls = tests.get("SLS") or []
    if sls:
        trials, per = [], []
        for t in sls:
            items = [_item(ref, "sls_hold", t["hold_s"])]
            if t.get("touchdowns") is not None:
                items.append(_item(ref, "sls_touch", t["touchdowns"]))
            if t.get("sway"):
                items.append(_item(ref, "sls_vel", t["sway"]["vel_mm_s"]))
            sc = _mean([i["score"] for i in items])
            trials.append({"side": t["side"], "eyes": t.get("eyes", "EO"), "hold_s": t["hold_s"],
                           "touchdowns": t.get("touchdowns"), "items": items, "score": sc})
            per.append(sc)
        out["monopodal"] = {"trials": trials, "score": _mean(per)}
    s = tests.get("STS")
    if s and s.get("cycle_s") is not None:
        items = [_item(ref, "sts_cycle", s["cycle_s"]), _item(ref, "sts_cv", s.get("cycle_cv_pct"))]
        out["sentarse_pararse"] = {"items": items, "score": _mean([i["score"] for i in items])}
    g = tests.get("GIRO")
    if g:
        items = [_item(ref, "turn_time", g["turn_s"]), _item(ref, "turn_steps", g["steps"])]
        out["giro"] = {"items": items, "score": _mean([i["score"] for i in items])}
    return out


def band_for(score, ref):
    for b in ref["bands"]:
        if score >= b["min"]:
            return b
    return ref["bands"][-1]


def flags(tests):
    """Observaciones clínicas automáticas (no puntúan)."""
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
    sls = [t for t in (tests.get("SLS") or []) if t.get("eyes", "EO") == "EO"]
    byside = {t["side"]: t for t in sls}
    if "L" in byside and "R" in byside:
        a, b = byside["L"]["hold_s"], byside["R"]["hold_s"]
        if max(a, b) > 0 and abs(a - b) / max(a, b) >= 0.3:
            f.append(f"Diferencia entre piernas en apoyo monopodal (I {a:.0f} s vs D {b:.0f} s).")
    for t in sls:
        if t["hold_s"] < 5:
            f.append(f"Apoyo monopodal {t['side']} < 5 s (umbral asociado a mayor riesgo de caídas).")
    s = tests.get("STS")
    if s and (s.get("load_asym_pct") or 0) >= 20:
        f.append(f"Asimetría de carga al pararse de {s['load_asym_pct']:.0f} %.")
    return f


def balance_score(tests, ref=None):
    """Combina dominios disponibles con pesos renormalizados. Devuelve dict completo."""
    ref = ref or load_reference()
    doms = domain_scores(tests, ref)
    num = den = 0.0
    for k, d in doms.items():
        if d["score"] is None:
            continue
        w = ref["domains"][k]["weight"]
        d["weight"], d["label"] = w, ref["domains"][k]["label"]
        num += w * d["score"]
        den += w
    if den == 0:
        return {"score": None, "domains": doms, "coverage_pct": 0, "flags": [], "band": None}
    total = round(num / den, 1)
    b = band_for(total, ref)
    cov = round(100 * den / sum(v["weight"] for v in ref["domains"].values()))
    missing = [ref["domains"][k]["label"] for k in ref["domains"] if k not in doms]
    return {"score": total, "band": {"label": b["label"], "color": b["color"]}, "domains": doms,
            "coverage_pct": cov, "missing_domains": missing, "flags": flags(tests)}
