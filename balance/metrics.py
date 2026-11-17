"""Métricas biomecánicas por prueba (COP bipodal, sentarse-pararse, giro).

Convenciones: fuerza en N, COP en mm, tiempo en s. Las señales llegan a ~100 Hz.
COP combinado = promedio ponderado por la fuerza vertical de cada plataforma, con las
plataformas separadas `plate_sep_mm` entre centros (ForceDecks FD4000: ~400 mm; configurable).
"""
import numpy as np

G = 9.81
CHI2_95 = 5.991  # chi-cuadrado 2 g.l., 95 %


# ----------------------------------------------------------------------------- utilidades
def _runs(mask, min_len=1):
    """Devuelve lista de (inicio, fin_exclusivo) de tramos True consecutivos con longitud >= min_len."""
    m = np.concatenate(([False], mask, [False])).astype(np.int8)
    d = np.diff(m)
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [(s, e) for s, e in zip(starts, ends) if e - s >= min_len]


def combined_cop(d, plate_sep_mm=400.0, min_force=20.0):
    """COP combinado (x: ML, y: AP) en mm; NaN donde la carga total es < min_force."""
    zl, zr = np.clip(d["zl"], 0, None), np.clip(d["zr"], 0, None)
    tot = zl + zr
    with np.errstate(invalid="ignore", divide="ignore"):
        x = (zl * (d["xl"] - plate_sep_mm / 2) + zr * (d["xr"] + plate_sep_mm / 2)) / tot
        y = (zl * d["yl"] + zr * d["yr"]) / tot
    bad = tot < min_force
    x[bad] = np.nan
    y[bad] = np.nan
    return x, y


def body_weight_n(d):
    """Peso corporal (N) = mediana de la carga total durante la prueba (útil en Quiet Stand)."""
    return float(np.median(d["zl"] + d["zr"]))


def lowpass(x, fs, fc=10.0):
    """Pasa-bajos zero-phase por FFT (corte ideal en fc Hz) tras quitar la media."""
    m = x.mean()
    f = np.fft.rfft(x - m)
    freqs = np.fft.rfftfreq(len(x), 1.0 / fs)
    f[freqs > fc] = 0
    return np.fft.irfft(f, n=len(x)) + m


def sway_metrics(x, y, fs, fc=10.0):
    """Métricas clásicas de oscilación del COP sobre series x, y (mm), filtradas a fc Hz."""
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < int(fs * 2):
        return None
    x, y = lowpass(x, fs, fc), lowpass(y, fs, fc)
    x, y = x - x.mean(), y - y.mean()
    dx, dy = np.diff(x), np.diff(y)
    path = float(np.sum(np.hypot(dx, dy)))
    dur = len(x) / fs
    cov = np.cov(np.vstack([x, y]))
    area = float(np.pi * CHI2_95 * np.sqrt(max(np.linalg.det(cov), 0.0)))
    return {
        "path_mm": round(path, 1),
        "vel_mm_s": round(path / dur, 2),
        "vel_ml_mm_s": round(float(np.sum(np.abs(dx)) / dur), 2),
        "vel_ap_mm_s": round(float(np.sum(np.abs(dy)) / dur), 2),
        "rms_ml_mm": round(float(np.sqrt(np.mean(x ** 2))), 2),
        "rms_ap_mm": round(float(np.sqrt(np.mean(y ** 2))), 2),
        "area95_mm2": round(area, 1),
        "dur_s": round(dur, 1),
    }


# ----------------------------------------------------------------------------- Quiet Stand
def quiet_stand(d, plate_sep_mm=400.0, trim_s=1.0):
    fs = d["fs"]
    x, y = combined_cop(d, plate_sep_mm)
    k = int(trim_s * fs)
    sl = slice(k, len(x) - k)
    m = sway_metrics(x[sl], y[sl], fs)
    if m is None:
        raise ValueError("Registro demasiado corto para Quiet Stand")
    tot = d["zl"] + d["zr"]
    pct_l = 100 * d["zl"][sl] / np.maximum(tot[sl], 1)
    m["bw_n"] = round(body_weight_n(d), 1)
    m["load_left_pct"] = round(float(np.mean(pct_l)), 1)
    m["load_asym_pct"] = round(float(abs(np.mean(pct_l) - 50) * 2), 1)  # 0 = simétrico
    return m


# ----------------------------------------------------------------------------- Sit-to-Stand-to-Sit
def _sts_events(d, bw_n):
    """Detecta fases de pie. Devuelve (rel, stands[(i0,i1)], up_thr, dn_thr); rel = carga total / peso."""
    fs = d["fs"]
    tot = np.clip(d["zl"], 0, None) + np.clip(d["zr"], 0, None)
    w = max(1, int(0.1 * fs))
    rel = np.convolve(tot, np.ones(w) / w, mode="same") / bw_n
    # umbrales adaptativos (la carga sentado/de pie varía según apoyo de pies): histéresis entre p10 y p90
    lo, hi = float(np.percentile(rel, 10)), float(np.percentile(rel, 90))
    if hi - lo < 0.3:
        return rel, [], None, None
    up_thr, dn_thr = lo + 0.65 * (hi - lo), lo + 0.40 * (hi - lo)
    state, ups, downs = False, [], []
    for i, v in enumerate(rel):
        if not state and v > up_thr:
            state = True
            ups.append(i)
        elif state and v < dn_thr:
            state = False
            downs.append(i)
    stands = []
    for u in ups:
        dn = next((x for x in downs if x > u), len(rel) - 1)  # si el registro termina de pie, cierra al final
        if (dn - u) / fs >= 0.3:
            stands.append((u, dn))
    return rel, stands, up_thr, dn_thr


