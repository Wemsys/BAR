"""
Cliente HTTP de bajo nivel para la API de Binance.

Implementa la firma HMAC-SHA256 que exigen los endpoints privados
(SPOT/MARGIN vía api.binance.com y sapi.binance.com, y Futuros USDT-M vía
fapi.binance.com), con manejo de reintentos ante rate limits (HTTP 429/418)
y errores de red transitorios.

No depende de ninguna librería de terceros para Binance (solo `requests`),
para mantener el código auditable y fácil de mantener.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from config import API_KEY, API_SECRET, FUTURES_BASE_URL, RECV_WINDOW, SPOT_BASE_URL, require_credentials

_SESSION = requests.Session()
_SESSION.headers.update({"X-MBX-APIKEY": API_KEY})


class BinanceAPIError(RuntimeError):
    """Error devuelto por la API de Binance (incluye código y mensaje)."""

    def __init__(self, status_code: int, code: Optional[int], msg: str, endpoint: str):
        self.status_code = status_code
        self.code = code
        self.msg = msg
        self.endpoint = endpoint
        super().__init__(f"[{endpoint}] HTTP {status_code} code={code}: {msg}")


def _sign(params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params.setdefault("recvWindow", RECV_WINDOW)
    query = urlencode(params, doseq=True)
    signature = hmac.new(API_SECRET.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    params["signature"] = signature
    return params


def _request(
    method: str,
    base_url: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    signed: bool = False,
    max_retries: int = 5,
) -> Any:
    """Ejecuta una request a Binance con reintentos ante 429/418 y errores de red."""
    if signed:
        require_credentials()

    params = params or {}
    url = f"{base_url}{path}"

    attempt = 0
    while True:
        attempt += 1
        try:
            call_params = _sign(params) if signed else params
            if method == "GET":
                resp = _SESSION.get(url, params=call_params, timeout=30)
            elif method == "POST":
                resp = _SESSION.post(url, params=call_params, timeout=30)
            elif method == "DELETE":
                resp = _SESSION.delete(url, params=call_params, timeout=30)
            else:
                raise ValueError(f"Método HTTP no soportado: {method}")
        except requests.exceptions.RequestException as exc:
            if attempt > max_retries:
                raise
            time.sleep(min(2 ** attempt, 30))
            continue

        if resp.status_code == 200:
            return resp.json()

        # Rate limit (429) o IP bloqueada temporalmente (418): esperar y reintentar.
        if resp.status_code in (429, 418) and attempt <= max_retries:
            retry_after = int(resp.headers.get("Retry-After", "0") or "0")
            wait = max(retry_after, min(2 ** attempt, 60))
            time.sleep(wait)
            continue

        # Errores de servidor transitorios.
        if resp.status_code >= 500 and attempt <= max_retries:
            time.sleep(min(2 ** attempt, 30))
            continue

        try:
            payload = resp.json()
            code = payload.get("code")
            msg = payload.get("msg", resp.text)
        except ValueError:
            code = None
            msg = resp.text

        raise BinanceAPIError(resp.status_code, code, msg, path)


# ---------------------------------------------------------------------------
# Wrappers públicos usados por los fetchers
# ---------------------------------------------------------------------------

def spot_public_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET sin firmar contra api.binance.com (p.ej. /api/v3/exchangeInfo)."""
    return _request("GET", SPOT_BASE_URL, path, params, signed=False)


def spot_signed_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET firmado contra api.binance.com o sapi.binance.com (spot/margin/sapi)."""
    return _request("GET", SPOT_BASE_URL, path, params, signed=True)


def futures_signed_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET firmado contra fapi.binance.com (futuros USDT-M)."""
    return _request("GET", FUTURES_BASE_URL, path, params, signed=True)


def ping() -> bool:
    """Comprueba conectividad básica (sin credenciales) contra la API pública."""
    _request("GET", SPOT_BASE_URL, "/api/v3/ping", signed=False)
    return True


def check_credentials() -> Dict[str, Any]:
    """Valida que las credenciales funcionan devolviendo el estado de la API key."""
    return spot_signed_get("/sapi/v1/account/apiRestrictions")
