"""
Utilidades de exportación a CSV.

Todas las funciones aceptan una lista de dicts (tal como las devuelven los
fetchers) y devuelven un pandas.DataFrame; `save_csv` lo vuelca a disco.
Se añade una columna `datetime_utc` legible a partir de cualquier campo de
timestamp en milisegundos para facilitar el filtrado manual en Excel/Sheets.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd


def _add_readable_datetime(df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
    if ts_col in df.columns and not df.empty:
        df = df.copy()
        df["datetime_utc"] = pd.to_datetime(df[ts_col], unit="ms", utc=True, errors="coerce")
    return df


def to_dataframe(rows: List[Dict[str, Any]], ts_col: str = "timestamp") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return _add_readable_datetime(df, ts_col)


def save_csv(df: pd.DataFrame, path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df.to_csv(path, index=False)
    return path


def export_all(
    output_dir: str,
    balances: Optional[List[Dict[str, Any]]] = None,
    balance_history: Optional[List[Dict[str, Any]]] = None,
    trades: Optional[List[Dict[str, Any]]] = None,
    deposits: Optional[List[Dict[str, Any]]] = None,
    withdrawals: Optional[List[Dict[str, Any]]] = None,
    fiat: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Exporta cada dataset no vacío a su propio CSV dentro de `output_dir`.
    Devuelve un dict {nombre_dataset: ruta_csv}."""
    written: Dict[str, str] = {}

    def _maybe_write(name: str, rows: Optional[List[Dict[str, Any]]], ts_col: str = "timestamp"):
        if rows:
            df = to_dataframe(rows, ts_col)
            path = os.path.join(output_dir, f"{name}.csv")
            written[name] = save_csv(df, path)

    _maybe_write("balances_actuales", balances, ts_col=None)
    if balance_history:
        df = pd.DataFrame(balance_history)
        written["balances_historicos"] = save_csv(df, os.path.join(output_dir, "balances_historicos.csv"))
    _maybe_write("operaciones", trades, ts_col="timestamp")
    _maybe_write("depositos", deposits, ts_col="timestamp")
    _maybe_write("retiros", withdrawals, ts_col="timestamp")
    _maybe_write("fiat", fiat, ts_col="timestamp")

    return written