def sit_stand(d, bw_n):
    """Repeticiones sentado-parado-sentado a partir de la carga total sobre las plataformas."""
    fs = d["fs"]
    rel, stands, _, _ = _sts_events(d, bw_n)
    n = len(stands)
    out = {"reps": n, "dur_s": round(len(rel) / fs, 1), "bw_ratio_peak": round(float(np.percentile(rel, 99)), 2)}
    if n >= 2:
        cyc = np.diff([s for s, _ in stands]) / fs
        out["cycle_s"] = round(float(np.mean(cyc)), 2)
        out["cycle_cv_pct"] = round(float(np.std(cyc) / np.mean(cyc) * 100), 1)
        out["total_s"] = round((stands[-1][0] - stands[0][0]) / fs + float(np.mean(cyc)), 1)
        out["stand_s"] = round(float(np.mean([(b - a) / fs for a, b in stands])), 2)
    # asimetría de carga entre piernas durante las fases de pie
    if n >= 1:
        asym = []
        for s0, e0 in stands:
            zl, zr = d["zl"][s0:e0], d["zr"][s0:e0]
            t = np.maximum(zl + zr, 1)
            asym.append(np.mean(np.abs(zl - zr) / t))
        out["load_asym_pct"] = round(float(np.mean(asym)) * 100, 1)
    return out


# ----------------------------------------------------------------------------- Giro 360°
def _swings(d, bw_n):
    """Episodios de pie descargado (< 15 % del peso, >= 0,1 s) que no tocan el inicio/fin del registro."""
    fs = d["fs"]
    out = []
    for plate, z in (("L", d["zl"]), ("R", d["zr"])):
        for s0, e0 in _runs(z < 0.15 * bw_n, min_len=int(0.1 * fs)):
            if s0 > 0 and e0 < len(z):
                out.append((plate, s0, e0))
    return out


def turn(d, bw_n):
    """Giro de 360°: duración, nº de pasos (episodios de pie descargado) y apoyo simple."""
    fs = d["fs"]
    zl, zr = d["zl"], d["zr"]
    tot = np.clip(zl, 0, None) + np.clip(zr, 0, None)
    dur = len(zl) / fs
    swings = _swings(d, bw_n)
    steps = len(swings)
    single = np.zeros(len(zl), dtype=bool)
    for plate, s0, e0 in swings:
        other = zr if plate == "L" else zl
        single[s0:e0] = other[s0:e0] > 0.5 * bw_n
    return {
        "turn_s": round(dur, 2),
        "steps": int(steps),
        "step_s": round(dur / steps, 2) if steps else None,
        "single_support_pct": round(100 * float(single.mean()), 1),
        "min_load_pct": round(100 * float(tot.min() / bw_n), 0),
    }


# ----------------------------------------------------------------------------- Datos para gráficas
def _dec(a, k, nd=1):
    return [round(float(v), nd) for v in a[::k]]


def plot_quiet(d, plate_sep_mm=400.0, trim_s=1.0):
    """Trayectoria del COP (centrada, filtrada a 10 Hz) y parámetros de la elipse del 95 %."""
    fs = d["fs"]
    x, y = combined_cop(d, plate_sep_mm)
    k = int(trim_s * fs)
    x, y = x[k:len(x) - k], y[k:len(y) - k]
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = lowpass(x[ok], fs), lowpass(y[ok], fs)
    x, y = x - x.mean(), y - y.mean()
    w, v = np.linalg.eigh(np.cov(np.vstack([x, y])))  # autovalores ascendentes
    major = v[:, 1]
    step = max(1, int(round(fs / 25)))  # ~25 Hz para dibujar
    return {"kind": "cop", "x": _dec(x, step, 2), "y": _dec(y, step, 2),
            "ellipse": {"a": round(float(np.sqrt(CHI2_95 * w[1])), 2), "b": round(float(np.sqrt(CHI2_95 * w[0])), 2),
                        "angle": round(float(np.arctan2(major[1], major[0])), 4)}}


def plot_sit_stand(d, bw_n):
    fs = d["fs"]
    rel, stands, up, dn = _sts_events(d, bw_n)
    step = max(1, int(round(fs / 20)))
    return {"kind": "sts", "dt": step / fs, "y": _dec(rel * 100, step, 0),
            "stands": [[round(a / fs, 2), round(b / fs, 2)] for a, b in stands],
            "up_pct": None if up is None else round(up * 100, 0), "dn_pct": None if dn is None else round(dn * 100, 0)}


def plot_turn(d, bw_n):
    fs = d["fs"]
    step = max(1, int(round(fs / 25)))
    return {"kind": "turn", "dt": step / fs, "l": _dec(d["zl"] / bw_n * 100, step, 0), "r": _dec(d["zr"] / bw_n * 100, step, 0),
            "swings": [[p, round(a / fs, 2), round(b / fs, 2)] for p, a, b in _swings(d, bw_n)]}
