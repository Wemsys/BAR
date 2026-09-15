"""
Cálculos de estadísticas para el dashboard (pestaña "Estadísticas").

Son funciones puras sobre DataFrames ya obtenidos/filtrados por
app.py: no hacen llamadas a la API, así que se pueden probar sin red ni
credenciales (ver tests_manual/test_offline.py).
"""
from __future__ import annotations

from collections import deque
from typing import Dict, Optional, Tuple

import pandas as pd

_LOT_EPSILON = 1e-12


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


# ---------------------------------------------------------------------------
# Pérdidas y ganancias realizadas (P&L)
# ---------------------------------------------------------------------------
#
# Spot/Margin: Binance no da un "P&L" por operación, así que se calcula con
# FIFO (First In, First Out) — el método de coste más habitual y el que
# exige Hacienda en España para valores/criptomonedas cuando no hay otro
# criterio: cada venta se empareja con las compras más antiguas todavía
# no consumidas de ESE MISMO símbolo (ej. BTCUSDT), y la ganancia/pérdida
# es (precio de venta − precio de coste) × cantidad emparejada.
#
# Futuros USDT-M: Binance ya calcula el PnL realizado de cada trade
# (columna `realized_pnl`, que viene de /fapi/v1/userTrades), así que ahí
# NO se usa FIFO — se sencillamente se suma esa columna.
#
# Limitaciones importantes (se muestran también en el dashboard):
#   1. El FIFO se calcula POR SÍMBOLO. Si compras BTC contra EUR y luego
#      vendes BTC contra USDT, son símbolos distintos (BTCEUR/BTCUSDT) y
#      el sistema no puede cruzar el coste entre ellos — esa venta
#      aparecerá como "sin lote de compra conocido". Para que el cálculo
#      sea fiable, opera cada activo siempre contra la misma moneda de
#      cotización, o interpreta los resultados por separado por símbolo.
#   2. Las comisiones solo se descuentan del P&L cuando se cobran en el
#      propio activo base (compras) o en el propio activo de cotización
#      (ventas) — el caso normal en Binance sin BNB para pagar comisiones.
#      Si pagas comisiones en un tercer activo (ej. BNB), esa comisión NO
#      se resta aquí; se sigue mostrando aparte en "Comisiones totales".
#   3. No incluye intereses de margin (préstamos) ni funding de futuros.
#   4. Para que el coste FIFO sea correcto, se necesita el HISTÓRICO
#      COMPLETO de compras de cada símbolo, no solo las del rango de
#      fechas elegido — por eso, para Spot/Margin, el dashboard trae
#      SIEMPRE todo el historial de cada símbolo hasta la fecha "Hasta"
#      (ignora el "Desde" al pedir los datos a Binance), y solo usa
#      "Desde" para decidir qué ventas cuentan en el resumen de P&L del
#      rango seleccionado.


