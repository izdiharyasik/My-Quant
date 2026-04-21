import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np

# --- 1. TERMINAL UI SETUP ---
st.set_page_config(page_title="CONVICTION_SWING_V6", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@300;400;700&display=swap');
    * { font-family: 'Fira Code', monospace !important; }
    .stApp { background-color: #050505 !important; color: #00FF41 !important; }
    [data-testid="stMetricValue"] { color: #00FF41 !important; font-size: 1.8rem !important; }
    .terminal-box { border: 1px solid #008F11; padding: 20px; background-color: #0A0A0A; margin-bottom: 20px; border-radius: 5px; }
    .stButton>button { background-color: #00FF41 !important; color: #000000 !important; font-weight: 900 !important; width: 100%; height: 3.5em; border: none !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. DB INITIALIZATION ---
@st.cache_resource
def init_connection():
    try: return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except: return None
supabase = init_connection()

# --- 3. QUANT ENGINE (SWING SPECIALIST) ---
class SwingEngine:
    def __init__(self):
        self.universe = [
            "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK", "GOTO.JK",
            "ADRO.JK", "ITMG.JK", "PTBA.JK", "HRUM.JK", "MEDC.JK", "AKRA.JK", "PGAS.JK",
            "MDKA.JK", "ANTM.JK", "TINS.JK", "INCO.JK", "UNTR.JK", "ICBP.JK", "INDF.JK",
            "AMRT.JK", "UNVR.JK", "KLBF.JK", "BSDE.JK", "CTRA.JK", "CPIN.JK", "ISAT.JK", "PANI.JK"
        ]

    def fetch_market_data(self):
        tickers = self.universe + ["^JKSE"]
        data = yf.download(tickers, period="150d", interval="1d", group_by='ticker', progress=False)
        return data

    def detect_fvg(self, ticker, df):
        if df is None or len(df) < 30: return None
        # Standardize columns
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        # Look back for most recent UNFILLED bullish FVG
        for i in range(2, 10):
            c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
            
            # Pattern: Candle 1 High < Candle 3 Low (Bullish Gap)
            if float(c1['High']) < float(c3['Low']):
                displacement = abs(float(c2['Close']) - float(c2['Open']))
                atr = (df['High'] - df['Low']).rolling(14).mean().iloc[-i-1]
                
                # Must be a large momentum candle
                if displacement > (1.2 * float(atr)):
                    current_px = float(df['Close'].iloc[-1])
                    entry_px = float(c3['Low'])
                    
                    # Entry Logic: Price must be retracing toward or sitting in the gap
                    # If price already fell 2% below the gap, it's "Invalidated/Filled"
                    if current_px >= (float(c1['High']) * 0.98) and current_px <= (entry_px * 1.03):
                        return {
                            "ticker": ticker,
                            "entry": entry_px,
                            "sl": float(c1['Low']),
                            "tp": entry_px + (entry_px - float(c1['Low'])) * 2.5,
                            "gap_top": float(c3['Low']),
                            "gap_bottom": float(c1['High']),
                            "c1_date": df.index[-i-2],
                            "c3_date": df.index[-i],
                            "df_plot": df.iloc[-i-15:] # Data for the chart
                        }
        return None

# --- 4. VISUALIZATION MODULE ---
def plot_fvg_evidence(data):
    df = data['df_plot']
    fig = go.Figure(data=[go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color='#00FF41', decreasing_line_color='#FF3131', name="Price"
    )])

    # Draw the FVG Box
    fig.add_shape(
        type="rect", x0=data['c1_date'], x1=df.index[-1],
        y0=data['gap_bottom'], y1=data['gap_top'],
        fillcolor="rgba(0, 255, 65, 0.2)", line_width=0, name="FVG Zone"
    )

    # Add Labels
    fig.add_annotation(x=data['c1_date'], y=data['gap_bottom'], text="C1 High", showarrow=True, arrowhead=1, font=dict(color="white"))
    fig.add_annotation(x=data['c3_date'], y=data['gap_top'], text="C3 Low (Entry)", showarrow=True, arrowhead=1, font=dict(color="white"))

    fig.update_layout(
        title=f"TECHNICAL EVIDENCE: {data['ticker']} BULLISH FVG",
        template="plotly_dark", xaxis_rangeslider_visible=False,
        height=500, margin=dict(l=10, r=10, t=50, b=10)
    )
    return fig

# --- 5. MAIN APPLICATION ---
def main():
    st.write(f">> SWING_DECISION_ENGINE_V6 | {datetime.now().strftime('%Y-%m-%d %H:%M')} WIB")
    engine = SwingEngine()
    
    # Portfolio Settings
    with st.sidebar:
        st.write("--- RISK_CONFIG ---")
        capital = st.number_input("TOTAL_CAPITAL (IDR)", 100_000_000)
        risk_pct = st.slider("RISK_PER_TRADE %", 0.5, 3.0, 1.0)
        st.write("--- FILTERS ---")
        st.write("MODE: SWING (1D)")
        st.write("MIN_LIQUIDITY: 15B IDR")

    # Fetch Batch Data
    with st.spinner(">> SYNCING_WITH_IDX_EXCHANGE..."):
        all_data = engine.fetch_market_data()
    
    if all_data is None:
        st.error("MARKET_DATA_OFFLINE")
        return

    # Market Regime check (IHSG 50EMA)
    ihsg = all_data["^JKSE"]
    if isinstance(ihsg.columns, pd.MultiIndex): ihsg.columns = ihsg.columns.get_level_values(0)
    last_ihsg = float(ihsg['Close'].iloc[-1])
    ema50 = float(ihsg['Close'].ewm(span=50).mean().iloc[-1])
    regime = "BULLISH" if last_ihsg > ema50 else "BEARISH"

    # Header Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("IHSG_BENCHMARK", f"{last_ihsg:,.0f}", f"{regime}")
    c2.metric("SCAN_UNIVERSE", f"{len(engine.universe)} Tickers")
    c3.metric("DB_STATUS", "SYNCHRONIZED" if supabase else "OFFLINE")

    if st.button("EXECUTE_SWING_SCANNER [ENTER]"):
        candidates = []
        for ticker in engine.universe:
            try:
                df = all_data[ticker].dropna()
                if df.empty: continue
                
                # Liquidity Gate (15B IDR)
                if (float(df['Close'].iloc[-1]) * float(df['Volume'].iloc[-1])) < 15_000_000_000: continue
                
                setup = engine.detect_fvg(ticker, df)
                if setup:
                    # Score based on proximity to entry
                    score = 100 - (abs(float(df['Close'].iloc[-1]) - setup['entry']) / setup['entry'] * 1000)
                    candidates.append({"ticker": ticker, "setup": setup, "score": score})
            except: continue

        if candidates:
            # Pick the single highest conviction trade
            best = max(candidates, key=lambda x: x['score'])
            s = best['setup']
            
            st.markdown(f"""<div class="terminal-box">
                <h2 style='color:#00FF41'>[CONVICTION_SIGNAL] {best['ticker']}</h2>
                <p>STRATEGY: Bullish FVG Retest | REGIME: {regime}</p>
                <hr style='border: 0.5px solid #008F11'>
                <b>EXECUTION:</b><br>
                ENTRY: {s['entry']:,.0f} (C3 Low)<br>
                STOP:  {s['sl']:,.0f} (C1 Low)<br>
                TARGET: {s['tp']:,.0f} (2.5R Ratio)
            </div>""", unsafe_allow_html=True)
            
            # Display Visual Evidence
            st.plotly_chart(plot_fvg_evidence(s), use_container_width=True)
            
            # Sizing & Logging
            risk_amt = capital * (risk_pct / 100)
            lots = int((risk_amt / abs(s['entry'] - s['sl'])) / 100) if abs(s['entry'] - s['sl']) > 0 else 0
            
            st.write(f">> RECOMMENDED_SIZE: {lots} LOTS")
            if st.button("CONFIRM_AND_LOG_TRADE"):
                if supabase:
                    supabase.table("trades").insert({
                        "ticker": best['ticker'], "entry_price": s['entry'], 
                        "stop_loss": s['sl'], "take_profit": s['tp'], 
                        "position_size": lots, "status": "ACTIVE"
                    }).execute()
                    st.success("TRADE_LOGGED_IN_DATABASE")
        else:
            st.warning("NO_HIGH_CONVICTION_SWING_SETUPS_FOUND")

if __name__ == "__main__":
    main()
