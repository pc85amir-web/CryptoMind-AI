"""Nobitex read-only account client using Ed25519 API-key authentication.

This module intentionally exposes GET-only account methods. It contains no
order placement, cancellation, transfer, or withdrawal implementation.
"""
from __future__ import annotations

import base64
import os
import time
from typing import Any
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE_URL = "https://apiv2.nobitex.ir"
USER_AGENT = "CryptoMindAI/1.1-readonly"


class NobitexAccountError(Exception):
    """A safe, user-displayable account API error."""


def _read_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        import streamlit as st
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


def _credentials() -> tuple[str, str]:
    return (
        _read_secret("NOBITEX_API_PUBLIC_KEY"),
        _read_secret("NOBITEX_API_PRIVATE_KEY"),
    )


def is_configured() -> bool:
    public_key, private_key = _credentials()
    return bool(public_key and private_key)


def _decode_private_key(value: str) -> bytes:
    """Decode URL-safe Base64 Ed25519 private key (32-byte seed or 64 bytes)."""
    cleaned = value.strip().replace("-", "+").replace("_", "/")
    raw = base64.b64decode(cleaned + "=" * (-len(cleaned) % 4), validate=True)
    if len(raw) == 64:
        raw = raw[:32]
    if len(raw) != 32:
        raise ValueError("کلید خصوصی باید پس از رمزگشایی ۳۲ یا ۶۴ بایت باشد.")
    return raw


def _request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    public_key, private_key_text = _credentials()
    if not public_key or not private_key_text:
        raise NobitexAccountError(
            "کلید API تنظیم نشده است. دو متغیر NOBITEX_API_PUBLIC_KEY و "
            "NOBITEX_API_PRIVATE_KEY را در Environment سرویس Render ثبت کن."
        )

    try:
        private_key = Ed25519PrivateKey.from_private_bytes(
            _decode_private_key(private_key_text)
        )
    except Exception as exc:
        raise NobitexAccountError(
            "فرمت کلید خصوصی API درست نیست. مقدار کامل Private Key را بدون فاصله اضافی ثبت کن."
        ) from exc

    request = requests.Request(
        method="GET",
        url=f"{BASE_URL}{path}",
        params=params or {},
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    prepared = request.prepare()
    parsed = urlsplit(prepared.url)
    signed_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    timestamp = str(int(time.time()))
    # Nobitex API-Key signature: timestamp + HTTP method + path/query + body.
    payload = f"{timestamp}GET{signed_path}".encode("utf-8")
    signature = base64.urlsafe_b64encode(private_key.sign(payload)).decode("ascii")
    prepared.headers.update({
        "Nobitex-Key": public_key,
        "Nobitex-Signature": signature,
        "Nobitex-Timestamp": timestamp,
    })

    session = requests.Session()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.send(prepared, timeout=(10, 30))
            if response.status_code in (401, 403):
                raise NobitexAccountError(
                    "احراز هویت ناموفق بود. کلید عمومی/خصوصی و مجوز READ را بررسی کن."
                )
            if response.status_code == 429:
                raise NobitexAccountError(
                    "محدودیت تعداد درخواست نوبیتکس فعال شده؛ کمی صبر کن و دوباره بزن."
                )
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise NobitexAccountError("پاسخ نوبیتکس JSON معتبر نبود.") from exc
            if data.get("status") not in ("ok", "success"):
                message = data.get("message") or data.get("code") or "درخواست پذیرفته نشد."
                raise NobitexAccountError(str(message))
            return data
        except NobitexAccountError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise NobitexAccountError(
        f"ارتباط با API نوبیتکس برقرار نشد: {last_error}"
    )


def get_profile() -> dict[str, Any]:
    return _request("/users/profile").get("profile", {})


def get_wallets() -> list[dict[str, Any]]:
    return _request("/users/wallets/list").get("wallets", [])


def get_wallet_transactions(wallet_id: int | str, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    return _request("/users/wallets/transactions/list", {
        "wallet": wallet_id,
        "page": page,
        "pageSize": page_size,
    })


def get_open_orders() -> list[dict[str, Any]]:
    return _request("/market/orders/list", {
        "status": "open", "details": 2, "order": "-created_at"
    }).get("orders", [])


def get_recent_orders() -> list[dict[str, Any]]:
    return _request("/market/orders/list", {
        "status": "all", "details": 2, "order": "-created_at"
    }).get("orders", [])


def get_recent_trades() -> list[dict[str, Any]]:
    # Nobitex documents this endpoint as returning the user's recent trades
    # (default window: the last three days); it is not a lifetime ledger.
    return _request("/market/trades/list").get("trades", [])
