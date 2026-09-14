"""
Dashboard Streamlit para explorar y exportar los datos de tu cuenta de
Binance: saldos actuales, histórico de saldos, operaciones, depósitos y
retiros, con filtro por rango de fechas y por moneda, y descarga en CSV
o PDF.

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

st.sidebar.subheader("Filtrar por moneda")
currency_filter_input = st.sidebar.text_input(
    "Monedas (opcional, coma-separado)",
    value="",
    help="Ej: BTC,ETH,USDT. Se aplica a saldos, operaciones, depósitos, retiros y fiat. Deja vacío para ver todas.",
)
currency_filter = [c.strip().upper() for c in currency_filter_input.split(",") if c.strip()]

st.sidebar.markdown("---")
run_button = st.sidebar.button("🔄 Cargar datos", type="primary", use_container_width=True)


def _matches_currency(asset: str) -> bool:
    """True si `asset` (p.ej. 'BTC') pasa el filtro de moneda (o si no hay filtro)."""
    if not currency_filter:
        return True
    return asset.upper() in currency_filter


def _symbol_matches_currency(symbol: str) -> bool:
    """True si `symbol` (p.ej. 'BTCUSDT') contiene alguna de las monedas
    filtradas como base o como quote (o si no hay filtro)."""
    if not currency_filter:
        return True
    symbol = symbol.upper()
    return any(symbol.startswith(c) or symbol.endswith(c) for c in currency_filter)


def to_ms(d: date, end_of_day: bool = False) -> int:
    dt = datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt + timedelta(days=1) - timedelta(milliseconds=1)
    return int(dt.timestamp() * 1000)


st.title("📊 Binance – Saldos y Operaciones")
st.caption("Consulta tus saldos e historial de operaciones vía la API de Binance, filtra por fechas y por moneda, y exporta a CSV o PDF.")

# Importamos los módulos del proyecto solo después de configurar la página
# (por si las credenciales llegan vía la barra lateral en este mismo run).
from config import ConfigError, require_credentials  # noqa: E402
from export import to_dataframe  # noqa: E402
from fetchers.balances import get_account_snapshot, get_all_current_balances  # noqa: E402
from fetchers.trades import get_trades_for_symbols  # noqa: E402
from fetchers.transfers import get_deposits, get_fiat_deposits_withdrawals, get_withdrawals  # noqa: E402
from pdf_export import dataframe_to_pdf_bytes  # noqa: E402
from symbols import discover_symbols  # noqa: E402


def _filters_description() -> str:
    parts = [f"{start_date.isoformat()} a {end_date.isoformat()} (UTC)"]
    if currency_filter:
        parts.append("monedas: " + ", ".join(currency_filter))
    return " | ".join(parts)


def _download_buttons(df: pd.DataFrame, label: str, filename_base: str, pdf_title: str):
    if df is None or df.empty:
        st.info("Sin datos para este rango/selección.")
        return
    st.dataframe(df, use_container_width=True)
    col_csv, col_pdf = st.columns(2)
    with col_csv:
        st.download_button(
            label=f"⬇️ {label} (CSV)",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"{filename_base}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col_pdf:
        pdf_bytes = dataframe_to_pdf_bytes(df, title=pdf_title, filters_desc=_filters_description())
        st.download_button(
            label=f"⬇️ {label} (PDF)",
            data=pdf_bytes,
            file_name=f"{filename_base}.pdf",
            mime="application/pdf",
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
        if currency_filter and not df_bal.empty and "asset" in df_bal.columns:
            df_bal = df_bal[df_bal["asset"].apply(_matches_currency)]
        _download_buttons(df_bal, "Saldos actuales", "saldos_actuales", "Binance – Saldos actuales")
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
        if currency_filter and not df_hist.empty and "asset" in df_hist.columns:
            df_hist = df_hist[df_hist["asset"].apply(_matches_currency)]
        _download_buttons(df_hist, "Histórico de saldos", "balances_historicos", "Binance – Histórico de saldos")
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
        if currency_filter:
            symbol_list = [s for s in symbol_list if _symbol_matches_currency(s)]
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
        if currency_filter and not df_trades.empty and "symbol" in df_trades.columns:
            df_trades = df_trades[df_trades["symbol"].apply(_symbol_matches_currency)]
        _download_buttons(df_trades, "Operaciones", "operaciones", f"Binance – Operaciones ({market})")

    with tab_deposits:
        st.subheader("Depósitos")
        with st.spinner("Consultando depósitos..."):
            try:
                deposits_rows = get_deposits(start_ms, end_ms)
            except Exception as e:
                st.error(f"Error obteniendo depósitos: {e}")
                deposits_rows = []
        df_dep = to_dataframe(deposits_rows, ts_col="timestamp")
        if currency_filter and not df_dep.empty and "asset" in df_dep.columns:
            df_dep = df_dep[df_dep["asset"].apply(_matches_currency)]
        _download_buttons(df_dep, "Depósitos", "depositos", "Binance – Depósitos")

    with tab_withdrawals:
        st.subheader("Retiros")
        with st.spinner("Consultando retiros..."):
            try:
                withdrawals_rows = get_withdrawals(start_ms, end_ms)
            except Exception as e:
                st.error(f"Error obteniendo retiros: {e}")
                withdrawals_rows = []
        df_wd = to_dataframe(withdrawals_rows, ts_col="timestamp")
        if currency_filter and not df_wd.empty and "asset" in df_wd.columns:
            df_wd = df_wd[df_wd["asset"].apply(_matches_currency)]
        _download_buttons(df_wd, "Retiros", "retiros", "Binance – Retiros")

    with tab_fiat:
        st.subheader("Operaciones Fiat (compra/venta con tarjeta o transferencia)")
        with st.spinner("Consultando operaciones fiat..."):
            try:
                fiat_rows = get_fiat_deposits_withdrawals(start_ms, end_ms)
            except Exception as e:
                st.error(f"Error obteniendo operaciones fiat: {e}")
                fiat_rows = []
        df_fiat = to_dataframe(fiat_rows, ts_col="timestamp")
        if currency_filter and not df_fiat.empty and "asset" in df_fiat.columns:
            df_fiat = df_fiat[df_fiat["asset"].apply(_matches_currency)]
        _download_buttons(df_fiat, "Fiat", "fiat", "Binance – Operaciones Fiat")

else:
    st.info("Configura tus credenciales (si hace falta) y el rango de fechas en la barra lateral, luego pulsa **Cargar datos**.")
