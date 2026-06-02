"""Universo de trabajo: las top-N acciones del S&P 500 por capitalizacion.

Se lee la lista del S&P 500 desde Wikipedia, se normalizan los simbolos al
formato de Yahoo (BRK.B -> BRK-B), se obtiene el market cap de cada una via
``fast_info`` (llamada liviana) y se ordena para quedarse con las N mayores.
"""
from __future__ import annotations

import logging
from io import StringIO

import pandas as pd
import requests
import yfinance as yf
from tqdm import tqdm

import config
from session import polite_sleep, with_retries

log = logging.getLogger(__name__)


def to_yahoo_symbol(symbol: str) -> str:
    """Normaliza un simbolo al formato de Yahoo: BRK.B -> BRK-B, BF.B -> BF-B."""
    return symbol.strip().upper().replace(".", "-")


def fetch_sp500_constituents() -> pd.DataFrame:
    """Lee la tabla de constituyentes del S&P 500 desde Wikipedia.

    Devuelve columnas: symbol, yahoo_symbol, name, sector.
    """
    resp = requests.get(
        config.SP500_WIKI_URL,
        headers={"User-Agent": config.HTTP_USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]  # la primera tabla es la de constituyentes
    df = df.rename(
        columns={"Symbol": "symbol", "Security": "name", "GICS Sector": "sector"}
    )
    out = df[["symbol", "name", "sector"]].copy()
    out["symbol"] = out["symbol"].astype(str).str.strip()
    out["yahoo_symbol"] = out["symbol"].map(to_yahoo_symbol)
    out = out.drop_duplicates(subset="yahoo_symbol").reset_index(drop=True)
    log.info("S&P 500: %d constituyentes leidos de Wikipedia", len(out))
    return out


@with_retries
def _market_cap(yahoo_symbol: str) -> float | None:
    """Market cap de un ticker via fast_info (None si no disponible)."""
    fi = yf.Ticker(yahoo_symbol).fast_info
    try:
        mc = fi["marketCap"]  # fast_info: usar acceso por clave, no .get()
    except Exception:  # noqa: BLE001 - fast_info puede lanzar varios tipos de error
        return None
    return float(mc) if mc else None


def top_n_by_market_cap(
    constituents: pd.DataFrame, n: int = config.DEFAULT_TOP_N
) -> pd.DataFrame:
    """Obtiene market cap por ticker, ordena descendente y toma las top-N.

    Devuelve: rank, symbol, yahoo_symbol, name, sector, market_cap.
    """
    caps: list[float | None] = []
    for sym in tqdm(constituents["yahoo_symbol"], desc="Market caps", unit="tk"):
        try:
            caps.append(_market_cap(sym))
        except Exception as exc:  # noqa: BLE001 - tolerar fallos por ticker
            log.warning("market cap fallo %s: %s", sym, exc)
            caps.append(None)
        polite_sleep()

    df = constituents.assign(market_cap=caps)
    df = df.dropna(subset=["market_cap"]).sort_values("market_cap", ascending=False)
    df = df.head(n).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    df = df[["rank", "symbol", "yahoo_symbol", "name", "sector", "market_cap"]]
    log.info("Top %d por market cap seleccionado", len(df))
    return df
