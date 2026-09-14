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

from binance_api import _sign  # noqa: E402
from export import export_all, to_dataframe  # noqa: E402
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

    symbols_mod.get_all_spot_symbols.cache_clear()
    symbols_mod.get_all_spot_symbols = lambda: {"BTCUSDT", "ETHUSDT", "ETHBTC"}
    result = discover_symbols(["BTC", "ETH"], market="SPOT")
    assert "BTCUSDT" in result
    assert "ETHUSDT" in result
    assert "ETHBTC" in result
    print("OK: discover_symbols arma correctamente los pares válidos")


if __name__ == "__main__":
    test_sign_produces_valid_signature()
    test_export_to_csv()
    test_symbol_pattern_matches_exchangeinfo_shape()
    print("\nTodas las pruebas offline pasaron correctamente.")
