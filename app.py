import os
import sqlite3
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from nobitex import get_market_stats, get_candles
from signals import analyze_market
from nobitex_account import (
    NobitexAccountError, is_configured, get_profile, get_wallets, get_open_orders,
    get_recent_orders, get_recent_trades, get_wallet_transactions,
)


# -------------------- تنظیمات پایه --------------------
st.set_page_config(
    page_title="CryptoMind AI",
    page_icon="📊",
    layout="wide",
)

TEHRAN = ZoneInfo("Asia/Tehran")
# در صورت اتصال دیسک دائمی Render، متغیر محیطی زیر را روی
# /var/data/cryptomind_trades.db قرار می‌دهیم.
DB_PATH = os.getenv("CRYPTOMIND_DB_PATH", "cryptomind_trades.db")


def now_text():
    return datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M:%S")


def db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                coin TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                invested_usd REAL NOT NULL,
                stop_loss REAL,
                target1 REAL,
                target2 REAL,
                entry_fee_usd REAL DEFAULT 0,
                entry_time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                exit_price REAL,
                exit_fee_usd REAL DEFAULT 0,
                exit_time TEXT,
                pnl_usd REAL,
                pnl_percent REAL,
                notes TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                wallets_json TEXT NOT NULL,
                open_orders_json TEXT NOT NULL,
                recent_orders_json TEXT NOT NULL,
                recent_trades_json TEXT NOT NULL
            )
        """)
        conn.commit()


def save_account_snapshot(wallets, open_orders, recent_orders, recent_trades):
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO account_snapshots (captured_at, wallets_json, open_orders_json, recent_orders_json, recent_trades_json) VALUES (?, ?, ?, ?, ?)",
            (now_text(), json.dumps(wallets, ensure_ascii=False),
             json.dumps(open_orders, ensure_ascii=False),
             json.dumps(recent_orders, ensure_ascii=False),
             json.dumps(recent_trades, ensure_ascii=False)),
        )
        conn.commit()


def get_account_snapshot_history(limit=20):
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT captured_at FROM account_snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_trades(status=None):
    with db_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status=? ORDER BY id DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC"
            ).fetchall()
    return [dict(row) for row in rows]


def create_trade(signal_row, invested_usd, entry_fee_usd):
    entry = float(signal_row["long_entry"])
    quantity = invested_usd / entry
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO trades (
                symbol, coin, direction, entry_price, quantity,
                invested_usd, stop_loss, target1, target2,
                entry_fee_usd, entry_time, status, notes
            ) VALUES (?, ?, 'LONG', ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
        """, (
            signal_row["symbol"],
            signal_row["coin"],
            entry,
            quantity,
            invested_usd,
            float(signal_row["long_stop"]),
            float(signal_row["long_target1"]),
            float(signal_row["long_target2"]),
            entry_fee_usd,
            now_text(),
            "معامله آزمایشی؛ بدون سفارش واقعی در نوبیتکس",
        ))
        conn.commit()


def close_trade(trade_id, exit_price, exit_fee_usd):
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM trades WHERE id=? AND status='OPEN'",
            (trade_id,),
        ).fetchone()
        if row is None:
            raise ValueError("معامله باز موردنظر پیدا نشد.")

        gross_pnl = (exit_price - row["entry_price"]) * row["quantity"]
        net_pnl = gross_pnl - row["entry_fee_usd"] - exit_fee_usd
        pnl_percent = (
            net_pnl / row["invested_usd"] * 100
            if row["invested_usd"] else 0
        )
        conn.execute("""
            UPDATE trades
            SET status='CLOSED', exit_price=?, exit_fee_usd=?,
                exit_time=?, pnl_usd=?, pnl_percent=?
            WHERE id=?
        """, (
            exit_price,
            exit_fee_usd,
            now_text(),
            net_pnl,
            pnl_percent,
            trade_id,
        ))
        conn.commit()


init_database()


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
    "نسخه فعلی: تحلیل تکنیکال بازار + مرکز نظارت فقط‌خواندنی حساب نوبیتکس. "
    "اتصال اخبار و شبکه اجتماعی X هنوز در مراحل بعدی توسعه است."
)

