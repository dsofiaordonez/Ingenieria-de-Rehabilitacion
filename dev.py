"""Servidor local de desarrollo: sirve public/ y la API (equivalente a lo que hace Vercel)."""
import os
from flask import send_from_directory
from api.index import app

PUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")


@app.get("/")
def _index():
    return send_from_directory(PUB, "index.html")


@app.get("/<path:p>")
def _static(p):  # en Vercel, public/ se sirve en la raíz automáticamente
    return send_from_directory(PUB, p)


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 3000)), debug=False)
