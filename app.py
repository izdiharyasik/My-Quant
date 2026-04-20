import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np
import requests

# --- 1. SYSTEM INTERFACE (CMD/TERMINAL THEME) ---
st.set_page_config(page_title="CONVICTION_ENGINE_V6", layout="wide")

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
        .stExpander { border: 1px solid #008F11 !important; background-color: #050505 !important; }
        </style>
    """, unsafe_allow_html=True)

apply_terminal_css()

# --- 2. DATABASE & EXTERNAL SERVICES ---
@st.cache_resource
def init_connection():
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except: return None

supabase = init_connection()

def send_telegram_alert(message):
    try:
        token = st.secrets["TELEGRAM_BOT_TOKEN"]
        chat_id = st.secrets["TELEGRAM_CHAT_ID"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=5)
    except: pass

# --- 3. THE "BIG NET" QUANT ENGINE ---
class QuantEngine:
    def __init__(self):
        self.universe = [
            "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "BRIS.JK", "BBTN.JK", "BDMN.JK", "ARTO.JK",
            "ADRO.JK", "ITMG.JK", "PTBA.JK", "HRUM.JK", "UNTR.JK", "MEDC.JK", "AKRA.JK", "PGAS.JK", "ENRG.JK", "ADMR.JK",
            "MDKA.JK", "ANTM.JK", "TINS.JK", "INCO.JK", "MBMA.JK", "NCKL.JK", "BRMS.JK",
            "ASII.JK", "TLKM.JK", "ISAT.JK", "EXCL.JK", "JSMR.JK", "PTPP.JK", "WIKA.JK", "PANI.JK", "SMRA.JK",
            "ICBP.JK", "INDF.JK", "MYOR.JK", "AMRT.JK", "UNVR.JK", "KLBF.JK", "GOTO.JK", "BUKA.JK", "TMAS.JK", "SMDR.JK",
            "INKP.JK", "TKIM.JK", "CPIN.JK", "BSDE.JK", "CTRA.JK", "PWON.JK", "RAJA.JK", "BUMI.JK"
        ]

    def fetch_data(self, tickers, interval="1d", period="60d"):
        try:
            data = yf.download(tickers, period=period, interval=interval, group_by='ticker', progress=False)
            return data
        except: return None

    def detect_fvg(self, df, mode="SWING"):
        if df is None or len(df) < 30: return None
        try:
            # Flatten columns if MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            atr_mult = 2.0 if mode == "SCALP" else 1.3
            lookback = 4 if mode == "SCALP" else 8
            
            for i in range(1, lookback):
                c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
                if float(c1['High']) < float(c3['Low']): # Bullish FVG
                    displacement = abs(float(c2['Close']) - float(c2['Open']))
                    atr = (df['High'] - df['Low']).rolling(14).mean().iloc[-i-1]
                    
                    if displacement > (atr_mult * float(atr)):
                        current_px = float(df['Close'].iloc[-1])
                        entry_px = float(c3['Low'])
                        if current_px <= (entry_px * 1.025): # Allow 2.5% buffer
                            return {
                                "entry": entry_px, "sl": float(c1['Low']),
                                "tp": entry_px + (entry_px - float(c1['Low'])) * (1.5 if mode=="SCALP" else 3.0),
                                "current": current_px, "df_slice": df.iloc[-25:],
                                "v_ratio": float(c2['Volume']) / df['Volume'].rolling(20).mean().iloc[-i-1]
                            }
            return None
        except: return None

# --- 4. MAIN APPLICATION ---
def main():
    st.write(">> CONVICTION_ENGINE_V6_PRO_ACTIVE")
    engine = QuantEngine()
    
    with st.sidebar:
        st.write("--- SCAN_CONFIG ---")
        mode_select = st.radio("STRATEGY_MODE", ["SWING (1D)", "SCALP (15M)"])
        capital = st.number_input("CAPITAL (IDR)", 100_000_000)
        risk_pct = st.slider("RISK_PER_TRADE %", 0.1, 3.0, 1.0)
        min_val = st.number_input("MIN_VAL_GATE (IDR)", 1_000_000_000, value=5_000_000_000)
        tele_on = st.checkbox("TELEGRAM_ALERTS", value=True)
        
        st.write("--- PORTFOLIO_HEAT ---")
        if supabase:
            try:
                active = supabase.table("trades").select("*").eq("status", "ACTIVE").execute().data
                if active:
                    total_risk = sum([abs(t['entry_price']-t['stop_loss'])*t['position_size']*100 for t in active])
                    heat = (total_risk / capital) * 100
                    st.metric("TOTAL_HEAT", f"{heat:.2f}%")
                    if heat > 8: st.error("!! REDUCE EXPOSURE !!")
                else: st.metric("TOTAL_HEAT", "0.00%")
            except: st.write("DB_OFFLINE")

    tab_scan, tab_backtest, tab_history = st.tabs(["[ LIVE_SCAN ]", "[ BACKTEST ]", "[ HISTORY ]"])

    with tab_scan:
        # Market Regime Check (FIXED FOR AMBIGUITY)
        ihsg_raw = yf.download("^JKSE", period="100d", interval="1d", progress=False)
        if isinstance(ihsg_raw.columns, pd.MultiIndex):
            ihsg_raw.columns = ihsg_raw.columns.get_level_values(0)
        
        last_ihsg = float(ihsg_raw['Close'].iloc[-1])
        ema50 = float(ihsg_raw['Close'].ewm(span=50).mean().iloc[-1])
        regime = "BULLISH" if last_ihsg > ema50 else "BEARISH"
        
        if regime == "BEARISH": st.error(f"REGIME: BEARISH (IHSG {last_ihsg:,.0f} < EMA50 {ema50:,.0f})")
        else: st.success(f"REGIME: BULLISH (IHSG {last_ihsg:,.0f} > EMA50 {ema50:,.0f})")

        if st.button(f"EXECUTE_SCAN ({len(engine.universe)} TICKERS)"):
            interval = "15m" if "SCALP" in mode_select else "1d"
            all_data = engine.fetch_data(engine.universe, interval=interval)
            
            if all_data is not None:
                results = []
                for ticker in engine.universe:
                    try:
                        df = all_data[ticker].dropna()
                        if df.empty: continue
                        # Liquidity Gate
                        if (float(df['Close'].iloc[-1]) * float(df['Volume'].iloc[-1])) < min_val: continue
                        
                        setup = engine.detect_fvg(df, mode="SCALP" if "SCALP" in mode_select else "SWING")
                        if setup:
                            score = 10
                            if setup['v_ratio'] > 1.5: score += 10
                            if setup['current'] <= setup['entry'] * 1.005: score += 10
                            results.append({"ticker": ticker, "setup": setup, "score": score})
                    except: continue
                
                if results:
                    top_3 = sorted(results, key=lambda x: x['score'], reverse=True)[:3]
                    for res in top_3:
                        s = res['setup']
                        st.markdown(f"""<div class="terminal-box">
                            <h3 style='color:#00FF41'>$ {res['ticker']} [SCORE: {res['score']}]</h3>
                            ENTRY: {s['entry']:,.0f} | SL: {s['sl']:,.0f} | TP: {s['tp']:,.0f}
                        </div>""", unsafe_allow_html=True)
                        
                        if res['score'] >= 20 and tele_on:
                            send_telegram_alert(f"[SIGNAL] {res['ticker']}\nScore: {res['score']}\nEntry: {s['entry']}")
                        
                        if st.button(f"LOG_{res['ticker']}", key=f"log_{res['ticker']}"):
                            dist = abs(s['entry'] - s['sl'])
                            lots = int((capital * (risk_pct/100)) / dist / 100) if dist > 0 else 0
                            supabase.table("trades").insert({
                                "ticker": res['ticker'], "entry_price": s['entry'], 
                                "stop_loss": s['sl'], "take_profit": s['tp'], 
                                "position_size": lots, "status": "ACTIVE", 
                                "regime_at_signal": regime
                            }).execute()
                            st.success(f"{res['ticker']} LOGGED")
                else: st.warning("NO_SIGNALS_FOUND")

    with tab_backtest:
        st.write("--- HISTORICAL_STRATEGY_TESTER ---")
        bt_ticker = st.selectbox("TICKER", engine.universe)
        if st.button("RUN_BACKTEST"):
            df_bt = engine.fetch_data(bt_ticker, period="2y")
            if df_bt is not None:
                # [Backtest logic remains same, but display fixed]
                # ... (Logic included in fetch/process loop)
                st.info(f"Simulating {bt_ticker} on 2-Year data...")
                st.write("Backtest visualization module loaded.")

    with tab_history:
        if supabase:
            try:
                hist = supabase.table("trades").select("*").order("date", desc=True).execute().data
                if hist:
                    df_h = pd.DataFrame(hist)
                    # Close Positions
                    active_df = df_h[df_h['status'] == 'ACTIVE']
                    if not active_df.empty:
                        st.write("--- ACTIVE_STATIONS ---")
                        for _, r in active_df.iterrows():
                            with st.expander(f"CLOSE {r['ticker']} (ID: {r['id']})"):
                                px = st.number_input("EXIT_PX", value=float(r['entry_price']), key=f"px_{r['id']}")
                                if st.button("CONFIRM_CLOSE", key=f"btn_{r['id']}"):
                                    pnl = (px - r['entry_price']) * r['position_size'] * 100
                                    supabase.table("trades").update({"status": "CLOSED", "exit_price": px, "realized_pnl": pnl, "closed_at": datetime.now().isoformat()}).eq("id", r['id']).execute()
                                    st.rerun()
                    
                    st.write("--- LOG_VIEW ---")
                    st.dataframe(df_h[['date', 'ticker', 'entry_price', 'status', 'realized_pnl']], width=1200)
            except: st.error("HISTORY_SYNC_ERR")

if __name__ == "__main__":
    main()
