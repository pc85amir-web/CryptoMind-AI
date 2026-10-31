import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo


def calculate_indicators(df):
    """محاسبه شاخص‌های تکنیکال روی داده‌های کندلی."""
    if df is None or df.empty or len(df) < 30:
        return None

    df = df.copy()

    df["EMA9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["EMA21"] = df["close"].ewm(span=21, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()

    previous_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    df["ATR"] = true_range.rolling(14).mean()
    df["VOLUME_AVG"] = df["volume"].rolling(20).mean()
    df["SUPPORT"] = df["low"].rolling(20).min()
    df["RESISTANCE"] = df["high"].rolling(20).max()

    return df


def analyze_market(df):
    """تحلیل تکنیکال و ساخت سطوح ورود، دو هدف و حد ضرر."""
    calculated = calculate_indicators(df)
    if calculated is None:
        return None

    last = calculated.iloc[-1]
    required = [
        "close", "RSI", "EMA9", "EMA21", "MACD",
        "MACD_SIGNAL", "ATR", "SUPPORT", "RESISTANCE",
        "VOLUME_AVG", "volume",
    ]
    if last[required].isna().any():
        return None

    price = float(last["close"])
    atr = float(last["ATR"])
    if price <= 0 or atr <= 0:
        return None

    long_score = 0
    short_score = 0
    long_reasons = []
    short_reasons = []

    # روند قیمت
    if last["close"] > last["EMA21"]:
        long_score += 1
        long_reasons.append("قیمت بالاتر از میانگین متحرک EMA 21 است؛ نشانه‌ای از روند کوتاه‌مدت مثبت.")
    else:
        short_score += 1
        short_reasons.append("قیمت پایین‌تر از میانگین متحرک EMA 21 است؛ نشانه‌ای از ضعف روند.")

    # تقاطع میانگین‌ها
    if last["EMA9"] > last["EMA21"]:
        long_score += 1
        long_reasons.append("EMA 9 بالاتر از EMA 21 قرار دارد؛ مومنتوم کوتاه‌مدت صعودی است.")
    else:
        short_score += 1
        short_reasons.append("EMA 9 پایین‌تر از EMA 21 قرار دارد؛ مومنتوم کوتاه‌مدت نزولی است.")

    # RSI
    rsi = float(last["RSI"])
    if 50 < rsi < 70:
        long_score += 1
        long_reasons.append(f"RSI برابر {rsi:.1f} است و فعلاً در محدوده‌ای سازگار با قدرت خریداران قرار دارد.")
    elif rsi >= 70:
        short_score += 1
        short_reasons.append(f"RSI برابر {rsi:.1f} است؛ احتمال داغ‌شدن بازار و اصلاح قیمت باید بررسی شود.")
    elif 30 < rsi < 50:
        short_score += 1
        short_reasons.append(f"RSI برابر {rsi:.1f} است و ضعف نسبی مومنتوم را نشان می‌دهد.")
    else:
        long_reasons.append(f"RSI برابر {rsi:.1f} است؛ محدوده اشباع فروش می‌تواند نیازمند بررسی برگشت قیمت باشد.")

    # MACD
    if last["MACD"] > last["MACD_SIGNAL"]:
        long_score += 1
        long_reasons.append("خط MACD بالاتر از خط سیگنال است؛ مومنتوم مثبت تأیید می‌شود.")
    else:
        short_score += 1
        short_reasons.append("خط MACD پایین‌تر از خط سیگنال است؛ مومنتوم منفی دیده می‌شود.")

    # حجم معاملات
    volume_avg = float(last["VOLUME_AVG"])
    if volume_avg > 0 and float(last["volume"]) > volume_avg * 1.1:
        if last["close"] > last["open"]:
            long_score += 1
            long_reasons.append("حجم کندل اخیر بیش از ۱۰٪ بالاتر از میانگین و کندل صعودی است.")
        elif last["close"] < last["open"]:
            short_score += 1
            short_reasons.append("حجم کندل اخیر بیش از ۱۰٪ بالاتر از میانگین و کندل نزولی است.")

    # اهداف بر اساس ATR؛ تخمینی‌اند و تضمین برخورد نیستند.
    target1_distance = 1.5 * atr
    target2_distance = 2.5 * atr
    stop_distance = 1.5 * atr

    # زمان صدور سیگنال در منطقه زمانی ایران
    signal_time = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M:%S")

    return {
        "price": price,
        "rsi": round(rsi, 2),
        "ema9": float(last["EMA9"]),
        "ema21": float(last["EMA21"]),
        "support": float(last["SUPPORT"]),
        "resistance": float(last["RESISTANCE"]),
        "atr": atr,
        "long_score": long_score,
        "short_score": short_score,
        "long_reasons": long_reasons,
        "short_reasons": short_reasons,
        "signal_time": signal_time,
        "long_entry": price,
        "long_stop": price - stop_distance,
        "long_target1": price + target1_distance,
        "long_target2": price + target2_distance,
        "short_entry": price,
        "short_stop": price + stop_distance,
        "short_target1": price - target1_distance,
        "short_target2": price - target2_distance,
    }
