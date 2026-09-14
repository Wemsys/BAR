"""
Utilidades de exportación a CSV.

Todas las funciones aceptan una lista de dicts (tal como las devuelven los
fetchers) y devuelven un pandas.DataFrame; `save_csv` lo vuelca a disco.
Se añade una columna `datetime_utc` legible a partir de cualquier campo de
timestamp en milisegundos para facilitar el filtrado manual en Excel/Sheets.

Formato del CSV (separador de columnas y separador decimal): por defecto
pandas escribe "," como separador de columnas y "." como separador
decimal (formato "internacional"/US). Excel y Power BI configurados en
español (o cualquier configuración regional que use "," como separador
decimal) esperan justo lo contrario: ";" separa columnas y "," son los
decimales ("formato europeo"). Como no se pueden mezclar coma-decimal con
coma-separador en el mismo archivo, se ofrecen ambos formatos completos
en vez de parámetros sueltos — ver `CSV_FORMATS` y `to_csv_bytes`/`save_csv`.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Nombre de formato -> (separador de columnas, separador decimal).
CSV_FORMATS: Dict[str, Tuple[str, str]] = {
    "internacional": (",", "."),  # 1234.56 — formato por defecto de la mayoría de herramientas en inglés
    "europeo": (";", ","),  # 1234,56 — el que esperan Excel/Power BI en español y otras configuraciones europeas
}


def _csv_params(csv_format: str) -> Tuple[str, str]:
    try:
        return CSV_FORMATS[csv_format]
    except KeyError:
        raise ValueError(f"csv_format debe ser uno de {list(CSV_FORMATS)}, recibido: {csv_format!r}")


def _add_readable_datetime(df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
    if ts_col in df.columns and not df.empty:
        df = df.copy()
        df["datetime_utc"] = pd.to_datetime(df[ts_col], unit="ms", utc=True, errors="coerce")
    return df


def to_dataframe(rows: List[Dict[str, Any]], ts_col: str = "timestamp") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return _add_readable_datetime(df, ts_col)


def to_csv_bytes(df: pd.DataFrame, csv_format: str = "internacional") -> bytes:
    """Serializa un DataFrame a bytes CSV (UTF-8) en el formato indicado
    ("internacional": coma+punto, o "europeo": punto y coma+coma)."""
    sep, decimal = _csv_params(csv_format)
    return df.to_csv(index=False, sep=sep, decimal=decimal).encode("utf-8")


def save_csv(df: pd.DataFrame, path: str, csv_format: str = "internacional") -> str:
    sep, decimal = _csv_params(csv_format)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df.to_csv(path, index=False, sep=sep, decimal=decimal, encoding="utf-8")
    return path


def export_all(
    output_dir: str,
    balances: Optional[List[Dict[str, Any]]] = None,
    balance_history: Optional[List[Dict[str, Any]]] = None,
    trades: Optional[List[Dict[str, Any]]] = None,
    deposits: Optional[List[Dict[str, Any]]] = None,
    withdrawals: Optional[List[Dict[str, Any]]] = None,
    fiat: Optional[List[Dict[str, Any]]] = None,
    csv_format: str = "internacional",
) -> Dict[str, str]:
    """Exporta cada dataset no vacío a su propio CSV dentro de `output_dir`.
    Devuelve un dict {nombre_dataset: ruta_csv}."""
    written: Dict[str, str] = {}

    def _maybe_write(name: str, rows: Optional[List[Dict[str, Any]]], ts_col: str = "timestamp"):
        if rows:
            df = to_dataframe(rows, ts_col)
            path = os.path.join(output_dir, f"{name}.csv")
            written[name] = save_csv(df, path, csv_format=csv_format)

    _maybe_write("balances_actuales", balances, ts_col=None)
    if balance_history:
        df = pd.DataFrame(balance_history)
        written["balances_historicos"] = save_csv(
            df, os.path.join(output_dir, "balances_historicos.csv"), csv_format=csv_format
        )
    _maybe_write("operaciones", trades, ts_col="timestamp")
    _maybe_write("depositos", deposits, ts_col="timestamp")
    _maybe_write("retiros", withdrawals, ts_col="timestamp")
    _maybe_write("fiat", fiat, ts_col="timestamp")

    return written
