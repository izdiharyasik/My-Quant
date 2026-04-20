import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np

# --- 1. SYSTEM CONFIG & TERMINAL UI ---
st.set_page_config(page_title="CONVICTION_ENGINE_V3", layout="wide")

def apply_terminal_theme():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@300;400;700&display=swap');
        * { font-family: 'Fira Code', monospace !important; }
        .stApp { background-color: #050505 !important; color: #00FF41 !important; }
        
        /* Metric Styling */
        [data-testid="stMetricValue"] { color: #00FF41 !important; font-size: 1.8rem !important; }
        [data-testid="stMetricLabel"] { color: #008F11 !important; }
        
        /* Terminal Boxes */
        .terminal-box {
            border: 1px solid #008F11;
            padding: 20px;
            background-color: #0A0A0A;
            margin-bottom: 20px;
        }
        
        /* Rejection Box */
        .rejection-box { 
            border: 1px solid #441111; 
            background-color: #1A0505;
            padding: 15px; 
            margin-bottom: 10px; 
        }

        /* High Visibility Buttons */
        .stButton>button {
            background-color: #00FF41 !important;
            color: #000000 !important;
            font-weight: 900 !important;
            border: none !important;
            width: 100%;
            height: 3em;
        }
        
        /* Checkbox and Selectbox Labels */
        label { color: #00FF41 !important; }
        </style>
    """, unsafe_allow_html=True)

apply_terminal_theme()

# --- 2. DB INITIALIZATION ---
@st.cache_resource
def init_connection():
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except:
        st.error("DATABASE_OFFLINE: CHECK_SECRETS")
        return None

supabase = init_connection()

# --- 3. QUANT LOGIC ENGINE ---
class QuantEngine:
    def __init__(self):
        # High Cap (>10T) IDX Universe
        self.universe = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK", "BBNI.JK", "UNTR.JK", "ICBP.JK", "ADRO.JK", "GOTO.JK"]

    def get_market_data(self, ticker, period="60d"):
        try:
            df = yf.download(ticker, period=period, interval="1d", progress=False)
            if df.empty: return None
            # Standardize columns (flattens YFinance MultiIndex)
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            return df
        except:
            return None

    def detect_fvg(self, df):
        if df is None or len(df) < 20: return None
        try:
            # ATR Calculation for displacement check
            df['tr'] = np.maximum(df['High'] - df['Low'], 
                       np.maximum(abs(df['High'] - df['Close'].shift(1)), 
                       abs(df['Low'] - df['Close'].shift(1))))
            atr = df['tr'].rolling(14).mean().iloc[-2]
            
            for i in range(2, 7):
                c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
                if float(c1['High']) < float(c3['Low']): # Bullish FVG
                    displacement = abs(float(c2['Close']) - float(c2['Open']))
                    if displacement > (1.2 * atr): # displacement check
                        return {
                            "entry": float(c3['Low']),
                            "sl": float(c1['Low']),
                            "tp": float(c3['Low'] + (c3['Low'] - c1['Low']) * 3),
                            "current": float(df['Close'].iloc[-1]),
                            "gap_size": (c3['Low'] - c1['High']) / c1['High'],
                            "df_slice": df.iloc[-i-15:]
                        }
            return None
        except: return None

# --- 4. STREAMLIT FRONTEND ---
def main():
    st.write(">> CONVICTION_ENGINE_V3_BOOT_SEQUENCE...")
    engine = QuantEngine()
    
    with st.sidebar:
        st.write("--- RISK_MGMT ---")
        capital = st.number_input("PORTFOLIO_CAPITAL", 100_000_000)
        risk_pct = st.slider("RISK_PER_TRADE %", 0.5, 5.0, 1.0)
        st.write("--- DB_STATUS ---")
        if supabase: st.success("SUPABASE: ONLINE")

    # Benchmarking Row (Safety added here)
    m1, m2, m3 = st.columns(3)
    ihsg_df = engine.get_market_data("^JKSE", "5d")
    ihsg_val = ihsg_df['Close'].iloc[-1] if ihsg_df is not None else 0.0
    
    m1.metric("BENCHMARK_IHSG", f"{ihsg_val:,.2f}")
    m2.metric("SCAN_UNIVERSE", f"{len(engine.universe)}")
    m3.metric("STRATEGY", "FVG_INSTITUTIONAL")

    if st.button("RUN_MARKET_SCANNER [ENTER]"):
        candidates = []
        watchlist = []

        with st.spinner(">> SCANNING_IDX_DATA..."):
            for ticker in engine.universe:
                df = engine.get_market_data(ticker)
                setup = engine.detect_fvg(df)
                if setup:
                    setup['ticker'] = ticker
                    # Scoring logic
                    score = 10
                    if setup['current'] <= setup['entry'] * 1.01: score += 10 # Near entry bonus
                    
                    if score >= 15:
                        candidates.append({"ticker": ticker, "setup": setup, "score": score})
                    else:
                        watchlist.append({"ticker": ticker, "setup": setup, "score": score})

        st.write("--- ANALYSIS_OUTPUT ---")
        if candidates:
            best = max(candidates, key=lambda x: x['score'])
            s = best['setup']
            expiry = datetime.now() + timedelta(days=3)
            
            st.markdown(f"""<div class="terminal-box">
                <h2 style='color:#00FF41'>[SIGNAL_ACTIVE] {best['ticker']}</h2>
                <p>CONVICTION_SCORE: {best['score']}/20 | EXPIRY: {expiry.strftime('%Y-%m-%d')}</p>
                <hr style='border: 0.5px solid #008F11'>
                <b>TECHNICAL_JUSTIFICATION:</b><br>
                • Institutional displacement detected (ATR > 1.2x)<br>
                • Clean Bullish Fair Value Gap identified<br>
                • Price within 1% of optimal entry zone
            </div>""", unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"ENTRY: {s['entry']:,.0f} | SL: {s['sl']:,.0f} | TP: {s['tp']:,.0f}")
                # Position Sizing
                risk_amt = capital * (risk_pct / 100)
                lots = int((risk_amt / (s['entry'] - s['sl'])) / 100) if (s['entry'] - s['sl']) > 0 else 0
                st.success(f"SIZE_CALCULATION: {lots} LOTS")
            
            with c2:
                # Logging check
                ch1 = st.checkbox("Confirm Price in FVG Zone")
                ch2 = st.checkbox("Confirm Reaction Candle")
                if st.button("LOG_TRADE_TO_DB"):
                    if ch1 and ch2 and supabase:
                        log_data = {"ticker": best['ticker'], "entry_price": s['entry'], "stop_loss": s['sl'], 
                                    "take_profit": s['tp'], "position_size": lots, "status": "ACTIVE", 
                                    "expiry_date": expiry.isoformat()}
                        supabase.table("trades").insert(log_data).execute()
                        st.balloons()
                    else: st.error("CHECKLIST_INCOMPLETE")
        else:
            st.warning("NO_CONVICTION_PICK_TODAY: CRITERIA_NOT_MET")

        # Watchlist
        if watchlist:
            st.write("--- NEAR_MISS_WATCHLIST ---")
            cols = st.columns(len(watchlist[:3]))
            for i, item in enumerate(watchlist[:3]):
                with cols[i]:
                    st.markdown(f"""<div class="rejection-box">
                        <b>{item['ticker']}</b><br>
                        SCORE: {item['score']}/20<br>
                        <small>REASON: Waiting for Retest</small>
                    </div>""", unsafe_allow_html=True)

    # 5. HISTORY
    st.divider()
    st.write("--- SYSTEM_LOGS ---")
    if supabase:
        try:
            history = supabase.table("trades").select("*").order("date", desc=True).execute().data
            if history:
                st.dataframe(pd.DataFrame(history)[['date', 'ticker', 'entry_price', 'status']])
        except: st.info("NO_HISTORY_FOUND")

if __name__ == "__main__":
    main()
