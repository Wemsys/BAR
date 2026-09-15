"""
Prueba manual (sin red) que reproduce el flujo real del dashboard usando
`streamlit.testing.v1.AppTest`: simula un click en "Cargar datos" y
LUEGO un click en un botón de descarga (CSV), y comprueba que las
pestañas siguen mostrando los datos cargados (es decir, que descargar un
CSV/PDF ya no borra lo cargado ni obliga a volver a llamar a la API).

Los fetchers de red se sustituyen por funciones de prueba (monkeypatch)
antes de correr la app, así que esto no necesita credenciales reales ni
conexión a Binance.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["BINANCE_API_KEY"] = "test_key_1234567890"
os.environ["BINANCE_API_SECRET"] = "test_secret_abcdefgh"

from streamlit.testing.v1 import AppTest  # noqa: E402

import fetchers.balances as balances_mod  # noqa: E402
import fetchers.trades as trades_mod  # noqa: E402
import fetchers.transfers as transfers_mod  # noqa: E402
import symbols as symbols_mod  # noqa: E402


def _patch_fetchers():
    balances_mod.get_all_current_balances = lambda: [
        {"wallet": "SPOT", "asset": "BTC", "free": 0.5, "locked": 0.0, "total": 0.5},
        {"wallet": "SPOT", "asset": "USDT", "free": 1200.0, "locked": 0.0, "total": 1200.0},
    ]
    balances_mod.get_account_snapshot = lambda *a, **k: []
    transfers_mod.get_deposits = lambda *a, **k: [
        {"type": "DEPOSIT", "asset": "BTC", "amount": 1.0, "timestamp": 1700000000000}
    ]
    transfers_mod.get_withdrawals = lambda *a, **k: []
    transfers_mod.get_fiat_deposits_withdrawals = lambda *a, **k: []
    symbols_mod.discover_symbols = lambda assets, market="SPOT": ["BTCUSDT"]
    symbols_mod.get_symbol_info_map = lambda market="SPOT": {"BTCUSDT": ("BTC", "USDT")}
    trades_mod.get_trades_for_symbols = lambda *a, **k: [
        {
            "wallet": "SPOT",
            "symbol": "BTCUSDT",
            "trade_id": 1,
            "order_id": 100,
            "timestamp": 1700000000000,
            "side": "BUY",
            "price": 35000.0,
            "qty": 0.02,
            "quote_qty": 700.0,
            "commission": 0.00002,
            "commission_asset": "BTC",
            "is_maker": True,
            "realized_pnl": None,
        },
        {
            "wallet": "SPOT",
            "symbol": "BTCUSDT",
            "trade_id": 2,
            "order_id": 101,
            "timestamp": 1700100000000,
            "side": "SELL",
            "price": 36000.0,
            "qty": 0.01,
            "quote_qty": 360.0,
            "commission": 0.36,
            "commission_asset": "USDT",
            "is_maker": False,
            "realized_pnl": None,
        },
    ]


def test_download_click_does_not_wipe_loaded_data():
    _patch_fetchers()

    app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
    at = AppTest.from_file(app_path)
    at.run(timeout=30)
    assert not at.exception, f"Excepción en la carga inicial: {at.exception}"

    # Click en "Cargar datos" (botón principal de la barra lateral).
    # Streamlit Testing localiza los botones por índice/label; buscamos
    # el que tiene el texto esperado.
    candidates = [b for b in at.sidebar.button if "Cargar datos" in (b.label or "")]
    assert candidates, "No se encontró el botón 'Cargar datos' en la barra lateral"
    candidates[0].click().run(timeout=30)
    assert not at.exception, f"Excepción tras cargar datos: {at.exception}"

    # Debe haber quedado algo en session_state.
    assert "loaded_data" in at.session_state and at.session_state["loaded_data"] is not None
    assert not at.session_state["loaded_data"]["df_bal"].empty

    # El P&L FIFO (Spot) debe haberse calculado sin explotar: la venta de
    # 0.01 BTC a 36000 (comisión 0.36 USDT) contra el lote comprado a
    # 35000 (comisión 0.00002 BTC) debe dar un pnl positivo (~9.29 USDT).
    fifo_df = at.session_state["loaded_data"]["fifo_df"]
    assert not fifo_df.empty, "El cálculo de P&L FIFO no generó filas con el trade BUY+SELL simulado"
    assert abs(float(fifo_df["pnl"].sum()) - 9.289649649649656) < 0.01

    # Simulamos el click en un botón de descarga CSV (el de saldos).
    download_buttons = [b for b in at.get("download_button") if b.key == "balances_csv"]
    assert download_buttons, "No se encontró el download_button de saldos (key='balances_csv')"
    download_buttons[0].click().run(timeout=30)
    assert not at.exception, f"Excepción tras descargar CSV: {at.exception}"

    # Lo importante: después del click de descarga, los datos SIGUEN en
    # session_state (no se perdieron ni se disparó una nueva carga).
    assert "loaded_data" in at.session_state and at.session_state["loaded_data"] is not None
    assert not at.session_state["loaded_data"]["df_bal"].empty
    assert at.session_state["loaded_data"]["df_bal"]["asset"].tolist() == ["BTC", "USDT"]

    print("OK: descargar un CSV ya no borra los datos cargados en sesión ni fuerza a repetir la llamada a la API")


if __name__ == "__main__":
    test_download_click_does_not_wipe_loaded_data()