# -------------------- دریافت بازار و تحلیل --------------------
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
    "تعداد بازارهای مورد بررسی", min_value=5, max_value=30, value=8
)
if st.sidebar.button("🔄 بروزرسانی تحلیل"):
    st.cache_data.clear()


@st.cache_data(ttl=90, show_spinner=False)
def load_markets():
    return get_market_stats()


@st.cache_data(ttl=180, show_spinner=False)
def load_analysis(symbol, timeframe):
    resolution = "D" if timeframe == "W" else timeframe
    candles = get_candles(symbol, resolution, 150)
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
                "volume": "sum",
            })
            .dropna()
            .reset_index()
        )

    return analyze_market(candles), candles


# دریافت فهرست بازار با زمان انتظار محدود؛ صفحه نباید بی‌نهایت منتظر بماند.
try:
    with st.spinner("در حال دریافت فهرست بازار از نوبیتکس..."):
        markets = load_markets()[:limit]
except Exception as error:
    st.error(
        "دریافت فهرست بازار از نوبیتکس ناموفق بود. "
        "ممکن است API نوبیتکس موقتاً کند یا از سرور Render در دسترس نباشد."
    )
    st.code(str(error))
    st.info("۳۰ تا ۶۰ ثانیه بعد روی «بروزرسانی تحلیل» بزن. اگر تکرار شد، بخش Logs در Render را بررسی می‌کنیم.")
    st.stop()

if not markets:
    st.warning("نوبیتکس فهرست بازار خالی برگرداند؛ کمی بعد دوباره تلاش کن.")
    st.stop()

# تحلیل کندل‌ها هم‌زمان انجام می‌شود تا ۲۰ درخواست پشت سر هم صفحه را معطل نکند.
results = []
failed_symbols = []
progress = st.progress(0, text="شروع تحلیل بازارها...")
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {
        executor.submit(
            load_analysis, market["symbol"], timeframes[selected_timeframe]
        ): market
        for market in markets
    }
    completed = 0
    for future in as_completed(futures):
        market = futures[future]
        completed += 1
        try:
            analysis, _ = future.result()
            if analysis:
                results.append({**market, **analysis})
            else:
                failed_symbols.append(market["symbol"])
        except Exception:
            failed_symbols.append(market["symbol"])
        progress.progress(
            completed / len(markets),
            text=f"تحلیل {completed} از {len(markets)} بازار..."
        )
progress.empty()

if failed_symbols:
    st.caption(f"برای {len(failed_symbols)} بازار داده کندلی دریافت نشد؛ بقیه بازارها تحلیل شدند.")

if not results:
    st.warning("در حال حاضر اطلاعات کافی برای تحلیل بازارها دریافت نشد.")
    st.info("تایم‌فریم دیگری انتخاب کن یا کمی بعد دوباره بروزرسانی کن.")
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

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🟢 فرصت‌های خرید",
    "🔴 فرصت‌های نزولی",
    "📈 تحلیل کامل ارز",
    "🧪 آزمایش (اختیاری)",
    "⚙️ تنظیمات",
    "🔐 حساب نوبیتکس",
])


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
    st.caption(
        f"نوع تحلیل: {direction_name} | زمان صدور تحلیل: {row['signal_time']}"
    )
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
    for reason in (reasons or []):
        st.write(f"- {reason}")

    st.caption(
        "تارگت‌ها و حد ضرر بر پایه ATR و تخمینی‌اند. "
        "قیمت ورود، قیمت مبنای آخرین کندل است و اجرای سفارش را تضمین نمی‌کند."
    )
    if not is_long:
        st.warning(
            "این بخش فقط تحلیل نزولی است؛ به معنی امکان بازکردن "
            "موقعیت Short در بازار اسپات نوبیتکس نیست."
        )
    st.divider()


# -------------------- تب خرید --------------------
with tab1:
    st.header("سه فرصت برتر صعودی")
    if long_markets.empty:
        st.warning("در حال حاضر فرصت خرید مناسبی با امتیاز تعیین‌شده پیدا نشد.")
    else:
        for _, row in long_markets.iterrows():
            show_trade_card(row, "long")


