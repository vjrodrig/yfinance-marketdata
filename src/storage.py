"""Escritura de los CSV de salida y del manifest de la corrida.

Layout (ver README):
  data/constituents/sp500_top100_<YYYYMMDD>.csv
  data/prices/prices_daily.csv
  data/fundamentals/valuation_snapshot.csv   (append; idempotente por dia)
  data/fundamentals/net_income_annual.csv     (upsert por ticker+period_end)
  data/fundamentals/net_income_quarterly.csv
  data/manifest.json
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd

import config

log = logging.getLogger(__name__)

SNAPSHOT_COLS = [
    "snapshot_date",
    "ticker",
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "ev_to_ebitda",
    "roe",
    "roic",
    "market_cap",
    "enterprise_value",
    "ebitda",
    "net_income_ttm",
    "trailing_eps",
]


def universe_path(day: date) -> Path:
    return config.CONSTITUENTS_DIR / f"sp500_top100_{day:%Y%m%d}.csv"


def write_universe(df: pd.DataFrame, day: date) -> Path:
    path = universe_path(day)
    df.to_csv(path, index=False)
    log.info("Universo escrito: %s (%d filas)", path, len(df))
    return path


def write_prices(df: pd.DataFrame) -> Path:
    path = config.PRICES_DIR / "prices_daily.csv"
    df.to_csv(path, index=False)
    log.info("Precios escritos: %s (%d filas)", path, len(df))
    return path


def append_snapshot(rows: list[dict], snapshot_date: date) -> Path:
    """Agrega la foto de ratios; idempotente por (snapshot_date, ticker)."""
    path = config.FUNDAMENTALS_DIR / "valuation_snapshot.csv"
    df = pd.DataFrame(rows)
    df.insert(0, "snapshot_date", snapshot_date)
    df = df.reindex(columns=SNAPSHOT_COLS)
    if path.exists():
        old = pd.read_csv(path)
        df = pd.concat([old, df], ignore_index=True)
        df["snapshot_date"] = df["snapshot_date"].astype(str)
        df = df.drop_duplicates(subset=["snapshot_date", "ticker"], keep="last")
    df = df.sort_values(["snapshot_date", "ticker"]).reset_index(drop=True)
    df.to_csv(path, index=False)
    log.info("Snapshot de ratios: %s (%d filas)", path, len(df))
    return path


def upsert_net_income(df: pd.DataFrame, filename: str) -> Path:
    """Inserta/actualiza utilidad por (ticker, period_end)."""
    path = config.FUNDAMENTALS_DIR / filename
    if path.exists():
        old = pd.read_csv(path)
        df = pd.concat([old, df], ignore_index=True)
    if not df.empty:
        df["period_end"] = df["period_end"].astype(str)
        df = df.drop_duplicates(subset=["ticker", "period_end"], keep="last")
        df = df.sort_values(["ticker", "period_end"]).reset_index(drop=True)
    df.to_csv(path, index=False)
    log.info("Utilidad escrita: %s (%d filas)", path, len(df))
    return path


def write_manifest(manifest: dict) -> Path:
    path = config.DATA_DIR / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, default=str))
    log.info("Manifest escrito: %s", path)
    return path
