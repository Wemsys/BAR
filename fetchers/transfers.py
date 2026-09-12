"""
Fetchers de depósitos y retiros (movimientos de entrada/salida de la cuenta).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from binance_api import spot_signed_get

_MAX_WINDOW_DAYS = 90  # Binance limita estas consultas a 90 días por llamada


def _iter_windows(start_ms: int, end_ms: int, window_days: int = _MAX_WINDOW_DAYS):
    window_ms = window_days * 24 * 60 * 60 * 1000
    cur = start_ms
    while cur < end_ms:
        nxt = min(cur + window_ms, end_ms)
        yield cur, nxt
        cur = nxt + 1


def get_deposits(start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> List[Dict[str, Any]]:
    """Historial de depósitos (cripto). start/end en ms epoch UTC."""
    if start_ms is None:
        start_ms = int((datetime.now(timezone.utc) - timedelta(days=365 * 5)).timestamp() * 1000)
    if end_ms is None:
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    rows: List[Dict[str, Any]] = []
    for w_start, w_end in _iter_windows(start_ms, end_ms):
        try:
            data = spot_signed_get(
                "/sapi/v1/capital/deposit/hisrec",
                {"startTime": w_start, "endTime": w_end, "limit": 1000},
            )
        except Exception:
            data = []
        for d in data:
            rows.append(
                {
                    "type": "DEPOSIT",
                    "asset": d.get("coin"),
                    "amount": float(d.get("amount", 0)),
                    "network": d.get("network"),
                    "status": d.get("status"),
                    "address": d.get("address"),
                    "tx_id": d.get("txId"),
                    "timestamp": d.get("insertTime"),
                }
            )
        time.sleep(0.15)
    return rows


def get_withdrawals(start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> List[Dict[str, Any]]:
    """Historial de retiros (cripto). start/end en ms epoch UTC."""
    if start_ms is None:
        start_ms = int((datetime.now(timezone.utc) - timedelta(days=365 * 5)).timestamp() * 1000)
    if end_ms is None:
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    rows: List[Dict[str, Any]] = []
    for w_start, w_end in _iter_windows(start_ms, end_ms):
        try:
            data = spot_signed_get(
                "/sapi/v1/capital/withdraw/history",
                {"startTime": w_start, "endTime": w_end, "limit": 1000},
            )
        except Exception:
            data = []
        for w in data:
            apply_time = w.get("applyTime")
            ts = None
            if apply_time:
                try:
                    ts = int(datetime.strptime(apply_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
                except ValueError:
                    ts = None
            rows.append(
                {
                    "type": "WITHDRAWAL",
                    "asset": w.get("coin"),
                    "amount": float(w.get("amount", 0)),
                    "network": w.get("network"),
                    "status": w.get("status"),
                    "address": w.get("address"),
                    "tx_id": w.get("txId"),
                    "timestamp": ts,
                    "fee": float(w.get("transactionFee", 0)),
                }
            )
        time.sleep(0.15)
    return rows


def get_fiat_deposits_withdrawals(start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> List[Dict[str, Any]]:
    """Historial de operaciones fiat (compra/venta con tarjeta, transferencia
    bancaria, etc.) vía /sapi/v1/fiat/orders. Devuelve [] si no aplica a tu cuenta."""
    if start_ms is None:
        start_ms = int((datetime.now(timezone.utc) - timedelta(days=365 * 5)).timestamp() * 1000)
    if end_ms is None:
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    rows: List[Dict[str, Any]] = []
    for tx_type in ("0", "1"):  # 0 = deposit, 1 = withdraw
        for w_start, w_end in _iter_windows(start_ms, end_ms):
            try:
                data = spot_signed_get(
                    "/sapi/v1/fiat/orders",
                    {"transactionType": tx_type, "beginTime": w_start, "endTime": w_end, "rows": 500},
                )
            except Exception:
                data = {}
            for f in data.get("data", []):
                rows.append(
                    {
                        "type": "FIAT_DEPOSIT" if tx_type == "0" else "FIAT_WITHDRAWAL",
                        "asset": f.get("fiatCurrency"),
                        "amount": float(f.get("amount", 0)),
                        "method": f.get("method"),
                        "status": f.get("status"),
                        "order_id": f.get("orderNo"),
                        "timestamp": f.get("createTime"),
                        "fee": float(f.get("totalFee", 0)),
                    }
                )
            time.sleep(0.15)
    return rows
