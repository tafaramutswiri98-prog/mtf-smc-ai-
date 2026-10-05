
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

st.set_page_config(page_title="MTF SMC AI Trader", page_icon="📈", layout="wide")

# ---------- Strategy engine ----------
def add_swings(df, n=2):
    out = df.copy()
    out["swing_high"] = False
    out["swing_low"] = False
    for i in range(n, len(out)-n):
        h = float(out["High"].iloc[i])
        l = float(out["Low"].iloc[i])
        hs = out["High"].iloc[i-n:i+n+1]
        ls = out["Low"].iloc[i-n:i+n+1]
        if h == hs.max() and (hs == h).sum() == 1:
            out.iloc[i, out.columns.get_loc("swing_high")] = True
        if l == ls.min() and (ls == l).sum() == 1:
            out.iloc[i, out.columns.get_loc("swing_low")] = True
    return out

def market_bias(df):
    s = add_swings(df)
    highs = s.loc[s.swing_high, "High"].tail(2).tolist()
    lows = s.loc[s.swing_low, "Low"].tail(2).tolist()
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL", None
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "BULLISH", {"last_high": highs[-1], "previous_high": highs[-2],
                            "last_low": lows[-1], "previous_low": lows[-2]}
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "BEARISH", {"last_high": highs[-1], "previous_high": highs[-2],
                           "last_low": lows[-1], "previous_low": lows[-2]}
    return "NEUTRAL", None

def liquidity_sweep(df, side):
    s = add_swings(df)
    if side == "BUY":
        levels = s.loc[s.swing_low, "Low"].tolist()
        if not levels: return None
        level = float(levels[-1])
        for i in range(max(0, len(s)-15), len(s)):
            if float(s["Low"].iloc[i]) < level and float(s["Close"].iloc[i]) > level:
                return {"type":"SELL-SIDE", "level":level, "index":i}
    else:
        levels = s.loc[s.swing_high, "High"].tolist()
        if not levels: return None
        level = float(levels[-1])
        for i in range(max(0, len(s)-15), len(s)):
            if float(s["High"].iloc[i]) > level and float(s["Close"].iloc[i]) < level:
                return {"type":"BUY-SIDE", "level":level, "index":i}
    return None

def latest_fvg(df, direction):
    for i in range(len(df)-1, 1, -1):
        c1, c3 = df.iloc[i-2], df.iloc[i]
        if direction == "BUY" and float(c1["High"]) < float(c3["Low"]):
            return {"type":"BULLISH FVG", "low":float(c1["High"]), "high":float(c3["Low"]), "index":i}
        if direction == "SELL" and float(c1["Low"]) > float(c3["High"]):
            return {"type":"BEARISH FVG", "low":float(c3["High"]), "high":float(c1["Low"]), "index":i}
    return None

def mss(df, direction):
    s = add_swings(df)
    if direction == "BUY":
        highs = s.index[s.swing_high].tolist()
        if not highs: return False
        level = float(s.loc[highs[-1], "High"])
        return float(df["Close"].iloc[-1]) > level
    else:
        lows = s.index[s.swing_low].tolist()
        if not lows: return False
        level = float(s.loc[lows[-1], "Low"])
        return float(df["Close"].iloc[-1]) < level

def analyze(df4, df1, df15):
    bias, structure = market_bias(df4)
    result = {"bias":bias, "signal":"NO TRADE", "score":0, "max_score":10,
              "liquidity":None, "fvg":None, "mss":False, "entry":None, "sl":None, "tp":None, "rr":None}
    if bias == "NEUTRAL":
        return result
    direction = "BUY" if bias == "BULLISH" else "SELL"
    result["score"] += 2
    sweep = liquidity_sweep(df1, direction)
    result["liquidity"] = sweep
    if sweep:
        result["score"] += 3
    result["mss"] = mss(df15, direction)
    if result["mss"]:
        result["score"] += 2
    fvg = latest_fvg(df15, direction)
    result["fvg"] = fvg
    if fvg:
        result["score"] += 2
        entry = (fvg["low"] + fvg["high"]) / 2
        if direction == "BUY":
            sl = (sweep["level"] if sweep else fvg["low"]) * 0.999
            risk = entry - sl
            tp = entry + 2.5 * risk
        else:
            sl = (sweep["level"] if sweep else fvg["high"]) * 1.001
            risk = sl - entry
            tp = entry - 2.5 * risk
        if risk > 0:
            result.update(entry=entry, sl=sl, tp=tp, rr=abs(tp-entry)/risk)
    if sweep and result["mss"] and fvg and result["rr"] and result["rr"] >= 2:
        result["signal"] = direction
        result["score"] += 1
    return result

