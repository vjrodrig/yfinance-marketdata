"""CLI: descarga precios diarios, utilidad y ratios del top-100 del S&P 500.

Uso tipico:
    python src/main.py                          # top 100, 5 anios, todo
    python src/main.py --tickers AAPL MSFT NVDA # tickers explicitos (smoke test)
    python src/main.py --limit 10 --skip-fundamentals
    python src/main.py --years 10 --refresh-universe
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta
from tqdm import tqdm

import config
import constituents as univ
import fundamentals as fund
import prices as prices_mod
import storage
from session import polite_sleep

log = logging.getLogger("marketdata")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Descarga precios diarios, utilidad y ratios (P/E, P/BV, EV/EBITDA, "
        "ROE, ROIC) del top-100 del S&P 500 usando yfinance."
    )
    p.add_argument("--top-n", type=int, default=config.DEFAULT_TOP_N,
                   help=f"Numero de acciones por capitalizacion (def. {config.DEFAULT_TOP_N}).")
    p.add_argument("--years", type=int, default=config.DEFAULT_YEARS,
                   help=f"Anios de historico de precios (def. {config.DEFAULT_YEARS}).")
    p.add_argument("--tickers", nargs="+", metavar="SYM",
                   help="Lista explicita de tickers; omite el ranking del S&P 500.")
    p.add_argument("--limit", type=int, default=None,
                   help="Limita el numero de tickers tras armar el universo (util para pruebas).")
    p.add_argument("--refresh-universe", action="store_true",
                   help="Re-descarga y re-rankea el universo aunque ya exista el CSV de hoy.")
    p.add_argument("--skip-prices", action="store_true", help="No descargar precios.")
    p.add_argument("--skip-fundamentals", action="store_true",
                   help="No descargar fundamentales (ratios/utilidad).")
    p.add_argument("--verbose", "-v", action="store_true", help="Logging en DEBUG.")
    return p.parse_args(argv)


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # yfinance y libs HTTP son ruidosas; bajarlas salvo en modo verbose.
    noisy = logging.DEBUG if verbose else logging.WARNING
    for name in ("yfinance", "urllib3", "requests", "peewee"):
        logging.getLogger(name).setLevel(noisy)


def resolve_universe(args: argparse.Namespace, today: date) -> tuple[pd.DataFrame, bool]:
    """Devuelve (universo, se_escribio_csv). El universo siempre tiene yahoo_symbol."""
    if args.tickers:
        syms = [univ.to_yahoo_symbol(s) for s in args.tickers]
        df = pd.DataFrame(
            {
                "rank": range(1, len(syms) + 1),
                "symbol": [s.replace("-", ".") for s in syms],
                "yahoo_symbol": syms,
                "name": None,
                "sector": None,
                "market_cap": pd.NA,
            }
        )
        log.info("Universo explicito: %d tickers", len(df))
        return df, False

    path = storage.universe_path(today)
    if path.exists() and not args.refresh_universe:
        df = pd.read_csv(path)
        log.info("Reusando universo de hoy: %s (%d filas). Usa --refresh-universe para rehacerlo.",
                 path, len(df))
        return df, False

    constituents = univ.fetch_sp500_constituents()
    df = univ.top_n_by_market_cap(constituents, n=args.top_n)
    storage.write_universe(df, today)
    return df, True


def run_fundamentals(tickers: list[str], today: date) -> dict:
    """Descarga ratios + utilidad por ticker y escribe los CSV. Devuelve stats."""
    snapshot_rows: list[dict] = []
    annual_frames: list[pd.DataFrame] = []
    quarterly_frames: list[pd.DataFrame] = []
    failed: list[str] = []

    for tk in tqdm(tickers, desc="Fundamentals", unit="tk"):
        try:
            info, income, q_income, balance = fund.fetch_ticker_fundamentals(tk)
            snapshot_rows.append(fund.build_snapshot(tk, info, income, balance))
            currency = fund.currency_of(info)
            annual_frames.append(fund.extract_net_income(income, tk, currency))
            quarterly_frames.append(fund.extract_net_income(q_income, tk, currency))
        except Exception as exc:  # noqa: BLE001 - tolerar fallos por ticker
            log.warning("fundamentals fallo %s: %s", tk, exc)
            failed.append(tk)
        finally:
            polite_sleep()

    if snapshot_rows:
        storage.append_snapshot(snapshot_rows, today)
    annual = (
        pd.concat(annual_frames, ignore_index=True)
        if annual_frames
        else pd.DataFrame(columns=fund.NET_INCOME_COLS)
    )
    quarterly = (
        pd.concat(quarterly_frames, ignore_index=True)
        if quarterly_frames
        else pd.DataFrame(columns=fund.NET_INCOME_COLS)
    )
    storage.upsert_net_income(annual, "net_income_annual.csv")
    storage.upsert_net_income(quarterly, "net_income_quarterly.csv")

    return {
        "snapshot_rows": len(snapshot_rows),
        "net_income_annual_rows": int(len(annual)),
        "net_income_quarterly_rows": int(len(quarterly)),
        "failed": failed,
    }


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    config.ensure_dirs()

    today = date.today()
    manifest: dict = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "params": {"top_n": args.top_n, "years": args.years,
                   "explicit_tickers": args.tickers, "limit": args.limit},
    }

    universe, _ = resolve_universe(args, today)
    if args.limit:
        universe = universe.head(args.limit).reset_index(drop=True)
    tickers = universe["yahoo_symbol"].astype(str).tolist()
    manifest["n_tickers"] = len(tickers)
    log.info("Universo final: %d tickers", len(tickers))

    if not args.skip_prices:
        start = (today - relativedelta(years=args.years)).isoformat()
        end = (today + timedelta(days=1)).isoformat()  # end exclusivo -> incluir hoy
        manifest["price_window"] = {"start": start, "end": end}
        log.info("Descargando precios diarios %s -> %s", start, end)
        df_prices, price_failed = prices_mod.download_prices(tickers, start, end)
        storage.write_prices(df_prices)
        manifest["prices"] = {
            "rows": int(len(df_prices)),
            "tickers_ok": int(df_prices["ticker"].nunique()) if not df_prices.empty else 0,
            "failed": price_failed,
        }
    else:
        log.info("Precios omitidos (--skip-prices)")

    if not args.skip_fundamentals:
        log.info("Descargando fundamentales (ratios + utilidad) de %d tickers", len(tickers))
        manifest["fundamentals"] = run_fundamentals(tickers, today)
    else:
        log.info("Fundamentales omitidos (--skip-fundamentals)")

    storage.write_manifest(manifest)
    _print_summary(manifest)
    return 0


def _print_summary(manifest: dict) -> None:
    print("\n" + "=" * 60)
    print("RESUMEN DE LA CORRIDA")
    print("=" * 60)
    print(f"Tickers en el universo : {manifest.get('n_tickers', 0)}")
    if "prices" in manifest:
        pr = manifest["prices"]
        print(f"Precios                : {pr['rows']:,} filas | "
              f"{pr['tickers_ok']} ok | {len(pr['failed'])} fallidos")
    if "fundamentals" in manifest:
        fu = manifest["fundamentals"]
        print(f"Ratios (snapshot)      : {fu['snapshot_rows']} filas")
        print(f"Utilidad anual         : {fu['net_income_annual_rows']} filas")
        print(f"Utilidad trimestral    : {fu['net_income_quarterly_rows']} filas")
        if fu["failed"]:
            print(f"Tickers con fallo      : {', '.join(fu['failed'])}")
    print(f"Salida en              : {config.DATA_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
