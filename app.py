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
    except Exception as e:
        print(f"Telegram Failed: {e}")

# --- 3. QUANT LOGIC ENGINE ---
class QuantEngine:
    def __init__(self):
        self.universe = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK", "GOTO.JK", 
                         "ADRO.JK", "ITMG.JK", "PTBA.JK", "HRUM.JK", "MDKA.JK", "ANTM.JK", "UNTR.JK", "ISAT.JK"]

    def fetch_batch_data(self, tickers, period="100d"):
        try:
            data = yf.download(tickers, period=period, interval="1d", progress=False, group_by='ticker')
            return data
        except: return None

    def get_regime(self, ihsg_df):
        # IHSG above/below 50 EMA
        ema50 = ihsg_df['Close'].ewm(span=50, adjust=False).mean()
        is_bullish = ihsg_df['Close'].iloc[-1] > ema50.iloc[-1]
        return "BULLISH" if is_bullish else "BEARISH"

    def detect_fvg(self, df):
        if df is None or len(df) < 25: return None
        try:
            tr = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Close'].shift(1)), abs(df['Low'] - df['Close'].shift(1))))
            atr = tr.rolling(14).mean().iloc[-2]
            for i in range(2, 8):
                c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
                if float(c1['High']) < float(c3['Low']):
                    displacement = abs(float(c2['Close']) - float(c2['Open']))
                    if displacement > (1.3 * atr):
                        return {
                            "entry": float(c3['Low']), "sl": float(c1['Low']),
                            "tp": float(c3['Low'] + (c3['Low'] - c1['Low']) * 3), # Fixed 1:3 RR
                            "current": float(df['Close'].iloc[-1]),
                            "gap": (float(c1['High']), float(c3['Low'])),
                            "df_slice": df.iloc[-i-15:],
                            "volume_ratio": float(c2['Volume']) / df['Volume'].rolling(20).mean().iloc[-i-1]
                        }
            return None
        except: return None

    def backtest_ticker(self, ticker):
        df = yf.download(ticker, period="2y", interval="1d", progress=False)
        if df.empty: return None
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
        
        results = []
        equity = [0]
        
        # Simple rolling window backtest
        for i in range(50, len(df)-10):
            window = df.iloc[i-30:i]
            setup = self.detect_fvg(window)
            if setup:
                # Look ahead for outcome
                future = df.iloc[i:i+20] # Max 20 days hold
                trade_result = 0
                for _, row in future.iterrows():
                    if row['Low'] <= setup['sl']:
                        trade_result = -1
                        break
                    if row['High'] >= setup['tp']:
                        trade_result = 3 # 1:3 RR
                        break
                if trade_result != 0:
                    results.append(trade_result)
                    equity.append(equity[-1] + trade_result)
        
        if not results: return None
        
        stats = {
            "win_rate": (len([r for r in results if r > 0]) / len(results)) * 100,
            "avg_rr": np.mean(results),
            "total_trades": len(results),
            "expectancy": np.sum(results) / len(results),
            "equity": equity
        }
        return stats

