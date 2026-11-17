import gzip
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from balance.io import classify_test, parse_forcedecks
from balance.metrics import single_leg, sit_stand, sway_metrics, turn
from balance.scoring import balance_score, sub_score, load_reference


def _num(v):
    return f"{v:.3f}".replace(".", ",")


def make_csv(z_l, z_r, fs=1000):
    """CSV sintético con formato ForceDecks (coma decimal, campos entre comillas)."""
    lines = ["ForceDecks Raw Data Export,2.0", f"Frequency,{fs}", "AthleteId,abc", "",
             "Time,Z Left,COPX Left,COPY Left,Z Right,COPX Right,COPY Right"]
    for i in range(len(z_l)):
        lines.append(f'"{_num(i / fs)}","{_num(z_l[i])}",0,0,"{_num(z_r[i])}",0,0')
    return "\r\n".join(lines).encode()


def test_classify():
    assert classify_test("ana-Quiet Stand_Close_Eyes-2026.11.11-07.52.21.csv")[0] == "QS_EC"
    assert classify_test("ana-Quiet Stand-2026.11.11-07.51.47.csv")[0] == "QS_EO"
    assert classify_test("x-Single Leg Stand-Close-Eyes-L-2026.10.29-09.28.00.csv")[0] == "SLS_EC"
    assert classify_test("x-Single Leg Stand-R-2026.10.29-09.28.00.csv")[0] == "SLS_EO"
    assert classify_test("eduardo-2026.11.11-Sit to satd to sit-07.38.07.csv")[0] == "STS"
    assert classify_test("x-2026.11.11-07.56.55_giro.csv")[0] == "GIRO"
    assert classify_test("x-Countermovement Jump-2026.11.11-07.56.27.csv")[0] == "CMJ"


def test_parse_decimal_comma():
    d = parse_forcedecks(make_csv(np.full(1000, 300.5), np.full(1000, 400.25)))
    assert d["athlete_id"] == "abc"
    assert d["zl"].mean() == pytest.approx(300.5, abs=0.01)
    assert d["fs"] == pytest.approx(100)


def test_sway_increases_with_amplitude():
    t = np.arange(0, 20, 0.01)
    small = sway_metrics(np.sin(t) * 2, np.cos(1.3 * t) * 2, 100)
    big = sway_metrics(np.sin(t) * 8, np.cos(1.3 * t) * 8, 100)
    assert big["vel_mm_s"] > small["vel_mm_s"] and big["area95_mm2"] > small["area95_mm2"]


def test_single_leg_hold_and_touchdown():
    fs = 100
    zs = np.full(1800, 700.0)
    zf = np.zeros(1800)
    zf[900:960] = 300  # un toque del pie libre a los 9 s
    d = {"zl": zs, "zr": zf, "xl": np.zeros(1800), "yl": np.zeros(1800), "xr": np.zeros(1800), "yr": np.zeros(1800), "fs": fs}
    r = single_leg(d, bw_n=700)
    assert r["side"] == "L" and r["touchdowns"] == 1 and 8 < r["hold_s"] < 10


def test_sit_stand_counts_reps():
    fs = 100
    one = np.concatenate([np.full(200, 100.0), np.full(300, 700.0)])
    tot = np.tile(one, 4)
    d = {"zl": tot / 2, "zr": tot / 2, "fs": fs}
    r = sit_stand(d, 700)
    assert r["reps"] == 4 and r["cycle_s"] == pytest.approx(5.0, abs=0.1)


def test_turn_counts_steps():
    fs = 100
    zl, zr = np.full(500, 350.0), np.full(500, 350.0)
    zl[100:160] = 0; zr[100:160] = 700   # paso 1 (pie izq. en el aire)
    zr[300:360] = 0; zl[300:360] = 700   # paso 2
    r = turn({"zl": zl, "zr": zr, "fs": fs}, 700)
    assert r["steps"] == 2 and r["turn_s"] == pytest.approx(5.0)


def test_sub_score_bounds_and_direction():
    ref = load_reference()
    assert sub_score("qs_vel", 5, ref) == 100 and sub_score("qs_vel", 99, ref) == 0
    assert sub_score("sls_hold", 18, ref) == 100 and sub_score("sls_hold", 2, ref) == 0
    assert sub_score("qs_vel", 20, ref) > sub_score("qs_vel", 25, ref)


def test_balance_score_renormalises_missing_domains():
    tests = {"QS_EO": {"vel_mm_s": 10, "area95_mm2": 50}}
    out = balance_score(tests)
    assert out["score"] == 100 and out["coverage_pct"] == 20 and out["band"]["label"] == "Bueno"


def test_api_roundtrip():
    from app import app
    c = app.test_client()
    n = 8000
    r = c.post("/api/analyze", data=gzip.compress(make_csv(np.full(n, 350.0) + np.random.randn(n), np.full(n, 350.0))),
               headers={"X-Filename": "p-Quiet%20Stand-2026.01.01.csv"})
    assert r.status_code == 200 and r.get_json()["test"] == "QS_EO"
    s = c.post("/api/score", json={"results": [r.get_json()]})
    assert s.status_code == 200 and 0 <= s.get_json()["score"] <= 100
