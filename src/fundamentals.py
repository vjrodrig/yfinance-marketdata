"""Fundamentales por ticker: foto de ratios, ROE, ROIC (calculado) y utilidad.

- Ratios P/E, P/BV, EV/EBITDA y ROE: foto actual desde ``Ticker.info``.
- ROIC: no es nativo en yfinance; se calcula NOPAT / capital invertido a partir
  del income statement y el balance.
- Utilidad (net income): serie anual y trimestral desde los estados financieros.

Las funciones ``build_snapshot`` / ``compute_roic`` / ``extract_net_income`` son
puras (no tocan la red): reciben los DataFrames ya descargados y son faciles de testear.
"""
from __future__ import annotations

import logging
import math

import pandas as pd
import yfinance as yf

from session import with_retries

log = logging.getLogger(__name__)

NET_INCOME_CANDIDATES = [
    "Net Income",
    "Net Income Common Stockholders",
    "Net Income Continuous Operations",
    "Net Income From Continuing Operation Net Minority Interest",
]
NET_INCOME_COLS = ["ticker", "period_end", "net_income", "currency"]


def _num(value) -> float | None:
    """Convierte a float; devuelve None ante None/NaN/no-numerico."""
    try:
        if value is None:
            return None
        f = float(value)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _row_value(df: pd.DataFrame | None, candidates: list[str]) -> float | None:
    """Valor mas reciente (primera columna) de la primera fila que matchee por nombre."""
    if df is None or getattr(df, "empty", True):
        return None
    index = {str(i).strip().lower(): i for i in df.index}
    for cand in candidates:
        key = cand.strip().lower()
        if key in index:
            return _num(df.loc[index[key]].iloc[0])
    return None


@with_retries
def fetch_ticker_fundamentals(ticker: str):
    """Trae info + estados financieros de un ticker (todas las llamadas de red).

    Devuelve (info, income_anual, income_trimestral, balance).
    """
    t = yf.Ticker(ticker)
    info = t.info or {}
    income = t.income_stmt
    quarterly_income = t.quarterly_income_stmt
    balance = t.balance_sheet
    return info, income, quarterly_income, balance


def compute_roic(income: pd.DataFrame, balance: pd.DataFrame) -> float | None:
    """ROIC = NOPAT / capital invertido (mas reciente disponible).

    NOPAT = EBIT * (1 - tasa impositiva). Capital invertido = fila "Invested Capital"
    del balance si existe; si no, Deuda total + Patrimonio - Caja. Devuelve None
    cuando faltan campos clave.
    """
    ebit = _row_value(
        income, ["EBIT", "Operating Income", "Total Operating Income As Reported"]
    )
    if ebit is None:
        return None

    tax_rate = _row_value(income, ["Tax Rate For Calcs"])
    if tax_rate is None:
        tax_rate = _ratio(
            _row_value(income, ["Tax Provision"]),
            _row_value(income, ["Pretax Income"]),
        )
    if tax_rate is None:
        return None
    tax_rate = min(max(tax_rate, 0.0), 1.0)  # sanea valores fuera de rango

    nopat = ebit * (1.0 - tax_rate)

    invested = _row_value(balance, ["Invested Capital"])
    if invested is None:
        debt = _row_value(balance, ["Total Debt"])
        if debt is None:
            long_debt = _row_value(balance, ["Long Term Debt"]) or 0.0
            short_debt = (
                _row_value(
                    balance, ["Current Debt", "Current Debt And Capital Lease Obligation"]
                )
                or 0.0
            )
            debt = (long_debt + short_debt) or None
        equity = _row_value(
            balance,
            ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"],
        )
        cash = _row_value(
            balance,
            ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
        )
        if debt is None or equity is None:
            return None
        invested = debt + equity - (cash or 0.0)

    return _ratio(nopat, invested)


def build_snapshot(
    ticker: str, info: dict, income: pd.DataFrame, balance: pd.DataFrame
) -> dict:
    """Arma la fila de foto de valoracion para un ticker."""
    g = info.get
    return {
        "ticker": ticker,
        "trailing_pe": _num(g("trailingPE")),
        "forward_pe": _num(g("forwardPE")),
        "price_to_book": _num(g("priceToBook")),
        "ev_to_ebitda": _num(g("enterpriseToEbitda")),
        "roe": _num(g("returnOnEquity")),
        "roic": compute_roic(income, balance),
        "market_cap": _num(g("marketCap")),
        "enterprise_value": _num(g("enterpriseValue")),
        "ebitda": _num(g("ebitda")),
        "net_income_ttm": _num(g("netIncomeToCommon")),
        "trailing_eps": _num(g("trailingEps")),
    }


def extract_net_income(
    stmt: pd.DataFrame, ticker: str, currency: str | None
) -> pd.DataFrame:
    """Serie de utilidad (net income) por periodo desde un income statement.

    Devuelve filas: ticker, period_end, net_income, currency.
    """
    empty = pd.DataFrame(columns=NET_INCOME_COLS)
    if stmt is None or stmt.empty:
        return empty

    index = {str(i).strip().lower(): i for i in stmt.index}
    row = None
    for cand in NET_INCOME_CANDIDATES:
        key = cand.strip().lower()
        if key in index:
            row = stmt.loc[index[key]]
            break
    if row is None:  # ultimo recurso: cualquier fila que contenga "net income"
        for low, orig in index.items():
            if "net income" in low:
                row = stmt.loc[orig]
                break
    if row is None:
        return empty

    out = pd.DataFrame(
        {
            "ticker": ticker,
            "period_end": [pd.to_datetime(c).date() for c in row.index],
            "net_income": [_num(v) for v in row.values],
            "currency": currency,
        }
    )
    return out.dropna(subset=["net_income"]).reset_index(drop=True)


def currency_of(info: dict) -> str | None:
    """Moneda de los estados financieros (cae a la moneda de cotizacion)."""
    return info.get("financialCurrency") or info.get("currency")
