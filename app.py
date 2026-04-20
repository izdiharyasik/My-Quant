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
        .stApp { background-color: #0D0D0D; color: #00FF41; }
        
        /* Metric Styling */
        [data-testid="stMetricValue"] { color: #00FF41 !important; font-size: 2rem !important; }
        [data-testid="stMetricLabel"] { color: #008F11 !important; }
        
        /* Terminal Boxes */
        .terminal-box {
            border: 1px solid #008F11;
            padding: 20px;
            background-color: #121212;
            box-shadow: 0 0 10px #008F1133;
            margin-bottom: 20px;
        }
        .rejection-box { border-left: 4px solid #FF3131; padding-left: 15px; margin-bottom: 10px; }
        
        /* Buttons */
        .stButton>button {
            background-color: #00FF41 !important;
            color: #0D0D0D !important;
            font-weight: bold;
            border: none;
            width: 100%;
        }
        
        /* Sidebar */
        [data-testid="stSidebar"] { background-color: #050505 !important; border-right: 1px solid #008F11; }
        </style>
    """, unsafe_allow_html=True)

apply_terminal_theme()

# --- 2. DB INITIALIZATION ---
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

# --- 3. QUANT LOGIC ENGINE ---
class QuantEngine:
    def __init__(self):
        # High Cap (>10T) IDX Universe
        self.universe = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK", "BBNI.JK", "UNTR.JK", "ICBP.JK", "ADRO.JK", "GOTO.JK"]
        self.fees = {'buy': 0.0015, 'sell': 0.0025}

    def get_market_data(self, ticker, period="60d"):
        df = yf.download(ticker, period=period, interval="1d", progress=False)
        if df.empty: return None
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
        return df

    def detect_fvg(self, df):
        if len(df) < 20: return None
        # ATR Calculation
        df['tr'] = np.maximum(df['High'] - df['Low'], 
                   np.maximum(abs(df['High'] - df['Close'].shift(1)), 
                   abs(df['Low'] - df['Close'].shift(1))))
        atr = df['tr'].rolling(14).mean().iloc[-2]
        
        for i in range(2, 6):
            c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
            
            # Bullish FVG
            if c1['High'] < c3['Low']:
                displacement = abs(c2['Close'] - c2['Open'])
                vol_spike = c2['Volume'] > df['Volume'].rolling(20).mean().iloc[-i-1]
                
                if displacement > (1.5 * atr) and vol_spike:
                    current_price = df['Close'].iloc[-1]
                    # Reaction check: rejection wick or engulfing
                    reaction = df.iloc[-1]['Low'] <= c3['Low'] and df.iloc[-1]['Close'] > c3['Low']
                    
                    return {
                        "type": "BULLISH",
                        "entry": float(c3['Low']),
                        "sl": float(c1['Low']),
                        "tp": float(c3['Low'] + (c3['Low'] - c1['Low']) * 3),
                        "reaction_confirmed": reaction,
                        "gap_size": (c3['Low'] - c1['High']) / c1['High'],
                        "vol_ratio": c2['Volume'] / df['Volume'].rolling(20).mean().iloc[-i-1],
                        "df_slice": df.iloc[-i-15:]
                    }
        return None

    def score_setup(self, ticker, setup, df):
        score = 0
        justification = []
        rejections = []

        # 1. FVG Quality (0-5)
        q = min(5, setup['gap_size'] * 500)
        score += q
        justification.append(f"FVG Gap Quality: {q:.1f}/5")

        # 2. Volume Spike (0-5)
        v = min(5, setup['vol_ratio'] * 2)
        score += v
        justification.append(f"Institutional Displacement Volume: {v:.1f}/5")

        # 3. Trend Alignment (0-5)
        sma50 = df['Close'].rolling(50).mean().iloc[-1]
        if df['Close'].iloc[-1] > sma50:
            score += 5
            justification.append("HTF Trend Alignment: 5/5 (Above SMA50)")
        else:
            rejections.append("Failed HTF Trend alignment (Price below SMA50)")

        # 4. R:R Ratio
        rr = (setup['tp'] - setup['entry']) / (setup['entry'] - setup['sl'])
        if rr >= 3:
            score += 5
            justification.append(f"Risk/Reward Efficiency: 5/5 ({rr:.1f}R)")
        else:
            rejections.append(f"Poor R:R ratio ({rr:.1f}R)")

        return score, justification, rejections

# --- 4. STREAMLIT FRONTEND ---
def main():
    st.write(">> INITIALIZING CONVICTION_ENGINE_V3...")
    engine = QuantEngine()
    
    with st.sidebar:
        st.write("--- SYSTEM_CONFIG ---")
        capital = st.number_input("TOTAL_CAPITAL (IDR)", 100_000_000)
        risk_pct = st.slider("RISK_PER_TRADE %", 0.5, 5.0, 1.0)
        st.write("--- DB_CONNECTION ---")
        st.success("SUPABASE: CONNECTED")

    # Metrics
    m1, m2, m3 = st.columns(3)
    ihsg_price = engine.get_market_data("^JKSE", "1d")['Close'].iloc[-1]
    m1.metric("BENCHMARK_IHSG", f"{ihsg_price:,.2f}")
    m2.metric("UNIVERSE_COUNT", f"{len(engine.universe)}")
    m3.metric("STRATEGY", "FVG_INSTITUTIONAL")

    if st.button("RUN SCANNER [EXEC]"):
        candidates = []
        rejection_watchlist = []

        for ticker in engine.universe:
            df = engine.get_market_data(ticker)
            setup = engine.detect_fvg(df)
            if setup:
                score, why, why_not = engine.score_setup(ticker, setup, df)
                data = {"ticker": ticker, "setup": setup, "score": score, "justification": why, "rejections": why_not}
                if score >= 15:
                    candidates.append(data)
                else:
                    rejection_watchlist.append(data)

        # 1. TOP PICK LOGIC
        st.write("--- DAILY_CONVICTION_OUTPUT ---")
        if candidates:
            best = max(candidates, key=lambda x: x['score'])
            setup = best['setup']
            
            # Expiry Logic
            expiry_date = datetime.now() + timedelta(days=3)
            
            with st.container():
                st.markdown(f"""<div class="terminal-box">
                    <h2 style='color:#00FF41'>$ {best['ticker']} [SIGNAL_ACTIVE]</h2>
                    <p>CONVICTION_SCORE: {best['score']}/20</p>
                    <p>EXPIRY: {expiry_date.strftime('%Y-%m-%d %H:%M')} (3 Trading Days)</p>
                    <hr style='border-color:#008F11'>
                    <b>WHY THIS TRADE:</b><br>
                    {''.join([f'• {line}<br>' for line in best['justification']])}
                </div>""", unsafe_allow_html=True)
            
            # Trade Details & Position Sizing
            c1, c2 = st.columns(2)
            with c1:
                st.write("--- EXECUTION_DETAILS ---")
                st.write(f"ENTRY_ZONE: {setup['entry']:,.0f}")
                st.write(f"STOP_LOSS:  {setup['sl']:,.0f}")
                st.write(f"TAKE_PROFIT: {setup['tp']:,.0f}")
                
                # Position Sizing
                risk_amt = capital * (risk_pct / 100)
                sl_width = setup['entry'] - setup['sl']
                lots = int((risk_amt / sl_width) / 100) if sl_width > 0 else 0
                st.success(f"SIZE_OUTPUT: {lots} LOTS")
                st.write(f"CAPITAL_DEPLOYED: IDR {lots * 100 * setup['entry']:,.0f}")

            with c2:
                # Execution Checklist
                st.write("--- PRE_TRADE_CHECKLIST ---")
                ch1 = st.checkbox("Price tapped FVG zone?")
                ch2 = st.checkbox("Reaction confirmed (Wick/Engulfing)?")
                ch3 = st.checkbox("R:R is >= 1:3?")
                
                tag = st.selectbox("MISTAKE_TAGGING", ["None", "Early Entry", "Overconfidence", "Ignored Trend"])
                
                if st.button("CONFIRM & LOG TRADE"):
                    if ch1 and ch2 and ch3:
                        log_data = {
                            "ticker": best['ticker'],
                            "entry_price": setup['entry'],
                            "stop_loss": setup['sl'],
                            "take_profit": setup['tp'],
                            "position_size": lots,
                            "expiry_date": expiry_date.isoformat(),
                            "mistake_tag": tag
                        }
                        supabase.table("trades").insert(log_data).execute()
                        st.balloons()
                    else:
                        st.error("ERR: ALL CHECKLIST ITEMS MUST BE VALIDATED")
        else:
            st.markdown("""<div class="terminal-box" style="border-color:#FF3131">
                <h2 style='color:#FF3131'>[!] NO_TRADE_FOUND</h2>
                <p>REASON: No tickers met the minimum conviction threshold (15/20).</p>
                <p>SCAN_STATUS: FINISHED</p>
            </div>""", unsafe_allow_html=True)

        # 2. REJECTION WATCHLIST (Near Misses)
        st.write("--- NEAR_MISS_WATCHLIST ---")
        if rejection_watchlist:
            cols = st.columns(len(rejection_watchlist[:3]))
            for i, item in enumerate(rejection_watchlist[:3]):
                with cols[i]:
                    st.markdown(f"""<div class="terminal-box rejection-box">
                        <b>$ {item['ticker']}</b><br>
                        SCORE: {item['score']}/20<br>
                        <small style='color:#FF3131'>REJECTION_LOG:<br>
                        {''.join([f'• {r}<br>' for r in item['rejections']])}</small>
                    </div>""", unsafe_allow_html=True)

    # 3. PERFORMANCE DASHBOARD
    st.write("--- PERFORMANCE_TRACKER ---")
    t1, t2 = st.tabs(["EQUITY_CURVE", "TRADE_HISTORY"])
    
    with t1:
        # Equity Tracking Logic
        hist_data = supabase.table("trades").select("*").execute().data
        if hist_data:
            df_hist = pd.DataFrame(hist_data)
            st.line_chart(df_hist.set_index('date')['pnl'])
        else:
            st.info("SYSTEM_WAITING: MORE TRADE DATA REQUIRED FOR EQUITY PROJECTION")
            
    with t2:
        history = supabase.table("trades").select("*").order("date", desc=True).execute().data
        if history:
            st.table(pd.DataFrame(history)[['date', 'ticker', 'entry_price', 'status', 'mistake_tag']])

if __name__ == "__main__":
    main()
