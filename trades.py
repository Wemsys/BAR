"""
Fetchers de historial de operaciones (trades) para Spot, Margin y Futuros.

Nota importante sobre fechas: los endpoints `myTrades` / `userTrades` de
Binance limitan la ventana startTime-endTime que se puede enviar en una
sola llamada (24h para spot, 7 días para futuros). Para poder pedir
CUALQUIER rango de fechas sin toparnos con ese límite, paginamos por
`fromId` (trade por trade, en bloques de hasta 1000) sobre el histórico
completo del símbolo y filtramos por fecha en el cliente. Es más robusto,
a costa de más llamadas si el símbolo tiene muchísimos trades.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from binance_api import futures_signed_get, spot_signed_get

_PAGE_LIMIT = 1000


def _paginate_by_id(
    fetch_page: Callable[[Optional[int]], List[Dict[str, Any]]],
    id_field: str,
    time_field: str,
    start_ms: Optional[int],
    end_ms: Optional[int],
    max_pages: int = 200,
) -> List[Dict[str, Any]]:
    """
    Recorre un endpoint paginable por id ascendente, deteniéndose cuando:
      - ya no hay más resultados, o
      - se supera `end_ms` (si se indicó), o
      - se alcanza `max_pages` (salvaguarda anti bucle infinito).
    Devuelve solo los registros dentro de [start_ms, end_ms].
    """
    results: List[Dict[str, Any]] = []
    from_id: Optional[int] = None
    pages = 0

    while True:
        pages += 1
        if pages > max_pages:
            break
        batch = fetch_page(from_id)
        if not batch:
            break

        for item in batch:
            ts = item.get(time_field)
            if start_ms is not None and ts is not None and ts < start_ms:
                continue
            if end_ms is not None and ts is not None and ts > end_ms:
                # Como el orden es ascendente por id/tiempo, si ya pasamos
                # el final del rango podemos cortar todo lo que sigue.
                return results
            results.append(item)

        if len(batch) < _PAGE_LIMIT:
            break

        last_id = batch[-1].get(id_field)
        if last_id is None:
            break
        from_id = last_id + 1
        time.sleep(0.15)  # margen de cortesía para no golpear el rate limit

    return results


def get_spot_trades(symbol: str, start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> List[Dict[str, Any]]:
    def fetch_page(from_id: Optional[int]) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"symbol": symbol, "limit": _PAGE_LIMIT}
        if from_id is not None:
            params["fromId"] = from_id
        try:
            return spot_signed_get("/api/v3/myTrades", params)
        except Exception:
            return []

    raw = _paginate_by_id(fetch_page, "id", "time", start_ms, end_ms)
    return [_normalize_trade(t, symbol, "SPOT") for t in raw]


def get_margin_trades(symbol: str, start_ms: Optional[int] = None, end_ms: Optional[int] = None, is_isolated: bool = False) -> List[Dict[str, Any]]:
    def fetch_page(from_id: Optional[int]) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"symbol": symbol, "limit": _PAGE_LIMIT}
        if is_isolated:
            params["isIsolated"] = "TRUE"
        if from_id is not None:
            params["fromId"] = from_id
        try:
            return spot_signed_get("/sapi/v1/margin/myTrades", params)
        except Exception:
            return []

    raw = _paginate_by_id(fetch_page, "id", "time", start_ms, end_ms)
    return [_normalize_trade(t, symbol, "MARGIN") for t in raw]


def get_futures_trades(symbol: str, start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> List[Dict[str, Any]]:
    def fetch_page(from_id: Optional[int]) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"symbol": symbol, "limit": _PAGE_LIMIT}
        if from_id is not None:
            params["fromId"] = from_id
        try:
            return futures_signed_get("/fapi/v1/userTrades", params)
        except Exception:
            return []

    raw = _paginate_by_id(fetch_page, "id", "time", start_ms, end_ms)
    return [_normalize_trade(t, symbol, "FUTURES_USDT_M") for t in raw]


def _normalize_trade(t: Dict[str, Any], symbol: str, wallet: str) -> Dict[str, Any]:
    qty = float(t.get("qty", t.get("quantity", 0)))
    price = float(t.get("price", 0))
    quote_qty = float(t.get("quoteQty", qty * price))
    return {
        "wallet": wallet,
        "symbol": symbol,
        "trade_id": t.get("id"),
        "order_id": t.get("orderId"),
        "timestamp": t.get("time"),
        "side": "BUY" if t.get("isBuyer") else "SELL" if "isBuyer" in t else t.get("side"),
        "price": price,
        "qty": qty,
        "quote_qty": quote_qty,
        "commission": float(t.get("commission", 0)),
        "commission_asset": t.get("commissionAsset"),
        "is_maker": t.get("isMaker"),
        "realized_pnl": t.get("realizedPnl"),
    }


def get_trades_for_symbols(
    symbols: List[str],
    market: str,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """Itera `symbols` llamando al fetcher correspondiente según `market`
    ("SPOT", "MARGIN" o "FUTURES") y concatena los resultados."""
    fetch_fn = {
        "SPOT": get_spot_trades,
        "MARGIN": get_margin_trades,
        "FUTURES": get_futures_trades,
    }[market]

    all_trades: List[Dict[str, Any]] = []
    for i, symbol in enumerate(symbols, start=1):
        trades = fetch_fn(symbol, start_ms, end_ms)
        all_trades.extend(trades)
        if progress_cb:
            progress_cb(symbol, i, len(symbols))
        time.sleep(0.1)
    return all_trades
