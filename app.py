"""App Flask para Vercel: sirve la interfaz (public/) y la API (/api/*). Entrypoint: app.py -> app."""
import gzip
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import numpy as np
from flask import Flask, jsonify, request, send_from_directory

from balance.pipeline import analyze_file, assemble_tests
from balance.scoring import balance_score, load_reference
from balance.tinetti import ITEMS, MAX_TOTAL, parse_tinetti_docx

app = Flask(__name__, static_folder=None)
PUBLIC = os.path.join(ROOT, "public")


def _body():
    raw = request.get_data()
    if raw[:2] == b"\x1f\x8b":  # el navegador comprime para esquivar el límite de 4,5 MB de Vercel
        raw = gzip.decompress(raw)
    return raw


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    raise TypeError(type(o))


@app.after_request
def _headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/api/reference")
def reference():
    return app.response_class(json.dumps({"reference": load_reference(), "tinetti_items": ITEMS,
                                          "tinetti_max": MAX_TOTAL}, default=_json_default), mimetype="application/json")


@app.post("/api/analyze")
def analyze():
    """Cuerpo: CSV (opcionalmente gzip). Cabeceras: X-Filename (url-encoded), X-BW-Map (json), X-Plate-Sep."""
    from urllib.parse import unquote
    filename = unquote(request.headers.get("X-Filename", "archivo.csv"))
    try:
        bw_map = json.loads(unquote(request.headers.get("X-BW-Map", "{}")) or "{}")
        sep = float(request.headers.get("X-Plate-Sep", 400))
        res = analyze_file(filename, _body(), bw_map, sep)
        return app.response_class(json.dumps(res, default=_json_default), mimetype="application/json")
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e), filename=filename), 422


@app.post("/api/score")
def score():
    """JSON: {results:[salidas de /api/analyze]} -> score de equilibrio y desglose."""
    payload = request.get_json(force=True, silent=True) or {}
    tests = assemble_tests(payload.get("results", []))
    if not tests:
        return jsonify(error="Sin pruebas válidas para puntuar"), 422
    out = balance_score(tests)
    return app.response_class(json.dumps(out, default=_json_default), mimetype="application/json")


@app.post("/api/tinetti")
def tinetti():
    """Cuerpo: .docx de Tinetti (resaltado = opción puntuada)."""
    try:
        pts = parse_tinetti_docx(_body())
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"No pude leer el Word: {e}"), 422
    return jsonify(patients=pts, max_total=MAX_TOTAL, items=[{"key": k, "label": l, "max": m} for k, l, m in ITEMS])


@app.get("/")
def index():
    return send_from_directory(PUBLIC, "index.html")


@app.get("/vendor/<path:name>")
def vendor(name):
    return send_from_directory(os.path.join(PUBLIC, "vendor"), name)


if __name__ == "__main__":  # desarrollo local: python app.py
    app.run(port=int(os.environ.get("PORT", 3000)))
