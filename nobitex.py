import requests
import pandas as pd
import time

BASE_URL = "https://apiv2.nobitex.ir"


def get_market_stats():

    url = f"{BASE_URL}/market/stats"

    response = requests.get(url, timeout=(4, 8), headers={"User-Agent": "CryptoMindAI/1.0"})
    response.raise_for_status()

    data = response.json()

    if data.get("status") != "ok":
        raise Exception("خطا در دریافت اطلاعات بازار")

    markets = []

    for market, info in data.get("stats", {}).items():

        if "-" not in market:
            continue

        base, quote = market.split("-", 1)

        if quote not in ["rls", "usdt"]:
            continue

        if info.get("isClosed"):
            continue

        symbol = (
            base.upper() + "IRT"
            if quote == "rls"
            else base.upper() + "USDT"
        )

        markets.append({
            "symbol": symbol,
            "coin": base.upper(),
            "quote": quote.upper(),
            "price": float(info.get("latest", 0)),
            "change": float(info.get("dayChange", 0)),
            "volume": float(info.get("volumeSrc", 0)),
            "high": float(info.get("dayHigh", 0)),
            "low": float(info.get("dayLow", 0)),
        })

    return sorted(
        markets,
        key=lambda x: x["volume"],
        reverse=True
    )


def get_candles(symbol, resolution="15", countback=150):

    url = f"{BASE_URL}/market/udf/history"

    params = {
        "symbol": symbol,
        "resolution": resolution,
        "to": int(time.time()),
        "countback": countback
    }

    response = requests.get(
        url,
        params=params,
        timeout=(4, 8),
        headers={"User-Agent": "CryptoMindAI/1.0"}
    )

    response.raise_for_status()

    data = response.json()

    if data.get("s") != "ok":
        return pd.DataFrame()

    df = pd.DataFrame({
        "time": data["t"],
        "open": data["o"],
        "high": data["h"],
        "low": data["l"],
        "close": data["c"],
        "volume": data["v"]
    })

    df["time"] = pd.to_datetime(
        df["time"],
        unit="s",
        utc=True
    )

    return df