# -------------------- تب نزولی --------------------
with tab2:
    st.header("سه فرصت برتر نزولی")
    if short_markets.empty:
        st.warning("در حال حاضر فرصت نزولی مناسبی با امتیاز تعیین‌شده پیدا نشد.")
    else:
        for _, row in short_markets.iterrows():
            show_trade_card(row, "short")


# -------------------- تب تحلیل کامل --------------------
with tab3:
    st.header("تحلیل کامل یک ارز")
    selected_coin = st.selectbox("انتخاب ارز", df["symbol"].tolist())
    market = df[df["symbol"] == selected_coin].iloc[0]
    _, candles = load_analysis(
        selected_coin, timeframes[selected_timeframe]
    )

    if not candles.empty:
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=candles["time"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name="قیمت",
        ))
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


# -------------------- تب معاملات آزمایشی --------------------
with tab4:
    st.header("دفتر ثبت معاملات آزمایشی (اختیاری و جدا از حساب واقعی)")
    st.warning(
        "تمام معاملات این قسمت فرضی هستند. هیچ سفارشی به نوبیتکس ارسال نمی‌شود. "
        "فعلاً فقط معاملات خرید (LONG) قابل ثبت‌اند؛ تحلیل نزولی به معنی "
        "امکان فروش استقراضی در بازار اسپات نیست."
    )

    if long_markets.empty:
        st.info("برای ثبت معامله جدید، ابتدا باید یک سیگنال خرید معتبر در تب خرید وجود داشته باشد.")
    else:
        st.subheader("ثبت معامله آزمایشی جدید")
        signal_options = {
            f"{row['coin']} / {row['quote']} — قیمت مبنا: {row['long_entry']:,.6f} — امتیاز {row['long_score']}/5":
            row["symbol"]
            for _, row in long_markets.iterrows()
        }
        selected_label = st.selectbox(
            "انتخاب سیگنال خرید", list(signal_options.keys())
        )
        selected_symbol = signal_options[selected_label]
        selected_signal = df[df["symbol"] == selected_symbol].iloc[0]

        with st.form("new_paper_trade_form"):
            amount = st.number_input(
                "مبلغ فرضی سرمایه‌گذاری (دلار)",
                min_value=1.0,
                max_value=1000000.0,
                value=20.0,
                step=5.0,
            )
            entry_fee = st.number_input(
                "کارمزد فرضی ورود (دلار)",
                min_value=0.0,
                value=0.0,
                step=0.01,
            )
            st.caption(
                f"قیمت مبنای ورود: {selected_signal['long_entry']:,.6f} | "
                f"حد ضرر: {selected_signal['long_stop']:,.6f} | "
                f"TP1: {selected_signal['long_target1']:,.6f} | "
                f"TP2: {selected_signal['long_target2']:,.6f}"
            )
            create_clicked = st.form_submit_button("➕ ثبت معامله آزمایشی")
        if create_clicked:
            create_trade(selected_signal, float(amount), float(entry_fee))
            st.success("معامله آزمایشی ثبت شد.")
            st.rerun()

    open_trades = get_trades("OPEN")
    st.divider()
    st.subheader("معاملات باز")

    if not open_trades:
        st.info("در حال حاضر معامله بازی ثبت نشده است.")
    else:
        current_prices = {
            row["symbol"]: float(row["price"])
            for _, row in df.iterrows()
        }
        open_display = []
        for trade in open_trades:
            current_price = current_prices.get(trade["symbol"])
            if current_price is not None:
                gross = (current_price - trade["entry_price"]) * trade["quantity"]
                net = gross - trade["entry_fee_usd"]
                pct = net / trade["invested_usd"] * 100
                pnl_label = f"{net:+,.4f} دلار ({pct:+.2f}٪)"
                if current_price <= trade["stop_loss"]:
                    st.error(f"هشدار {trade['coin']}: قیمت فعلی به حد ضرر یا پایین‌تر رسیده است.")
                elif current_price >= trade["target2"]:
                    st.success(f"هشدار {trade['coin']}: قیمت فعلی به تارگت دوم یا بالاتر رسیده است.")
                elif current_price >= trade["target1"]:
                    st.info(f"اطلاع {trade['coin']}: قیمت فعلی به تارگت اول یا بالاتر رسیده است.")
            else:
                current_price = None
                pnl_label = "قیمت فعلی در فهرست بازارهای دریافت‌شده نیست"

            open_display.append({
                "شناسه": trade["id"],
                "ارز": trade["coin"],
                "جفت‌ارز": trade["symbol"],
                "زمان ورود": trade["entry_time"],
                "قیمت ورود": trade["entry_price"],
                "قیمت فعلی": current_price,
                "مبلغ سرمایه‌گذاری ($)": trade["invested_usd"],
                "سود/زیان شناور": pnl_label,
                "حد ضرر": trade["stop_loss"],
                "TP1": trade["target1"],
                "TP2": trade["target2"],
            })
        st.dataframe(pd.DataFrame(open_display), use_container_width=True, hide_index=True)

        st.subheader("بستن معامله آزمایشی")
        open_ids = [trade["id"] for trade in open_trades]
        selected_trade_id = st.selectbox(
            "شناسه معامله‌ای که می‌خواهید ببندید", open_ids
        )
        chosen_trade = next(t for t in open_trades if t["id"] == selected_trade_id)
        current_default = current_prices.get(chosen_trade["symbol"], chosen_trade["entry_price"])
        with st.form("close_paper_trade_form"):
            exit_price = st.number_input(
                "قیمت خروج", min_value=0.00000001,
                value=float(current_default), format="%.8f"
            )
            exit_fee = st.number_input(
                "کارمزد فرضی خروج (دلار)", min_value=0.0,
                value=0.0, step=0.01
            )
            close_clicked = st.form_submit_button("🔒 ثبت خروج و بستن معامله")
        if close_clicked:
            close_trade(
                int(selected_trade_id), float(exit_price), float(exit_fee)
            )
            st.success("معامله بسته شد و سود/زیان آن ذخیره شد.")
            st.rerun()

    # تاریخچه و آمار
    st.divider()
    st.subheader("تاریخچه معاملات بسته‌شده")
    closed_trades = get_trades("CLOSED")
    if closed_trades:
        closed_df = pd.DataFrame([{
            "شناسه": t["id"],
            "ارز": t["coin"],
            "زمان ورود": t["entry_time"],
            "زمان خروج": t["exit_time"],
            "قیمت ورود": t["entry_price"],
            "قیمت خروج": t["exit_price"],
            "مبلغ سرمایه‌گذاری ($)": t["invested_usd"],
            "سود/زیان خالص ($)": t["pnl_usd"],
            "سود/زیان (٪)": t["pnl_percent"],
        } for t in closed_trades])
        st.dataframe(
            closed_df.style.map(
                lambda value: "color: green" if isinstance(value, (int, float)) and value > 0
                else ("color: red" if isinstance(value, (int, float)) and value < 0 else ""),
                subset=["سود/زیان خالص ($)", "سود/زیان (٪)"],
            ),
            use_container_width=True,
            hide_index=True,
        )
        total_pnl = sum(float(t["pnl_usd"] or 0) for t in closed_trades)
        wins = sum(1 for t in closed_trades if (t["pnl_usd"] or 0) > 0)
        win_rate = wins / len(closed_trades) * 100
        m1, m2, m3 = st.columns(3)
        m1.metric("تعداد معاملات بسته‌شده", len(closed_trades))
        m2.metric("مجموع سود/زیان خالص", f"{total_pnl:+,.2f} دلار")
        m3.metric("درصد معاملات سودده", f"{win_rate:.1f}%")
        csv_data = closed_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "⬇️ دریافت فایل تاریخچه معاملات (CSV)",
            data=csv_data,
            file_name="cryptomind_trade_history.csv",
            mime="text/csv",
        )
    else:
        st.info("هنوز معامله بسته‌شده‌ای در تاریخچه وجود ندارد.")



