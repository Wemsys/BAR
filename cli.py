#!/usr/bin/env python3
"""
CLI para exportar saldos y operaciones de tu cuenta de Binance a CSV.

Ejemplos:

    # Todo lo disponible, histórico completo, a ./exports
    python cli.py --types all

    # Solo operaciones spot entre dos fechas
    python cli.py --types trades --market SPOT --start 2024-01-01 --end 2024-12-31

    # Indicando símbolos manualmente en vez de auto-descubrirlos
    python cli.py --types trades --market SPOT --symbols BTCUSDT,ETHUSDT

Requisitos: variables de entorno BINANCE_API_KEY y BINANCE_API_SECRET
definidas (ver README.md).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import List, Optional

from config import ConfigError, require_credentials
from export import export_all
from fetchers.balances import (
    get_account_snapshot,
    get_all_current_balances,
)
from fetchers.trades import get_trades_for_symbols
from fetchers.transfers import get_deposits, get_fiat_deposits_withdrawals, get_withdrawals
from symbols import discover_symbols


def parse_date(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def collect_assets_hint(start_ms, end_ms) -> List[str]:
    """Reúne activos conocidos (saldo actual + depósitos/retiros) para
    alimentar el auto-descubrimiento de símbolos."""
    assets = set()
    for b in get_all_current_balances():
        assets.add(b["asset"])
    try:
        for d in get_deposits(start_ms, end_ms):
            assets.add(d["asset"])
        for w in get_withdrawals(start_ms, end_ms):
            assets.add(w["asset"])
    except Exception:
        pass
    return sorted(assets)


def main():
    parser = argparse.ArgumentParser(description="Exporta datos de tu cuenta de Binance a CSV.")
    parser.add_argument(
        "--types",
        default="all",
        help="Coma-separado: balances,balance_history,trades,deposits,withdrawals,fiat,all (default: all)",
    )
    parser.add_argument("--market", default="SPOT", choices=["SPOT", "MARGIN", "FUTURES", "ALL"], help="Mercado para --types trades")
    parser.add_argument("--start", default=None, help="Fecha inicio YYYY-MM-DD (UTC). Si se omite, sin límite inferior.")
    parser.add_argument("--end", default=None, help="Fecha fin YYYY-MM-DD (UTC). Si se omite, hasta hoy.")
    parser.add_argument("--symbols", default=None, help="Lista de símbolos separados por coma (omite el auto-descubrimiento).")
    parser.add_argument("--output", default="./exports", help="Carpeta de salida para los CSV (default: ./exports)")
    args = parser.parse_args()

    try:
        require_credentials()
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    start_ms = parse_date(args.start)
    end_ms = parse_date(args.end)
    if end_ms is not None:
        # Incluir el día completo de "end"
        end_ms += 24 * 60 * 60 * 1000 - 1

    requested = {t.strip().lower() for t in args.types.split(",")}
    if "all" in requested:
        requested = {"balances", "balance_history", "trades", "deposits", "withdrawals", "fiat"}

    balances = None
    balance_history = None
    trades = None
    deposits = None
    withdrawals = None
    fiat = None

    if "balances" in requested:
        print("Obteniendo saldos actuales (spot/margin/futuros)...")
        balances = get_all_current_balances()
        print(f"  -> {len(balances)} saldos encontrados.")

    if "balance_history" in requested:
        print("Obteniendo histórico de saldos (accountSnapshot, últimos ~30-90 días)...")
        balance_history = []
        for acc_type in ("SPOT", "MARGIN", "FUTURES"):
            balance_history.extend(get_account_snapshot(acc_type, start_ms, end_ms))
        print(f"  -> {len(balance_history)} registros históricos encontrados.")

    if "deposits" in requested:
        print("Obteniendo historial de depósitos...")
        deposits = get_deposits(start_ms, end_ms)
        print(f"  -> {len(deposits)} depósitos encontrados.")

    if "withdrawals" in requested:
        print("Obteniendo historial de retiros...")
        withdrawals = get_withdrawals(start_ms, end_ms)
        print(f"  -> {len(withdrawals)} retiros encontrados.")

    if "fiat" in requested:
        print("Obteniendo historial de operaciones fiat...")
        fiat = get_fiat_deposits_withdrawals(start_ms, end_ms)
        print(f"  -> {len(fiat)} operaciones fiat encontradas.")

    if "trades" in requested:
        if args.symbols:
            symbol_list = [s.strip().upper() for s in args.symbols.split(",")]
        else:
            print("Auto-descubriendo símbolos a partir de tus activos...")
            asset_hints = collect_assets_hint(start_ms, end_ms)
            print(f"  Activos detectados: {', '.join(asset_hints) if asset_hints else '(ninguno)'}")
            markets_for_discovery = ["SPOT"] if args.market != "FUTURES" else ["FUTURES"]
            symbol_list = []
            for m in markets_for_discovery:
                symbol_list.extend(discover_symbols(asset_hints, market=m))
            symbol_list = sorted(set(symbol_list))
        print(f"  Símbolos a consultar: {', '.join(symbol_list) if symbol_list else '(ninguno)'}")

        trades = []
        markets = ["SPOT", "MARGIN", "FUTURES"] if args.market == "ALL" else [args.market]

        def progress(symbol, i, total):
            print(f"    [{i}/{total}] {symbol}: OK")

        for m in markets:
            print(f"Obteniendo trades de {m}...")
            trades.extend(get_trades_for_symbols(symbol_list, m, start_ms, end_ms, progress_cb=progress))
        print(f"  -> {len(trades)} operaciones encontradas en total.")

    print(f"\nExportando CSVs a {args.output} ...")
    written = export_all(
        args.output,
        balances=balances,
        balance_history=balance_history,
        trades=trades,
        deposits=deposits,
        withdrawals=withdrawals,
        fiat=fiat,
    )
    if not written:
        print("No se generó ningún archivo (sin datos o sin tipos seleccionados).")
    for name, path in written.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
