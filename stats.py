"""
Cálculos de estadísticas para el dashboard (pestaña "Estadísticas").

Son funciones puras sobre DataFrames ya obtenidos/filtrados por
app.py: no hacen llamadas a la API, así que se pueden probar sin red ni
credenciales (ver tests_manual/test_offline.py).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


def balances_by_asset(df_bal: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Saldo total por moneda (sumando Spot+Margin+Futuros), orden desc."""
    if df_bal is None or df_bal.empty or "asset" not in df_bal.columns:
        return pd.DataFrame(columns=["asset", "total"])
    out = df_bal.groupby("asset", as_index=False)["total"].sum()
    return out.sort_values("total", ascending=False).reset_index(drop=True)


def deposits_vs_withdrawals_by_asset(
    df_dep: Optional[pd.DataFrame], df_wd: Optional[pd.DataFrame]
) -> pd.DataFrame:
    """Tabla ancha: asset, depositado, retirado, neto (depositado - retirado)."""
    dep = (
        df_dep.groupby("asset")["amount"].sum()
        if df_dep is not None and not df_dep.empty and "asset" in df_dep.columns
        else pd.Series(dtype=float)
    )
    wd = (
        df_wd.groupby("asset")["amount"].sum()
        if df_wd is not None and not df_wd.empty and "asset" in df_wd.columns
        else pd.Series(dtype=float)
    )
    assets = sorted(set(dep.index) | set(wd.index))
    rows = []
    for a in assets:
        d = float(dep.get(a, 0.0))
        w = float(wd.get(a, 0.0))
        rows.append({"asset": a, "depositado": d, "retirado": w, "neto": d - w})
    return pd.DataFrame(rows, columns=["asset", "depositado", "retirado", "neto"])


def to_long_dep_wd(wide_df: pd.DataFrame) -> pd.DataFrame:
    """Convierte la tabla ancha de depósitos/retiros a formato largo
    (asset, tipo, amount), útil para un gráfico de barras agrupadas."""
    if wide_df is None or wide_df.empty:
        return pd.DataFrame(columns=["asset", "tipo", "amount"])
    long_rows = []
    for _, r in wide_df.iterrows():
        long_rows.append({"asset": r["asset"], "tipo": "Depósito", "amount": r["depositado"]})
        long_rows.append({"asset": r["asset"], "tipo": "Retiro", "amount": r["retirado"]})
    return pd.DataFrame(long_rows, columns=["asset", "tipo", "amount"])


def monthly_transaction_counts(
    df_dep: Optional[pd.DataFrame], df_wd: Optional[pd.DataFrame]
) -> pd.DataFrame:
    """Nº de depósitos y retiros por mes (conteo, no importe: así siempre
    es comparable aunque mezcles varias monedas distintas)."""
    frames = []
    for df, label in ((df_dep, "Depósito"), (df_wd, "Retiro")):
        if df is not None and not df.empty and "datetime_utc" in df.columns:
            tmp = df.copy()
            tmp["mes"] = tmp["datetime_utc"].dt.tz_localize(None).dt.to_period("M").astype(str)
            g = tmp.groupby("mes").size().reset_index(name="count")
            g["tipo"] = label
            frames.append(g)
    if not frames:
        return pd.DataFrame(columns=["mes", "count", "tipo"])
    return pd.concat(frames, ignore_index=True).sort_values("mes").reset_index(drop=True)


def trade_side_counts(df_trades: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Nº de operaciones de compra vs venta."""
    if df_trades is None or df_trades.empty or "side" not in df_trades.columns:
        return pd.DataFrame(columns=["side", "count"])
    return df_trades.groupby("side").size().reset_index(name="count")


def trades_by_symbol(df_trades: Optional[pd.DataFrame], top_n: int = 15) -> pd.DataFrame:
    """Nº de operaciones y volumen (quote_qty) por símbolo, top N por nº
    de operaciones."""
    if df_trades is None or df_trades.empty or "symbol" not in df_trades.columns:
        return pd.DataFrame(columns=["symbol", "trades", "quote_volume"])
    g = df_trades.groupby("symbol").agg(
        trades=("symbol", "count"),
        quote_volume=("quote_qty", "sum") if "quote_qty" in df_trades.columns else ("symbol", "count"),
    ).reset_index()
    return g.sort_values("trades", ascending=False).head(top_n).reset_index(drop=True)


def fees_by_asset(df_trades: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Comisiones totales pagadas, agrupadas por la moneda en que se cobraron."""
    if df_trades is None or df_trades.empty or "commission_asset" not in df_trades.columns:
        return pd.DataFrame(columns=["commission_asset", "total_commission"])
    g = df_trades.groupby("commission_asset")["commission"].sum().reset_index()
    g.columns = ["commission_asset", "total_commission"]
    return g.sort_values("total_commission", ascending=False).reset_index(drop=True)