@st.cache_data(ttl=300)
def get_data(symbol, period):
    d = yf.download(symbol, period=period, interval="15m", auto_adjust=False, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d = d.dropna()
    d.index = pd.to_datetime(d.index)
    return d

def resample(df, rule):
    return df.resample(rule).agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()

# ---------- UI ----------
st.title("📈 MTF SMC AI Trader")
st.caption("4H Direction → 1H Liquidity → 15M Confirmation → FVG/SMC Entry")

with st.sidebar:
    st.header("⚙️ Settings")
    symbol = st.selectbox("Market", ["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","NZDUSD=X"])
    period = st.selectbox("Historical data", ["30d","60d","90d"], index=1)
    risk_pct = st.number_input("Risk per trade (%)", 0.1, 5.0, 0.5, 0.1)
    account = st.number_input("Account balance", 10.0, 1000000.0, 100.0, 10.0)
    st.warning("Demo/signal mode only. Live order execution is disabled.")

if st.button("🔄 Analyze Market", type="primary"):
    with st.spinner("Analyzing 4H, 1H and 15M structure..."):
        data = get_data(symbol, period)
        if len(data) < 300:
            st.error("Not enough market data.")
            st.stop()
        d15 = data
        d1 = resample(data, "1h")
        d4 = resample(data, "4h")
        result = analyze(d4, d1, d15)

    st.session_state["result"] = result
    st.session_state["data"] = data

if "result" in st.session_state:
    r = st.session_state["result"]

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("4H Bias", r["bias"])
    c2.metric("Signal", r["signal"])
    c3.metric("Strategy Score", f'{r["score"]}/{r["max_score"]}')
    c4.metric("R:R", f'{r["rr"]:.2f}' if r["rr"] else "—")

    st.divider()
    left, right = st.columns(2)

    with left:
        st.subheader("🔎 Market Structure")
        st.write("**4H direction:**", r["bias"])
        st.write("**1H liquidity sweep:**", "✅ " + r["liquidity"]["type"] if r["liquidity"] else "❌ Not confirmed")
        st.write("**15M MSS:**", "✅ Confirmed" if r["mss"] else "❌ Not confirmed")
        st.write("**15M FVG:**", "✅ " + r["fvg"]["type"] if r["fvg"] else "❌ Not found")

    with right:
        st.subheader("🎯 Trade Plan")
        if r["signal"] != "NO TRADE":
            st.write(f"**Direction:** {r['signal']}")
            st.write(f"**Entry:** `{r['entry']:.5f}`")
            st.write(f"**Stop Loss:** `{r['sl']:.5f}`")
            st.write(f"**Take Profit:** `{r['tp']:.5f}`")
            st.write(f"**Risk:** {risk_pct:.2f}% (${account*risk_pct/100:.2f})")
            st.success("Qualified setup detected. This is a research signal, not a guarantee.")
        else:
            st.info("NO TRADE — one or more mandatory conditions are missing.")

    st.subheader("📊 Recent 15M Price")
    chart = st.session_state["data"][["Open","High","Low","Close"]].tail(150)
    st.line_chart(chart["Close"])

    st.subheader("🧾 Strategy checklist")
    checks = pd.DataFrame({
        "Condition": ["4H bias", "1H liquidity sweep", "15M MSS", "15M FVG", "R:R ≥ 2"],
        "Status": [
            r["bias"] != "NEUTRAL",
            r["liquidity"] is not None,
            r["mss"],
            r["fvg"] is not None,
            r["rr"] is not None and r["rr"] >= 2
        ]
    })
    checks["Status"] = checks["Status"].map({True:"✅ PASS", False:"❌ FAIL"})
    st.dataframe(checks, use_container_width=True, hide_index=True)

st.divider()
st.caption("MTF SMC AI Trader v1 — research prototype. Historical results do not guarantee future performance.")
