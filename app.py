import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np
import time

# --- 1. SYSTEM INTERFACE (CMD/TERMINAL THEME) ---
st.set_page_config(page_title="CONVICTION_ENGINE_V5", layout="wide")

def apply_terminal_css():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@300;400;700&display=swap');
        * { font-family: 'Fira Code', monospace !important; }
        .stApp { background-color: #050505 !important; color: #00FF41 !important; }
        [data-testid="stMetricValue"] { color: #00FF41 !important; font-size: 1.8rem !important; }
        [data-testid="stMetricLabel"] { color: #008F11 !important; }
        .terminal-box { border: 1px solid #008F11; padding: 20px; background-color: #0A0A0A; margin-bottom: 20px; border-radius: 5px; }
        .rejection-box { border: 1px solid #441111; background-color: #1A0505; padding: 15px; margin-bottom: 10px; }
        .stButton>button { background-color: #00FF41 !important; color: #000000 !important; font-weight: 900 !important; border: none !important; width: 100%; height: 3.5em; }
        label { color: #00FF41 !important; }
        </style>
    """, unsafe_allow_html=True)

apply_terminal_css()

# --- 2. DATABASE ---
@st.cache_resource
def init_connection():
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except: return None

supabase = init_connection()

# --- 3. ENGINE LOGIC ---
class QuantEngine:
    def __init__(self):
        # Optimized Universe
        self.universe = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK", "GOTO.JK", 
                         "ADRO.JK", "ITMG.JK", "PTBA.JK", "HRUM.JK", "MDKA.JK", "ANTM.JK", "UNTR.JK"]

    def fetch_all_data(self):
        """Batch download to prevent rate limiting"""
        tickers = self.universe + ["^JKSE"]
        try:
            data = yf.download(tickers, period="100d", interval="1d", progress=False, group_by='ticker')
            return data
        except: return None

    def detect_fvg(self, df):
        if df is None or len(df) < 25: return None
        try:
            # ATR Calc
            tr = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Close'].shift(1)), abs(df['Low'] - df['Close'].shift(1))))
            atr = tr.rolling(14).mean().iloc[-2]
            
            for i in range(2, 8):
                c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
                if float(c1['High']) < float(c3['Low']):
                    displacement = abs(float(c2['Close']) - float(c2['Open']))
                    if displacement > (1.2 * atr):
                        return {
                            "entry": float(c3['Low']), "sl": float(c1['Low']),
                            "tp": float(c3['Low'] + (c3['Low'] - c1['Low']) * 3),
                            "current": float(df['Close'].iloc[-1]),
                            "gap": (float(c1['High']), float(c3['Low'])),
                            "df_slice": df.iloc[-i-15:],
                            "volume_ratio": float(c2['Volume']) / df['Volume'].rolling(20).mean().iloc[-i-1]
                        }
            return None
        except: return None

# --- 4. MAIN APP ---
def main():
    st.write(">> CONVICTION_ENGINE_V5_STABLE_LOADED")
    engine = QuantEngine()
    
    with st.sidebar:
        st.write("--- SYSTEM_PARAMS ---")
        capital = st.number_input("CAPITAL (IDR)", 100_000_000)
        risk_pct = st.slider("RISK_PER_TRADE %", 0.5, 3.0, 1.0)
        st.divider()
        if st.button("RESET_CACHE"): st.cache_data.clear()

    # Pre-fetch data
    with st.spinner(">> ESTABLISHING_MARKET_LINK..."):
        all_data = engine.fetch_all_data()
    
    if all_data is None:
        st.error("CRITICAL_ERROR: YAHOO_FINANCE_RATE_LIMIT. WAIT 5 MINUTES.")
        return

    # IHSG Check
    try:
        ihsg_df = all_data["^JKSE"]
        ihsg_val = ihsg_df['Close'].iloc[-1]
    except: ihsg_val = 0.0

    m1, m2, m3 = st.columns(3)
    m1.metric("IHSG_BENCHMARK", f"{ihsg_val:,.2f}")
    m2.metric("SCAN_NET", f"{len(engine.universe)} Tickers")
    m3.metric("DB_LINK", "ONLINE" if supabase else "OFFLINE")

    if st.button("RUN_QUANT_SCAN [EXECUTE]"):
        signals, watchlist = [], []
        
        for ticker in engine.universe:
            try:
                df = all_data[ticker].dropna()
                if df.empty: continue
                
                # Liquidity Gate
                avg_val = (df['Close'] * df['Volume']).rolling(20).mean().iloc[-1]
                if avg_val < 10_000_000_000: continue
                
                setup = engine.detect_fvg(df)
                if setup:
                    # Alpha Calc
                    ticker_perf = (df['Close'].iloc[-1] / df['Close'].iloc[-20]) - 1
                    ihsg_perf = (ihsg_df['Close'].iloc[-1] / ihsg_df['Close'].iloc[-20]) - 1
                    rs = ticker_perf - ihsg_perf
                    
                    score = 10
                    if rs > 0: score += 5
                    if setup['volume_ratio'] > 1.5: score += 5
                    if setup['current'] <= setup['entry'] * 1.015: score += 10
                    
                    data = {"ticker": ticker, "setup": setup, "score": score, "rs": rs}
                    if score >= 20: signals.append(data)
                    else: watchlist.append(data)
            except: continue

        st.write("--- ANALYSIS_LOG ---")
        if signals:
            best = max(signals, key=lambda x: x['score'])
            s = best['setup']
            expiry = datetime.now() + timedelta(days=3)
            
            st.markdown(f"""<div class="terminal-box">
                <h2 style='color:#00FF41'>[SIGNAL_ACTIVE] {best['ticker']}</h2>
                <p>SCORE: {best['score']}/30 | ALPHA: {best['rs']*100:+.2f}% | EXPIRY: {expiry.strftime('%Y-%m-%d')}</p>
                <hr style='border: 0.5px solid #008F11'>
                <b>JUSTIFICATION:</b><br>
                • Institutional Gap identified at {s['entry']:,.0f}<br>
                • Outperforming IHSG benchmark (RS Alpha positive)<br>
                • Position within optimal retest parameters
            </div>""", unsafe_allow_html=True)
            
            col1, col2 = st.columns([2, 1])
            with col1:
                fig = go.Figure(data=[go.Candlestick(x=s['df_slice'].index, open=s['df_slice']['Open'], high=s['df_slice']['High'], low=s['df_slice']['Low'], close=s['df_slice']['Close'])])
                fig.add_shape(type="rect", x0=s['df_slice'].index[0], x1=s['df_slice'].index[-1], y0=s['gap'][0], y1=s['gap'][1], fillcolor="#00FF41", opacity=0.1, line_width=0)
                fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                st.write(f"ENTRY: {s['entry']:,.0f}")
                st.write(f"STOP:  {s['sl']:,.0f}")
                st.write(f"PROFIT: {s['tp']:,.0f}")
                risk_amt = capital * (risk_pct / 100)
                lots = int((risk_amt / (s['entry'] - s['sl'])) / 100) if (s['entry'] - s['sl']) > 0 else 0
                st.success(f"SIZE: {lots} LOTS")
                
                ch1 = st.checkbox("Confirm Price Action")
                if st.button("LOG_TO_DATABASE"):
                    if ch1 and supabase:
                        log_data = {"ticker": best['ticker'], "entry_price": s['entry'], "stop_loss": s['sl'], "take_profit": s['tp'], "position_size": lots, "status": "ACTIVE", "expiry_date": expiry.isoformat()}
                        supabase.table("trades").insert(log_data).execute()
                        st.success("STATION_LOGGED")
        else:
            st.warning("NO_PICK_DETECTED: MARKET_CONSOLIDATING")

        if watchlist:
            st.write("--- WATCHLIST ---")
            w_cols = st.columns(min(len(watchlist), 4))
            for i, item in enumerate(watchlist[:4]):
                with w_cols[i]:
                    st.markdown(f"""<div class="rejection-box">
                        <b>{item['ticker']}</b><br>Score: {item['score']}/30<br><small>Waiting for zone</small>
                    </div>""", unsafe_allow_html=True)

    # 5. LOGS
    st.divider()
    if supabase:
        try:
            history = supabase.table("trades").select("*").order("date", desc=True).execute().data
            if history:
                st.write("--- SYSTEM_HISTORY_LOG ---")
                st.dataframe(pd.DataFrame(history)[['date', 'ticker', 'entry_price', 'status']], width=1000)
        except: pass

if __name__ == "__main__":
    main()
