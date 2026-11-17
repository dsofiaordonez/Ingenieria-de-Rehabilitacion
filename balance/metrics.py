"""Métricas biomecánicas por prueba (COP, apoyo monopodal, sentarse-pararse, giro).

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


# ----------------------------------------------------------------------------- Single Leg Stand
def single_leg(d, bw_n=None, trim_s=0.5):
    """Apoyo monopodal: pierna de apoyo se infiere de la plataforma más cargada.

    - hold_s: tiempo continuo más largo con la pierna libre descargada (< 10 % de la carga total).
    - touchdowns: nº de veces que el pie libre vuelve a apoyar tras haberse elevado.
    - sway: oscilación del COP de la plataforma de apoyo durante el tramo de apoyo monopodal.
    """
    fs = d["fs"]
    zl, zr = d["zl"], d["zr"]
    side = "L" if np.mean(zl) > np.mean(zr) else "R"
    zs, zf = (zl, zr) if side == "L" else (zr, zl)
    xs, ys = (d["xl"], d["yl"]) if side == "L" else (d["xr"], d["yr"])
    tot = np.clip(zl, 0, None) + np.clip(zr, 0, None)
    ref = bw_n or float(np.percentile(tot, 90))
    free_off = (np.clip(zf, 0, None) < 0.10 * ref) & (zs > 0.5 * ref)
    runs = _runs(free_off, min_len=int(0.3 * fs))
    dur = len(zl) / fs
    if not runs:
        return {"side": side, "hold_s": 0.0, "touchdowns": None, "dur_s": round(dur, 1), "sway": None}
    s, e = max(runs, key=lambda r: r[1] - r[0])
    hold = (e - s) / fs
    # toques posteriores: tramos con pie libre cargado > 10 % entre el primer y último apoyo monopodal
    first, last = runs[0][0], runs[-1][1]
    loaded_between = _runs(~free_off[first:last], min_len=int(0.1 * fs))
    td = len(loaded_between)
    k = int(trim_s * fs)
    s2, e2 = s + k, e - k
    sway = None
    if e2 - s2 > 2 * fs:
        sway = sway_metrics(xs[s2:e2].astype(float), ys[s2:e2].astype(float), fs)
    return {
        "side": side,
        "hold_s": round(hold, 1),
        "touchdowns": int(td),
        "dur_s": round(dur, 1),
        "sway": sway,
    }


# ----------------------------------------------------------------------------- Sit-to-Stand-to-Sit
def sit_stand(d, bw_n):
    """Repeticiones sentado-parado-sentado a partir de la carga total sobre las plataformas."""
    fs = d["fs"]
    tot = np.clip(d["zl"], 0, None) + np.clip(d["zr"], 0, None)
    # suavizado 0.1 s
    w = max(1, int(0.1 * fs))
    tot = np.convolve(tot, np.ones(w) / w, mode="same")
    rel = tot / bw_n
    # umbrales adaptativos (la carga sentado/de pie varía según apoyo de pies): histéresis entre p10 y p90
    lo, hi = float(np.percentile(rel, 10)), float(np.percentile(rel, 90))
    if hi - lo < 0.3:
        return {"reps": 0, "dur_s": round(len(tot) / fs, 1), "bw_ratio_peak": round(float(np.percentile(rel, 99)), 2)}
    up_thr, dn_thr = lo + 0.65 * (hi - lo), lo + 0.40 * (hi - lo)
    state, events = False, []
    for i, v in enumerate(rel):
        if not state and v > up_thr:
            state = True
            events.append(("up", i))
        elif state and v < dn_thr:
            state = False
            events.append(("down", i))
    ups = [i for k, i in events if k == "up"]
    downs = [i for k, i in events if k == "down"]
    stands = []
    for u in ups:
        dn = next((x for x in downs if x > u), len(rel) - 1)  # si el registro termina de pie, cierra al final
        if (dn - u) / fs >= 0.3:
            stands.append((u, dn))
    n = len(stands)
    out = {"reps": n, "dur_s": round(len(tot) / fs, 1), "bw_ratio_peak": round(float(np.percentile(rel, 99)), 2)}
    if n >= 2:
        cyc = np.diff([s for s, _ in stands]) / fs
        out["cycle_s"] = round(float(np.mean(cyc)), 2)
        out["cycle_cv_pct"] = round(float(np.std(cyc) / np.mean(cyc) * 100), 1)
        out["total_s"] = round((stands[-1][0] - stands[0][0]) / fs + float(np.mean(cyc)), 1)
        out["stand_s"] = round(float(np.mean([(b - a) / fs for a, b in stands])), 2)
    # asimetría de carga entre piernas durante las fases de pie
    if n >= 1:
        a = []
        for s, e in stands:
            zl, zr = d["zl"][s:e], d["zr"][s:e]
            t = np.maximum(zl + zr, 1)
            a.append(np.mean(np.abs(zl - zr) / t))
        out["load_asym_pct"] = round(float(np.mean(a)) * 100, 1)
    return out


# ----------------------------------------------------------------------------- Giro 360°
def turn(d, bw_n):
    """Giro de 360°: duración, nº de pasos (episodios de pie descargado) y apoyo simple."""
    fs = d["fs"]
    zl, zr = d["zl"], d["zr"]
    tot = np.clip(zl, 0, None) + np.clip(zr, 0, None)
    dur = len(zl) / fs
    thr = 0.15 * bw_n
    steps = 0
    single = np.zeros(len(zl), dtype=bool)
    for z, other in ((zl, zr), (zr, zl)):
        off = z < thr
        # ignora el tramo inicial/final en que el pie aún no está/ya salió de la plataforma
        runs = [(s, e) for s, e in _runs(off, min_len=int(0.1 * fs)) if s > 0 and e < len(z)]
        steps += len(runs)
        for s, e in runs:
            single[s:e] = other[s:e] > 0.5 * bw_n
    return {
        "turn_s": round(dur, 2),
        "steps": int(steps),
        "step_s": round(dur / steps, 2) if steps else None,
        "single_support_pct": round(100 * float(single.mean()), 1),
        "min_load_pct": round(100 * float(tot.min() / bw_n), 0),
    }
