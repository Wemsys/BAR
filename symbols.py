"""
Descubrimiento automático de símbolos (pares de trading) para consultar
el historial de operaciones.

Binance NO ofrece un endpoint único de "todos mis trades en todos los
símbolos": /api/v3/myTrades (y equivalentes de margin/futuros) requieren
indicar el símbolo exacto (ej. BTCUSDT). Para no tener que iterar sobre
los ~2000 pares existentes (inviable por límites de peticiones), este
módulo construye una lista corta y razonable de candidatos:

1. Activos con saldo actual (spot/margin/futuros).
2. Activos que aparecen en el historial de depósitos/retiros.
3. Se combinan esos activos entre sí y contra una lista de "quotes"
   habituales (USDT, BTC, ETH, etc. - ver config.COMMON_QUOTE_ASSETS).
4. Se valida cada combinación contra /api/v3/exchangeInfo para quedarnos
   solo con símbolos que realmente existen en Binance.

Si operas con pares que no siguen este patrón, puedes añadir símbolos
manualmes con --symbols en el CLI o en el campo correspondiente del
dashboard.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable, List, Set

from binance_api import spot_public_get
from config import COMMON_QUOTE_ASSETS


@lru_cache(maxsize=1)
def get_all_spot_symbols() -> Set[str]:
    """Devuelve el conjunto de todos los símbolos spot existentes en Binance."""
    data = spot_public_get("/api/v3/exchangeInfo")
    return {s["symbol"] for s in data.get("symbols", [])}


@lru_cache(maxsize=1)
def get_all_futures_symbols() -> Set[str]:
    from binance_api import _request  # import local para evitar ciclos
    from config import FUTURES_BASE_URL

    data = _request("GET", FUTURES_BASE_URL, "/fapi/v1/exchangeInfo", signed=False)
    return {s["symbol"] for s in data.get("symbols", [])}


def discover_symbols(assets: Iterable[str], market: str = "SPOT") -> List[str]:
    """
    Construye símbolos candidatos combinando `assets` entre sí y contra
    COMMON_QUOTE_ASSETS, y devuelve solo los que existen de verdad.
    """
    assets = {a.upper() for a in assets if a}
    all_candidates_bases = assets | set(COMMON_QUOTE_ASSETS)

    valid = get_all_spot_symbols() if market == "SPOT" else get_all_futures_symbols()

    found: Set[str] = set()
    for base in assets:
        for quote in COMMON_QUOTE_ASSETS:
            if base == quote:
                continue
            for sym in (f"{base}{quote}", f"{quote}{base}"):
                if sym in valid:
                    found.add(sym)
        # además, cruza activos entre sí (por si operaste ALT/ALT)
        for other in all_candidates_bases:
            if other == base:
                continue
            for sym in (f"{base}{other}", f"{other}{base}"):
                if sym in valid:
                    found.add(sym)

    return sorted(found)