def fifo_realized_pnl(
    df_trades_all: Optional[pd.DataFrame],
    symbol_info: Optional[Dict[str, Tuple[Optional[str], Optional[str]]]] = None,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> pd.DataFrame:
    """
    Calcula el P&L realizado con FIFO, símbolo por símbolo.

    `df_trades_all` debe traer el HISTÓRICO COMPLETO de trades de cada
    símbolo (no solo el rango de fechas visible), para que el coste de
    las compras más antiguas esté disponible al emparejar las ventas.

    `symbol_info` es {symbol: (base_asset, quote_asset)} (ver
    `symbols.get_symbol_info_map`); sin él no se puede separar base de
    quote y se devuelve vacío.

    Devuelve un DataFrame con una fila por "lote" de venta emparejado
    (una venta puede generar varias filas si consume varios lotes de
    compra distintos), con una columna `in_range` que indica si esa
    venta cae dentro de [start_ms, end_ms]. `pnl` es None cuando la venta
    no tuvo lote de compra disponible (ver limitación 1 arriba).
    """
    columns = [
        "symbol",
        "quote_asset",
        "timestamp",
        "datetime_utc",
        "qty",
        "cost_per_unit",
        "proceeds_per_unit",
        "pnl",
        "in_range",
    ]
    if df_trades_all is None or df_trades_all.empty or not symbol_info:
        return pd.DataFrame(columns=columns)

    required = {"symbol", "side", "qty", "price", "timestamp"}
    if not required.issubset(df_trades_all.columns):
        return pd.DataFrame(columns=columns)

    rows = []
    for symbol, group in df_trades_all.groupby("symbol"):
        base_asset, quote_asset = symbol_info.get(symbol, (None, None))
        group_sorted = group.sort_values("timestamp")
        lots: deque = deque()  # cada item: [cantidad_restante, coste_por_unidad]

        for _, t in group_sorted.iterrows():
            side = t.get("side")
            qty = float(t.get("qty") or 0)
            price = float(t.get("price") or 0)
            commission = float(t.get("commission") or 0) if pd.notna(t.get("commission")) else 0.0
            commission_asset = t.get("commission_asset")
            ts = t.get("timestamp")
            if qty <= 0:
                continue

            if side == "BUY":
                eff_qty = qty
                eff_cost = qty * price
                if commission_asset == base_asset:
                    eff_qty = max(qty - commission, 0.0)
                elif commission_asset == quote_asset:
                    eff_cost += commission
                if eff_qty <= _LOT_EPSILON:
                    continue
                lots.append([eff_qty, eff_cost / eff_qty])

            elif side == "SELL":
                remaining = qty
                gross_proceeds = qty * price
                net_proceeds = gross_proceeds - commission if commission_asset == quote_asset else gross_proceeds
                proceeds_per_unit = net_proceeds / qty if qty else 0.0

                while remaining > _LOT_EPSILON and lots:
                    lot = lots[0]
                    matched = min(lot[0], remaining)
                    pnl = matched * (proceeds_per_unit - lot[1])
                    rows.append(
                        {
                            "symbol": symbol,
                            "quote_asset": quote_asset,
                            "timestamp": ts,
                            "qty": matched,
                            "cost_per_unit": lot[1],
                            "proceeds_per_unit": proceeds_per_unit,
                            "pnl": pnl,
                        }
                    )
                    lot[0] -= matched
                    remaining -= matched
                    if lot[0] <= _LOT_EPSILON:
                        lots.popleft()

                if remaining > 1e-9:
                    # Venta sin lote de compra conocido dentro del histórico
                    # traído (activo recibido por transferencia/airdrop, o
                    # comprado contra otra moneda de cotización - ver
                    # limitación 1 en la cabecera del módulo).
                    rows.append(
                        {
                            "symbol": symbol,
                            "quote_asset": quote_asset,
                            "timestamp": ts,
                            "qty": remaining,
                            "cost_per_unit": None,
                            "proceeds_per_unit": proceeds_per_unit,
                            "pnl": None,
                        }
                    )

    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)
    df["datetime_utc"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True, errors="coerce")
    in_range = pd.Series(True, index=df.index)
    if start_ms is not None:
        in_range &= df["timestamp"] >= start_ms
    if end_ms is not None:
        in_range &= df["timestamp"] <= end_ms
    df["in_range"] = in_range
    return df[columns]


def fifo_pnl_summary(fifo_df: Optional[pd.DataFrame], only_in_range: bool = True) -> pd.DataFrame:
    """P&L realizado neto por moneda de cotización (nunca se suman P&L de
    monedas distintas entre sí), más cuántas ventas quedaron sin coste
    base conocido."""
    columns = ["quote_asset", "pnl_realizado", "ventas_sin_costo_base"]
    if fifo_df is None or fifo_df.empty:
        return pd.DataFrame(columns=columns)
    df = fifo_df[fifo_df["in_range"]] if only_in_range else fifo_df
    if df.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for quote_asset, group in df.groupby("quote_asset"):
        rows.append(
            {
                "quote_asset": quote_asset,
                "pnl_realizado": group["pnl"].sum(skipna=True),
                "ventas_sin_costo_base": int(group["pnl"].isna().sum()),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("quote_asset").reset_index(drop=True)


def fifo_pnl_by_symbol(fifo_df: Optional[pd.DataFrame], only_in_range: bool = True) -> pd.DataFrame:
    """P&L realizado por símbolo (dentro de cada símbolo la moneda de
    cotización es siempre la misma, así que sí se puede sumar)."""
    columns = ["symbol", "quote_asset", "pnl_realizado", "qty_vendida"]
    if fifo_df is None or fifo_df.empty:
        return pd.DataFrame(columns=columns)
    df = fifo_df[fifo_df["in_range"]] if only_in_range else fifo_df
    if df.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for (symbol, quote_asset), group in df.groupby(["symbol", "quote_asset"]):
        rows.append(
            {
                "symbol": symbol,
                "quote_asset": quote_asset,
                "pnl_realizado": group["pnl"].sum(skipna=True),
                "qty_vendida": group["qty"].sum(),
            }
        )
    out = pd.DataFrame(rows, columns=columns)
    return out.sort_values("pnl_realizado", ascending=False).reset_index(drop=True)


def futures_realized_pnl_summary(df_trades: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Para Futuros, Binance ya da el PnL realizado por trade
    (`realized_pnl`, típicamente en USDT) — no hace falta FIFO, solo
    sumar. Se agrupa por símbolo."""
    columns = ["symbol", "pnl_realizado"]
    if df_trades is None or df_trades.empty or "realized_pnl" not in df_trades.columns:
        return pd.DataFrame(columns=columns)
    df = df_trades.copy()
    df["realized_pnl"] = pd.to_numeric(df["realized_pnl"], errors="coerce")
    g = df.groupby("symbol")["realized_pnl"].sum(min_count=1).reset_index()
    g.columns = columns
    return g.sort_values("pnl_realizado", ascending=False).reset_index(drop=True)
