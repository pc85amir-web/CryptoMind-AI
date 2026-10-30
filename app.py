import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from nobitex import get_market_stats, get_candles
from signals import analyze_market


st.set_page_config(
    page_title="CryptoMind AI",
    page_icon="📊",
    layout="wide"
)


st.markdown("""
<style>

.main {
    direction: rtl;
}

h1, h2, h3, p {
    text-align: right;
}

.buy {
    color: #00c853;
    font-weight: bold;
}

.sell {
    color: #ff1744;
    font-weight: bold;
}

</style>
""", unsafe_allow_html=True)


st.title("🧠 CryptoMind AI")
st.subheader("دستیار هوشمند تحلیل بازار ارزهای دیجیتال")

st.info(
    "نسخه آزمایشی: اطلاعات عمومی بازار نوبیتکس "
    "و تحلیل تکنیکال خودکار"
)


# Sidebar

st.sidebar.title("تنظیمات")

timeframes = {
    "۵ دقیقه": "5",
    "۱۵ دقیقه": "15",
    "۱ ساعت": "60",
    "۴ ساعت": "240",
    "روزانه": "D",
    "هفتگی": "W"
}

selected_timeframe = st.sidebar.selectbox(
    "انتخاب تایم‌فریم",
    list(timeframes.keys()),
    index=1
)

limit = st.sidebar.slider(
    "تعداد بازارهای مورد بررسی",
    min_value=5,
    max_value=30,
    value=20
)

refresh = st.sidebar.button("🔄 بروزرسانی تحلیل")


if refresh:
    st.cache_data.clear()


@st.cache_data(ttl=120)
def load_markets():
    return get_market_stats()


@st.cache_data(ttl=120)
def load_analysis(symbol, timeframe):

    resolution = timeframe

    # Weekly candles are built from daily candles
    if timeframe == "W":
        resolution = "D"

    candles = get_candles(
        symbol,
        resolution,
        150
    )

    if candles.empty:
        return None, candles

    if timeframe == "W":

        candles = (
            candles.set_index("time")
            .resample("W")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            })
            .dropna()
            .reset_index()
        )

    result = analyze_market(candles)

    return result, candles


# Load markets

try:

    markets = load_markets()

    markets = markets[:limit]

except Exception as error:

    st.error(f"خطا در دریافت اطلاعات نوبیتکس: {error}")
    st.stop()


results = []

progress = st.progress(0)

for index, market in enumerate(markets):

    try:

        analysis, candles = load_analysis(
            market["symbol"],
            timeframes[selected_timeframe]
        )

        if analysis:

            results.append({
                **market,
                **analysis
            })

    except Exception:
        pass

    progress.progress((index + 1) / len(markets))


progress.empty()


if not results:

    st.warning(
        "در حال حاضر اطلاعات کافی برای تحلیل بازارها دریافت نشد."
    )

    st.stop()


df = pd.DataFrame(results)


# LONG and SHORT ranking

long_markets = df[
    df["long_score"] >= 3
].sort_values(
    "long_score",
    ascending=False
).head(3)


short_markets = df[
    df["short_score"] >= 3
].sort_values(
    "short_score",
    ascending=False
).head(3)


# Tabs

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🟢 فرصت‌های خرید",
    "🔴 فرصت‌های نزولی",
    "📈 تحلیل ارز",
    "📋 معاملات آزمایشی",
    "⚙️ تنظیمات"
])


with tab1:

    st.header("سه فرصت برتر صعودی")

    if long_markets.empty:

        st.warning("در حال حاضر فرصت خرید مناسبی پیدا نشد.")

    else:

        for _, row in long_markets.iterrows():

            st.markdown(
                f"### 🟢 {row['coin']} / {row['quote']}"
            )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric("قیمت", f"{row['price']:,.4f}")
            c2.metric("امتیاز خرید", f"{row['long_score']}/5")
            c3.metric("RSI", row["rsi"])
            c4.metric("تغییر روزانه", f"{row['change']}%")

            st.write(
                f"حمایت: {row['support']:,.4f}"
            )

            st.write(
                f"مقاومت: {row['resistance']:,.4f}"
            )

            st.write(
                f"حد ضرر تخمینی: {row['long_stop']:,.4f}"
            )

            st.write(
                f"هدف تخمینی: {row['long_target']:,.4f}"
            )

            st.divider()


with tab2:

    st.header("سه فرصت برتر نزولی")

    if short_markets.empty:

        st.warning("در حال حاضر فرصت نزولی مناسبی پیدا نشد.")

    else:

        for _, row in short_markets.iterrows():

            st.markdown(
                f"### 🔴 {row['coin']} / {row['quote']}"
            )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric("قیمت", f"{row['price']:,.4f}")
            c2.metric("امتیاز نزولی", f"{row['short_score']}/5")
            c3.metric("RSI", row["rsi"])
            c4.metric("تغییر روزانه", f"{row['change']}%")

            st.write(
                f"حمایت: {row['support']:,.4f}"
            )

            st.write(
                f"مقاومت: {row['resistance']:,.4f}"
            )

            st.write(
                f"حد ضرر تخمینی: {row['short_stop']:,.4f}"
            )

            st.write(
                f"هدف تخمینی: {row['short_target']:,.4f}"
            )

            st.warning(
                "این مورد فقط تحلیل نزولی است و به معنی امکان "
                "بازکردن موقعیت Short در نوبیتکس نیست."
            )

            st.divider()


with tab3:

    st.header("تحلیل کامل یک ارز")

    selected_coin = st.selectbox(
        "انتخاب ارز",
        df["symbol"].tolist()
    )

    market = df[
        df["symbol"] == selected_coin
    ].iloc[0]

    candles = get_candles(
        selected_coin,
        timeframes[selected_timeframe],
        150
    )

    if selected_timeframe == "W" and not candles.empty:

        candles = (
            candles.set_index("time")
            .resample("W")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            })
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
                name="Price"
            )
        )

        fig.update_layout(
            title=f"نمودار {selected_coin}",
            xaxis_title="زمان",
            yaxis_title="قیمت",
            height=550,
            xaxis_rangeslider_visible=False
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

    st.write("### اطلاعات تحلیل")

    st.write(f"قیمت فعلی: {market['price']:,.4f}")
    st.write(f"RSI: {market['rsi']}")
    st.write(f"حمایت: {market['support']:,.4f}")
    st.write(f"مقاومت: {market['resistance']:,.4f}")
    st.write(f"EMA 9: {market['ema9']:,.4f}")
    st.write(f"EMA 21: {market['ema21']:,.4f}")


with tab4:

    st.header("معاملات آزمایشی")

    st.info(
        "این بخش در نسخه بعدی به سیستم ثبت معاملات، "
        "محاسبه سود و زیان و تاریخچه معاملات متصل خواهد شد."
    )


with tab5:

    st.header("تنظیمات مدیریت سرمایه")

    capital = st.number_input(
        "سرمایه اولیه (دلار)",
        min_value=10.0,
        value=100.0
    )

    risk = st.number_input(
        "ریسک هر معامله (درصد)",
        min_value=0.1,
        max_value=5.0,
        value=2.0
    )

    st.metric(
        "حداکثر زیان برنامه‌ریزی‌شده هر معامله",
        f"${capital * risk / 100:.2f}"
    )

    st.warning(
        "این تنظیمات فعلاً فقط نمایشی هستند و هنوز "
        "به موتور ثبت معاملات متصل نشده‌اند."
    )


st.divider()

st.caption(
    "CryptoMind AI | نسخه آزمایشی | "
    "این برنامه توصیه مالی یا تضمین سود ارائه نمی‌کند."
)