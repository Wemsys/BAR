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
from typing import Dict, Iterable, List, Set, Tuple

from binance_api import spot_public_get
from config import COMMON_QUOTE_ASSETS


@lru_cache(maxsize=1)
def get_spot_exchange_info() -> List[dict]:
    """Lista cruda de símbolos spot desde /api/v3/exchangeInfo (incluye
    baseAsset/quoteAsset de cada uno, útil para separar base/quote sin
    tener que adivinarlo por texto)."""
    data = spot_public_get("/api/v3/exchangeInfo")
    return data.get("symbols", [])


@lru_cache(maxsize=1)
def get_futures_exchange_info() -> List[dict]:
    from binance_api import _request  # import local para evitar ciclos
    from config import FUTURES_BASE_URL

    data = _request("GET", FUTURES_BASE_URL, "/fapi/v1/exchangeInfo", signed=False)
    return data.get("symbols", [])


def get_all_spot_symbols() -> Set[str]:
    """Devuelve el conjunto de todos los símbolos spot existentes en Binance."""
    return {s["symbol"] for s in get_spot_exchange_info()}


def get_all_futures_symbols() -> Set[str]:
    return {s["symbol"] for s in get_futures_exchange_info()}


def get_symbol_info_map(market: str = "SPOT") -> Dict[str, Tuple[str, str]]:
    """Devuelve {symbol: (baseAsset, quoteAsset)} usando la información
    oficial de Binance (exchangeInfo) en vez de adivinar la separación
    base/quote por texto. "SPOT" y "MARGIN" comparten el exchangeInfo de
    spot (margin opera sobre los mismos pares); "FUTURES" usa el suyo."""
    info_list = get_spot_exchange_info() if market in ("SPOT", "MARGIN") else get_futures_exchange_info()
    return {s["symbol"]: (s.get("baseAsset"), s.get("quoteAsset")) for s in info_list}


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
