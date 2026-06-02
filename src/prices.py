"""Descarga de precios diarios (OHLCV) en formato largo/tidy.

Estrategia: ``yf.download`` por lotes (pocas requests grandes -> menos 429) con
fallback individual via ``Ticker.history`` para los tickers que vuelvan vacios.
Salida: una fila por (fecha, ticker) con open/high/low/close/adj_close/volume.
"""
from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

import config
from session import with_retries

log = logging.getLogger(__name__)

PRICE_COLS = ["open", "high", "low", "close", "adj_close", "volume"]
_FIELD_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


@with_retries
def _download_batch(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    return yf.download(
        tickers,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,  # conserva Close y Adj Close por separado
        actions=False,
        group_by="ticker",
        threads=True,
        progress=False,
    )


@with_retries
def _history_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    return yf.Ticker(ticker).history(
        start=start, end=end, interval="1d", auto_adjust=False, actions=False
    )


def _extract_block(raw: pd.DataFrame | None, ticker: str) -> pd.DataFrame | None:
    """Extrae el sub-DataFrame de un ticker, tolerando ambas orientaciones de columnas."""
    if raw is None or raw.empty:
        return None
    cols = raw.columns
    if isinstance(cols, pd.MultiIndex):
        if ticker in set(cols.get_level_values(0)):
            return raw[ticker]
        if ticker in set(cols.get_level_values(-1)):  # orientacion (campo, ticker)
            return raw.xs(ticker, axis=1, level=-1)
        return None
    return raw  # columnas planas -> un solo ticker


def _tidy_one(block: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Convierte el bloque OHLCV de un ticker a formato largo."""
    df = block.rename(columns=_FIELD_MAP)
    keep = [c for c in PRICE_COLS if c in df.columns]
    df = df[keep].dropna(how="all").reset_index()
    df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["ticker"] = ticker
    return df[["date", "ticker", *keep]]


def download_prices(
    tickers: list[str], start: str, end: str
) -> tuple[pd.DataFrame, list[str]]:
    """Descarga precios diarios para todos los tickers.

    Devuelve (DataFrame largo, lista de tickers fallidos).
    """
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    batches = [
        tickers[i : i + config.PRICE_BATCH_SIZE]
        for i in range(0, len(tickers), config.PRICE_BATCH_SIZE)
    ]

    for batch in batches:
        try:
            raw = _download_batch(batch, start, end)
        except Exception as exc:  # noqa: BLE001
            log.warning("lote fallo (%s ...): %s -> fallback individual", batch[0], exc)
            raw = None

        for tk in batch:
            try:
                block = _extract_block(raw, tk)
                if block is None or block.dropna(how="all").empty:
                    block = _history_single(tk, start, end)  # fallback
                if block is None or block.dropna(how="all").empty:
                    log.warning("sin datos de precios: %s", tk)
                    failed.append(tk)
                    continue
                frames.append(_tidy_one(block, tk))
            except Exception as exc:  # noqa: BLE001
                log.warning("precio fallo %s: %s", tk, exc)
                failed.append(tk)

    if not frames:
        return pd.DataFrame(columns=["date", "ticker", *PRICE_COLS]), failed

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    log.info(
        "Precios: %d filas, %d tickers ok, %d fallidos",
        len(out),
        out["ticker"].nunique(),
        len(failed),
    )
    return out, failed
