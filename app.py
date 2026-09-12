"""
Dashboard Streamlit para explorar y exportar los datos de tu cuenta de
Binance: saldos actuales, histórico de saldos, operaciones, depósitos y
retiros, con filtro por rango de fechas y descarga en CSV.

Ejecutar:
    streamlit run app.py

Credenciales: se leen de BINANCE_API_KEY / BINANCE_API_SECRET (variables
de entorno o archivo .env). También puedes pegarlas en la barra lateral
solo para la sesión actual (no se guardan en ningún sitio) si prefieres
no usar variables de entorno.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Binance – Saldos y Operaciones", page_icon="📊", layout="wide")


def _set_session_credentials(api_key: str, api_secret: str) -> None:
    """Inyecta las credenciales en variables de entorno del proceso para
    que binance_api.py las recoja. Solo viven en memoria de esta sesión."""
    if api_key:
        os.environ["BINANCE_API_KEY"] = api_key.strip()
    if api_secret:
        os.environ["BINANCE_API_SECRET"] = api_secret.strip()


# --- Sidebar: credenciales y filtros -----------------------------------
st.sidebar.title("⚙️ Configuración")

env_key_present = bool(os.environ.get("BINANCE_API_KEY"))
env_secret_present = bool(os.environ.get("BINANCE_API_SECRET"))

with st.sidebar.expander("Credenciales de la API", expanded=not (env_key_present and env_secret_present)):
    if env_key_present and env_secret_present:
        st.success("Credenciales detectadas en variables de entorno.")
    api_key_input = st.text_input("API Key", type="password", value="", help="Se usa solo en esta sesión, no se guarda en disco.")
    api_secret_input = st.text_input("API Secret", type="password", value="")
    if st.button("Usar estas credenciales para esta sesión"):
        _set_session_credentials(api_key_input, api_secret_input)
        st.success("Credenciales cargadas en la sesión.")
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("Rango de fechas")
default_start = date.today() - timedelta(days=90)
start_date = st.sidebar.date_input("Desde", value=default_start)
end_date = st.sidebar.date_input("Hasta", value=date.today())

st.sidebar.subheader("Mercado para operaciones")
market = st.sidebar.selectbox("Mercado", ["SPOT", "MARGIN", "FUTURES"], index=0)
manual_symbols = st.sidebar.text_input("Símbolos manuales (opcional, coma-separado)", value="", help="Ej: BTCUSDT,ETHUSDT. Si se deja vacío, se auto-descubren.")

st.sidebar.markdown("---")
run_button = st.sidebar.button("🔄 Cargar datos", type="primary", use_container_width=True)


def to_ms(d: date, end_of_day: bool = False) -> int:
    dt = datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt + timedelta(days=1) - timedelta(milliseconds=1)
    return int(dt.timestamp() * 1000)


st.title("📊 Binance – Saldos y Operaciones")
st.caption("Consulta tus saldos e historial de operaciones vía la API de Binance, filtra por fechas y exporta a CSV.")

# Importamos los módulos del proyecto solo después de configurar la página
# (por si las credenciales llegan vía la barra lateral en este mismo run).
from config import ConfigError, require_credentials  # noqa: E402
from export import to_dataframe  # noqa: E402
from fetchers.balances import get_account_snapshot, get_all_current_balances  # noqa: E402
from fetchers.trades import get_trades_for_symbols  # noqa: E402
from fetchers.transfers import get_deposits, get_fiat_deposits_withdrawals, get_withdrawals  # noqa: E402
from symbols import discover_symbols  # noqa: E402


def _download_button(df: pd.DataFrame, label: str, filename: str):
    if df is None or df.empty:
        st.info("Sin datos para este rango/selección.")
        return
    st.dataframe(df, use_container_width=True)
    st.download_button(
        label=f"⬇️ Descargar {label} (CSV)",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        use_container_width=True,
    )


tab_balances, tab_history, tab_trades, tab_deposits, tab_withdrawals, tab_fiat = st.tabs(
    ["Saldos actuales", "Histórico de saldos", "Operaciones", "Depósitos", "Retiros", "Fiat"]
)

if run_button:
    try:
        require_credentials()
    except ConfigError as e:
        st.error(str(e))
        st.stop()

    start_ms = to_ms(start_date)
    end_ms = to_ms(end_date, end_of_day=True)

    with st.spinner("Consultando saldos actuales..."):
        try:
            balances_rows = get_all_current_balances()
        except Exception as e:
            st.error(f"Error obteniendo saldos: {e}")
            balances_rows = []

    with tab_balances:
        st.subheader("Saldos actuales (Spot + Margin + Futuros)")
        df_bal = pd.DataFrame(balances_rows)
        _download_button(df_bal, "saldos_actuales", "saldos_actuales.csv")
        if not df_bal.empty and "total" in df_bal.columns:
            st.bar_chart(df_bal.set_index("asset")["total"])

    with st.spinner("Consultando histórico de saldos (accountSnapshot)..."):
        history_rows = []
        for acc_type in ("SPOT", "MARGIN", "FUTURES"):
            try:
                history_rows.extend(get_account_snapshot(acc_type, start_ms, end_ms))
            except Exception:
                pass

    with tab_history:
        st.subheader("Histórico diario de saldos")
        st.caption("Binance solo conserva snapshots diarios de los últimos ~30-90 días, según el tipo de cuenta.")
        df_hist = pd.DataFrame(history_rows)
        _download_button(df_hist, "balances_historicos", "balances_historicos.csv")
        if not df_hist.empty and "date" in df_hist.columns and "total_btc_value" in df_hist.columns:
            chart_df = df_hist.drop_duplicates(subset=["date", "wallet"])[["date", "total_btc_value"]].dropna()
            if not chart_df.empty:
                chart_df["total_btc_value"] = chart_df["total_btc_value"].astype(float)
                st.line_chart(chart_df.set_index("date"))

    with tab_trades:
        st.subheader(f"Operaciones – {market}")
        if manual_symbols.strip():
            symbol_list = [s.strip().upper() for s in manual_symbols.split(",") if s.strip()]
        else:
            with st.spinner("Auto-descubriendo símbolos..."):
                assets = {b["asset"] for b in balances_rows}
                try:
                    for d in get_deposits(start_ms, end_ms):
                        assets.add(d["asset"])
                    for w in get_withdrawals(start_ms, end_ms):
                        assets.add(w["asset"])
                except Exception:
                    pass
                discovery_market = "FUTURES" if market == "FUTURES" else "SPOT"
                symbol_list = discover_symbols(assets, market=discovery_market)
        st.caption(f"Símbolos consultados: {', '.join(symbol_list) if symbol_list else '(ninguno detectado)'}")

        trades_rows = []
        if symbol_list:
            progress_bar = st.progress(0.0, text="Consultando operaciones...")

            def progress_cb(symbol, i, total):
                progress_bar.progress(i / total, text=f"Consultando {symbol} ({i}/{total})")

            try:
                trades_rows = get_trades_for_symbols(symbol_list, market, start_ms, end_ms, progress_cb=progress_cb)
            except Exception as e:
                st.error(f"Error obteniendo operaciones: {e}")
            progress_bar.empty()

        df_trades = to_dataframe(trades_rows, ts_col="timestamp")
        _download_button(df_trades, "operaciones", "operaciones.csv")

    with tab_deposits:
        st.subheader("Depósitos")
        with st.spinner("Consultando depósitos..."):
            try:
                deposits_rows = get_deposits(start_ms, end_ms)
            except Exception as e:
                st.error(f"Error obteniendo depósitos: {e}")
                deposits_rows = []
        df_dep = to_dataframe(deposits_rows, ts_col="timestamp")
        _download_button(df_dep, "depositos", "depositos.csv")

    with tab_withdrawals:
        st.subheader("Retiros")
        with st.spinner("Consultando retiros..."):
            try:
                withdrawals_rows = get_withdrawals(start_ms, end_ms)
            except Exception as e:
                st.error(f"Error obteniendo retiros: {e}")
                withdrawals_rows = []
        df_wd = to_dataframe(withdrawals_rows, ts_col="timestamp")
        _download_button(df_wd, "retiros", "retiros.csv")

    with tab_fiat:
        st.subheader("Operaciones Fiat (compra/venta con tarjeta o transferencia)")
        with st.spinner("Consultando operaciones fiat..."):
            try:
                fiat_rows = get_fiat_deposits_withdrawals(start_ms, end_ms)
            except Exception as e:
                st.error(f"Error obteniendo operaciones fiat: {e}")
                fiat_rows = []
        df_fiat = to_dataframe(fiat_rows, ts_col="timestamp")
        _download_button(df_fiat, "fiat", "fiat.csv")

else:
    st.info("Configura tus credenciales (si hace falta) y el rango de fechas en la barra lateral, luego pulsa **Cargar datos**.")
