"""
Dashboard Streamlit para explorar y exportar los datos de tu cuenta de
Binance: saldos actuales, histórico de saldos, operaciones, depósitos,
retiros y estadísticas, con filtro por rango de fechas y por moneda, y
descarga en CSV o PDF.

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

import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Binance – Saldos y Operaciones", page_icon="📊", layout="wide")

# Paleta categórica validada (ver skill de dataviz): orden fijo, nunca
# reciclado. Solo usamos los dos primeros slots (comparaciones de 2
# categorías: Depósito/Retiro, Compra/Venta) y un tono único para barras
# de una sola serie (magnitud por categoría, sin necesidad de leyenda).
COLOR_SLOT_1 = "#2a78d6"  # azul
COLOR_SLOT_2 = "#eb6834"  # naranja


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
    help="Ej: BTC,ETH,USDT. Se aplica a saldos, operaciones, depósitos, retiros, fiat y estadísticas. Deja vacío para ver todas.",
)
currency_filter = [c.strip().upper() for c in currency_filter_input.split(",") if c.strip()]

st.sidebar.subheader("Formato del CSV")
csv_format_label = st.sidebar.radio(
    "Separador de decimales",
    ["Europeo: 1.234,56 (Excel/Power BI en español)", "Internacional: 1234.56 (punto decimal)"],
    index=0,
    help="Si Power BI o Excel no detectan los decimales del CSV, es casi seguro que están configurados "
    "en español (esperan coma decimal y punto y coma como separador de columnas). Elige 'Europeo' aquí "
    "para que el CSV ya salga en ese formato. Esto no afecta al PDF.",
)
csv_format = "europeo" if csv_format_label.startswith("Europeo") else "internacional"

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
from export import to_csv_bytes, to_dataframe  # noqa: E402
from fetchers.balances import get_account_snapshot, get_all_current_balances  # noqa: E402
from fetchers.trades import get_trades_for_symbols  # noqa: E402
from fetchers.transfers import get_deposits, get_fiat_deposits_withdrawals, get_withdrawals  # noqa: E402
from pdf_export import dataframe_to_pdf_bytes  # noqa: E402
import stats  # noqa: E402
from symbols import discover_symbols  # noqa: E402


def _filters_description() -> str:
    parts = [f"{start_date.isoformat()} a {end_date.isoformat()} (UTC)"]
    if currency_filter:
        parts.append("monedas: " + ", ".join(currency_filter))
    return " | ".join(parts)


def _download_buttons(df: pd.DataFrame, label: str, filename_base: str, pdf_title: str, filters_desc: str, key_prefix: str):
    if df is None or df.empty:
        st.info("Sin datos para este rango/selección.")
        return
    st.dataframe(df, use_container_width=True)
    col_csv, col_pdf = st.columns(2)
    with col_csv:
        st.download_button(
            label=f"⬇️ {label} (CSV)",
            data=to_csv_bytes(df, csv_format=csv_format),
            file_name=f"{filename_base}.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"{key_prefix}_csv",
        )
    with col_pdf:
        pdf_bytes = dataframe_to_pdf_bytes(df, title=pdf_title, filters_desc=filters_desc)
        st.download_button(
            label=f"⬇️ {label} (PDF)",
            data=pdf_bytes,
            file_name=f"{filename_base}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key=f"{key_prefix}_pdf",
        )


tab_balances, tab_history, tab_trades, tab_deposits, tab_withdrawals, tab_fiat, tab_stats = st.tabs(
    ["Saldos actuales", "Histórico de saldos", "Operaciones", "Depósitos", "Retiros", "Fiat", "📈 Estadísticas"]
)

if "loaded_data" not in st.session_state:
    st.session_state["loaded_data"] = None

if run_button:
    try:
        require_credentials()
    except ConfigError as e:
        st.error(str(e))
        st.stop()

    start_ms = to_ms(start_date)
    end_ms = to_ms(end_date, end_of_day=True)

    # ------------------------------------------------------------------
    # Fase 1: obtener TODOS los datos una sola vez (para no duplicar
    # llamadas a la API entre pestañas y para poder cruzar datasets en
    # "Estadísticas").
    # ------------------------------------------------------------------
    with st.spinner("Consultando saldos actuales..."):
        try:
            balances_rows = get_all_current_balances()
        except Exception as e:
            st.error(f"Error obteniendo saldos: {e}")
            balances_rows = []

    with st.spinner("Consultando histórico de saldos (accountSnapshot)..."):
        history_rows = []
        for acc_type in ("SPOT", "MARGIN", "FUTURES"):
            try:
                history_rows.extend(get_account_snapshot(acc_type, start_ms, end_ms))
            except Exception:
                pass

    with st.spinner("Consultando depósitos..."):
        try:
            deposits_rows = get_deposits(start_ms, end_ms)
        except Exception as e:
            st.error(f"Error obteniendo depósitos: {e}")
            deposits_rows = []

    with st.spinner("Consultando retiros..."):
        try:
            withdrawals_rows = get_withdrawals(start_ms, end_ms)
        except Exception as e:
            st.error(f"Error obteniendo retiros: {e}")
            withdrawals_rows = []

    with st.spinner("Consultando operaciones fiat..."):
        try:
            fiat_rows = get_fiat_deposits_withdrawals(start_ms, end_ms)
        except Exception as e:
            st.error(f"Error obteniendo operaciones fiat: {e}")
            fiat_rows = []

    if manual_symbols.strip():
        symbol_list = [s.strip().upper() for s in manual_symbols.split(",") if s.strip()]
    else:
        with st.spinner("Auto-descubriendo símbolos..."):
            assets = {b["asset"] for b in balances_rows}
            assets |= {d["asset"] for d in deposits_rows}
            assets |= {w["asset"] for w in withdrawals_rows}
            discovery_market = "FUTURES" if market == "FUTURES" else "SPOT"
            symbol_list = discover_symbols(assets, market=discovery_market)
    if currency_filter:
        symbol_list = [s for s in symbol_list if _symbol_matches_currency(s)]

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

    # ------------------------------------------------------------------
    # Fase 2: aplicar el filtro de moneda y construir los DataFrames que
    # usan tanto las pestañas de datos como la de Estadísticas.
    # ------------------------------------------------------------------
    df_bal = pd.DataFrame(balances_rows)
    if currency_filter and not df_bal.empty and "asset" in df_bal.columns:
        df_bal = df_bal[df_bal["asset"].apply(_matches_currency)]

    df_hist = pd.DataFrame(history_rows)
    if currency_filter and not df_hist.empty and "asset" in df_hist.columns:
        df_hist = df_hist[df_hist["asset"].apply(_matches_currency)]

    df_trades = to_dataframe(trades_rows, ts_col="timestamp")
    if currency_filter and not df_trades.empty and "symbol" in df_trades.columns:
        df_trades = df_trades[df_trades["symbol"].apply(_symbol_matches_currency)]

    df_dep = to_dataframe(deposits_rows, ts_col="timestamp")
    if currency_filter and not df_dep.empty and "asset" in df_dep.columns:
        df_dep = df_dep[df_dep["asset"].apply(_matches_currency)]

    df_wd = to_dataframe(withdrawals_rows, ts_col="timestamp")
    if currency_filter and not df_wd.empty and "asset" in df_wd.columns:
        df_wd = df_wd[df_wd["asset"].apply(_matches_currency)]

    df_fiat = to_dataframe(fiat_rows, ts_col="timestamp")
    if currency_filter and not df_fiat.empty and "asset" in df_fiat.columns:
        df_fiat = df_fiat[df_fiat["asset"].apply(_matches_currency)]

    # ------------------------------------------------------------------
    # Fase 3: guardar todo en session_state. Streamlit vuelve a ejecutar
    # este script en cada interacción (incluidos los botones de descarga
    # CSV/PDF), así que si no guardamos los datos aquí, cada descarga
    # forzaría a "olvidar" lo cargado y a tener que pulsar "Cargar datos"
    # de nuevo. Guardándolos, las descargas ya no vuelven a llamar a la
    # API — solo se repite la consulta cuando pulsas "Cargar datos" (o
    # cambias fechas/moneda/símbolos y vuelves a pulsarlo).
    # ------------------------------------------------------------------
    st.session_state["loaded_data"] = {
        "df_bal": df_bal,
        "df_hist": df_hist,
        "df_trades": df_trades,
        "df_dep": df_dep,
        "df_wd": df_wd,
        "df_fiat": df_fiat,
        "symbol_list": symbol_list,
        "market": market,
        "filters_desc": _filters_description(),
    }

data = st.session_state["loaded_data"]

if data:
    df_bal = data["df_bal"]
    df_hist = data["df_hist"]
    df_trades = data["df_trades"]
    df_dep = data["df_dep"]
    df_wd = data["df_wd"]
    df_fiat = data["df_fiat"]
    symbol_list = data["symbol_list"]
    loaded_market = data["market"]
    filters_desc = data["filters_desc"]

    st.caption(f"📅 Datos cargados con: {filters_desc} — mercado operaciones: {loaded_market}. Vuelve a pulsar **Cargar datos** para refrescar.")

    # ------------------------------------------------------------------
    # Fase 4: renderizar cada pestaña con los datos ya cargados (no
    # dispara llamadas nuevas a la API; sobrevive a las descargas).
    # ------------------------------------------------------------------
    with tab_balances:
        st.subheader("Saldos actuales (Spot + Margin + Futuros)")
        _download_buttons(df_bal, "Saldos actuales", "saldos_actuales", "Binance – Saldos actuales", filters_desc, "balances")
        if not df_bal.empty and "total" in df_bal.columns:
            st.bar_chart(df_bal.set_index("asset")["total"])

    with tab_history:
        st.subheader("Histórico diario de saldos")
        st.caption("Binance solo conserva snapshots diarios de los últimos ~30-90 días, según el tipo de cuenta.")
        _download_buttons(df_hist, "Histórico de saldos", "balances_historicos", "Binance – Histórico de saldos", filters_desc, "history")
        if not df_hist.empty and "date" in df_hist.columns and "total_btc_value" in df_hist.columns:
            chart_df = df_hist.drop_duplicates(subset=["date", "wallet"])[["date", "total_btc_value"]].dropna()
            if not chart_df.empty:
                chart_df["total_btc_value"] = chart_df["total_btc_value"].astype(float)
                st.line_chart(chart_df.set_index("date"))

    with tab_trades:
        st.subheader(f"Operaciones – {loaded_market}")
        st.caption(f"Símbolos consultados: {', '.join(symbol_list) if symbol_list else '(ninguno detectado)'}")
        _download_buttons(df_trades, "Operaciones", "operaciones", f"Binance – Operaciones ({loaded_market})", filters_desc, "trades")

    with tab_deposits:
        st.subheader("Depósitos")
        _download_buttons(df_dep, "Depósitos", "depositos", "Binance – Depósitos", filters_desc, "deposits")

    with tab_withdrawals:
        st.subheader("Retiros")
        _download_buttons(df_wd, "Retiros", "retiros", "Binance – Retiros", filters_desc, "withdrawals")

    with tab_fiat:
        st.subheader("Operaciones Fiat (compra/venta con tarjeta o transferencia)")
        _download_buttons(df_fiat, "Fiat", "fiat", "Binance – Operaciones Fiat", filters_desc, "fiat")

    with tab_stats:
        st.subheader("📈 Estadísticas")
        st.caption(f"Rango: {filters_desc}")

        # --- KPIs ---------------------------------------------------
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Monedas con saldo", int(df_bal["asset"].nunique()) if not df_bal.empty else 0)
        k2.metric("Depósitos (nº)", int(len(df_dep)))
        k3.metric("Retiros (nº)", int(len(df_wd)))
        k4.metric("Operaciones (nº)", int(len(df_trades)))

        st.markdown("---")

        # --- Saldos por moneda ---------------------------------------
        st.markdown("#### Saldos por moneda")
        bal_stats = stats.balances_by_asset(df_bal)
        if bal_stats.empty:
            st.info("Sin saldos para mostrar con el filtro actual.")
        else:
            chart = (
                alt.Chart(bal_stats)
                .mark_bar(color=COLOR_SLOT_1, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("asset:N", sort="-y", title="Moneda"),
                    y=alt.Y("total:Q", title="Saldo total (unidades nativas)"),
                    tooltip=[alt.Tooltip("asset:N", title="Moneda"), alt.Tooltip("total:Q", title="Saldo", format=",.8f")],
                )
                .properties(height=320)
            )
            st.altair_chart(chart, use_container_width=True)

        st.markdown("---")

        # --- Depósitos vs Retiros por moneda --------------------------
        st.markdown("#### Depósitos vs Retiros por moneda")
        dep_wd_wide = stats.deposits_vs_withdrawals_by_asset(df_dep, df_wd)
        if dep_wd_wide.empty:
            st.info("Sin depósitos ni retiros para mostrar con el filtro actual.")
        else:
            dep_wd_long = stats.to_long_dep_wd(dep_wd_wide)
            chart = (
                alt.Chart(dep_wd_long)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("asset:N", title="Moneda"),
                    xOffset=alt.XOffset("tipo:N", sort=["Depósito", "Retiro"]),
                    y=alt.Y("amount:Q", title="Importe (unidades nativas)"),
                    color=alt.Color(
                        "tipo:N",
                        sort=["Depósito", "Retiro"],
                        scale=alt.Scale(domain=["Depósito", "Retiro"], range=[COLOR_SLOT_1, COLOR_SLOT_2]),
                        legend=alt.Legend(title="Tipo"),
                    ),
                    tooltip=[
                        alt.Tooltip("asset:N", title="Moneda"),
                        alt.Tooltip("tipo:N", title="Tipo"),
                        alt.Tooltip("amount:Q", title="Importe", format=",.8f"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(chart, use_container_width=True)
            st.caption("Tabla de neto (depositado − retirado) por moneda:")
            st.dataframe(dep_wd_wide, use_container_width=True)

        st.markdown("---")

        # --- Depósitos vs Retiros en el tiempo (conteo mensual) -------
        st.markdown("#### Depósitos vs Retiros por mes (nº de operaciones)")
        st.caption("Se compara el número de movimientos, no el importe, para que sea comparable aunque mezcles varias monedas.")
        monthly = stats.monthly_transaction_counts(df_dep, df_wd)
        if monthly.empty:
            st.info("Sin depósitos ni retiros para mostrar con el filtro actual.")
        else:
            chart = (
                alt.Chart(monthly)
                .mark_line(point=alt.OverlayMarkDef(size=80), strokeWidth=2)
                .encode(
                    x=alt.X("mes:N", title="Mes"),
                    y=alt.Y("count:Q", title="Nº de operaciones"),
                    color=alt.Color(
                        "tipo:N",
                        sort=["Depósito", "Retiro"],
                        scale=alt.Scale(domain=["Depósito", "Retiro"], range=[COLOR_SLOT_1, COLOR_SLOT_2]),
                        legend=alt.Legend(title="Tipo"),
                    ),
                    tooltip=[alt.Tooltip("mes:N", title="Mes"), alt.Tooltip("tipo:N", title="Tipo"), alt.Tooltip("count:Q", title="Nº operaciones")],
                )
                .properties(height=300)
            )
            st.altair_chart(chart, use_container_width=True)

        st.markdown("---")

        # --- Operaciones: compra vs venta, por símbolo, comisiones ----
        st.markdown("#### Operaciones")
        col_a, col_b = st.columns(2)

        with col_a:
            st.caption("Compra vs venta (nº de operaciones)")
            side_counts = stats.trade_side_counts(df_trades)
            if side_counts.empty:
                st.info("Sin operaciones para mostrar con el filtro actual.")
            else:
                chart = (
                    alt.Chart(side_counts)
                    .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                    .encode(
                        x=alt.X("side:N", title="Lado", sort=["BUY", "SELL"]),
                        y=alt.Y("count:Q", title="Nº de operaciones"),
                        color=alt.Color(
                            "side:N",
                            sort=["BUY", "SELL"],
                            scale=alt.Scale(domain=["BUY", "SELL"], range=[COLOR_SLOT_1, COLOR_SLOT_2]),
                            legend=None,
                        ),
                        tooltip=[alt.Tooltip("side:N", title="Lado"), alt.Tooltip("count:Q", title="Nº operaciones")],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart, use_container_width=True)

        with col_b:
            st.caption("Comisiones totales pagadas (por moneda de cobro)")
            fees = stats.fees_by_asset(df_trades)
            if fees.empty:
                st.info("Sin comisiones para mostrar con el filtro actual.")
            else:
                chart = (
                    alt.Chart(fees)
                    .mark_bar(color=COLOR_SLOT_1, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                    .encode(
                        x=alt.X("commission_asset:N", sort="-y", title="Moneda"),
                        y=alt.Y("total_commission:Q", title="Comisión total"),
                        tooltip=[
                            alt.Tooltip("commission_asset:N", title="Moneda"),
                            alt.Tooltip("total_commission:Q", title="Comisión", format=",.8f"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart, use_container_width=True)

        st.caption("Operaciones por símbolo (top 15 por nº de operaciones):")
        by_symbol = stats.trades_by_symbol(df_trades)
        if by_symbol.empty:
            st.info("Sin operaciones para mostrar con el filtro actual.")
        else:
            chart = (
                alt.Chart(by_symbol)
                .mark_bar(color=COLOR_SLOT_1, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("symbol:N", sort="-y", title="Símbolo"),
                    y=alt.Y("trades:Q", title="Nº de operaciones"),
                    tooltip=[
                        alt.Tooltip("symbol:N", title="Símbolo"),
                        alt.Tooltip("trades:Q", title="Nº operaciones"),
                        alt.Tooltip("quote_volume:Q", title="Volumen (quote)", format=",.2f"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(chart, use_container_width=True)
            st.caption("El volumen (quote) está en la moneda de cotización propia de cada símbolo (p.ej. USDT en BTCUSDT) — no se suma entre símbolos con distinta moneda de cotización.")

else:
    st.info("Configura tus credenciales (si hace falta) y el rango de fechas en la barra lateral, luego pulsa **Cargar datos**.")
