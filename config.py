"""
Configuración central del sistema.

Las credenciales SIEMPRE se leen de variables de entorno (o de un archivo
.env local que tú controlas). Nunca se deben escribir en el código ni
compartir en un chat.

Variables de entorno soportadas:
    BINANCE_API_KEY      -> API key de Binance (obligatoria)
    BINANCE_API_SECRET   -> API secret de Binance (obligatoria)
    BINANCE_BASE_URL     -> Base URL spot/sapi (opcional, default api.binance.com)
    BINANCE_FUTURES_URL  -> Base URL futuros USDT-M (opcional)
    BINANCE_RECV_WINDOW  -> recvWindow en ms para las firmas (opcional, default 10000)
"""
from __future__ import annotations

import os

try:
    # Si existe python-dotenv y un archivo .env en el directorio actual,
    # se carga automáticamente. Es opcional: si no está instalado o no hay
    # archivo .env, simplemente se ignora.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dependencia opcional
    pass


class ConfigError(RuntimeError):
    """Error de configuración (por ejemplo, credenciales ausentes)."""


API_KEY = os.environ.get("BINANCE_API_KEY", "").strip()
API_SECRET = os.environ.get("BINANCE_API_SECRET", "").strip()

SPOT_BASE_URL = os.environ.get("BINANCE_BASE_URL", "https://api.binance.com").rstrip("/")
FUTURES_BASE_URL = os.environ.get("BINANCE_FUTURES_URL", "https://fapi.binance.com").rstrip("/")

RECV_WINDOW = int(os.environ.get("BINANCE_RECV_WINDOW", "10000"))

# Activos "quote" habituales usados para el auto-descubrimiento de símbolos
# de trading (ver symbols.py). Puedes ampliar esta lista si operas con
# otras monedas de cotización.
COMMON_QUOTE_ASSETS = [
    "USDT", "FDUSD", "BUSD", "USDC", "BTC", "ETH", "BNB", "EUR", "TRY", "BRL",
]


def require_credentials() -> None:
    """Lanza un error claro si faltan las credenciales."""
    missing = []
    if not API_KEY:
        missing.append("BINANCE_API_KEY")
    if not API_SECRET:
        missing.append("BINANCE_API_SECRET")
    if missing:
        raise ConfigError(
            "Faltan variables de entorno: "
            + ", ".join(missing)
            + ". Defínelas antes de ejecutar (ver README.md)."
        )
