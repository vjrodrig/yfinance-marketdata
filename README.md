# yfinance-marketdata

Descarga, para las **100 mayores acciones del S&P 500** (por capitalización de mercado),
usando la librería [`yfinance`](https://pypi.org/project/yfinance/):

- **Precios diarios** (OHLCV) — por defecto 5 años de histórico.
- **Utilidad** (net income) — serie **anual** y **trimestral**.
- **Ratios de valoración y rentabilidad** — P/E, P/BV, EV/EBITDA, ROE y ROIC.

> **Nota sobre los ratios:** yfinance entrega P/E, P/BV, EV/EBITDA y ROE solo como
> **foto actual** (no como serie histórica diaria). El **ROIC** no es nativo: se **calcula**
> como `NOPAT / capital invertido` a partir del income statement y el balance. Cada corrida
> guarda la foto con su fecha (`snapshot_date`), de modo que ejecutando la herramienta
> periódicamente se va acumulando un histórico de ratios.

## Requisitos

- **Python ≥ 3.10** (la dependencia `curl_cffi` no soporta 3.9). Entorno probado: **3.12**.

## Instalación

```bash
python3.12 -m venv env
env/bin/pip install -r requirements.txt
```

## Uso

```bash
# Top 100 del S&P 500, 5 años de precios, ratios + utilidad (corrida completa)
env/bin/python src/main.py

# Prueba rápida con tickers explícitos (omite el ranking del S&P 500)
env/bin/python src/main.py --tickers AAPL MSFT NVDA

# Variantes
env/bin/python src/main.py --years 10                 # 10 años de precios
env/bin/python src/main.py --limit 10                 # solo los 10 primeros del universo
env/bin/python src/main.py --skip-fundamentals        # solo precios
env/bin/python src/main.py --refresh-universe         # rehace el ranking aunque exista el de hoy
```

Flags principales: `--top-n` (def. 100), `--years` (def. 5), `--tickers`, `--limit`,
`--refresh-universe`, `--skip-prices`, `--skip-fundamentals`, `--verbose`.

> La primera corrida completa rankea ~500 constituyentes por market cap (una llamada liviana
> por ticker), por lo que puede tardar varios minutos. El universo se cachea en un CSV por día;
> las corridas siguientes del mismo día lo reutilizan (salvo `--refresh-universe`).

## Salida (`data/`, CSV)

| Archivo | Contenido |
|---------|-----------|
| `constituents/sp500_top100_<YYYYMMDD>.csv` | `rank, symbol, yahoo_symbol, name, sector, market_cap` |
| `prices/prices_daily.csv` | `date, ticker, open, high, low, close, adj_close, volume` (formato largo) |
| `fundamentals/valuation_snapshot.csv` | `snapshot_date, ticker, trailing_pe, forward_pe, price_to_book, ev_to_ebitda, roe, roic, market_cap, enterprise_value, ebitda, net_income_ttm, trailing_eps` |
| `fundamentals/net_income_annual.csv` | `ticker, period_end, net_income, currency` |
| `fundamentals/net_income_quarterly.csv` | `ticker, period_end, net_income, currency` |
| `manifest.json` | parámetros de la corrida, conteos y tickers con fallo |

Los **precios** y la **foto de ratios** viven en archivos **separados**. La foto de ratios se
**appendea** de forma idempotente por `(snapshot_date, ticker)`; la utilidad hace *upsert* por
`(ticker, period_end)`; los precios reescriben la ventana solicitada.

## Estructura del código

```
src/
  main.py          # CLI / orquestación
  config.py        # rutas y parámetros por defecto
  session.py       # pausas con jitter + reintentos con backoff (anti-429)
  constituents.py  # lista S&P 500 (Wikipedia) -> normaliza símbolos -> top-N por market cap
  prices.py        # yf.download por lotes + fallback Ticker.history -> formato largo
  fundamentals.py  # foto de ratios (.info), ROIC calculado, net income (estados financieros)
  storage.py       # escritura de CSVs + manifest
```

## Limitaciones y notas

- **Datos de Yahoo, "as-is".** Algunos ratios pueden venir vacíos para ciertos tickers
  (p. ej. EV/EBITDA en financieras), y el **ROIC** queda vacío si faltan los campos necesarios
  o es poco significativo (bancos/aseguradoras). Nunca rompe la corrida: el ticker se registra
  en `manifest.json`.
- **Rate limiting.** Con 100+ tickers Yahoo puede responder `429`; la herramienta usa lotes,
  pausas con jitter y reintentos con backoff. Aun así, conviene no abusar de corridas seguidas.
- La pertenencia al S&P 500 cambia con el tiempo; el universo se sella por fecha en su CSV.