# -------------------- تب نظارت فقط‌خواندنی حساب نوبیتکس --------------------
with tab6:
    st.header("🔐 مرکز نظارت بر حساب نوبیتکس")
    st.info(
        "اتصال این بخش فقط‌خواندنی است: موجودی، سفارش‌ها، معاملات و گردش کیف‌پول را نمایش می‌دهد. "
        "هیچ تابعی برای ثبت سفارش، لغو سفارش یا برداشت وجه در این برنامه وجود ندارد."
    )

    if not is_configured():
        st.warning("هنوز کلید API در Render ثبت نشده است؛ بنابراین اتصال حساب فعال نیست.")
        st.markdown("""
**برای اتصال امن، بعد از ساخت حساب نوبیتکس:**
1. در نوبیتکس یک API Key بساز و فقط مجوز **READ / مشاهده** را فعال کن.
2. اگر امکان محدودکردن IP وجود داشت، IP سرویس را طبق راهنمای Render محدود کن.
3. در Render وارد سرویس `CryptoMind-AI` شو و بخش `Environment` را باز کن.
4. دو متغیر زیر را جداگانه اضافه کن:
   - `NOBITEX_API_PUBLIC_KEY` = کلید عمومی
   - `NOBITEX_API_PRIVATE_KEY` = کلید خصوصی
5. ذخیره کن تا Render نسخه را دوباره راه‌اندازی کند.

**نکته امنیتی:** کلیدها را در GitHub، کد برنامه، پیام یا تصویر برای من نفرست. مجوزهای معامله و برداشت را فعال نکن.
        """)
    else:
        st.success("کلیدهای اتصال پیدا شد. برای دریافت اطلاعات حساب، دکمه زیر را بزن.")
        refresh_account = st.button("🔄 همگام‌سازی اطلاعات حساب", type="primary", key="sync_real_nobitex")
        if refresh_account:
            try:
                with st.spinner("در حال دریافت اطلاعات از نوبیتکس..."):
                    profile = get_profile()
                    wallets = get_wallets()
                    open_orders = get_open_orders()
                    recent_orders = get_recent_orders()
                    recent_trades = get_recent_trades()
                save_account_snapshot(wallets, open_orders, recent_orders, recent_trades)
                st.session_state["nobitex_last_sync"] = {
                    "profile": profile,
                    "wallets": wallets,
                    "open_orders": open_orders,
                    "recent_orders": recent_orders,
                    "recent_trades": recent_trades,
                    "captured_at": now_text(),
                }
                st.success("همگام‌سازی با موفقیت انجام شد و نسخه‌ای از اطلاعات در پایگاه داده برنامه ذخیره شد.")
            except NobitexAccountError as error:
                st.error(str(error))
            except Exception as error:
                st.error(f"خطای غیرمنتظره هنگام همگام‌سازی: {error}")

        account_data = st.session_state.get("nobitex_last_sync")
        if account_data:
            wallets = account_data["wallets"]
            open_orders = account_data["open_orders"]
            recent_orders = account_data["recent_orders"]
            recent_trades = account_data["recent_trades"]
            profile = account_data.get("profile", {})
            st.caption(f"آخرین همگام‌سازی موفق: {account_data['captured_at']} به وقت تهران")
            if profile:
                display_name = " ".join(str(profile.get(k, "")).strip() for k in ("firstName", "lastName")).strip()
                if display_name:
                    st.caption(f"حساب متصل: {display_name}")

            nonzero_wallets = []
            total_rial_value = 0.0
            for wallet in wallets:
                balance = float(wallet.get("balance") or 0)
                blocked = float(wallet.get("blockedBalance") or 0)
                active = float(wallet.get("activeBalance") or max(balance - blocked, 0))
                rial_value = float(wallet.get("rialBalanceSell") or wallet.get("rialBalance") or 0)
                if balance or blocked:
                    nonzero_wallets.append({
                        "ارز": str(wallet.get("currency", "")).upper(),
                        "موجودی کل": balance,
                        "موجودی مسدود": blocked,
                        "موجودی قابل استفاده": active,
                        "ارزش تقریبی به ریال (طبق API)": rial_value,
                    })
                    total_rial_value += rial_value

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("کیف‌پول‌های دارای موجودی", len(nonzero_wallets))
            m2.metric("سفارش‌های باز", len(open_orders))
            m3.metric("سفارش‌های دریافت‌شده", len(recent_orders))
            m4.metric("معاملات اخیر دریافت‌شده", len(recent_trades))
            if total_rial_value:
                st.metric("ارزش تقریبی کل دارایی به تومان", f"{total_rial_value / 10:,.0f}")
                st.caption("ارزش ریالی بر اساس فیلد ارزش دارایی برگشتی از API نوبیتکس است و ممکن است با قیمت قابل اجرای لحظه‌ای تفاوت داشته باشد.")

            st.subheader("💰 موجودی و ارزش دارایی‌ها")
            if nonzero_wallets:
                st.dataframe(pd.DataFrame(nonzero_wallets), use_container_width=True, hide_index=True)
            else:
                st.info("در پاسخ فعلی، کیف‌پول دارای موجودی پیدا نشد.")

            st.subheader("🟠 سفارش‌های باز")
            if open_orders:
                open_df = pd.DataFrame([{
                    "شناسه سفارش": order.get("id"),
                    "بازار": order.get("market") or f"{order.get('srcCurrency', '')} / {order.get('dstCurrency', '')}",
                    "نوع": "خرید" if str(order.get("type", "")).lower() == "buy" else "فروش",
                    "وضعیت": order.get("status"),
                    "قیمت سفارش": order.get("price"),
                    "مقدار سفارش": order.get("amount"),
                    "مقدار انجام‌شده": order.get("matchedAmount"),
                    "مقدار باقی‌مانده": order.get("unmatchedAmount"),
                    "میانگین اجرای فعلی": order.get("averagePrice"),
                    "زمان ثبت": order.get("created_at"),
                } for order in open_orders])
                st.dataframe(open_df, use_container_width=True, hide_index=True)
            else:
                st.success("در حال حاضر سفارش بازی وجود ندارد.")

            st.subheader("📑 تاریخچه سفارش‌ها")
            if recent_orders:
                orders_df = pd.DataFrame([{
                    "شناسه": order.get("id"),
                    "بازار": order.get("market") or f"{order.get('srcCurrency', '')} / {order.get('dstCurrency', '')}",
                    "نوع": "خرید" if str(order.get("type", "")).lower() == "buy" else "فروش",
                    "وضعیت": order.get("status"),
                    "قیمت": order.get("price"),
                    "مقدار": order.get("amount"),
                    "انجام‌شده": order.get("matchedAmount"),
                    "میانگین اجرا": order.get("averagePrice"),
                    "کارمزد": order.get("fee"),
                    "زمان ثبت": order.get("created_at"),
                } for order in recent_orders])
                st.dataframe(orders_df, use_container_width=True, hide_index=True)
                st.download_button(
                    "⬇️ دانلود تاریخچه سفارش‌ها (CSV)",
                    orders_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="nobitex_orders.csv", mime="text/csv",
                )
            else:
                st.info("سفارشی در پاسخ فعلی دریافت نشد.")

            st.subheader("⚡ معاملات اجراشده اخیر")
            if recent_trades:
                trades_df = pd.DataFrame([{
                    "شناسه معامله": trade.get("id"),
                    "شناسه سفارش": trade.get("orderId"),
                    "بازار": trade.get("market"),
                    "نوع": "خرید" if str(trade.get("type", "")).lower() == "buy" else "فروش",
                    "قیمت اجرا": trade.get("price"),
                    "مقدار": trade.get("amount"),
                    "ارزش کل": trade.get("total"),
                    "کارمزد": trade.get("fee"),
                    "زمان اجرا": trade.get("timestamp"),
                } for trade in recent_trades])
                st.dataframe(trades_df, use_container_width=True, hide_index=True)
                st.download_button(
                    "⬇️ دانلود معاملات اجراشده (CSV)",
                    trades_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="nobitex_fills.csv", mime="text/csv",
                )
            else:
                st.info("معامله‌ای در بازه اخیر API دریافت نشد.")

            st.subheader("🧾 گردش کیف‌پول و واریز/برداشت/معامله")
            transaction_wallets = [w for w in wallets if w.get("id") and (float(w.get("balance") or 0) != 0 or float(w.get("blockedBalance") or 0) != 0)]
            if transaction_wallets:
                selected_wallet = st.selectbox(
                    "انتخاب کیف‌پول برای مشاهده گردش",
                    transaction_wallets,
                    format_func=lambda w: f"{str(w.get('currency', '')).upper()} — شناسه {w.get('id')}",
                    key="wallet_transactions_choice",
                )
                if st.button("نمایش گردش این کیف‌پول", key="load_wallet_transactions"):
                    try:
                        with st.spinner("در حال دریافت گردش کیف‌پول..."):
                            tx_data = get_wallet_transactions(selected_wallet["id"], page=1, page_size=50)
                        txs = tx_data.get("transactions", [])
                        st.session_state["nobitex_wallet_transactions"] = txs
                        st.session_state["nobitex_wallet_tx_currency"] = selected_wallet.get("currency", "")
                    except NobitexAccountError as error:
                        st.error(str(error))
                txs = st.session_state.get("nobitex_wallet_transactions", [])
                if txs:
                    tx_df = pd.DataFrame([{
                        "ارز": tx.get("currency"),
                        "مقدار تغییر": tx.get("amount"),
                        "کارمزد": tx.get("calculatedFee"),
                        "شرح": tx.get("description"),
                        "زمان": tx.get("created_at"),
                        "شناسه": tx.get("id"),
                    } for tx in txs])
                    st.dataframe(tx_df, use_container_width=True, hide_index=True)
                elif "nobitex_wallet_transactions" in st.session_state:
                    st.info("گردشی برای این کیف‌پول در صفحه اول پیدا نشد.")
            else:
                st.info("برای کیف‌پول‌های بدون موجودی، گردش را فعلاً از این قسمت انتخاب نمی‌کنیم.")

            st.subheader("🗃️ سوابق همگام‌سازی در این برنامه")
            st.caption("این سوابق فعلاً در SQLite محلی سرویس ذخیره می‌شوند. فضای دیسک Render رایگان ممکن است با راه‌اندازی مجدد یا انتشار نسخه جدید پاک شود؛ برای نگهداری دائمی باید دیسک پایدار یا پایگاه داده بیرونی متصل کنیم.")
            sync_history = get_account_snapshot_history(20)
            if sync_history:
                st.dataframe(pd.DataFrame(sync_history), use_container_width=True, hide_index=True)
            st.warning(
                "محدودیت مهم محاسبه سود/زیان: API معاملات اخیر نوبیتکس به‌صورت پیش‌فرض فقط بازه اخیر (حدود ۳ روز) را برمی‌گرداند. "
                "برای محاسبه سود/زیان واقعی و مادام‌العمر باید تاریخچه کامل از زمان شروع دارایی، واریزها، برداشت‌ها، "
                "انتقال‌ها و کارمزدها جمع‌آوری شود. بنابراین فعلاً عدد سود/زیان کل حساب را حدس نمی‌زنیم و نمایش نمی‌دهیم. "
                "پس از شروع همگام‌سازی منظم، می‌توانیم گزارش دقیق‌تری برای داده‌های ثبت‌شده بسازیم؛ داده‌های قبل از اولین اتصال ممکن است نیاز به دریافت و تطبیق جداگانه داشته باشند."
            )
        else:
            st.info("برای شروع، روی «همگام‌سازی اطلاعات حساب» بزن تا اولین دریافت ثبت شود.")

# -------------------- تب تنظیمات --------------------
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
        "این عدد فعلاً برای راهنمایی مدیریت سرمایه است و به سفارش‌گذاری واقعی متصل نیست."
    )
    st.caption(
        f"مسیر فایل پایگاه داده معاملات: {DB_PATH}. "
        "برای ماندگاری اطلاعات بعد از راه‌اندازی مجدد Render باید دیسک دائمی متصل شود."
    )

st.divider()
st.caption(
    "CryptoMind AI | نسخه آزمایشی | "
    "تحلیل‌ها قطعی نیستند و توصیه مالی یا تضمین سود محسوب نمی‌شوند."
)