# --- 4. MAIN APP ---
def main():
    st.write(">> CONVICTION_ENGINE_V6_STABLE_LOADED")
    engine = QuantEngine()
    
    # --- FEATURE 3: PORTFOLIO HEAT METER ---
    active_risk_pct = 0.0
    with st.sidebar:
        st.write("--- SYSTEM_PARAMS ---")
        capital = st.number_input("CAPITAL (IDR)", 100_000_000)
        risk_pct = st.slider("RISK_PER_TRADE %", 0.5, 3.0, 1.0)
        tele_alerts = st.checkbox("ENABLE_TELEGRAM_ALERTS", value=True)
        
        st.write("--- PORTFOLIO_HEAT ---")
        if supabase:
            try:
                active_trades = supabase.table("trades").select("*").eq("status", "ACTIVE").execute().data
                if active_trades:
                    total_risk_idr = 0
                    for t in active_trades:
                        total_risk_idr += abs(t['entry_price'] - t['stop_loss']) * t['position_size'] * 100
                    active_risk_pct = (total_risk_idr / capital) * 100
                    
                    heat_color = "normal"
                    if active_risk_pct >= 8.0: 
                        heat_color = "inverse"
                        st.error("REDUCE EXPOSURE")
                    elif active_risk_pct >= 4.0:
                        st.warning("HEAT LEVEL: ELEVATED")
                    
                    st.metric("TOTAL_HEAT", f"{active_risk_pct:.2f}%", delta_color=heat_color)
                else:
                    st.metric("TOTAL_HEAT", "0.00%")
            except: st.write("HEAT_CALC_OFFLINE")

    tab_scan, tab_backtest, tab_history = st.tabs(["[ LIVE_SCAN ]", "[ BACKTEST_ENGINE ]", "[ SYSTEM_HISTORY ]"])

    with tab_scan:
        all_data = engine.fetch_batch_data(engine.universe + ["^JKSE"])
        if all_data is None:
            st.error("DATA_FETCH_FAILED: RATE_LIMIT_REACHED")
            return

        ihsg_df = all_data["^JKSE"]
        ihsg_df.columns = [col[0] if isinstance(col, tuple) else col for col in ihsg_df.columns]
        
        # --- FEATURE 1: REGIME FILTER ---
        regime = engine.get_regime(ihsg_df)
        if regime == "BEARISH":
            st.error(f"REGIME: BEARISH — SIGNAL CONFIDENCE REDUCED (^JKSE < 50EMA)")
        else:
            st.success(f"REGIME: BULLISH — SCAN ACTIVE (^JKSE > 50EMA)")

        if st.button("RUN_QUANT_SCAN [EXECUTE]"):
            signals, watchlist = [], []
            for ticker in engine.universe:
                try:
                    df = all_data[ticker].dropna()
                    if (df['Close'] * df['Volume']).rolling(20).mean().iloc[-1] < 10_000_000_000: continue
                    
                    setup = engine.detect_fvg(df)
                    if setup:
                        # Alpha Calc
                        ticker_perf = (df['Close'].iloc[-1] / df['Close'].iloc[-20]) - 1
                        ihsg_perf = (ihsg_df['Close'].iloc[-1] / ihsg_df['Close'].iloc[-20]) - 1
                        score = 10
                        if (ticker_perf - ihsg_perf) > 0: score += 5
                        if setup['volume_ratio'] > 1.5: score += 5
                        if setup['current'] <= setup['entry'] * 1.015: score += 10
                        
                        data = {"ticker": ticker, "setup": setup, "score": score}
                        if score >= 20: signals.append(data)
                        else: watchlist.append(data)
                except: continue

            if signals:
                best = max(signals, key=lambda x: x['score'])
                s = best['setup']
                expiry = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
                
                # --- FEATURE 4: TELEGRAM ALERT ---
                if tele_alerts:
                    msg = f"[SIGNAL] {best['ticker']}\nScore: {best['score']}/30\nEntry: {s['entry']:,.0f}\nStop: {s['sl']:,.0f}\nTarget: {s['tp']:,.0f}\nExpiry: {expiry}"
                    send_telegram_alert(msg)

                st.markdown(f"""<div class="terminal-box">
                    <h2 style='color:#00FF41'>[SIGNAL_ACTIVE] {best['ticker']}</h2>
                    <p>SCORE: {best['score']}/30 | REGIME: {regime} | EXPIRY: {expiry}</p>
                    <hr style='border: 0.5px solid #008F11'>
                </div>""", unsafe_allow_html=True)
                
                col1, col2 = st.columns([2, 1])
                with col1:
                    fig = go.Figure(data=[go.Candlestick(x=s['df_slice'].index, open=s['df_slice']['Open'], high=s['df_slice']['High'], low=s['df_slice']['Low'], close=s['df_slice']['Close'])])
                    fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.write(f"ENTRY: {s['entry']:,.0f} | STOP: {s['sl']:,.0f} | TP: {s['tp']:,.0f}")
                    risk_amt = capital * (risk_pct / 100)
                    lots = int((risk_amt / abs(s['entry'] - s['sl'])) / 100)
                    st.success(f"SIZE: {lots} LOTS")
                    
                    if st.button("LOG_TO_DATABASE"):
                        if supabase:
                            supabase.table("trades").insert({
                                "ticker": best['ticker'], "entry_price": s['entry'], "stop_loss": s['sl'], 
                                "take_profit": s['tp'], "position_size": lots, "status": "ACTIVE", 
                                "regime_at_signal": regime
                            }).execute()
                            st.success("STATION_LOGGED")
            else:
                st.warning("NO_PICK_DETECTED")

    with tab_backtest:
        # --- FEATURE 2: BACKTEST ENGINE ---
        st.write("--- HISTORICAL_STRATEGY_SIMULATION ---")
        bt_ticker = st.selectbox("SELECT_TICKER", engine.universe)
        if st.button("RUN_BACKTEST"):
            with st.spinner("PROCESSING_2Y_HISTORY..."):
                stats = engine.backtest_ticker(bt_ticker)
                if stats:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("WIN_RATE", f"{stats['win_rate']:.1f}%")
                    c2.metric("EXPECTANCY (R)", f"{stats['expectancy']:.2f}")
                    c3.metric("AVG_R_PER_TRADE", f"{stats['avg_rr']:.2f}")
                    c4.metric("TOTAL_SIGNALS", stats['total_trades'])
                    
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(y=stats['equity'], mode='lines', line=dict(color='#00FF41')))
                    fig.update_layout(title=f"Cumulative R: {bt_ticker}", template="plotly_dark", height=300)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.error("INSUFFICIENT_DATA_FOR_BACKTEST")

    with tab_history:
        # --- FEATURE 5: CLOSE TRADE + P&L ---
        if supabase:
            try:
                raw_data = supabase.table("trades").select("*").order("date", desc=True).execute().data
                df_hist = pd.DataFrame(raw_data)
                
                if not df_hist.empty:
                    st.write("--- ACTIVE_POSITIONS ---")
                    active_df = df_hist[df_hist['status'] == 'ACTIVE']
                    for _, t in active_df.iterrows():
                        with st.expander(f"CLOSE_{t['ticker']}_ID_{t['id']}"):
                            cx1, cx2, cx3 = st.columns(3)
                            exit_px = cx1.number_input("EXIT_PRICE", value=float(t['entry_price']), key=f"ex_{t['id']}")
                            outcome = cx2.radio("OUTCOME", ["TP_HIT", "SL_HIT", "MANUAL"], key=f"out_{t['id']}")
                            if cx3.button("CONFIRM_CLOSE", key=f"btn_{t['id']}"):
                                pnl = (exit_px - t['entry_price']) * t['position_size'] * 100
                                supabase.table("trades").update({
                                    "status": "CLOSED", "exit_price": exit_px, 
                                    "realized_pnl": pnl, "closed_at": datetime.now().isoformat()
                                }).eq("id", t['id']).execute()
                                st.rerun()

                    st.write("--- SYSTEM_HISTORY_LOG ---")
                    st.dataframe(df_hist[['date', 'ticker', 'entry_price', 'status', 'realized_pnl']], width=1200)
                    
                    closed_df = df_hist[df_hist['status'] == 'CLOSED']
                    if not closed_df.empty:
                        st.write("--- PERFORMANCE_SUMMARY ---")
                        sc1, sc2, sc3 = st.columns(3)
                        sc1.metric("TOTAL_PNL", f"IDR {closed_df['realized_pnl'].sum():,.0f}")
                        win_count = len(closed_df[closed_df['realized_pnl'] > 0])
                        sc2.metric("WIN_RATE", f"{(win_count/len(closed_df))*100:.1f}%")
                        sc3.metric("TRADES", len(closed_df))
            except: st.info("HISTORY_SYNC_FAILED")

if __name__ == "__main__":
    main()
