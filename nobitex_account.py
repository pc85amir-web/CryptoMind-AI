"""Read-only Nobitex API-Key monitor. No trade, cancel, or withdrawal calls."""
import base64
import os
import time
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE_URL = "https://apiv2.nobitex.ir"


class NobitexAccountError(Exception):
    pass


def _credentials():
    public_key = os.getenv("NOBITEX_API_PUBLIC_KEY", "").strip()
    private_key = os.getenv("NOBITEX_API_PRIVATE_KEY", "").strip()
    if not public_key or not private_key:
        try:
            import streamlit as st
            public_key = public_key or str(st.secrets.get("NOBITEX_API_PUBLIC_KEY", "")).strip()
            private_key = private_key or str(st.secrets.get("NOBITEX_API_PRIVATE_KEY", "")).strip()
        except Exception:
            pass
    return public_key, private_key


def is_configured():
    public_key, private_key = _credentials()
    return bool(public_key and private_key)


def _request(path, params=None):
    public_key, private_key_b64 = _credentials()
    if not public_key or not private_key_b64:
        raise NobitexAccountError(
            "کلید API هنوز در تنظیمات امن Render ثبت نشده است."
        )
    timestamp = str(int(time.time()))
    request = requests.Request("GET", f"{BASE_URL}{path}", params=params or {})
    prepared = request.prepare()
    parsed = urlsplit(prepared.url)
    full_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    payload = f"{timestamp}GET{full_path}".encode("utf-8")
    try:
        key_bytes = base64.urlsafe_b64decode(private_key_b64 + "=" * (-len(private_key_b64) % 4))
        # برخی خروجی‌ها ۶۴ بایت‌اند؛ Ed25519 از ۳۲ بایت seed استفاده می‌کند.
        if len(key_bytes) == 64:
            key_bytes = key_bytes[:32]
        private_key = Ed25519PrivateKey.from_private_bytes(key_bytes)
        signature = base64.urlsafe_b64encode(private_key.sign(payload)).decode("ascii")
    except Exception as exc:
        raise NobitexAccountError("کلید خصوصی API قابل خواندن نیست؛ مقدار آن را بررسی کن.") from exc

    headers = {
        "Nobitex-Key": public_key,
        "Nobitex-Signature": signature,
        "Nobitex-Timestamp": timestamp,
        "Accept": "application/json",
        "User-Agent": "CryptoMindAI/1.0",
    }
    try:
        prepared.headers.update(headers)
        response = requests.Session().send(prepared, timeout=25)
        if response.status_code in (401, 403):
            raise NobitexAccountError("کلید API نامعتبر است یا مجوز READ ندارد.")
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise NobitexAccountError(f"ارتباط با نوبیتکس برقرار نشد: {exc}") from exc
    except ValueError as exc:
        raise NobitexAccountError("پاسخ نوبیتکس قابل خواندن نبود.") from exc
    if data.get("status") not in ("ok", "success"):
        raise NobitexAccountError(data.get("message") or data.get("code") or "نوبیتکس درخواست را نپذیرفت.")
    return data


def get_wallets():
    return _request("/users/wallets/list").get("wallets", [])


def get_open_orders():
    return _request("/market/orders/list", {"status": "open", "details": 2, "order": "-created_at"}).get("orders", [])


def get_recent_orders():
    return _request("/market/orders/list", {"status": "all", "details": 2, "order": "-created_at", "pageSize": 100}).get("orders", [])


def get_recent_trades():
    return _request("/market/trades/list").get("trades", [])

