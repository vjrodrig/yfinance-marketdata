"""Utilidades de robustez frente al rate limiting de Yahoo (HTTP 429).

yfinance 1.x usa por defecto una sesion ``curl_cffi`` que imita el TLS de un
navegador, lo que ya reduce los bloqueos. Aqui agregamos las dos piezas que
mas ayudan con 100+ tickers: pausas con jitter entre llamadas por-ticker y
reintentos con backoff exponencial.
"""
from __future__ import annotations

import logging
import random
import time

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

import config

log = logging.getLogger(__name__)


def polite_sleep() -> None:
    """Pausa breve con jitter entre llamadas por-ticker para no gatillar 429."""
    time.sleep(random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX))


# Decorador de reintentos con backoff exponencial + jitter. Reintenta ante
# cualquier excepcion de red/parseo de yfinance (incluida YFRateLimitError) y
# re-lanza la ultima si se agotan los intentos.
with_retries = retry(
    reraise=True,
    stop=stop_after_attempt(config.MAX_RETRIES),
    wait=wait_exponential_jitter(initial=config.RETRY_BACKOFF_BASE, max=30),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
