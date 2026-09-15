"""
Pruebas manuales SIN red ni credenciales reales: validan la lógica de
firma HMAC y la exportación a CSV con datos simulados. No se conecta a
Binance (el sandbox de build no tiene salida a api.binance.com).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["BINANCE_API_KEY"] = "test_key_1234567890"
os.environ["BINANCE_API_SECRET"] = "test_secret_abcdefgh"

import pandas as pd  # noqa: E402

from binance_api import _sign  # noqa: E402
from export import export_all, to_csv_bytes, to_dataframe  # noqa: E402
import stats  # noqa: E402
from symbols import discover_symbols  # noqa: E402


def test_sign_produces_valid_signature():
    params = {"symbol": "BTCUSDT", "limit": 1000}
    signed = _sign(params)
    assert "signature" in signed
    assert len(signed["signature"]) == 64  # hex sha256
    assert "timestamp" in signed
    assert signed["recvWindow"] == 10000
    print("OK: _sign genera timestamp + firma HMAC-SHA256 de 64 hex chars")


def test_export_to_csv(tmp_path="/tmp/binance_export_test"):
    balances = [
        {"wallet": "SPOT", "asset": "BTC", "free": 0.5, "locked": 0.0, "total": 0.5},
        {"wallet": "SPOT", "asset": "USDT", "free": 1200.0, "locked": 0.0, "total": 1200.0},
    ]
    trades = [
        {
            "wallet": "SPOT",
            "symbol": "BTCUSDT",
            "trade_id": 1,
            "order_id": 100,
            "timestamp": 1700000000000,
            "side": "BUY",
            "price": 35000.0,
            "qty": 0.01,
            "quote_qty": 350.0,
            "commission": 0.00001,
            "commission_asset": "BTC",
            "is_maker": True,
            "realized_pnl": None,
        }
    ]
    written = export_all(tmp_path, balances=balances, trades=trades)
    assert "balances_actuales" in written
    assert "operaciones" in written
    assert os.path.exists(written["balances_actuales"])
    assert os.path.exists(written["operaciones"])

    df = to_dataframe(trades)
    assert "datetime_utc" in df.columns
    assert str(df["datetime_utc"].iloc[0]).startswith("2023-11-14")
    print("OK: export_all genera CSVs válidos y datetime_utc se calcula bien")


def test_symbol_pattern_matches_exchangeinfo_shape():
    # No llamamos a la red real; validamos que la función arma bien los
    # candidatos usando un set simulado en vez de get_all_spot_symbols().
    import symbols as symbols_mod

    symbols_mod.get_all_spot_symbols = lambda: {"BTCUSDT", "ETHUSDT", "ETHBTC"}
    result = discover_symbols(["BTC", "ETH"], market="SPOT")
    assert "BTCUSDT" in result
    assert "ETHUSDT" in result
    assert "ETHBTC" in result
    print("OK: discover_symbols arma correctamente los pares válidos")


def test_fifo_realized_pnl_basic_two_lots():
    # 2 compras a distinto precio + 1 venta que consume la primera compra
    # entera y la mitad de la segunda. Sin comisiones, para verificar el
    # emparejamiento FIFO puro.
    trades = to_dataframe(
        [
            {"symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "price": 10000.0, "commission": 0.0, "commission_asset": "USDT", "timestamp": 1000},
            {"symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "price": 20000.0, "commission": 0.0, "commission_asset": "USDT", "timestamp": 2000},
            {"symbol": "BTCUSDT", "side": "SELL", "qty": 1.5, "price": 30000.0, "commission": 0.0, "commission_asset": "USDT", "timestamp": 3000},
        ],
        ts_col="timestamp",
    )
    symbol_info = {"BTCUSDT": ("BTC", "USDT")}
    fifo = stats.fifo_realized_pnl(trades, symbol_info)
    assert len(fifo) == 2  # la venta consume 2 lotes -> 2 filas
    assert abs(fifo["pnl"].sum() - 25000.0) < 1e-6  # 1*(30000-10000) + 0.5*(30000-20000)
    assert fifo["pnl"].isna().sum() == 0

    summary = stats.fifo_pnl_summary(fifo, only_in_range=False)
    assert summary.iloc[0]["quote_asset"] == "USDT"
    assert abs(summary.iloc[0]["pnl_realizado"] - 25000.0) < 1e-6
    assert summary.iloc[0]["ventas_sin_costo_base"] == 0


def test_fifo_realized_pnl_with_commissions():
    # Comisión de compra en el activo base (BTC) y comisión de venta en
    # el activo de cotización (USDT) - el caso normal en Binance sin BNB.
    trades = to_dataframe(
        [
            {"symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "price": 10000.0, "commission": 0.001, "commission_asset": "BTC", "timestamp": 1000},
            {"symbol": "BTCUSDT", "side": "SELL", "qty": 0.999, "price": 20000.0, "commission": 20.0, "commission_asset": "USDT", "timestamp": 2000},
        ],
        ts_col="timestamp",
    )
    symbol_info = {"BTCUSDT": ("BTC", "USDT")}
    fifo = stats.fifo_realized_pnl(trades, symbol_info)
    # Coste total pagado = 10000 USDT; ingreso neto = 0.999*20000 - 20 = 19960 USDT
    # PnL esperado = 19960 - 10000 = 9960 USDT
    assert abs(fifo["pnl"].sum() - 9960.0) < 1e-6


def test_fifo_realized_pnl_sale_without_lot():
    # Venta sin ninguna compra previa del mismo símbolo -> pnl None y se
    # cuenta como "venta sin costo base".
    trades = to_dataframe(
        [{"symbol": "ETHUSDT", "side": "SELL", "qty": 2.0, "price": 2000.0, "commission": 0.0, "commission_asset": "USDT", "timestamp": 1000}],
        ts_col="timestamp",
    )
    symbol_info = {"ETHUSDT": ("ETH", "USDT")}
    fifo = stats.fifo_realized_pnl(trades, symbol_info)
    assert len(fifo) == 1
    assert pd.isna(fifo.iloc[0]["pnl"])
    summary = stats.fifo_pnl_summary(fifo, only_in_range=False)
    assert summary.iloc[0]["ventas_sin_costo_base"] == 1

    # Casos vacíos no deben explotar
    assert stats.fifo_realized_pnl(pd.DataFrame(), {}).empty
    assert stats.fifo_realized_pnl(trades, None).empty
    assert stats.fifo_pnl_summary(pd.DataFrame()).empty
    assert stats.fifo_pnl_by_symbol(pd.DataFrame()).empty
    print("OK: fifo_realized_pnl empareja lotes FIFO, aplica comisiones y marca ventas sin coste base")


def test_fifo_in_range_flag():
    # La venta más antigua queda FUERA del rango elegido; el coste de su
    # compra debe seguir usándose para las ventas posteriores, pero el
    # resumen "en rango" no debe contarla.
    trades = to_dataframe(
        [
            {"symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "price": 10000.0, "commission": 0.0, "commission_asset": "USDT", "timestamp": 1000},
            {"symbol": "BTCUSDT", "side": "SELL", "qty": 0.4, "price": 15000.0, "commission": 0.0, "commission_asset": "USDT", "timestamp": 2000},  # fuera de rango
            {"symbol": "BTCUSDT", "side": "SELL", "qty": 0.6, "price": 20000.0, "commission": 0.0, "commission_asset": "USDT", "timestamp": 5000},  # dentro de rango
        ],
        ts_col="timestamp",
    )
    symbol_info = {"BTCUSDT": ("BTC", "USDT")}
    fifo = stats.fifo_realized_pnl(trades, symbol_info, start_ms=4000, end_ms=6000)
    assert len(fifo) == 2
    in_range_rows = fifo[fifo["in_range"]]
    assert len(in_range_rows) == 1
    assert abs(in_range_rows.iloc[0]["pnl"] - 0.6 * (20000 - 10000)) < 1e-6

    summary_in_range = stats.fifo_pnl_summary(fifo, only_in_range=True)
    assert abs(summary_in_range.iloc[0]["pnl_realizado"] - 6000.0) < 1e-6
    summary_all_time = stats.fifo_pnl_summary(fifo, only_in_range=False)
    assert abs(summary_all_time.iloc[0]["pnl_realizado"] - (2000 + 6000)) < 1e-6
    print("OK: el flag in_range separa el P&L del rango elegido del histórico completo usado para el coste")


def test_futures_realized_pnl_summary():
    df_trades = to_dataframe(
        [
            {"symbol": "BTCUSDT", "realized_pnl": 100.5, "timestamp": 1000},
            {"symbol": "BTCUSDT", "realized_pnl": -40.0, "timestamp": 2000},
            {"symbol": "ETHUSDT", "realized_pnl": 15.0, "timestamp": 3000},
        ],
        ts_col="timestamp",
    )
    out = stats.futures_realized_pnl_summary(df_trades)
    btc_row = out[out["symbol"] == "BTCUSDT"].iloc[0]
    assert abs(btc_row["pnl_realizado"] - 60.5) < 1e-6
    eth_row = out[out["symbol"] == "ETHUSDT"].iloc[0]
    assert abs(eth_row["pnl_realizado"] - 15.0) < 1e-6
    assert stats.futures_realized_pnl_summary(pd.DataFrame()).empty
    print("OK: futures_realized_pnl_summary suma el realized_pnl que ya da Binance, agrupado por símbolo")


def test_stats_functions():
    df_bal = to_dataframe(
        [
            {"wallet": "SPOT", "asset": "BTC", "free": 0.5, "locked": 0.0, "total": 0.5},
            {"wallet": "MARGIN", "asset": "BTC", "free": 0.1, "locked": 0.0, "total": 0.1},
            {"wallet": "SPOT", "asset": "USDT", "free": 1200.0, "locked": 0.0, "total": 1200.0},
        ],
        ts_col=None,
    )
    bal_stats = stats.balances_by_asset(df_bal)
    assert list(bal_stats["asset"]) == ["USDT", "BTC"]  # orden desc por total
    assert abs(bal_stats.loc[bal_stats["asset"] == "BTC", "total"].iloc[0] - 0.6) < 1e-9

    df_dep = to_dataframe(
        [
            {"type": "DEPOSIT", "asset": "BTC", "amount": 1.0, "timestamp": 1700000000000},
            {"type": "DEPOSIT", "asset": "ETH", "amount": 2.0, "timestamp": 1702600000000},
        ],
        ts_col="timestamp",
    )
    df_wd = to_dataframe(
        [{"type": "WITHDRAWAL", "asset": "BTC", "amount": 0.4, "timestamp": 1701000000000}],
        ts_col="timestamp",
    )
    dep_wd = stats.deposits_vs_withdrawals_by_asset(df_dep, df_wd)
    btc_row = dep_wd[dep_wd["asset"] == "BTC"].iloc[0]
    assert abs(btc_row["depositado"] - 1.0) < 1e-9
    assert abs(btc_row["retirado"] - 0.4) < 1e-9
    assert abs(btc_row["neto"] - 0.6) < 1e-9
    eth_row = dep_wd[dep_wd["asset"] == "ETH"].iloc[0]
    assert eth_row["retirado"] == 0.0

    long_df = stats.to_long_dep_wd(dep_wd)
    assert set(long_df["tipo"].unique()) == {"Depósito", "Retiro"}

    monthly = stats.monthly_transaction_counts(df_dep, df_wd)
    assert not monthly.empty
    assert set(monthly["tipo"].unique()) <= {"Depósito", "Retiro"}

    df_trades = to_dataframe(
        [
            {"wallet": "SPOT", "symbol": "BTCUSDT", "trade_id": 1, "side": "BUY", "quote_qty": 350.0, "commission": 0.1, "commission_asset": "USDT", "timestamp": 1700000000000},
            {"wallet": "SPOT", "symbol": "BTCUSDT", "trade_id": 2, "side": "SELL", "quote_qty": 400.0, "commission": 0.2, "commission_asset": "USDT", "timestamp": 1700100000000},
            {"wallet": "SPOT", "symbol": "ETHUSDT", "trade_id": 3, "side": "BUY", "quote_qty": 100.0, "commission": 0.05, "commission_asset": "USDT", "timestamp": 1700200000000},
        ],
        ts_col="timestamp",
    )
    side_counts = stats.trade_side_counts(df_trades)
    assert dict(zip(side_counts["side"], side_counts["count"])) == {"BUY": 2, "SELL": 1}

    by_symbol = stats.trades_by_symbol(df_trades)
    assert by_symbol.iloc[0]["symbol"] == "BTCUSDT"
    assert by_symbol.iloc[0]["trades"] == 2

    fees = stats.fees_by_asset(df_trades)
    assert abs(fees.loc[fees["commission_asset"] == "USDT", "total_commission"].iloc[0] - 0.35) < 1e-9

    # Casos vacíos no deben explotar
    empty = pd.DataFrame()
    assert stats.balances_by_asset(empty).empty
    assert stats.deposits_vs_withdrawals_by_asset(empty, empty).empty
    assert stats.monthly_transaction_counts(empty, empty).empty
    assert stats.trade_side_counts(empty).empty
    assert stats.trades_by_symbol(empty).empty
    assert stats.fees_by_asset(empty).empty

    print("OK: funciones de stats.py calculan agregados correctamente y toleran datasets vacíos")


def test_csv_format_decimal_and_separator():
    df = pd.DataFrame([{"asset": "BTC", "total": 1234.56}])

    intl = to_csv_bytes(df, csv_format="internacional").decode("utf-8")
    assert "1234.56" in intl
    assert ";" not in intl.splitlines()[0]  # cabecera separada por comas

    eur = to_csv_bytes(df, csv_format="europeo").decode("utf-8")
    assert "1234,56" in eur
    assert ";" in eur.splitlines()[0]  # cabecera separada por punto y coma

    try:
        to_csv_bytes(df, csv_format="invalido")
        raise AssertionError("Se esperaba ValueError para un csv_format desconocido")
    except ValueError:
        pass

    print("OK: to_csv_bytes produce formato internacional (1234.56) y europeo (1234,56;) correctamente")


if __name__ == "__main__":
    test_sign_produces_valid_signature()
    test_export_to_csv()
    test_symbol_pattern_matches_exchangeinfo_shape()
    test_fifo_realized_pnl_basic_two_lots()
    test_fifo_realized_pnl_with_commissions()
    test_fifo_realized_pnl_sale_without_lot()
    test_fifo_in_range_flag()
    test_futures_realized_pnl_summary()
    test_stats_functions()
    test_csv_format_decimal_and_separator()
    print("\nTodas las pruebas offline pasaron correctamente.")
