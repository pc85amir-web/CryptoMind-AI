import pandas as pd
import numpy as np


def calculate_indicators(df):

    if df.empty or len(df) < 30:
        return None

    df = df.copy()

    # Moving Averages
    df["EMA9"] = df["close"].ewm(
        span=9,
        adjust=False
    ).mean()

    df["EMA21"] = df["close"].ewm(
        span=21,
        adjust=False
    ).mean()

    # RSI
    delta = df["close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1/14,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["close"].ewm(
        span=12,
        adjust=False
    ).mean()

    ema26 = df["close"].ewm(
        span=26,
        adjust=False
    ).mean()

    df["MACD"] = ema12 - ema26

    df["MACD_SIGNAL"] = df["MACD"].ewm(
        span=9,
        adjust=False
    ).mean()

    # ATR
    previous_close = df["close"].shift(1)

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs()
    ], axis=1).max(axis=1)

    df["ATR"] = tr.rolling(14).mean()

    # Volume
    df["VOLUME_AVG"] = df["volume"].rolling(20).mean()

    # Support and resistance
    df["SUPPORT"] = df["low"].rolling(20).min()
    df["RESISTANCE"] = df["high"].rolling(20).max()

    return df


def analyze_market(df):

    df = calculate_indicators(df)

    if df is None:
        return None

    last = df.iloc[-1]

    if last.isna().any():
        return None

    long_score = 0
    short_score = 0

    # Trend
    if last["close"] > last["EMA21"]:
        long_score += 1
    else:
        short_score += 1

    if last["EMA9"] > last["EMA21"]:
        long_score += 1
    else:
        short_score += 1

    # RSI
    if 50 < last["RSI"] < 70:
        long_score += 1

    if 30 < last["RSI"] < 50:
        short_score += 1

    # MACD
    if last["MACD"] > last["MACD_SIGNAL"]:
        long_score += 1
    else:
        short_score += 1

    # Volume
    if (
        last["VOLUME_AVG"] > 0
        and last["volume"] > last["VOLUME_AVG"] * 1.1
    ):
        if last["close"] > last["open"]:
            long_score += 1
        elif last["close"] < last["open"]:
            short_score += 1

    price = float(last["close"])
    atr = float(last["ATR"])

    return {
        "price": price,
        "rsi": round(float(last["RSI"]), 2),
        "ema9": round(float(last["EMA9"]), 4),
        "ema21": round(float(last["EMA21"]), 4),
        "support": float(last["SUPPORT"]),
        "resistance": float(last["RESISTANCE"]),
        "atr": atr,
        "long_score": long_score,
        "short_score": short_score,
        "long_stop": price - 1.5 * atr,
        "long_target": price + 2.5 * atr,
        "short_stop": price + 1.5 * atr,
        "short_target": price - 2.5 * atr
    }