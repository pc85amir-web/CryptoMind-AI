import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


import streamlit as st
import pandas as pd
import plotly.graph_objects as go


from nobitex import get_market_stats, get_candles
from signals import analyze_market




# -------------------- تنظیمات پایه --------------------
st.set_page_config(
    page_title="CryptoMind AI",
    page_icon="📊",
    layout="wide",
)


TEHRAN = ZoneInfo("Asia/Tehran")
# در صورت اتصال دیسک دائمی Render، متغیر محیطی زیر را روی
