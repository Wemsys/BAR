"""
Fetchers de saldos (balances) de las distintas wallets de Binance.

Incluye también el "account snapshot" diario, que es la forma más simple
de obtener la EVOLUCIÓN histórica de saldos sin tener que reconstruirla
manualmente a partir del historial de operaciones.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from binance_api import futures_signed_get, spot_signed_get


def get_spot_balances() -> List[Dict[str, Any]]:
    """Saldos actuales de la wallet Spot (solo activos con saldo != 0)."""
    data = spot_signed_get("/api/v3/account")
    rows = []
    for b in data.get("balances", []):
        free = float(b["free"])
        locked = float(b["locked"])
        if free == 0 and locked == 0:
            continue
        rows.append(
            {
                "wallet": "SPOT",
                "asset": b["asset"],
                "free": free,
                "locked": locked,
                "total": free + locked,
            }
        )
    return rows


def get_margin_balances() -> List[Dict[str, Any]]:
    """Saldos actuales de la wallet Margin (cross margin). Devuelve [] si no
    tienes margin habilitado (Binance responde con error en ese caso, que
    se captura y se ignora)."""
    try:
        data = spot_signed_get("/sapi/v1/margin/account")
    except Exception:
        return []
    rows = []
    for b in data.get("userAssets", []):
        free = float(b["free"])
        locked = float(b["locked"])
        borrowed = float(b.get("borrowed", 0))
        net = float(b.get("netAsset", free + locked - borrowed))
        if free == 0 and locked == 0 and borrowed == 0:
            continue
        rows.append(
            {
                "wallet": "MARGIN",
                "asset": b["asset"],
                "free": free,
                "locked": locked,
                "borrowed": borrowed,
                "total": net,
            }
        )
    return rows


def get_futures_balances() -> List[Dict[str, Any]]:
    """Saldos actuales de Futuros USDT-M. Devuelve [] si no tienes la
    wallet de futuros habilitada."""
    try:
        data = futures_signed_get("/fapi/v2/balance")
    except Exception:
        return []
    rows = []
    for b in data:
        balance = float(b["balance"])
        if balance == 0:
            continue
        rows.append(
            {
                "wallet": "FUTURES_USDT_M",
                "asset": b["asset"],
                "free": float(b.get("availableBalance", balance)),
                "locked": balance - float(b.get("availableBalance", balance)),
                "total": balance,
            }
        )
    return rows


def get_all_current_balances() -> List[Dict[str, Any]]:
    """Combina saldos actuales de Spot + Margin + Futuros en una sola tabla."""
    rows: List[Dict[str, Any]] = []
    rows.extend(get_spot_balances())
    rows.extend(get_margin_balances())
    rows.extend(get_futures_balances())
    return rows


def get_account_snapshot(
    account_type: str,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """
    Histórico diario de saldos vía /sapi/v1/accountSnapshot.

    account_type: "SPOT", "MARGIN" o "FUTURES".
    Binance solo conserva ~30-90 días de snapshots y como máximo `limit`
    (máx. 30 por llamada) registros por request, por lo que para rangos
    largos se pagina automáticamente hacia atrás usando startTime/endTime.
    """
    params: Dict[str, Any] = {"type": account_type, "limit": min(limit, 30)}
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms

    try:
        data = spot_signed_get("/sapi/v1/accountSnapshot", params)
    except Exception:
        return []

    if data.get("code") not in (0, None):
        return []

    rows: List[Dict[str, Any]] = []
    for snap in data.get("snapshotVos", []):
        update_time = snap.get("updateTime")
        date_str = datetime.utcfromtimestamp(update_time / 1000).strftime("%Y-%m-%d") if update_time else ""
        payload = snap.get("data", {})

        if account_type == "SPOT":
            for b in payload.get("balances", []):
                free = float(b["free"])
                locked = float(b["locked"])
                if free == 0 and locked == 0:
                    continue
                rows.append(
                    {
                        "date": date_str,
                        "wallet": "SPOT",
                        "asset": b["asset"],
                        "free": free,
                        "locked": locked,
                        "total": free + locked,
                        "total_btc_value": payload.get("totalAssetOfBtc"),
                    }
                )
        elif account_type == "MARGIN":
            for b in payload.get("userAssets", []):
                free = float(b["free"])
                locked = float(b["locked"])
                if free == 0 and locked == 0:
                    continue
                rows.append(
                    {
                        "date": date_str,
                        "wallet": "MARGIN",
                        "asset": b["asset"],
                        "free": free,
                        "locked": locked,
                        "total": free + locked,
                        "total_btc_value": payload.get("totalAssetOfBtc"),
                    }
                )
        elif account_type == "FUTURES":
            for a in payload.get("assets", []):
                wallet_balance = float(a.get("walletBalance", 0))
                if wallet_balance == 0:
                    continue
                rows.append(
                    {
                        "date": date_str,
                        "wallet": "FUTURES_USDT_M",
                        "asset": a["asset"],
                        "free": wallet_balance,
                        "locked": 0.0,
                        "total": wallet_balance,
                        "total_btc_value": None,
                    }
                )
    return rows
