"""Configuracion central: rutas de salida y parametros por defecto.

Los modulos importan de aqui las constantes (rutas, delays, reintentos). Los
parametros de cada corrida (top-n, anios, tickers) se reciben por CLI en main.py.
"""
from __future__ import annotations

from pathlib import Path

# Raiz del repo = carpeta padre de src/
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONSTITUENTS_DIR = DATA_DIR / "constituents"
PRICES_DIR = DATA_DIR / "prices"
FUNDAMENTALS_DIR = DATA_DIR / "fundamentals"

# Parametros por defecto del universo y del historico
DEFAULT_TOP_N = 100
DEFAULT_YEARS = 5
PRICE_BATCH_SIZE = 20  # tickers por lote en yf.download (menos requests = menos 429)

# Robustez frente a rate limits (llamadas por-ticker a Yahoo)
REQUEST_DELAY_MIN = 0.4  # segundos
REQUEST_DELAY_MAX = 1.2  # segundos
MAX_RETRIES = 4
RETRY_BACKOFF_BASE = 2.0  # segundos (crecimiento exponencial con jitter, tope 30s)

# Fuentes externas
SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def ensure_dirs() -> None:
    """Crea las carpetas de salida si no existen."""
    for d in (CONSTITUENTS_DIR, PRICES_DIR, FUNDAMENTALS_DIR):
        d.mkdir(parents=True, exist_ok=True)
