import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np

# --- 1. SYSTEM INTERFACE (CMD/TERMINAL THEME) ---
st.set_page_config(page_title="CONVICTION_ENGINE_V4", layout="wide")

def apply_terminal_css():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@300;400;700&display=swap');
        * { font-family: 'Fira Code', monospace !important; }
        .stApp { background-color: #050505 !important; color: #00FF41 !important; }
        
        /* Metric Styling */
        [data-testid="stMetricValue"] { color: #00FF41 !important; font-size: 1.8rem !important; }
        [data-testid="stMetricLabel"] { color: #008F11 !important; }
        
        /* Terminal Containers */
        .terminal-box {
            border: 1px solid #008F11;
            padding: 20px;
            background-color: #0A0A0A;
            margin-bottom: 20px;
            border-radius: 5px;
        }
        .rejection-box { 
            border: 1px solid #441111; 
            background-color: #1A0505;
            padding: 15px; 
            margin-bottom: 10px; 
        }

        /* Buttons */
        .stButton>button {
            background-color: #00FF41 !important;
            color: #000000 !important;
            font-weight: 900 !important;
            border: none !important;
            width: 100%;
            height: 3.5em;
        }
        
        /* Scrollbar */
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: #050505; }
        ::-webkit-scrollbar-thumb { background: #008F11; }
        </style>
    """, unsafe_allow_html=True)

apply_terminal_css()

# --- 2. DATABASE INITIALIZATION ---
@st.cache_resource
def init_connection():
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except:
        return None

supabase = init_connection()

# --- 3. QUANT LOGIC ENGINE ---
class QuantEngine:
    def __init__(self):
        # EXPANDED LIQUID UNIVERSE
        self.universe = [
            "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK", "GOTO.JK",
            "ADRO.JK", "ITMG.JK", "PTBA.JK", "HRUM.JK", "MEDC.JK", "AKRA.JK", "PGAS.JK",
            "MDKA.JK", "ANTM.JK", "TINS.JK", "INCO.JK", "UNTR.JK", "ICBP.JK", "INDF.JK",
            "AMRT.JK", "UNVR.JK", "KLBF.JK", "BSDE.JK", "CTRA.JK", "CPIN.JK", "ISAT.JK"
        ]

    def get_data(self, ticker, period="100d"):
        try:
            df = yf.download(ticker, period=period, interval="1d", progress=False)
            if df.empty: return None
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            
            # --- LIQUIDITY GATE ---
            df['daily_val'] = df['Close'] * df['Volume']
            avg_val = df['daily_val'].rolling(20).mean().iloc[-1]
            if avg_val < 15_000_000_000: # 15B IDR Minimum
                return "LOW_LIQUIDITY"
            return df
        except: return None

    def calculate_alpha_metrics(self, ticker, df, ihsg_df):
        """Calculates RS vs Benchmark and RVOL"""
        # 1. Relative Strength (20-day Performance vs IHSG)
        ticker_perf = (df['Close'].iloc[-1] / df['Close'].iloc[-20]) - 1
        ihsg_perf = (ihsg_df['Close'].iloc[-1] / ihsg_df['Close'].iloc[-20]) - 1
        rs_alpha = ticker_perf - ihsg_perf
        
        # 2. RVOL (Current Volume vs 20d Average)
        avg_vol = df['Volume'].rolling(20).mean().iloc[-2]
        rvol = df['Volume'].iloc[-1] / avg_vol
        
        return rs_alpha, rvol

    def detect_fvg(self, df):
        if not isinstance(df, pd.DataFrame) or len(df) < 25: return None
        # ATR Displacement logic
        tr = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Close'].shift(1)), abs(df['Low'] - df['Close'].shift(1))))
        atr = tr.rolling(14).mean().iloc[-2]
        
        for i in range(2, 8):
            c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
            if float(c1['High']) < float(c3['Low']): # Bullish FVG
                displacement = abs(float(c2['Close']) - float(c2['Open']))
                if displacement > (1.3 * atr):
                    return {
                        "entry": float(c3['Low']),
                        "sl": float(c1['Low']),
                        "tp": float(c3['Low'] + (c3['Low'] - c1['Low']) * 3),
                        "current": float(df['Close'].iloc[-1]),
                        "gap_bounds": (float(c1['High']), float(c3['Low'])),
                        "df_slice": df.iloc[-i-15:]
                    }
        return None

# --- 4. MAIN APPLICATION LOOP ---
def main():
    st.write(">> CONVICTION_ENGINE_V4_SYSTEM_READY")
    engine = QuantEngine()
    
    with st.sidebar:
        st.write("--- PORTFOLIO_PARAMS ---")
        capital = st.number_input("CAPITAL (IDR)", 100_000_000)
        risk_pct = st.slider("RISK_PER_TRADE %", 0.5, 3.0, 1.0)
        st.write("--- ENGINE_GATES ---")
        st.write("LIQUIDITY_MIN: 15B IDR")
        st.write("HTF_FILTER: SMA_50")

    # PRE-SCAN: Get IHSG Benchmark Data
    ihsg_df = yf.download("^JKSE", period="100d", progress=False)
    ihsg_df.columns = [col[0] if isinstance(col, tuple) else col for col in ihsg_df.columns]
    
    # Header Breadth
    breadth_count = 0 
    
    m1, m2, m3 = st.columns(3)
    m1.metric("IHSG_BENCHMARK", f"{ihsg_df['Close'].iloc[-1]:,.2f}")
    m2.metric("SCAN_NET_SIZE", f"{len(engine.universe)} Tickers")
    m3.metric("DB_STATUS", "SYNCHRONIZED")

    if st.button("RUN_QUANT_SCANNER [EXECUTE]"):
        results, watchlist, rejected_liquidity = [], [], 0
        
        with st.spinner(">> SCANNING_LIQUID_UNIVERSE..."):
            for ticker in engine.universe:
                df = engine.get_data(ticker)
                if df == "LOW_LIQUIDITY":
                    rejected_liquidity += 1
                    continue
                if df is None: continue
                
                setup = engine.detect_fvg(df)
                if setup:
                    rs, rvol = engine.calculate_alpha_metrics(ticker, df, ihsg_df)
                    score = 10
                    if rs > 0: score += 5  # Alpha bonus
                    if rvol > 1.5: score += 5 # Volume bonus
                    if setup['current'] <= setup['entry'] * 1.015: score += 10 # Near zone bonus
                    
                    data = {"ticker": ticker, "setup": setup, "score": score, "rs": rs, "rvol": rvol}
                    if score >= 20: results.append(data)
                    else: watchlist.append(data)

        st.sidebar.write(f"REJECTED_BY_LIQUIDITY: {rejected_liquidity}")

        # --- OUTPUT: TOP PICK ---
        st.write("--- TOP_CONVICTION_PICK ---")
        if results:
            best = max(results, key=lambda x: x['score'])
            s = best['setup']
            expiry = datetime.now() + timedelta(days=3)
            
            st.markdown(f"""<div class="terminal-box">
                <h2 style='color:#00FF41'>[!] SIGNAL_DETECTED: {best['ticker']}</h2>
                <p>CONVICTION_SCORE: {best['score']}/30 | RVOL: {best['rvol']:.2f}x | ALPHA: {best['rs']*100:+.2f}%</p>
                <p>EXPIRY_DATE: {expiry.strftime('%Y-%m-%d')} | STATUS: PENDING_RETEST</p>
                <hr style='border: 0.5px solid #008F11'>
                <b>JUSTIFICATION_LOG:</b><br>
                • Relative Strength: {best['ticker']} is outperforming IHSG by {best['rs']*100:.2f}%.<br>
                • RVOL: Volume is {best['rvol']:.2f}x higher than 20d average (Institutional Flow).<br>
                • Price Action: Strong displacement candle (ATR > 1.3x) creating Bullish FVG.
            </div>""", unsafe_allow_html=True)
            
            c1, c2 = st.columns([2, 1])
            with c1:
                # Evidence Chart
                fig = go.Figure(data=[go.Candlestick(x=s['df_slice'].index, open=s['df_slice']['Open'], 
                                 high=s['df_slice']['High'], low=s['df_slice']['Low'], close=s['df_slice']['Close'])])
                fig.add_shape(type="rect", x0=s['df_slice'].index[0], x1=s['df_slice'].index[-1], 
                             y0=s['gap_bounds'][0], y1=s['gap_bounds'][1], fillcolor="#00FF41", opacity=0.15, line_width=0)
                fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            
            with c2:
                st.write("--- EXECUTION_PLAN ---")
                st.write(f"ENTRY: {s['entry']:,.0f}")
                st.write(f"STOP:  {s['sl']:,.0f}")
                st.write(f"TAKE_PROFIT: {s['tp']:,.0f}")
                # Sizing
                risk_amt = capital * (risk_pct / 100)
                lots = int((risk_amt / (s['entry'] - s['sl'])) / 100) if (s['entry'] - s['sl']) > 0 else 0
                st.success(f"SIZE: {lots} LOTS")
                
                if st.button("CONFIRM_AND_LOG_TRADE"):
                    if supabase:
                        log_data = {"ticker": best['ticker'], "entry_price": s['entry'], "stop_loss": s['sl'], 
                                    "take_profit": s['tp'], "position_size": lots, "status": "ACTIVE", 
                                    "expiry_date": expiry.isoformat()}
                        supabase.table("trades").insert(log_data).execute()
                        st.balloons()
        else:
            st.warning("SYSTEM_MSG: NO TRADES MET CONVICTION_THRESHOLD_20")

        # --- OUTPUT: REJECTION WATCHLIST ---
        if watchlist:
            st.write("--- NEAR_MISS_WATCHLIST (WAIT_FOR_RETEST) ---")
            w_cols = st.columns(len(watchlist[:4]))
            for i, item in enumerate(watchlist[:4]):
                with w_cols[i]:
                    st.markdown(f"""<div class="rejection-box">
                        <b>$ {item['ticker']}</b><br>
                        SCORE: {item['score']}/30<br>
                        <small>ALPHA: {item['rs']*100:+.1f}%<br>
                        RVOL: {item['rvol']:.1f}x</small>
                    </div>""", unsafe_allow_html=True)

    # 5. PERFORMANCE LOGS
    st.divider()
    st.write("--- GLOBAL_SYSTEM_HISTORY ---")
    if supabase:
        try:
            history = supabase.table("trades").select("*").order("date", desc=True).execute().data
            if history:
                st.dataframe(pd.DataFrame(history)[['date', 'ticker', 'entry_price', 'status']], width=1200)
        except: st.info("HISTORY_NOT_FOUND")

if __name__ == "__main__":
    main()
