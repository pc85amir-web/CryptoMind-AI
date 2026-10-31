import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from nobitex import get_market_stats, get_candles
from signals import analyze_market


st.set_page_config(
    page_title="CryptoMind AI",
    page_icon="📊",
    layout="wide",
)

st.markdown(
    """
    <style>
    .main { direction: rtl; }
    h1, h2, h3, p, div { text-align: right; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🧠 CryptoMind AI")
st.subheader("دستیار هوشمند تحلیل بازار ارزهای دیجیتال")
st.info(
    "نسخه توسعه‌یافته آزمایشی: تحلیل تکنیکال، دو تارگت، حد ضرر "
    "و توضیح دلایل سیگنال. این نسخه هنوز اخبار و X را تحلیل نمی‌کند."
)

st.sidebar.title("تنظیمات")
timeframes = {
    "۵ دقیقه": "5",
    "۱۵ دقیقه": "15",
    "۱ ساعت": "60",
    "۴ ساعت": "240",
    "روزانه": "D",
    "هفتگی": "W",
}
selected_timeframe = st.sidebar.selectbox(
    "انتخاب تایم‌فریم", list(timeframes.keys()), index=1
)
limit = st.sidebar.slider(
    "تعداد بازارهای مورد بررسی", min_value=5, max_value=30, value=20
)
if st.sidebar.button("🔄 بروزرسانی تحلیل"):
    st.cache_data.clear()


@st.cache_data(ttl=120)
def load_markets():
    return get_market_stats()


@st.cache_data(ttl=120)
def load_analysis(symbol, timeframe):
    resolution = "D" if timeframe == "W" else timeframe
    candles = get_candles(symbol, resolution, 150)

    if candles.empty:
        return None, candles

    if timeframe == "W":
        candles = (
            candles.set_index("time")
            .resample("W")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
            .reset_index()
        )

    return analyze_market(candles), candles


try:
    markets = load_markets()[:limit]
except Exception as error:
    st.error(f"خطا در دریافت اطلاعات نوبیتکس: {error}")
    st.stop()

if not markets:
    st.warning("بازاری از نوبیتکس دریافت نشد.")
    st.stop()

results = []
progress = st.progress(0)

for index, market in enumerate(markets):
    try:
        analysis, _ = load_analysis(
            market["symbol"], timeframes[selected_timeframe]
        )
        if analysis:
            results.append({**market, **analysis})
    except Exception:
        # خطای یک بازار نباید کل داشبورد را متوقف کند.
        pass
    progress.progress((index + 1) / len(markets))

progress.empty()

if not results:
    st.warning("در حال حاضر اطلاعات کافی برای تحلیل بازارها دریافت نشد.")
    st.stop()

df = pd.DataFrame(results)

long_markets = (
    df[df["long_score"] >= 3]
    .sort_values("long_score", ascending=False)
    .head(3)
)
short_markets = (
    df[df["short_score"] >= 3]
    .sort_values("short_score", ascending=False)
    .head(3)
)

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "🟢 فرصت‌های خرید",
        "🔴 فرصت‌های نزولی",
        "📈 تحلیل کامل ارز",
        "📋 معاملات آزمایشی",
        "⚙️ تنظیمات",
    ]
)


def show_trade_card(row, direction):
    is_long = direction == "long"
    title_color = "🟢" if is_long else "🔴"
    direction_name = "خرید / LONG" if is_long else "تحلیل نزولی / SHORT"
    entry = row["long_entry"] if is_long else row["short_entry"]
    stop = row["long_stop"] if is_long else row["short_stop"]
    target1 = row["long_target1"] if is_long else row["short_target1"]
    target2 = row["long_target2"] if is_long else row["short_target2"]
    score = row["long_score"] if is_long else row["short_score"]
    reasons = row["long_reasons"] if is_long else row["short_reasons"]

    st.markdown(f"### {title_color} {row['coin']} / {row['quote']}")
    st.caption(f"نوع تحلیل: {direction_name} | زمان صدور تحلیل: {row['signal_time']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("قیمت مبنا / ورود تخمینی", f"{entry:,.6f}")
    c2.metric("امتیاز تکنیکال", f"{score} از 5")
    c3.metric("RSI", f"{row['rsi']:.2f}")
    c4.metric("تغییر روزانه", f"{row['change']:.2f}%")

    p1, p2, p3 = st.columns(3)
    p1.metric("🎯 تارگت اول", f"{target1:,.6f}")
    p2.metric("🎯 تارگت دوم", f"{target2:,.6f}")
    p3.metric("🛑 حد ضرر", f"{stop:,.6f}")

    st.write(f"حمایت محاسبه‌شده: {row['support']:,.6f}")
    st.write(f"مقاومت محاسبه‌شده: {row['resistance']:,.6f}")
    st.write("**چرا این ارز انتخاب شده؟**")
    if reasons:
        for reason in reasons:
            st.write(f"- {reason}")
    else:
        st.write("- دلیل تکنیکال کافی برای این جهت ثبت نشده است.")

    st.caption(
        "تارگت‌ها و حد ضرر بر پایه ATR و صرفاً تخمینی هستند. "
        "قیمت ورود نمایش‌داده‌شده قیمت مبنای آخرین کندل دریافتی است، "
        "نه تضمین اجرای سفارش در همان قیمت."
    )
    if not is_long:
        st.warning(
            "این بخش فقط تحلیل نزولی است؛ به معنی امکان بازکردن موقعیت "
            "Short در بازار اسپات نوبیتکس نیست."
        )
    st.divider()


with tab1:
    st.header("سه فرصت برتر صعودی")
    if long_markets.empty:
        st.warning("در حال حاضر فرصت خرید مناسبی با امتیاز تعیین‌شده پیدا نشد.")
    else:
        for _, row in long_markets.iterrows():
            show_trade_card(row, "long")


with tab2:
    st.header("سه فرصت برتر نزولی")
    if short_markets.empty:
        st.warning("در حال حاضر فرصت نزولی مناسبی با امتیاز تعیین‌شده پیدا نشد.")
    else:
        for _, row in short_markets.iterrows():
            show_trade_card(row, "short")


with tab3:
    st.header("تحلیل کامل یک ارز")
    selected_coin = st.selectbox("انتخاب ارز", df["symbol"].tolist())
    market = df[df["symbol"] == selected_coin].iloc[0]
    _, candles = load_analysis(
        selected_coin, timeframes[selected_timeframe]
    )

    if selected_timeframe == "W" and not candles.empty:
        candles = (
            candles.set_index("time")
            .resample("W")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
            .reset_index()
        )

    if not candles.empty:
        fig = go.Figure()
        fig.add_trace(
            go.Candlestick(
                x=candles["time"],
                open=candles["open"],
                high=candles["high"],
                low=candles["low"],
                close=candles["close"],
                name="قیمت",
            )
        )
        fig.update_layout(
            title=f"نمودار {selected_coin}",
            xaxis_title="زمان",
            yaxis_title="قیمت",
            height=550,
            xaxis_rangeslider_visible=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.write(f"قیمت مبنا: {market['price']:,.6f}")
    st.write(f"RSI: {market['rsi']:.2f}")
    st.write(f"EMA 9: {market['ema9']:,.6f}")
    st.write(f"EMA 21: {market['ema21']:,.6f}")
    st.write(f"حمایت: {market['support']:,.6f}")
    st.write(f"مقاومت: {market['resistance']:,.6f}")
    st.write(f"ATR: {market['atr']:,.6f}")
    st.write(f"زمان تحلیل: {market['signal_time']}")


with tab4:
    st.header("معاملات آزمایشی")
    st.info(
        "در این مرحله تارگت‌ها و دلایل سیگنال نمایش داده می‌شوند. "
        "ثبت دائمی معاملات، پایش خودکار برخورد به تارگت‌ها و محاسبه "
        "سود و زیان در مرحله بعد اضافه خواهد شد."
    )


with tab5:
    st.header("تنظیمات مدیریت سرمایه")
    capital = st.number_input(
        "سرمایه اولیه (دلار)", min_value=10.0, value=100.0
    )
    risk = st.number_input(
        "ریسک هر معامله (درصد)",
        min_value=0.1,
        max_value=5.0,
        value=2.0,
    )
    st.metric(
        "حداکثر زیان برنامه‌ریزی‌شده هر معامله",
        f"${capital * risk / 100:.2f}",
    )
    st.warning(
        "این تنظیمات فعلاً محاسبات نمایشی هستند و هنوز به سفارش‌گذاری "
        "یا دفتر ثبت معاملات متصل نشده‌اند."
    )

st.divider()
st.caption(
    "CryptoMind AI | نسخه آزمایشی توسعه‌یافته | "
    "تحلیل‌ها قطعی نیستند و توصیه مالی یا تضمین سود محسوب نمی‌شوند."
)
