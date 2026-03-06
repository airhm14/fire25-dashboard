# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
import time
import requests
import xml.etree.ElementTree as ET
from fire25.signals import calculate_puddle_signal
from fire25.backtest import (
    compute_backtest_metrics,
    plot_backtest_results,
    run_backtest,
    run_strategy_backtest,
)
from fire25.strategy import (
    STAGE_DEPLOYMENT_RATES,
    compute_deployment,
    detect_defcon,
    estimate_vol_factor,
    evaluate_smart_shoulder,
)
from fire25.macro_summary import summarize_macro_today
from fire25.data_provider import detect_asset_type, get_market_data
from fire25.fx_provider import get_fx_rate
from fire25.indicator_engine import compute_indicators
from fire25.portfolio_engine import compute_cash, compute_portfolio_value
from fire25.regime_engine import detect_market_regime
from fire25.monte_carlo import (
    calculate_fire_probability,
    compute_monte_carlo_statistics,
    plot_monte_carlo,
    simulate_monte_carlo_with_contributions,
)


def fmt_money(x):
    return f"${x:,.2f}" if x is not None else "N/A"


def fmt_num(x, d=2):
    return f"{x:,.{d}f}" if x is not None else "N/A"


def asset_source_label(symbol: str) -> str:
    asset_type = detect_asset_type(symbol)
    if asset_type == "KR_EQUITY":
        return "KR_EQUITY / PyKRX"
    if asset_type == "CRYPTO":
        return "CRYPTO / Upbit"
    return "US_EQUITY / yfinance"


def build_core_assets(
    qqqm_qty: float,
    schd_qty: float,
    iau_qty: float,
    qqqm_data: dict,
    schd_data: dict,
    iau_data: dict,
) -> dict:
    """Build normalized input payload for portfolio engine."""
    return {
        "QQQM": {"qty": qqqm_qty, "price": qqqm_data["price"], "currency": qqqm_data["currency"]},
        "SCHD": {"qty": schd_qty, "price": schd_data["price"], "currency": schd_data["currency"]},
        "IAU": {"qty": iau_qty, "price": iau_data["price"], "currency": iau_data["currency"]},
    }


# Google Sheets integration imports
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# =====================================================================
# Page setup
# =====================================================================
st.set_page_config(
    page_title="TEAM FIRE 25 Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =====================================================================
# Login gate
# =====================================================================
def check_password():
    """Validate optional dashboard password from Streamlit secrets."""
    
    # If password is not configured in secrets, allow access.
    if "password" not in st.secrets:
        return True
    
    def password_entered():
        """Validate entered password."""
        if st.session_state["password_input"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password_input"]
        else:
            st.session_state["password_correct"] = False
    
    # Already authenticated.
    if st.session_state.get("password_correct", False):
        return True
    
    # Render login prompt.
    st.markdown("""
    <div style="display: flex; justify-content: center; align-items: center; min-height: 60vh;">
        <div style="text-align: center;">
            <h1 style="color: #10b981; margin-bottom: 10px;">TEAM FIRE 25</h1>
            <p style="color: #94a3b8; margin-bottom: 30px;">Enter password to access the dashboard.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input(
            "Password",
            type="password",
            on_change=password_entered,
            key="password_input",
            placeholder="Enter password..."
        )
        
        if "password_correct" in st.session_state and not st.session_state["password_correct"]:
            st.error("Invalid password")
        
        st.markdown("""
        <p style="text-align: center; color: #64748b; font-size: 0.85em; margin-top: 20px;">
            Password is configured via Streamlit Secrets.
        </p>
        """, unsafe_allow_html=True)
    
    return False

# Login check
if not check_password():
    st.stop()

# =====================================================================
# Custom CSS
# =====================================================================
st.markdown("""
<style>
    /* Global background and base text */
    .main { background-color: #0f172a; color: #f1f5f9; }
    
    /* Metric card typography */
    div[data-testid="stMetricValue"] { font-size: 2.5em; font-weight: 700; }
    
    /* Up move = red */
    .positive { color: #ef4444; }
    
    /* Down move = blue */
    .negative { color: #3b82f6; }
    
    /* 寃쎄퀬 諛뺤뒪 */
    .warning-box {
        background-color: rgba(239, 68, 68, 0.1);
        border: 2px solid #ef4444;
        border-radius: 8px;
        padding: 20px;
        margin: 10px 0;
    }
    
    .warning-title {
        font-size: 1.5em;
        font-weight: 700;
        color: #ef4444;
        margin-bottom: 10px;
    }
    
    .info-box {
        background-color: rgba(251, 191, 36, 0.1);
        border: 2px solid #fbbf24;
        border-radius: 8px;
        padding: 20px;
        margin: 10px 0;
    }
    
    .success-box {
        background-color: rgba(16, 185, 129, 0.1);
        border: 2px solid #10b981;
        border-radius: 8px;
        padding: 20px;
        margin: 10px 0;
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
        border-right: 1px solid #334155;
    }
    
    /* Sidebar inner container */
    section[data-testid="stSidebar"] > div {
        background-color: transparent;
    }
    
    /* Sidebar input fields */
    section[data-testid="stSidebar"] input {
        background-color: #334155 !important;
        border: 1px solid #475569 !important;
        color: #e2e8f0 !important;
        transition: all 0.3s ease !important;
    }
    
    section[data-testid="stSidebar"] input:hover {
        background-color: #3f4f63 !important;
        border-color: #64748b !important;
    }
    
    section[data-testid="stSidebar"] input:focus {
        border-color: #10b981 !important;
        box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2) !important;
        background-color: #3f4f63 !important;
    }
    
    /* Sidebar number input controls */
    section[data-testid="stSidebar"] button[kind="icon"] {
        background-color: #475569 !important;
        color: #cbd5e1 !important;
        border-radius: 4px !important;
    }
    
    section[data-testid="stSidebar"] button[kind="icon"]:hover {
        background-color: #10b981 !important;
        color: white !important;
    }
    
    /* Sidebar labels */
    section[data-testid="stSidebar"] label {
        color: #cbd5e1 !important;
        font-weight: 600 !important;
    }
    
    /* Sidebar subheaders */
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] h3 {
        color: #10b981 !important;
        border-bottom: 2px solid #10b981;
        padding-bottom: 8px;
        margin-bottom: 15px;
    }
    
    /* Sidebar buttons */
    section[data-testid="stSidebar"] button {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
        color: white !important;
        border: none !important;
        font-weight: 700 !important;
        transition: all 0.3s ease !important;
    }
    
    section[data-testid="stSidebar"] button:hover {
        background: linear-gradient(135deg, #059669 0%, #047857 100%) !important;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3) !important;
    }
    
    section[data-testid="stSidebar"] button:active {
        transform: translateY(0px);
        box-shadow: 0 2px 6px rgba(16, 185, 129, 0.3) !important;
    }
    
    /* Header typography */
    h1, h2, h3 { 
        color: #10b981; 
        font-family: 'Arial Black', sans-serif; 
        text-shadow: 0 0 10px rgba(16, 185, 129, 0.3);
    }
</style>
""", unsafe_allow_html=True)

# =====================================================================
# Title
# =====================================================================
# Korea time (UTC+9)
kst = timezone(timedelta(hours=9))
current_time_kst = datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S KST')

st.markdown("<h1 style='text-align: center;'>TEAM FIRE 25 전략 통제</h1>", unsafe_allow_html=True)
st.markdown(f"<p style='text-align: center; color: #94a3b8;'>마지막 업데이트: {current_time_kst}</p>", unsafe_allow_html=True)
st.markdown("---")

# =====================================================================
# Google Sheets helpers
# =====================================================================
def get_google_sheets_client():
    """Create a Google Sheets client."""
    try:
        from google.oauth2.service_account import Credentials
        import gspread
        
        # Read service-account credentials from Streamlit secrets.
        if "gcp_service_account" not in st.secrets:
            return None, "Google Sheets 연동 설정이 없습니다."
        
        credentials = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        client = gspread.authorize(credentials)
        return client, None
    except ImportError:
        return None, "gspread 패키지가 설치되어 있지 않습니다."
    except Exception as e:
        return None, f"Google Sheets 연결 실패: {str(e)}"

def load_portfolio_from_sheets():
    """Load the latest portfolio snapshot from Google Sheets."""
    client, error = get_google_sheets_client()
    if error:
        return None, error
    
    try:
        sheet_url = st.secrets.get("spreadsheet_url", "")
        if not sheet_url:
            return None, "스프레드시트 URL이 설정되지 않았습니다."
        
        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet("Portfolio")
        
        # Read all rows and use the latest portfolio row.
        all_data = worksheet.get_all_values()
        if len(all_data) <= 1:
            return None, "저장된 데이터가 없습니다."
        
        last_row = all_data[-1]
        # Header: Date, QQQM, SCHD, IAU, SGOV, Cash, NewCash, TotalValue
        
        return {
            'date': last_row[0],
            'qqqm_qty': float(last_row[1]) if last_row[1] else 0,
            'schd_qty': float(last_row[2]) if last_row[2] else 0,
            'iau_qty': float(last_row[3]) if last_row[3] else 0,
            'sgov_qty': float(last_row[4]) if last_row[4] else 0,
            'cash_deposit': float(last_row[5]) if last_row[5] else 0,
            'new_cash': float(last_row[6]) if last_row[6] else 0,
            'total_value': float(last_row[7]) if last_row[7] else 0
        }, None
    except Exception as e:
        error_msg = str(e)
        if "WorksheetNotFound" in error_msg or "worksheet" in error_msg.lower():
            return None, "Portfolio worksheet not found. Click Save once to create it."
        return None, f"Failed to load data: {error_msg}"

def save_portfolio_to_sheets(qqqm, schd, iau, sgov, cash, new_cash, total_value):
    """Save portfolio data to Google Sheets."""
    client, error = get_google_sheets_client()
    if error:
        return False, error
    
    try:
        sheet_url = st.secrets.get("spreadsheet_url", "")
        if not sheet_url:
            return False, "Spreadsheet URL is not configured."
        
        spreadsheet = client.open_by_url(sheet_url)
        
        # Load portfolio worksheet (create it if missing).
        try:
            worksheet = spreadsheet.worksheet("Portfolio")
        except Exception:
            worksheet = spreadsheet.add_worksheet(title="Portfolio", rows=1000, cols=10)
            # Add header row.
            worksheet.append_row(["Date", "QQQM", "SCHD", "IAU", "SGOV", "Cash", "NewCash", "TotalValue"])
        
        # Current date/time (KST).
        import pytz
        kst = pytz.timezone('Asia/Seoul')
        now = datetime.now(kst).strftime("%Y-%m-%d %H:%M")
        
        # Append one record.
        worksheet.append_row([now, qqqm, schd, iau, sgov, cash, new_cash, round(total_value, 2)])
        
        return True, "Saved successfully."
    except Exception as e:
        return False, f"Save failed: {str(e)}"

def get_portfolio_history():
    """Load portfolio history rows from Google Sheets."""
    client, error = get_google_sheets_client()
    if error:
        return None, error
    
    try:
        sheet_url = st.secrets.get("spreadsheet_url", "")
        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet("Portfolio")
        
        all_data = worksheet.get_all_values()
        if len(all_data) <= 1:
            return None, "No history data found."
        
        # Convert rows into a DataFrame.
        headers = all_data[0]
        data = all_data[1:]
        
        history_df = pd.DataFrame(data, columns=headers)
        history_df['TotalValue'] = pd.to_numeric(history_df['TotalValue'], errors='coerce')
        history_df['Date'] = pd.to_datetime(history_df['Date'], format='%Y-%m-%d %H:%M', errors='coerce')
        
        return history_df, None
    except Exception as e:
        return None, f"Failed to load history: {str(e)}"

# Check Google Sheets connection state
gs_available = "gcp_service_account" in st.secrets if hasattr(st, 'secrets') else False

# =====================================================================
# Sidebar: portfolio inputs
# =====================================================================
portfolio_mode = "Personal Mode"
is_personal_mode = True
sheets_saved_data = None

with st.sidebar:
    st.header("📊 포트폴리오 설정")

    portfolio_mode = st.radio(
        "포트폴리오 모드",
        ["Personal Mode", "Public Mode"],
        index=0,
        help="Personal: Google Sheets 연동 / Public: 저장 없이 데모용",
    )
    is_personal_mode = portfolio_mode == "Personal Mode"
    
    # Show Google Sheets status
    if is_personal_mode:
        if gs_available:
            sheets_saved_data, load_error = load_portfolio_from_sheets()
            if load_error and "저장된 데이터가 없습니다." not in load_error:
                st.warning(f"⚠️ {load_error}")
            elif sheets_saved_data:
                st.success(f"🟢 마지막 저장: {sheets_saved_data['date']}")
            else:
                st.info("☁️ Google Sheets connected")
        else:
            st.info("☁️ Google Sheets not connected")
    else:
        st.warning("📢 Public Mode: 개인 히스토리 저장/조회가 비활성화됩니다.")
    
    st.subheader("보유 주식")
    
    # Personal mode: use saved values first. Public mode: use demo defaults.
    if is_personal_mode:
        default_qqqm = sheets_saved_data['qqqm_qty'] if sheets_saved_data else 100.0
        default_schd = sheets_saved_data['schd_qty'] if sheets_saved_data else 50.0
        default_iau = sheets_saved_data['iau_qty'] if sheets_saved_data else 20.0
        default_sgov = sheets_saved_data['sgov_qty'] if sheets_saved_data else 30.0
        default_cash = sheets_saved_data['cash_deposit'] if sheets_saved_data else 2000.0
        default_new = 0.0
    else:
        default_qqqm = 0.0
        default_schd = 0.0
        default_iau = 0.0
        default_sgov = 0.0
        default_cash = 10000.0
        default_new = 0.0
    
    qqqm_qty = st.number_input("QQQM 수량", min_value=0.0, value=default_qqqm, step=1.0, format="%.2f")
    schd_qty = st.number_input("SCHD 수량", min_value=0.0, value=default_schd, step=1.0, format="%.2f")
    iau_qty = st.number_input("IAU 수량", min_value=0.0, value=default_iau, step=1.0, format="%.2f")
    sgov_qty = st.number_input("SGOV 수량", min_value=0.0, value=default_sgov, step=1.0, format="%.2f",
                                help="단기국채 ETF (SGOV) 보유 수량")
    
    st.subheader("💵 예수금")
    cash_deposit = st.number_input("예수금 (USD)", min_value=0.0, value=default_cash, step=100.0, format="%.2f",
                                    help="증권계좌 현금 (바로 투자 가능한 자금)")
    
    st.markdown("---")
    st.subheader("💰 신규 자금")
    new_cash = st.number_input("월급/추가 입금 (USD)", min_value=0.0, value=default_new, step=100.0, format="%.2f",
                                help="이번 달 투입할 신규 자금 (월급, 보너스 등)")
    backtest_enabled = st.toggle("Backtest (experimental)", value=False)
    backtest_vol_adjust = st.toggle("Vol-adjusted sizing", value=False, disabled=not backtest_enabled)
    
    st.markdown("---")
    st.markdown(
        """
    <div style="
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(147, 51, 234, 0.1) 100%);
        border: 2px solid #3b82f6;
        border-radius: 12px;
        padding: 15px;
        margin: 10px 0;
    ">
        <h3 style="color: #3b82f6; margin: 0 0 12px 0; font-size: 1.1em;">🎯 목표 비중</h3>
        <div style="font-size: 0.9em; line-height: 1.8;">
            <div style="display: flex; justify-content: space-between; margin: 5px 0;"><span style="color: #94a3b8;">QQQM</span><span style="color: #10b981; font-weight: 700;">72%</span></div>
            <div style="display: flex; justify-content: space-between; margin: 5px 0;"><span style="color: #94a3b8;">SCHD</span><span style="color: #3b82f6; font-weight: 700;">16%</span></div>
            <div style="display: flex; justify-content: space-between; margin: 5px 0;"><span style="color: #94a3b8;">IAU</span><span style="color: #fbbf24; font-weight: 700;">2%</span></div>
            <div style="display: flex; justify-content: space-between; margin: 5px 0;"><span style="color: #94a3b8;">현금</span><span style="color: #94a3b8; font-weight: 700;">10%</span></div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )
    
    # 버튼
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        refresh_button = st.button("🔄 새로고침", width='stretch')
    with col_btn2:
        save_button = st.button(
            "💾 저장",
            width='stretch',
            disabled=(not gs_available) or (not is_personal_mode),
        )
        if not is_personal_mode:
            st.markdown(
                "<p style='text-align: center; margin-top: 6px;'><span style='background: #7c2d12; color: #ffedd5; border: 1px solid #fb923c; border-radius: 999px; padding: 2px 10px; font-size: 0.75em; font-weight: 700;'>DEMO</span></p>",
                unsafe_allow_html=True,
            )
    
    # Refresh button clears Streamlit cache.
    if refresh_button:
        st.cache_data.clear()
        st.success("Cache cleared. Fetching latest market data...")
        st.rerun()
    
    # Defer Save handling until total_value is computed.
    if 'save_clicked' not in st.session_state:
        st.session_state.save_clicked = False
    if save_button:
        st.session_state.save_clicked = True

if not is_personal_mode:
    st.info("Public Portfolio Mode: entered portfolio data is not persisted.")

# =====================================================================
# 1) Data Layer
# =====================================================================
# =====================================================================
# Data fetch helper
# =====================================================================
@st.cache_data(ttl=60)  # 60-second cache
def get_stock_data(symbol, period="3mo", interval="day"):
    """Fetch quote and indicator snapshot from unified market data provider."""
    import time
    
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep(retry_delay * attempt)

            market_data = get_market_data(symbol, period=period, interval=interval)
            df = market_data["df"]
            currency = market_data["currency"]
            asset_type = market_data["asset_type"]
            
            if df.empty:
                if attempt < max_retries - 1:
                    continue
                return None
            
            df = compute_indicators(df)
            
            # Latest row snapshot
            latest = df.iloc[-1]
            prev_close = df.iloc[-2]['Close'] if len(df) > 1 else latest['Close']
            
            return {
                'symbol': symbol,
                'asset_type': asset_type,
                'currency': currency,
                'price': latest['Close'],
                'prev_close': prev_close,
                'change': latest['Close'] - prev_close,
                'change_pct': ((latest['Close'] - prev_close) / prev_close) * 100,
                'sma_20': latest['SMA_20'],
                'sma_50': latest['SMA_50'],
                'sma_100': latest['SMA_100'],
                'sma_200': latest['SMA_200'],
                'rsi': latest['RSI'],
                'volume': latest['Volume'],
                'timestamp': latest.name,
                'df': df
            }
        except Exception as e:
            if attempt < max_retries - 1:
                continue
            else:
                st.warning(f"⚠️ {symbol} 데이터 조회 실패: {str(e)}")
                return None
    
    return None

# =====================================================================
# Data loading
# =====================================================================
with st.spinner('데이터 수신 중...'):
    qqqm_data = get_stock_data('QQQM', period="1y")  # 1 year for SMA200
    schd_data = get_stock_data('SCHD', period="1y")
    iau_data = get_stock_data('IAU', period="1y")
    sgov_data = get_stock_data('SGOV', period="1mo")  # SGOV quote
    vix_data = get_stock_data('^VIX', period="1mo")  # VIX 1-month window

def _build_placeholder_asset(symbol: str) -> dict:
    now = pd.Timestamp.now(tz="Asia/Seoul")
    base_df = pd.DataFrame(
        {
            "Open": [1.0],
            "High": [1.0],
            "Low": [1.0],
            "Close": [1.0],
            "Volume": [0.0],
            "SMA_20": [1.0],
            "SMA_50": [1.0],
            "SMA_100": [1.0],
            "SMA_200": [1.0],
            "RSI": [50.0],
        },
        index=[now],
    )
    return {
        'symbol': symbol,
        'asset_type': detect_asset_type(symbol),
        'currency': 'USD',
        'price': 1.0,
        'prev_close': 1.0,
        'change': 0.0,
        'change_pct': 0.0,
        'sma_20': 1.0,
        'sma_50': 1.0,
        'sma_100': 1.0,
        'sma_200': 1.0,
        'rsi': 50.0,
        'volume': 0.0,
        'timestamp': now,
        'df': base_df,
    }


if qqqm_data is None:
    st.error("Core asset (QQQM) data could not be loaded. Please refresh and try again.")
    st.stop()

if schd_data is None:
    st.warning("⚠️ SCHD 데이터 조회 실패로 중립 데이터로 대체합니다.")
    schd_data = _build_placeholder_asset("SCHD")

if iau_data is None:
    st.warning("⚠️ IAU 데이터 조회 실패로 중립 데이터로 대체합니다.")
    iau_data = _build_placeholder_asset("IAU")

# Fear & Greed Index fetch (cached for 30 minutes)
@st.cache_data(ttl=1800)
def get_fear_greed_index():
    """Fetch CNN Fear and Greed Index."""
    
    # 諛⑸쾿 1: CNN 怨듭떇 API
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Referer': 'https://edition.cnn.com/markets/fear-and-greed'
        }
        response = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if data and 'fear_and_greed' in data:
                fng = data['fear_and_greed']
                score = fng.get('score', None)
                if score is not None:
                    prev_close = None
                    historical = data.get('fear_and_greed_historical', {})
                    if historical and 'previous_close' in historical:
                        prev_close = historical['previous_close']
                    
                    return {
                        'value': int(round(score)),
                        'classification': fng.get('rating', 'Neutral'),
                        'previous': prev_close,
                        'source': 'CNN'
                    }
    except:
        pass
    
    # Method 2: fallback endpoint
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/current",
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if data and 'score' in data:
                return {
                    'value': int(round(data['score'])),
                    'classification': data.get('rating', 'Neutral'),
                    'previous': data.get('previous_close', None),
                    'source': 'CNN'
                }
    except:
        pass
    
    # Data unavailable
    return None

with st.spinner('Loading Fear & Greed Index...'):
    fng_data = get_fear_greed_index()

# =====================================================================
# 2) Indicator Calculation
# =====================================================================

# SGOV price (use fallback when unavailable)
if sgov_data:
    sgov_price = sgov_data['price']
else:
    sgov_price = 100.50  # SGOV 湲곕낯 異붿젙媛

# =====================================================================
# 4) Portfolio Engine
# =====================================================================

# FX rate (KRW per USD). Safe fallback is handled inside get_fx_rate().
fx_krw_per_usd = get_fx_rate("KRWUSD")

# Cash-like total (SGOV + cash deposit)
cash_result = compute_cash(
    sgov_qty=sgov_qty,
    sgov_price=sgov_price,
    cash_deposit=cash_deposit,
    currency=(sgov_data['currency'] if sgov_data else 'USD'),
)
sgov_value = cash_result["sgov_value"]
total_cash = cash_result["cash_total"]

# =====================================================================
# Portfolio valuation
# =====================================================================
assets = build_core_assets(
    qqqm_qty=qqqm_qty,
    schd_qty=schd_qty,
    iau_qty=iau_qty,
    qqqm_data=qqqm_data,
    schd_data=schd_data,
    iau_data=iau_data,
)

portfolio_result = compute_portfolio_value(assets=assets, cash=total_cash)
asset_values = portfolio_result["asset_values"]
asset_weights = portfolio_result["asset_weights"]
total_value = portfolio_result["total_value"]

qqqm_value = asset_values.get("QQQM", 0.0)
schd_value = asset_values.get("SCHD", 0.0)
iau_value = asset_values.get("IAU", 0.0)

qqqm_pct = asset_weights.get("QQQM", 0.0)
schd_pct = asset_weights.get("SCHD", 0.0)
iau_pct = asset_weights.get("IAU", 0.0)
cash_pct = (total_cash / total_value) * 100 if total_value > 0 else 0

# SGOV/cash component ratios
sgov_pct = (sgov_value / total_value) * 100 if total_value > 0 else 0
deposit_pct = (cash_deposit / total_value) * 100 if total_value > 0 else 0

# =====================================================================
# 5) UI Rendering
# =====================================================================
# =====================================================================
# Google Sheets save handling
# =====================================================================
if st.session_state.get('save_clicked', False) and gs_available and is_personal_mode:
    success, message = save_portfolio_to_sheets(
        qqqm_qty, schd_qty, iau_qty, sgov_qty, 
        cash_deposit, new_cash, total_value
    )
    if success:
        st.sidebar.success(f"OK: {message}")
    else:
        st.sidebar.error(f"Error: {message}")
    st.session_state.save_clicked = False

# =====================================================================
# Sidebar: cash and source summary
# =====================================================================
with st.sidebar:
    st.markdown("---")
    st.markdown("### Cash-like Assets")
    
    # SGOV snapshot
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("SGOV", f"{sgov_qty:,.2f} shares")
    with col2:
        st.metric("Price", f"${sgov_price:.2f}")
    
    st.markdown(f"**SGOV Value** :green[${sgov_value:,.2f}]")
    st.markdown(f"**Cash Deposit** ${cash_deposit:,.2f}")
    st.markdown(f"**Total Cash-like Assets:** :blue[${total_cash:,.2f}]")
    
    if new_cash > 0:
        st.markdown("---")
        st.markdown(f"**+ New Cash:** :blue[${new_cash:,.2f}]")
        st.markdown(f"**Post-Deposit Total:** :orange[${total_cash + new_cash:,.2f}]")

    st.markdown("---")
    st.markdown("### Data Sources")
    for display_name, symbol in [
        ("QQQM", "QQQM"),
        ("SCHD", "SCHD"),
        ("IAU", "IAU"),
        ("SGOV", "SGOV"),
        ("VIX(^VIX)", "^VIX"),
    ]:
        st.caption(f"{display_name}: {asset_source_label(symbol)}")
    st.caption(f"FX rate: 1 USD = {fx_krw_per_usd:,.2f} KRW")

# =====================================================================
# Main dashboard real-time quotes
st.header("Real-Time Quotes")

col1, col2, col3, col4 = st.columns(4)

with col1:
    change_class = 'positive' if qqqm_data['change'] >= 0 else 'negative'
    st.metric(
        label="QQQM (Growth Core)",
        value=f"${qqqm_data['price']:.2f}",
        delta=f"{qqqm_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>Volume: {qqqm_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col2:
    change_class = 'positive' if schd_data['change'] >= 0 else 'negative'
    st.metric(
        label="SCHD (Dividend Core)",
        value=f"${schd_data['price']:.2f}",
        delta=f"{schd_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>Volume: {schd_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col3:
    change_class = 'positive' if iau_data['change'] >= 0 else 'negative'
    st.metric(
        label="IAU (Gold)",
        value=f"${iau_data['price']:.2f}",
        delta=f"{iau_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>Volume: {iau_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col4:
    if sgov_data:
        st.metric(
            label="SGOV (Cash ETF)",
            value=f"${sgov_price:.2f}",
            delta=f"{sgov_data['change_pct']:+.2f}%"
        )
        st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>Holdings: {sgov_qty:,.2f} shares</p>", unsafe_allow_html=True)
    else:
        st.metric(label="SGOV (Cash ETF)", value=f"${sgov_price:.2f}")
        st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>Holdings: {sgov_qty:,.2f} shares</p>", unsafe_allow_html=True)

    # Market sentiment (VIX + Fear & Greed)
st.markdown("<br>", unsafe_allow_html=True)
col_vix, col_fng = st.columns(2)

with col_vix:
    if vix_data:
        vix_color = "#10b981" if vix_data['price'] <= 20 else ("#fbbf24" if vix_data['price'] <= 30 else "#ef4444")
        vix_status = "안정" if vix_data['price'] <= 14 else ("정상" if vix_data['price'] <= 20 else ("주의" if vix_data['price'] <= 30 else "위험"))
        defcon_warning = "⚠️ DEFCON 조건!" if vix_data['price'] <= 14.0 else ""
        
        st.markdown(f"""
        <div style="background: #1e293b; border: 2px solid {vix_color}; border-radius: 12px; padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <p style="color: #94a3b8; font-size: 0.9em; margin: 0;">VIX (변동성 지수)</p>
                    <p style="color: {vix_color}; font-size: 2.5em; font-weight: 800; margin: 5px 0;">{vix_data['price']:.2f}</p>
                    <p style="color: {'#ef4444' if vix_data['change_pct'] > 0 else '#10b981'}; font-size: 1em; margin: 0;">
                        {'📈' if vix_data['change_pct'] > 0 else '📉'} {vix_data['change_pct']:+.2f}%
                    </p>
                </div>
                <div style="text-align: right;">
                    <p style="color: {vix_color}; font-size: 1.5em; font-weight: 700; margin: 0;">{vix_status}</p>
                    <p style="color: #ef4444; font-size: 1em; font-weight: 700; margin: 5px 0;">{defcon_warning}</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning("VIX 데이터 없음")

with col_fng:
    if fng_data:
        fng_value = fng_data['value']
        
        # Color and label by Fear & Greed score
        if fng_value >= 75:
            fng_color = "#ef4444"
            fng_label = "극단적 탐욕"
            fng_icon = "🔴"
            fng_advice = "시장 과열 주의"
        elif fng_value >= 55:
            fng_color = "#f97316"
            fng_label = "탐욕"
            fng_icon = "🟡"
            fng_advice = "상승 추세"
        elif fng_value >= 45:
            fng_color = "#fbbf24"
            fng_label = "중립"
            fng_icon = "🟡"
            fng_advice = "관망세"
        elif fng_value >= 25:
            fng_color = "#3b82f6"
            fng_label = "공포"
            fng_icon = "🔵"
            fng_advice = "매수 기회 탐색"
        else:
            fng_color = "#8b5cf6"
            fng_label = "극단적 공포"
            fng_icon = "🔴"
            fng_advice = "역추세 매수 고려"
        
        # Daily change vs previous close
        prev_value = fng_data.get('previous')
        if prev_value:
            try:
                prev_val = int(prev_value)
                fng_change = fng_value - prev_val
                fng_change_str = f"{'📈' if fng_change > 0 else '📉'} {fng_change:+d} (전일대비)"
            except:
                fng_change_str = ""
        else:
            fng_change_str = ""
        
        st.markdown(f"""
        <div style="background: #1e293b; border: 2px solid {fng_color}; border-radius: 12px; padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <p style="color: #94a3b8; font-size: 0.9em; margin: 0;">Fear & Greed Index</p>
                    <p style="color: {fng_color}; font-size: 2.5em; font-weight: 800; margin: 5px 0;">{fng_value}</p>
                    <p style="color: #94a3b8; font-size: 0.9em; margin: 0;">{fng_change_str}</p>
                </div>
                <div style="text-align: right;">
                    <p style="font-size: 1.8em; margin: 0;">{fng_icon}</p>
                    <p style="color: {fng_color}; font-size: 1.3em; font-weight: 700; margin: 5px 0;">{fng_label}</p>
                    <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{fng_advice}</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="background: #1e293b; border: 2px solid #475569; border-radius: 12px; padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <p style="color: #94a3b8; font-size: 0.9em; margin: 0;">Fear & Greed Index</p>
                    <p style="color: #64748b; font-size: 2.5em; font-weight: 800; margin: 5px 0;">N/A</p>
                    <p style="color: #475569; font-size: 0.85em; margin: 0;">CNN 연결 실패</p>
                </div>
                <div style="text-align: right;">
                    <p style="font-size: 1.8em; margin: 0;">⚠️</p>
                    <p style="color: #64748b; font-size: 1.3em; font-weight: 700; margin: 5px 0;">데이터 없음</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

st.header("📊 Portfolio Summary")
sum_col1, sum_col2, sum_col3, sum_col4, sum_col5 = st.columns(5)
with sum_col1:
    st.metric("Total Value", f"${total_value:,.2f}")
with sum_col2:
    st.metric("QQQM", f"{qqqm_pct:.1f}%")
with sum_col3:
    st.metric("SCHD", f"{schd_pct:.1f}%")
with sum_col4:
    st.metric("IAU", f"{iau_pct:.1f}%")
with sum_col5:
    st.metric("Cash", f"{cash_pct:.1f}%")

regime_info = detect_market_regime(
    qqqm_data["df"],
    vix_data["price"] if vix_data else None,
)

regime_label_map = {
    "BULL": "🟢 BULL MARKET",
    "CORRECTION": "🟡 CORRECTION",
    "BEAR": "🔴 BEAR MARKET",
    "RECOVERY": "🔵 RECOVERY",
}
regime_color_map = {
    "BULL": "#10b981",
    "CORRECTION": "#f59e0b",
    "BEAR": "#ef4444",
    "RECOVERY": "#3b82f6",
}

current_regime = regime_info.get("regime", "CORRECTION")
current_regime_label = regime_label_map.get(current_regime, "🟡 CORRECTION")
current_regime_color = regime_color_map.get(current_regime, "#f59e0b")
current_confidence = float(regime_info.get("confidence", 0.0))
current_reasons = regime_info.get("reason", [])

st.header("📊 Market Regime")
st.markdown(
    f"<span style='background: {current_regime_color}; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700;'>{current_regime_label}</span>",
    unsafe_allow_html=True,
)
st.caption(f"Confidence: {current_confidence * 100:.1f}%")
for item in current_reasons:
    st.markdown(f"- {item}")

macro_summary = summarize_macro_today(
    vix_data=vix_data,
    fng_data=fng_data,
    qqqm_data=qqqm_data,
    sgov_data=sgov_data,
    market_news=None,
)

st.header("Today's Macro Summary")
st.markdown(
    f"<span style='background: {macro_summary['color']}; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700;'>{macro_summary['regime_label']}</span>",
    unsafe_allow_html=True,
)
for line in macro_summary["bullets"]:
    st.markdown(f"- {line}")
st.caption(macro_summary["title"])
st.markdown(f"**Implication**: {macro_summary['implication']}")

st.markdown("---")

# =====================================================================
# 3) Strategy Engine
# =====================================================================
# =====================================================================
# Strategy logic: Manual v5.10
# =====================================================================
st.header("Strategy Condition Analysis")

# DEFCON is computed by strategy engine
defcon_triggered = detect_defcon(
    vix_data['price'] if vix_data else None,
    qqqm_data.get('rsi'),
)

# Puddle logic is computed by signals engine
puddle_result = calculate_puddle_signal(qqqm_data["df"], cooldown_days=30)
puddle_stage = puddle_result.stage
puddle_alert = puddle_result.alert
puddle_cooldown_active = puddle_result.cooldown_active
cooldown_info = puddle_result.cooldown_info or ""

shoulder_eval = evaluate_smart_shoulder(qqqm_data['df'], qqqm_pct)
condition_1_over_77 = bool(shoulder_eval['over_threshold'])
condition_2_below_sma20 = bool(shoulder_eval['below_sma20'])
condition_3_after_high = bool(shoulder_eval['after_high'])
smart_shoulder_triggered = bool(shoulder_eval['triggered'])
rebalancing_needed = bool(shoulder_eval['rebalancing_needed'])

# Alerts
if defcon_triggered:
    st.markdown(f"""
    <div class="warning-box">
        <div class="warning-title">⚠️ DEFCON Saving Triggered</div>
        <p><strong>VIX:</strong> {vix_data['price']:.2f} (<= 14.00)</p>
        <p><strong>RSI:</strong> {qqqm_data['rsi']:.2f} (>= 70)</p>
        <p><strong>Action:</strong> New cash 100% to SGOV (QQQM/SCHD/IAU buy blocked)</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: #8b5cf6; font-size: 1.1em;">🔔 If SGOV was already bought</p>
        <div style="background: rgba(139, 92, 246, 0.1); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;"><strong>Watch:</strong> DEFCON clears when VIX &gt; 14 or RSI &lt; 70</p>
            <p style="margin: 5px 0;"><strong>After clear:</strong> Resume normal allocation (72/16/2/10)</p>
            <p style="margin: 5px 0;"><strong>Existing positions:</strong> Hold (no forced sell)</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

if puddle_alert:
    # Puddle stage guidance card
    stage_info = {
        1: {"name": "Stage 1: Break below SMA50", "color": "#fbbf24", "rate": 15, "desc": "Mild correction. Build conservatively."},
        2: {"name": "Stage 2: Break below SMA100", "color": "#f97316", "rate": 35, "desc": "Deeper correction. Scale in by plan."},
        3: {"name": "Stage 3: Break below SMA200", "color": "#ef4444", "rate": 50, "desc": "High stress zone. Deploy with discipline."},
        4: {"name": "Stage 4: Recover above SMA200", "color": "#10b981", "rate": 100, "desc": "Recovery confirmed. Resume normal allocation."}
    }
    
    info = stage_info[puddle_stage]
    
    # Dashboard policy: use current account snapshot only.
    # Backtests/simulations should track remaining_cash internally across events.
    remaining_cash = sgov_value + cash_deposit
    injection_amount = compute_deployment(puddle_stage, remaining_cash)
    cash_base = remaining_cash
    
    # Moving average labels
    sma_50_val = f"${qqqm_data['sma_50']:.2f}" if pd.notna(qqqm_data['sma_50']) else "N/A"
    sma_100_val = f"${qqqm_data['sma_100']:.2f}" if pd.notna(qqqm_data['sma_100']) else "N/A"
    sma_200_val = f"${qqqm_data['sma_200']:.2f}" if pd.notna(qqqm_data['sma_200']) else "N/A"
    
    # Next action guidance
    next_action_info = {
        1: {"next": "Stage 2 (below SMA100)", "watch": "SMA100", "next_rate": "Deploy 35%"},
        2: {"next": "Stage 3 (below SMA200)", "watch": "SMA200", "next_rate": "Deploy 50%"},
        3: {"next": "Stage 4 (recover SMA200)", "watch": "SMA200 recovery", "next_rate": "Deploy 100%"},
        4: {"next": "Normal operation", "watch": "Portfolio allocation", "next_rate": "Back to target allocation"}
    }
    next_info = next_action_info[puddle_stage]
    
    st.markdown(f"""
    <div class="warning-box" style="border-color: {info['color']};">
        <div class="warning-title" style="color: {info['color']};">Puddle Entry Zone: {info['name']}</div>
        <p style="color: #10b981; font-size: 0.9em;">30-day cooldown cleared. New signal is actionable.</p>
        <p><strong>Current Price:</strong> ${qqqm_data['price']:.2f}</p>
        <p><strong>SMA50:</strong> {sma_50_val} | <strong>SMA100:</strong> {sma_100_val} | <strong>SMA200:</strong> {sma_200_val}</p>
        <p><strong>Interpretation:</strong> {info['desc']}</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: {info['color']}; font-size: 1.1em;">Current Deployment Plan (v5.10)</p>
        <div style="background: rgba(251, 191, 36, 0.05); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;"><strong>Cash-like Assets:</strong> ${cash_base:,.2f}</p>
            <p style="margin: 5px 0;">Breakdown: SGOV ${sgov_value:,.2f} + Cash ${cash_deposit:,.2f}</p>
            <p style="margin: 5px 0;"><strong>Deployment Rate:</strong> {info['rate']}%</p>
            <p style="margin: 5px 0; font-size: 1.2em; color: {info['color']};"><strong>Deployment Amount:</strong> ${injection_amount:,.2f}</p>
        </div>
        <p style="color: #10b981; font-weight: 700; margin-top: 10px;">New cash is allocated immediately using 72/16/2/10 target.</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: #8b5cf6; font-size: 1.1em;">After This Deployment</p>
        <div style="background: rgba(139, 92, 246, 0.1); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;"><strong>Next Stage:</strong> {next_info['next']}</p>
            <p style="margin: 5px 0;"><strong>Watch:</strong> {next_info['watch']}</p>
            <p style="margin: 5px 0;"><strong>Next Rate:</strong> {next_info['next_rate']}</p>
            <p style="margin: 5px 0; color: #94a3b8;"><strong>New cash:</strong> Immediate allocation (72/16/2/10).</p>
            <p style="margin: 5px 0; color: #94a3b8;"><strong>Cooldown:</strong> Same stage cannot trigger for 30 days.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# Cooldown active while signal is blocked
if puddle_cooldown_active and not puddle_alert:
    st.markdown(f"""
    <div class="info-box">
        <div class="warning-title">Puddle Cooldown Active</div>
        <p><strong>Current Price:</strong> ${qqqm_data['price']:.2f} (waiting)</p>
        <p><strong>Reason:</strong> {cooldown_info if cooldown_info else "Signal triggered within last 30 days"}</p>
        <hr style="border-color: rgba(251, 191, 36, 0.3); margin: 10px 0;">
        <p style="color: #fbbf24;"><strong>Action:</strong> Wait for next valid trigger (duplicate buy prevention).</p>
        <p style="color: #94a3b8; font-size: 0.9em;">New cash continues to be allocated immediately by target weights.</p>
        <p style="color: #64748b; font-size: 0.85em;">Cooldown expires after 30 days.</p>
    </div>
    """, unsafe_allow_html=True)

if rebalancing_needed:
    excess = qqqm_pct - 72
    
    # Build explanation of pending trigger conditions.
    missing_conditions = []
    if not condition_2_below_sma20:
        missing_conditions.append("Break below SMA20")
    if not condition_3_after_high:
        missing_conditions.append("Recent high updated")
    
    next_action_text = " + ".join(missing_conditions) if missing_conditions else "All conditions met"
    status_20 = "Below SMA20" if condition_2_below_sma20 else "Above SMA20"
    status_high = "After recent high" if condition_3_after_high else "Recent high not confirmed"
    st.info(
        "QQQM overweight detected\n"
        f"- QQQM allocation: {qqqm_pct:.2f}% (target: 72%)\n"
        f"- Excess: +{excess:.2f}%p\n"
        f"- SMA20 status: {status_20}\n"
        f"- High update status: {status_high}\n"
        "- Current action: Wait for Smart Shoulder trigger\n"
        f"- Next trigger conditions: {next_action_text}"
    )

if smart_shoulder_triggered:
    excess = qqqm_pct - 72
    st.error(
        "Smart Shoulder triggered\n"
        f"- QQQM allocation: {qqqm_pct:.2f}% (target: 72%)\n"
        f"- Excess: +{excess:.2f}%p\n"
        f"- Condition 2: Below SMA20 (${qqqm_data['sma_20']:.2f})\n"
        "- Action: Rebalance portfolio to 72/16/2/10"
    )

# RSI status
col1, col2, col3 = st.columns(3)

with col1:
    rsi_status = ""
    rsi_color = ""
    if qqqm_data['rsi'] >= 70:
        rsi_status = "Overbought"
        rsi_color = "#ef4444"
    elif qqqm_data['rsi'] <= 30:
        rsi_status = "Oversold"
        rsi_color = "#3b82f6"
    else:
        rsi_status = "Neutral"
        rsi_color = "#10b981"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {rsi_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">RSI(14)</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {rsi_color}; margin: 10px 0;">{qqqm_data['rsi']:.2f}</p>
        <p style="font-size: 1.1em; color: {rsi_color}; font-weight: 600;">{rsi_status}</p>
    </div>
    """, unsafe_allow_html=True)

with col2:
    sma_status = ""
    sma_color = ""
    if qqqm_data['price'] > qqqm_data['sma_20']:
        sma_status = "Above SMA20"
        sma_color = "#10b981"
    else:
        sma_status = "Below SMA20"
        sma_color = "#fbbf24"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {sma_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">SMA20</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {sma_color}; margin: 10px 0;">${qqqm_data['sma_20']:.2f}</p>
        <p style="font-size: 1.1em; color: {sma_color}; font-weight: 600;">{sma_status}</p>
    </div>
    """, unsafe_allow_html=True)

with col3:
    sma_status = ""
    sma_color = ""
    if pd.notna(qqqm_data['sma_50']) and qqqm_data['price'] > qqqm_data['sma_50']:
        sma_status = "Above SMA50"
        sma_color = "#10b981"
    elif pd.notna(qqqm_data['sma_50']):
        sma_status = "Below SMA50"
        sma_color = "#ef4444"
    else:
        sma_status = "Insufficient data"
        sma_color = "#94a3b8"
    
    sma_50_display = f"${qqqm_data['sma_50']:.2f}" if pd.notna(qqqm_data['sma_50']) else "N/A"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {sma_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">SMA50</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {sma_color}; margin: 10px 0;">{sma_50_display}</p>
        <p style="font-size: 1.1em; color: {sma_color}; font-weight: 600;">{sma_status}</p>
    </div>
    """, unsafe_allow_html=True)

# Additional indicators: SMA100, SMA200, puddle stage
st.markdown("<br>", unsafe_allow_html=True)
col4, col5, col6 = st.columns(3)

with col4:
    sma_status = ""
    sma_color = ""
    if pd.notna(qqqm_data['sma_100']) and qqqm_data['price'] > qqqm_data['sma_100']:
        sma_status = "Above SMA100"
        sma_color = "#10b981"
    elif pd.notna(qqqm_data['sma_100']):
        sma_status = "Below SMA100"
        sma_color = "#f97316"
    else:
        sma_status = "Insufficient data"
        sma_color = "#94a3b8"
    
    sma_100_display = f"${qqqm_data['sma_100']:.2f}" if pd.notna(qqqm_data['sma_100']) else "N/A"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {sma_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">SMA100</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {sma_color}; margin: 10px 0;">{sma_100_display}</p>
        <p style="font-size: 1.1em; color: {sma_color}; font-weight: 600;">{sma_status}</p>
    </div>
    """, unsafe_allow_html=True)

with col5:
    sma_status = ""
    sma_color = ""
    if pd.notna(qqqm_data['sma_200']) and qqqm_data['price'] > qqqm_data['sma_200']:
        sma_status = "Above SMA200"
        sma_color = "#10b981"
    elif pd.notna(qqqm_data['sma_200']):
        sma_status = "Below SMA200"
        sma_color = "#ef4444"
    else:
        sma_status = "Insufficient data"
        sma_color = "#94a3b8"
    
    sma_200_display = f"${qqqm_data['sma_200']:.2f}" if pd.notna(qqqm_data['sma_200']) else "N/A"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {sma_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">SMA200</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {sma_color}; margin: 10px 0;">{sma_200_display}</p>
        <p style="font-size: 1.1em; color: {sma_color}; font-weight: 600;">{sma_status}</p>
    </div>
    """, unsafe_allow_html=True)

with col6:
    # Puddle stage
    if puddle_stage == 0:
        stage_text = "Normal"
        stage_color = "#10b981"
        stage_icon = "OK"
    elif puddle_stage == 1:
        stage_text = "Stage 1 (SMA50)"
        stage_color = "#fbbf24"
        stage_icon = "S1"
    elif puddle_stage == 2:
        stage_text = "Stage 2 (SMA100)"
        stage_color = "#f97316"
        stage_icon = "S2"
    elif puddle_stage == 3:
        stage_text = "Stage 3 (SMA200)"
        stage_color = "#ef4444"
        stage_icon = "S3"
    else:  # stage 4
        stage_text = "Stage 4 (Recovery)"
        stage_color = "#10b981"
        stage_icon = "S4"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {stage_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">Puddle Stage</p>
        <p style="font-size: 2em; font-weight: 700; color: {stage_color}; margin: 10px 0;">{stage_icon}</p>
        <p style="font-size: 1.1em; color: {stage_color}; font-weight: 600;">{stage_text}</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# =====================================================================
# Portfolio allocation analysis
# =====================================================================
st.header("Portfolio Allocation")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Asset Breakdown")
    st.metric("Total Assets", f"${total_value:,.2f}")
    
    portfolio_df = pd.DataFrame({
        'Asset': ['QQQM', 'SCHD', 'IAU', 'SGOV', 'Cash Deposit', 'Total Cash'],
        'Value': [qqqm_value, schd_value, iau_value, sgov_value, cash_deposit, total_cash],
        'Current Weight (%)': [qqqm_pct, schd_pct, iau_pct, sgov_pct, deposit_pct, cash_pct],
        'Target Weight (%)': ['72.00%', '16.00%', '2.00%', '-', '-', '10.00%'],
        'Gap (%p)': [
            f'{qqqm_pct - 72:+.2f}%p',
            f'{schd_pct - 16:+.2f}%p',
            f'{iau_pct - 2:+.2f}%p',
            '-',
            '-',
            f'{cash_pct - 10:+.2f}%p',
        ]
    })

    def highlight_rows(row):
        if row['Asset'] == 'Total Cash':
            return ['background-color: rgba(59, 130, 246, 0.1)'] * len(row)
        if row['Asset'] in ['SGOV', 'Cash Deposit']:
            return ['background-color: rgba(148, 163, 184, 0.05)'] * len(row)
        return [''] * len(row)

    st.dataframe(
        portfolio_df.style.format({
            'Value': '${:,.2f}',
            'Current Weight (%)': '{:.2f}%',
        }).apply(highlight_rows, axis=1),
        width='stretch'
    )

with col2:
    st.subheader("Allocation Chart")
    
    # Pie chart (mobile-optimized layout)
    fig = go.Figure(data=[go.Pie(
        labels=['QQQM', 'SCHD', 'IAU', 'SGOV', 'Cash Deposit'],
        values=[qqqm_value, schd_value, iau_value, sgov_value, cash_deposit],
        hole=0.4,
        marker=dict(colors=['#10b981', '#3b82f6', '#fbbf24', '#94a3b8', '#64748b']),
        textinfo='label+percent',
        textfont=dict(size=11, color='white'),
        textposition='inside',
        insidetextorientation='horizontal',
        hovertemplate='<b>%{label}</b><br>$%{value:,.2f}<br>%{percent}<extra></extra>',
        domain=dict(x=[0.1, 0.9], y=[0.15, 0.95])
    )])
    
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'),
        height=380,
        margin=dict(l=0, r=0, t=10, b=10),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0,
            xanchor="center",
            x=0.5,
            font=dict(size=10)
        ),
        uniformtext=dict(minsize=11, mode='show')  # Keep text readable across slices
    )
    
    st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})

st.markdown("---")

# =====================================================================
# Technical chart
# =====================================================================
st.header("📊 QQQM Technical Analysis")

# Price chart
fig = go.Figure()

# Candlestick
fig.add_trace(go.Candlestick(
    x=qqqm_data['df'].index,
    open=qqqm_data['df']['Open'],
    high=qqqm_data['df']['High'],
    low=qqqm_data['df']['Low'],
    close=qqqm_data['df']['Close'],
    name='QQQM',
    increasing_line_color='#ef4444',
    decreasing_line_color='#3b82f6'
))

# Moving average lines
fig.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['SMA_20'],
    mode='lines',
    name='SMA20',
    line=dict(color='#fbbf24', width=1.5)
))

fig.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['SMA_50'],
    mode='lines',
    name='SMA50',
    line=dict(color='#3b82f6', width=2)
))

fig.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['SMA_100'],
    mode='lines',
    name='SMA100',
    line=dict(color='#f97316', width=2)
))

fig.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['SMA_200'],
    mode='lines',
    name='SMA200',
    line=dict(color='#ef4444', width=2.5)
))

fig.update_layout(
    plot_bgcolor='rgba(30, 41, 59, 0.5)',
    paper_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#e2e8f0'),
    xaxis=dict(
        gridcolor='rgba(148, 163, 184, 0.2)',
        showgrid=True
    ),
    yaxis=dict(
        gridcolor='rgba(148, 163, 184, 0.2)',
        showgrid=True,
        title='Price (USD)'
    ),
    height=500,
    hovermode='x unified',
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        bgcolor='rgba(30, 41, 59, 0.8)',
        bordercolor='#475569',
        borderwidth=1
    )
)

st.plotly_chart(fig, width='stretch')

# RSI 李⑦듃
fig_rsi = go.Figure()

fig_rsi.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['RSI'],
    mode='lines',
    name='RSI(14)',
    line=dict(color='#10b981', width=2)
))

# Overbought / Oversold lines
fig_rsi.add_hline(y=70, line_dash="dash", line_color="#ef4444", annotation_text="怨쇱뿴(70)")
fig_rsi.add_hline(y=30, line_dash="dash", line_color="#3b82f6", annotation_text="移⑥껜(30)")

fig_rsi.update_layout(
    plot_bgcolor='rgba(30, 41, 59, 0.5)',
    paper_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#e2e8f0'),
    xaxis=dict(
        gridcolor='rgba(148, 163, 184, 0.2)',
        showgrid=True
    ),
    yaxis=dict(
        gridcolor='rgba(148, 163, 184, 0.2)',
        showgrid=True,
        title='RSI',
        range=[0, 100]
    ),
    height=300,
    hovermode='x unified'
)

st.plotly_chart(fig_rsi, width='stretch')

if backtest_enabled:
    bt_stage_rates = {k: v for k, v in STAGE_DEPLOYMENT_RATES.items() if k in (1, 2, 3)}
    bt_fee_bps = 1.0
    bt_slippage_bps = 2.0
    bt_current_vol_factor = estimate_vol_factor(qqqm_data['df'])
    bt_result = run_backtest(
        qqqm_data['df'][['Open', 'Close', 'SMA_50', 'SMA_100', 'SMA_200']].copy(),
        initial_cash=10000.0,
        stage_rates=bt_stage_rates,
        vol_adjust=backtest_vol_adjust,
        buy_only=True,
        fee_bps=bt_fee_bps,
        slippage_bps=bt_slippage_bps,
    )

    st.markdown("---")
    st.header("Backtest (Experimental)")
    st.caption("Rule: signal calculated at D close, executed at D+1 open, with fee 1bp and slippage 2bp")
    st.markdown(f"""
    <div class="info-box">
        <div class="warning-title">Assumptions</div>
        <p>Signal timing: evaluated at day D close</p>
        <p>Execution timing: filled at day D+1 open (next trading day)</p>
        <p>Stage 4: deploy all remaining cash at next-day open</p>
        <p>stage_rates (1/2/3): {bt_stage_rates} | stage 4: 100%</p>
        <p>volatility adjustment: {'ON' if backtest_vol_adjust else 'OFF'}</p>
        <p>fee_bps: {bt_fee_bps:.1f} | slippage_bps: {bt_slippage_bps:.1f}</p>
        <p>execution mode: long-only, buy-only</p>
    </div>
    """, unsafe_allow_html=True)

    if backtest_vol_adjust:
        st.caption(f"Current estimated vol_factor (QQQM): {bt_current_vol_factor:.2f}")

    metrics_rows = [
        {"Metric": "CAGR", "Value": f"{bt_result.metrics.get('CAGR', 0.0) * 100:.2f}%"},
        {"Metric": "Total Return", "Value": f"{bt_result.metrics.get('TotalReturn', 0.0) * 100:.2f}%"},
        {"Metric": "Benchmark Return", "Value": f"{bt_result.metrics.get('BenchmarkTotalReturn', 0.0) * 100:.2f}%"},
        {"Metric": "MDD", "Value": f"{bt_result.metrics.get('MDD', 0.0) * 100:.2f}%"},
        {"Metric": "Volatility(ann)", "Value": f"{bt_result.metrics.get('Volatility', 0.0) * 100:.2f}%"},
        {"Metric": "Sharpe", "Value": f"{bt_result.metrics.get('Sharpe', 0.0):.2f}"},
        {"Metric": "NumTrades", "Value": f"{int(bt_result.metrics.get('NumTrades', 0))}"},
        {"Metric": "MaxDD Window", "Value": str(bt_result.metrics.get('MaxDD_start_end', None))},
    ]
    st.dataframe(pd.DataFrame(metrics_rows), width='stretch', hide_index=True)

    if not bt_result.equity_curve.empty:
        fig_bt = go.Figure()
        fig_bt.add_trace(go.Scatter(
            x=bt_result.equity_curve.index,
            y=bt_result.equity_curve.values,
            mode='lines',
            name='Equity Curve',
            line=dict(color='#10b981', width=2),
        ))
        if not bt_result.benchmark_curve.empty:
            fig_bt.add_trace(go.Scatter(
                x=bt_result.benchmark_curve.index,
                y=bt_result.benchmark_curve.values,
                mode='lines',
                name='Benchmark (Buy & Hold)',
                line=dict(color='#3b82f6', width=2, dash='dash'),
            ))
        fig_bt.update_layout(
            plot_bgcolor='rgba(30, 41, 59, 0.5)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#e2e8f0'),
            xaxis=dict(gridcolor='rgba(148, 163, 184, 0.2)', showgrid=True),
            yaxis=dict(gridcolor='rgba(148, 163, 184, 0.2)', showgrid=True, title='Equity (USD)'),
            height=320,
            hovermode='x unified',
            margin=dict(l=40, r=20, t=20, b=20),
        )
        st.plotly_chart(fig_bt, width='stretch', config={'displayModeBar': False})

        if not bt_result.trades.empty:
            latest_n = 20
            st.caption(f"Trades: {len(bt_result.trades)} | Showing latest {latest_n}")
            trades_view = bt_result.trades.sort_values("exec_date", ascending=False).head(latest_n).copy()
            trades_view["signal_date"] = pd.to_datetime(trades_view["signal_date"]).dt.strftime("%Y-%m-%d")
            trades_view["exec_date"] = pd.to_datetime(trades_view["exec_date"]).dt.strftime("%Y-%m-%d")
            trades_view["action"] = trades_view["action"].map(lambda x: "留ㅼ닔" if x == "BUY" else str(x))
            trades_view["planned_cash"] = trades_view["planned_cash"].map(fmt_money)
            trades_view["fee"] = trades_view["fee"].map(fmt_money)
            trades_view["exec_price"] = trades_view["exec_price"].map(fmt_money)
            trades_view["shares_bought"] = trades_view["shares_bought"].map(lambda x: fmt_num(x, 2))
            trades_view["cash_after"] = trades_view["cash_after"].map(fmt_money)
            trades_view["shares_after"] = trades_view["shares_after"].map(lambda x: fmt_num(x, 2))
            if "vol_factor" in trades_view.columns:
                trades_view["vol_factor"] = trades_view["vol_factor"].map(lambda x: fmt_num(x, 2) if x is not None else "N/A")
            trades_view = trades_view.rename(
                columns={
                    "signal_date": "Signal Date",
                    "exec_date": "Execution Date",
                    "stage": "Stage",
                    "action": "Action",
                    "planned_cash": "Planned Cash",
                    "fee": "Fee",
                    "exec_price": "Execution Price",
                    "shares_bought": "Shares Bought",
                    "cash_after": "Cash After",
                    "shares_after": "Shares After",
                    "vol_factor": "Volatility Factor",
                    "reason": "Reason",
                }
            )
            trades_view = trades_view[
                ["Signal Date", "Execution Date", "Stage", "Action", "Planned Cash", "Fee", "Execution Price", "Shares Bought", "Shares After", "Cash After", "Volatility Factor", "Reason"]
            ]
            st.dataframe(
                trades_view,
                width='stretch',
                hide_index=True,
            )

st.markdown("---")
st.header("Strategy Lab")
st.caption("Research mode: single run, cash-ratio study, cooldown sensitivity, and multi-asset validation")

lab_modes = ["SINGLE RUN", "CASH STUDY", "COOLDOWN STUDY", "MULTI-ASSET VALIDATION"]
lab_mode = st.selectbox("Research Mode", lab_modes, index=0)

lab_col1, lab_col2, lab_col3 = st.columns(3)
with lab_col1:
    lab_symbol = st.selectbox("Symbol", ["QQQM", "SPY", "VTI", "BTC-USD"], index=0)
with lab_col2:
    lab_start_date = st.date_input("Start Date", value=pd.Timestamp("2012-01-01").date())
with lab_col3:
    lab_initial_cash = st.number_input("Initial Capital (USD)", min_value=1000.0, value=10000.0, step=1000.0)

lab_assets = st.multiselect("Multi-Asset Set", ["QQQM", "SPY", "VTI", "BTC-USD"], default=["QQQM", "SPY", "VTI", "BTC-USD"])

ctrl_col1, ctrl_col2 = st.columns(2)
with ctrl_col1:
    lab_cash_ratio = st.slider("cash_ratio", min_value=0.05, max_value=0.30, value=0.10, step=0.01)
with ctrl_col2:
    lab_cooldown = st.slider("cooldown_days", min_value=10, max_value=60, value=30, step=1)

with st.expander("Stage Deployment Rates (1/2/3)", expanded=False):
    rate_col1, rate_col2, rate_col3 = st.columns(3)
    with rate_col1:
        lab_rate_1 = st.slider("stage1_rate", min_value=0.0, max_value=1.0, value=float(STAGE_DEPLOYMENT_RATES[1]), step=0.01)
    with rate_col2:
        lab_rate_2 = st.slider("stage2_rate", min_value=0.0, max_value=1.0, value=float(STAGE_DEPLOYMENT_RATES[2]), step=0.01)
    with rate_col3:
        lab_rate_3 = st.slider("stage3_rate", min_value=0.0, max_value=1.0, value=float(STAGE_DEPLOYMENT_RATES[3]), step=0.01)

crisis_period = st.selectbox("Crash Analysis (optional)", ["None", "2008", "2020", "2022"], index=0)

lab_stage_rates = {1: float(lab_rate_1), 2: float(lab_rate_2), 3: float(lab_rate_3)}
rate_sum = lab_rate_1 + lab_rate_2 + lab_rate_3
if rate_sum > 1.0:
    st.error(f"Stage deployment sum must be <= 1.0 (current: {rate_sum:.2f})")


def _apply_crisis_filter(df: pd.DataFrame, period_label: str) -> pd.DataFrame:
    if period_label == "None":
        return df
    ranges = {
        "2008": ("2008-01-01", "2009-12-31"),
        "2020": ("2020-01-01", "2020-12-31"),
        "2022": ("2022-01-01", "2022-12-31"),
    }
    start_s, end_s = ranges[period_label]
    s_ts = pd.Timestamp(start_s)
    e_ts = pd.Timestamp(end_s)
    if len(df) > 0 and isinstance(df["date"].iloc[0], pd.Timestamp) and df["date"].iloc[0].tzinfo is not None:
        s_ts = s_ts.tz_localize(df["date"].iloc[0].tz)
        e_ts = e_ts.tz_localize(df["date"].iloc[0].tz)
    out = df[(df["date"] >= s_ts) & (df["date"] <= e_ts)].copy()
    return out


lab_run = st.button("Run Strategy Lab", width='stretch')

if lab_run and rate_sum <= 1.0:
    export_df = None

    def _run_one(symbol: str, cooldown_days: int, cash_ratio: float):
        out = run_strategy_backtest(
            symbol=symbol,
            start_date=str(lab_start_date),
            initial_cash=float(lab_initial_cash),
            cooldown_days=int(cooldown_days),
            stage_rates=lab_stage_rates,
            cash_ratio=float(cash_ratio),
        )
        out = _apply_crisis_filter(out, crisis_period)
        if out.empty:
            raise ValueError(f"No rows after crisis filter ({crisis_period})")
        return out

    if lab_mode == "SINGLE RUN":
        with st.spinner("Running strategy research backtest..."):
            lab_df = _run_one(lab_symbol, lab_cooldown, lab_cash_ratio)
            lab_metrics = compute_backtest_metrics(lab_df)

        mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
        mcol1.metric("Total Return", f"{lab_metrics['Total Return'] * 100:.2f}%")
        mcol2.metric("CAGR", f"{lab_metrics['CAGR'] * 100:.2f}%")
        mcol3.metric("Max DD", f"{lab_metrics['Max Drawdown'] * 100:.2f}%")
        mcol4.metric("Volatility", f"{lab_metrics['Volatility'] * 100:.2f}%")
        mcol5.metric("Sharpe", f"{lab_metrics['Sharpe Ratio']:.2f}")

        compare_df = pd.DataFrame(
            [
                {"Category": "Strategy", "Return": f"{lab_metrics['strategy_return'] * 100:.2f}%"},
                {"Category": "Buy & Hold", "Return": f"{lab_metrics['buy_hold_return'] * 100:.2f}%"},
            ]
        )
        st.dataframe(compare_df, width='stretch', hide_index=True)

        st.plotly_chart(plot_backtest_results(lab_df), width='stretch', config={"displayModeBar": False})

        deploy_df = lab_df[lab_df["deploy_cash"] > 0].copy()
        fig_dep = go.Figure()
        fig_dep.add_trace(go.Bar(x=deploy_df["date"], y=deploy_df["deploy_cash"], name="Deploy Cash", marker_color="#f59e0b"))
        fig_dep.update_layout(height=260, yaxis=dict(title="Deploy Cash (USD)"), hovermode="x unified", margin=dict(l=40, r=20, t=20, b=20))
        st.plotly_chart(fig_dep, width='stretch', config={"displayModeBar": False})

        st.caption(f"rows={len(lab_df)} | symbol={lab_symbol} | cooldown={lab_cooldown} | cash_ratio={lab_cash_ratio:.2f} | rates={lab_stage_rates} | crisis={crisis_period}")
        export_df = lab_df.copy()

    elif lab_mode == "CASH STUDY":
        cash_grid = [0.05, 0.10, 0.20, 0.30]
        rows = []
        with st.spinner("Running cash allocation study..."):
            for cr in cash_grid:
                run_df = _run_one(lab_symbol, lab_cooldown, cr)
                m = compute_backtest_metrics(run_df)
                rows.append(
                    {
                        "Cash Ratio": cr,
                        "CAGR": m["CAGR"],
                        "Sharpe": m["Sharpe Ratio"],
                        "MaxDD": m["Max Drawdown"],
                        "Total Return": m["Total Return"],
                    }
                )
        cash_df = pd.DataFrame(rows)
        show_cash_df = cash_df.copy()
        show_cash_df["CAGR"] = show_cash_df["CAGR"].map(lambda x: f"{x * 100:.2f}%")
        show_cash_df["MaxDD"] = show_cash_df["MaxDD"].map(lambda x: f"{x * 100:.2f}%")
        show_cash_df["Total Return"] = show_cash_df["Total Return"].map(lambda x: f"{x * 100:.2f}%")
        st.dataframe(show_cash_df, width='stretch', hide_index=True)
        export_df = cash_df

    elif lab_mode == "COOLDOWN STUDY":
        cooldown_grid = [10, 20, 30, 40, 60]
        rows = []
        with st.spinner("Running cooldown sensitivity study..."):
            for cd in cooldown_grid:
                run_df = _run_one(lab_symbol, cd, lab_cash_ratio)
                m = compute_backtest_metrics(run_df)
                rows.append(
                    {
                        "Cooldown": cd,
                        "CAGR": m["CAGR"],
                        "Sharpe": m["Sharpe Ratio"],
                        "MaxDD": m["Max Drawdown"],
                        "Total Return": m["Total Return"],
                    }
                )
        cooldown_df = pd.DataFrame(rows)
        st.dataframe(cooldown_df, width='stretch', hide_index=True)

        fig_cd = go.Figure()
        fig_cd.add_trace(go.Scatter(x=cooldown_df["Cooldown"], y=cooldown_df["CAGR"], mode="lines+markers", name="CAGR", line=dict(color="#10b981")))
        fig_cd.add_trace(go.Scatter(x=cooldown_df["Cooldown"], y=cooldown_df["Total Return"], mode="lines+markers", name="Total Return", line=dict(color="#3b82f6")))
        fig_cd.add_trace(go.Scatter(x=cooldown_df["Cooldown"], y=cooldown_df["Sharpe"], mode="lines+markers", name="Sharpe", line=dict(color="#f59e0b"), yaxis="y2"))
        fig_cd.update_layout(
            height=320,
            xaxis=dict(title="Cooldown Days"),
            yaxis=dict(title="Return", tickformat=".1%"),
            yaxis2=dict(title="Sharpe", overlaying="y", side="right"),
            hovermode="x unified",
            margin=dict(l=40, r=40, t=20, b=20),
        )
        st.plotly_chart(fig_cd, width='stretch', config={"displayModeBar": False})
        export_df = cooldown_df

    else:  # MULTI-ASSET VALIDATION
        if not lab_assets:
            st.warning("Select at least one asset.")
        else:
            rows = []
            with st.spinner("Running multi-asset validation..."):
                for sym in lab_assets:
                    run_df = _run_one(sym, lab_cooldown, lab_cash_ratio)
                    m = compute_backtest_metrics(run_df)
                    rows.append(
                        {
                            "Asset": sym,
                            "CAGR": m["CAGR"],
                            "Sharpe": m["Sharpe Ratio"],
                            "MaxDD": m["Max Drawdown"],
                            "Strategy Return": m["strategy_return"],
                            "BuyHold Return": m["buy_hold_return"],
                        }
                    )
            multi_df = pd.DataFrame(rows)
            show_multi_df = multi_df.copy()
            for col in ["CAGR", "MaxDD", "Strategy Return", "BuyHold Return"]:
                show_multi_df[col] = show_multi_df[col].map(lambda x: f"{x * 100:.2f}%")
            st.dataframe(show_multi_df, width='stretch', hide_index=True)
            export_df = multi_df

    if export_df is not None and not export_df.empty:
        csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Export Research Result",
            data=csv_bytes,
            file_name=f"strategy_lab_{lab_mode.lower().replace(' ', '_')}.csv",
            mime="text/csv",
            width='stretch',
        )

st.markdown("---")
st.header("📊 FIRE Simulator")
st.caption("Bootstrap future portfolio paths from historical returns to estimate long-run FIRE outcomes.")

mc_col1, mc_col2, mc_col3 = st.columns(3)
with mc_col1:
    mc_symbol = st.selectbox("MC Symbol", ["QQQM", "SPY", "VTI", "BTC-USD"], index=0)
with mc_col2:
    mc_start_date = st.date_input("MC Return Start", value=pd.Timestamp("2012-01-01").date())
with mc_col3:
    mc_years = st.slider("Horizon (Years)", min_value=5, max_value=40, value=20, step=1)

mc_col4, mc_col5, mc_col6 = st.columns(3)
with mc_col4:
    mc_initial = st.number_input("Initial Capital", min_value=1000.0, value=max(total_value, 10000.0), step=1000.0)
with mc_col5:
    mc_annual_inv = st.number_input("Annual Investment", min_value=0.0, value=12000.0, step=1000.0)
with mc_col6:
    mc_target = st.number_input("Target FIRE Capital", min_value=10000.0, value=1000000.0, step=10000.0)

mc_simulations = st.slider("Simulations", min_value=200, max_value=5000, value=1000, step=100)
mc_run = st.button("Run FIRE Simulator", width='stretch')

if mc_run:
    with st.spinner("Running Monte Carlo FIRE simulation..."):
        hist_df = run_strategy_backtest(
            symbol=mc_symbol,
            start_date=str(mc_start_date),
            initial_cash=10000.0,
            cooldown_days=30,
            stage_rates={1: float(STAGE_DEPLOYMENT_RATES[1]), 2: float(STAGE_DEPLOYMENT_RATES[2]), 3: float(STAGE_DEPLOYMENT_RATES[3])},
            cash_ratio=0.10,
        )
        hist_returns = pd.to_numeric(hist_df["portfolio_value"], errors="coerce").pct_change().dropna().values

        sim_paths = simulate_monte_carlo_with_contributions(
            returns=hist_returns,
            years=int(mc_years),
            simulations=int(mc_simulations),
            initial_capital=float(mc_initial),
            annual_investment=float(mc_annual_inv),
        )

        mc_stats = compute_monte_carlo_statistics(sim_paths, initial_capital=float(mc_initial), years=int(mc_years))
        fire_prob = calculate_fire_probability(sim_paths, target_value=float(mc_target))

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Median Final", f"${mc_stats['median_final_value']:,.0f}")
    sc2.metric("5th Percentile", f"${mc_stats['5th_percentile']:,.0f}")
    sc3.metric("95th Percentile", f"${mc_stats['95th_percentile']:,.0f}")
    sc4.metric("FIRE Probability", f"{fire_prob * 100:.1f}%")

    st.plotly_chart(plot_monte_carlo(sim_paths), width='stretch', config={"displayModeBar": False})

    final_values = sim_paths.iloc[-1].astype(float)
    fig_dist = go.Figure()
    fig_dist.add_trace(
        go.Histogram(
            x=final_values.values,
            nbinsx=50,
            marker_color="#3b82f6",
            opacity=0.85,
            name="Final Wealth",
        )
    )
    fig_dist.add_vline(x=float(mc_target), line_color="#ef4444", line_dash="dash", annotation_text="FIRE Target")
    fig_dist.update_layout(
        height=300,
        xaxis=dict(title="Final Portfolio Value (USD)", gridcolor="rgba(148, 163, 184, 0.2)"),
        yaxis=dict(title="Count", gridcolor="rgba(148, 163, 184, 0.2)"),
        plot_bgcolor="rgba(30, 41, 59, 0.5)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e2e8f0"),
        margin=dict(l=40, r=20, t=20, b=20),
    )
    st.plotly_chart(fig_dist, width='stretch', config={"displayModeBar": False})

    export_sim = sim_paths.copy()
    export_sim.insert(0, "day", export_sim.index)
    st.download_button(
        "Export simulation results as CSV",
        data=export_sim.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"fire_simulator_{mc_symbol}_{mc_years}y_{mc_simulations}sims.csv",
        mime="text/csv",
        width='stretch',
    )

st.markdown("---")

# =====================================================================
# Execution plan status
# =====================================================================
st.header("Execution Plan")
status_lines = []

if defcon_triggered:
    status_lines.append("DEFCON active: route new cash to SGOV only")

if puddle_alert:
    deploy_base = float(sgov_value + cash_deposit)
    deploy_amount = compute_deployment(puddle_stage, deploy_base)
    status_lines.append(
        f"Puddle stage {puddle_stage} signal: deploy_base=${deploy_base:,.2f}, suggested_deploy=${deploy_amount:,.2f}"
    )
elif puddle_cooldown_active:
    status_lines.append(f"Puddle cooldown active: {cooldown_info if cooldown_info else 'Signal triggered within last 30 days'}")

if smart_shoulder_triggered:
    status_lines.append("Smart Shoulder triggered: rebalancing required")
elif rebalancing_needed:
    missing_text = " / ".join(shoulder_eval.get("reasons", [])) if shoulder_eval.get("reasons") else "Additional conditions required"
    status_lines.append(f"⚠️ QQQM 77% 초과 대기: {missing_text}")

if not status_lines:
    status_lines.append("Core strategy operating normally")

for line in status_lines:
    st.markdown(f"- {line}")

if new_cash > 0:
    st.caption(f"New cash: ${new_cash:,.2f} | Target ratio: 72/16/2/10")

st.markdown("---")

# =====================================================================
# Footer separator
# =====================================================================
st.markdown("---")

# =====================================================================
# Portfolio market-driver analysis
# =====================================================================
st.header("Today's Market Drivers")

@st.cache_data(ttl=1800)  # 30-minute cache
def get_market_summary(symbol):
    """Fetch symbol-specific headline list from Yahoo Finance RSS."""
    news_list = []
    try:
        feed_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
        response = requests.get(feed_url, timeout=10)
        if response.status_code != 200:
            return news_list

        root = ET.fromstring(response.content)
        for item in root.findall('.//item')[:5]:
            title = (item.findtext('title') or '').strip()
            if not title:
                continue
            news_list.append({
                'title': title,
                'publisher': (item.findtext('source') or 'Yahoo Finance').strip(),
                'link': (item.findtext('link') or '#').strip(),
            })

        return news_list
    except Exception:
        return news_list

def get_broader_market_news():
    """Fetch broader market headlines (RSS-based fallback)."""
    all_news = []
    for symbol in ['SPY', 'QQQ', '^GSPC']:
        try:
            symbol_news = get_market_summary(symbol)
            for item in symbol_news[:3]:
                title = item.get('title', '')
                if title and title not in [n['title'] for n in all_news]:
                    all_news.append(item)
        except:
            continue
    return all_news[:5]

def analyze_market_sentiment(change_pct, news_list):
    """Analyze market sentiment factors from price change and headlines."""
    
    # Sentiment keyword categories
    keyword_categories = {
        'Policy/Rates': {
            'keywords': ['fed', 'federal', 'reserve', 'rate', 'rates', 'interest', 'powell', 'fomc', 'cut', 'hike', 'dovish', 'hawkish', 'monetary', 'treasury', 'yield', 'bond'],
            'positive': ['cut', 'dovish', 'lower', 'ease', 'pause'],
            'negative': ['hike', 'hawkish', 'higher', 'raise', 'surge']
        },
        'Earnings/Companies': {
            'keywords': ['earnings', 'revenue', 'profit', 'guidance', 'beat', 'miss', 'outlook', 'forecast', 'results', 'quarter', 'q1', 'q2', 'q3', 'q4', 'eps', 'sales'],
            'positive': ['beat', 'strong', 'surge', 'record', 'exceeded', 'top', 'raise'],
            'negative': ['miss', 'weak', 'disappoint', 'below', 'cut', 'lower', 'warn']
        },
        'AI/湲곗닠': {
            'keywords': ['ai', 'artificial', 'intelligence', 'nvidia', 'nvda', 'chip', 'chips', 'semiconductor', 'tech', 'apple', 'aapl', 'microsoft', 'msft', 'google', 'googl', 'amazon', 'amzn', 'meta', 'tesla', 'tsla', 'software', 'cloud', 'data', 'center'],
            'positive': ['surge', 'boom', 'growth', 'demand', 'breakthrough', 'rally', 'soar', 'jump'],
            'negative': ['concern', 'bubble', 'overvalued', 'decline', 'fall', 'drop', 'selloff']
        },
        'Inflation': {
            'keywords': ['inflation', 'cpi', 'pce', 'price', 'consumer', 'cost', 'spending'],
            'positive': ['cool', 'ease', 'slow', 'lower', 'decline', 'fall', 'drop'],
            'negative': ['rise', 'hot', 'sticky', 'higher', 'surge', 'jump', 'accelerate']
        },
        'Geopolitics/Trade': {
            'keywords': ['tariff', 'china', 'chinese', 'trade', 'war', 'geopolitical', 'russia', 'ukraine', 'sanction', 'tension', 'europe', 'asia', 'import', 'export', 'trump', 'biden'],
            'positive': ['deal', 'ease', 'resolve', 'agreement', 'peace', 'relief'],
            'negative': ['tension', 'escalate', 'threat', 'risk', 'war', 'tariff', 'sanction', 'conflict']
        },
        '寃쎄린/怨좎슜': {
            'keywords': ['job', 'jobs', 'employment', 'gdp', 'economy', 'economic', 'recession', 'growth', 'labor', 'unemployment', 'payroll', 'hire', 'hiring', 'layoff', 'worker'],
            'positive': ['strong', 'growth', 'add', 'robust', 'resilient', 'expand', 'hire'],
            'negative': ['weak', 'slow', 'recession', 'layoff', 'decline', 'contract', 'cut']
        },
        'Safe-Haven Assets': {
            'keywords': ['gold', 'silver', 'safe', 'haven', 'precious', 'metal', 'commodity', 'oil', 'crude', 'energy'],
            'positive': ['rally', 'surge', 'demand', 'rise', 'gain', 'climb', 'high'],
            'negative': ['fall', 'drop', 'decline', 'sell', 'low', 'slide', 'tumble']
        },
        'Market Sentiment': {
            'keywords': ['rally', 'selloff', 'sell-off', 'bull', 'bear', 'volatility', 'vix', 'fear', 'optimism', 'sentiment', 'investor', 'market', 'stock', 'stocks', 'wall', 'street', 'dow', 'nasdaq', 's&p', 'index'],
            'positive': ['rally', 'bull', 'optimism', 'confidence', 'buy', 'gain', 'rise', 'surge', 'record', 'high'],
            'negative': ['selloff', 'sell-off', 'bear', 'fear', 'panic', 'sell', 'crash', 'plunge', 'tumble', 'drop', 'fall', 'low']
        }
    }
    
    all_titles = ' '.join([n['title'] for n in news_list]).lower() if news_list else ''
    
    detected_factors = []
    
    for category, data in keyword_categories.items():
        # Category keyword matching
        category_found = False
        matched_keyword = None
        for kw in data['keywords']:
            if kw in all_titles:
                category_found = True
                matched_keyword = kw
                break
        
        if category_found:
            # Determine sentiment direction
            sentiment = 'neutral'
            for pos_kw in data['positive']:
                if pos_kw in all_titles:
                    sentiment = 'positive'
                    break
            if sentiment == 'neutral':
                for neg_kw in data['negative']:
                    if neg_kw in all_titles:
                        sentiment = 'negative'
                        break
            
            detected_factors.append({
                'category': category,
                'sentiment': sentiment,
                'keyword': matched_keyword
            })
    
    return detected_factors

def get_market_interpretation(symbol, name, change_pct, news_list):
    """Build integrated market interpretation block."""
    
    factors = analyze_market_sentiment(change_pct, news_list)
    
    # Price direction
    if change_pct > 1.0:
        direction = "Strong up"
        direction_detail = "Broad upside momentum"
    elif change_pct > 0.3:
        direction = "Up"
        direction_detail = "Moderate upside"
    elif change_pct > -0.3:
        direction = "Flat"
        direction_detail = "Limited movement"
    elif change_pct > -1.0:
        direction = "Down"
        direction_detail = "Moderate downside"
    else:
        direction = "Strong down"
        direction_detail = "Broad downside pressure"
    
    # Key factors (up to 3)
    main_factors = []
    for f in factors[:3]:
        sentiment_icon = "+" if f['sentiment'] == 'positive' else ("-" if f['sentiment'] == 'negative' else "=")
        main_factors.append(f"{sentiment_icon} {f['category']}")
    
    # Fallback factors when news-based signals are sparse
    if not main_factors:
        if symbol == 'QQQM':
            if change_pct > 0.5:
                main_factors = ["+ Tech leadership", "+ AI/semiconductor demand"]
            elif change_pct < -0.5:
                main_factors = ["- Tech weakness", "- Rate pressure concern"]
            else:
                main_factors = ["= Tech mixed", "= Direction unclear"]
        elif symbol == 'SCHD':
            if change_pct > 0.5:
                main_factors = ["+ Dividend strength", "+ Defensive preference"]
            elif change_pct < -0.5:
                main_factors = ["- Dividend weakness", "- Growth rotation"]
            else:
                main_factors = ["= Dividend consolidation", "= Yield stable"]
        elif symbol == 'IAU':
            if change_pct > 0.5:
                main_factors = ["+ Gold strength", "+ Safe-haven demand", "+ USD softness"]
            elif change_pct < -0.5:
                main_factors = ["- Gold weakness", "- Risk-on rotation", "- USD strength"]
            else:
                main_factors = ["= Gold consolidation", "= Wait-and-see flow"]
        else:
            if change_pct > 0.5:
                main_factors = ["+ Market strength", "+ Buy-side inflow"]
            elif change_pct < -0.5:
                main_factors = ["- Market weakness", "- Sell-side pressure"]
            else:
                main_factors = ["= Direction unclear", "= Wait-and-see flow"]
    
    return {
        'direction': direction,
        'direction_detail': direction_detail,
        'factors': main_factors,
        'news': news_list[:2] if news_list else []  # Top 2 headlines
    }

# Gather analysis inputs
with st.spinner('Analyzing market drivers...'):
    qqqm_news = get_market_summary('QQQM')
    schd_news = get_market_summary('SCHD')
    iau_news = get_market_summary('IAU')
    
    # Use broader market headlines when symbol feed is sparse.
    market_news = None
    if not qqqm_news or not schd_news or not iau_news:
        market_news = get_broader_market_news()
    
    if not qqqm_news:
        qqqm_news = market_news or []
    if not schd_news:
        schd_news = market_news or []
    if not iau_news:
        iau_news = market_news or []
    
    qqqm_analysis = get_market_interpretation('QQQM', 'Nasdaq 100', qqqm_data['change_pct'], qqqm_news)
    schd_analysis = get_market_interpretation('SCHD', 'Dividend', schd_data['change_pct'], schd_news)
    iau_analysis = get_market_interpretation('IAU', 'Gold', iau_data['change_pct'], iau_news)

# =====================================================================
# Portfolio summary (top placement)
# =====================================================================
portfolio_change = (
    (qqqm_data['change_pct'] * 0.72) + 
    (schd_data['change_pct'] * 0.16) + 
    (iau_data['change_pct'] * 0.02)
)
portfolio_daily_change = total_value * (portfolio_change / 100)

# Color mapping (up=red, down=blue)
port_color = "#ef4444" if portfolio_change >= 0 else "#3b82f6"
port_bg = "rgba(239, 68, 68, 0.05)" if portfolio_change >= 0 else "rgba(59, 130, 246, 0.05)"
port_icon = "📈" if portfolio_change >= 0 else "📉"

# Build market sentiment summary
def generate_market_summary():
    # Aggregate unique factors
    all_factors = []
    for analysis in [qqqm_analysis, schd_analysis, iau_analysis]:
        for f in analysis['factors']:
            if f not in all_factors:
                all_factors.append(f)
    
    # Market mood by portfolio daily change
    if portfolio_change > 1.5:
        market_mood = "Strong bullish"
        mood_emoji = "BULL"
    elif portfolio_change > 0.5:
        market_mood = "Bullish"
        mood_emoji = "UP"
    elif portfolio_change > -0.5:
        market_mood = "Neutral"
        mood_emoji = "NEUTRAL"
    elif portfolio_change > -1.5:
        market_mood = "Bearish"
        mood_emoji = "DOWN"
    else:
        market_mood = "Strong bearish"
        mood_emoji = "BEAR"
    
    # Extract top-2 key issues
    key_issues = []
    for f in all_factors[:2]:
        # Strip factor sign prefixes
        issue = f.replace("+ ", "").replace("- ", "").replace("= ", "")
        key_issues.append(issue)
    
    if key_issues:
        return f"{mood_emoji} {market_mood} | Key Issues: {', '.join(key_issues)}"
    else:
        return f"{mood_emoji} {market_mood}"

market_summary_text = generate_market_summary()

# Portfolio summary cards
col1, col2, col3 = st.columns([2, 2, 3])

with col1:
    st.markdown(f"""
    <div style="background: #1e293b; 
                border: 2px solid {port_color}; border-radius: 12px; padding: 20px; text-align: center;">
        <p style="color: #cbd5e1; font-size: 0.9em; margin: 0 0 8px 0;">Today's Return</p>
        <p style="color: {port_color}; font-size: 2.4em; font-weight: 800; margin: 0;">
            {port_icon} {portfolio_change:+.2f}%
        </p>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div style="background: #1e293b; 
                border: 2px solid {port_color}; border-radius: 12px; padding: 20px; text-align: center;">
        <p style="color: #cbd5e1; font-size: 0.9em; margin: 0 0 8px 0;">Estimated P/L</p>
        <p style="color: {port_color}; font-size: 2.4em; font-weight: 800; margin: 0;">
            {'+' if portfolio_daily_change >= 0 else ''}${portfolio_daily_change:,.2f}
        </p>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div style="background: #1e293b; 
                border: 2px solid #10b981; border-radius: 12px; padding: 20px;">
        <p style="color: #10b981; font-size: 0.9em; margin: 0 0 10px 0; font-weight: 600;">Market Sentiment Summary</p>
        <p style="color: #f1f5f9; font-size: 1.15em; font-weight: 700; margin: 0; line-height: 1.5;">
            {market_summary_text}
        </p>
    </div>
    """, unsafe_allow_html=True)

# Weight contribution details
st.markdown(f"""
<div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 12px 15px; margin-top: 15px;">
    <p style="color: #e2e8f0; font-size: 0.95em; margin: 0; text-align: center;">
        <span style="color: #10b981; font-weight: 600;">QQQM</span> {qqqm_data['change_pct']:+.2f}% 횞 72% &nbsp;&nbsp;|&nbsp;&nbsp; 
        <span style="color: #3b82f6; font-weight: 600;">SCHD</span> {schd_data['change_pct']:+.2f}% 횞 16% &nbsp;&nbsp;|&nbsp;&nbsp; 
        <span style="color: #fbbf24; font-weight: 600;">IAU</span> {iau_data['change_pct']:+.2f}% 횞 2%
    </p>
</div>
""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# =====================================================================
# Asset detail analysis
# =====================================================================
st.subheader("📊 Asset Detail Analysis")

# QQQM 遺꾩꽍
qqqm_color = "#ef4444" if qqqm_data['change_pct'] >= 0 else "#3b82f6"
qqqm_icon = "📈" if qqqm_data['change_pct'] >= 0 else "📉"

with st.expander(f"🟢 **QQQM (Nasdaq 100)** - {qqqm_icon} {qqqm_data['change_pct']:+.2f}% (${qqqm_data['price']:.2f})", expanded=True):
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background: rgba(16, 185, 129, 0.1); border-radius: 12px;">
            <p style="color: #10b981; font-size: 0.9em; margin: 0;">Today's Direction</p>
            <p style="color: {qqqm_color}; font-size: 1.8em; font-weight: 700; margin: 5px 0;">{qqqm_analysis['direction']}</p>
            <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{qqqm_analysis['direction_detail']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("**Key Drivers**")
        for factor in qqqm_analysis['factors']:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{factor}")
        
        if qqqm_analysis['news']:
            st.markdown("**Related Headlines**")
            for news in qqqm_analysis['news']:
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;[{news['title'][:50]}...]({news['link']})")

# SCHD 遺꾩꽍
schd_color = "#ef4444" if schd_data['change_pct'] >= 0 else "#3b82f6"
schd_icon = "📈" if schd_data['change_pct'] >= 0 else "📉"

with st.expander(f"🔵 **SCHD (Dividend Growth)** - {schd_icon} {schd_data['change_pct']:+.2f}% (${schd_data['price']:.2f})", expanded=True):
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background: rgba(59, 130, 246, 0.1); border-radius: 12px;">
            <p style="color: #3b82f6; font-size: 0.9em; margin: 0;">Today's Direction</p>
            <p style="color: {schd_color}; font-size: 1.8em; font-weight: 700; margin: 5px 0;">{schd_analysis['direction']}</p>
            <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{schd_analysis['direction_detail']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("**Key Drivers**")
        for factor in schd_analysis['factors']:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{factor}")
        
        if schd_analysis['news']:
            st.markdown("**Related Headlines**")
            for news in schd_analysis['news']:
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;[{news['title'][:50]}...]({news['link']})")

# IAU 遺꾩꽍
iau_color = "#ef4444" if iau_data['change_pct'] >= 0 else "#3b82f6"
iau_icon = "📈" if iau_data['change_pct'] >= 0 else "📉"

with st.expander(f"🟡 **IAU (Gold)** - {iau_icon} {iau_data['change_pct']:+.2f}% (${iau_data['price']:.2f})", expanded=True):
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background: rgba(251, 191, 36, 0.1); border-radius: 12px;">
            <p style="color: #fbbf24; font-size: 0.9em; margin: 0;">Today's Direction</p>
            <p style="color: {iau_color}; font-size: 1.8em; font-weight: 700; margin: 5px 0;">{iau_analysis['direction']}</p>
            <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{iau_analysis['direction_detail']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("**Key Drivers**")
        for factor in iau_analysis['factors']:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{factor}")
        
        if iau_analysis['news']:
            st.markdown("**Related Headlines**")
            for news in iau_analysis['news']:
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;[{news['title'][:50]}...]({news['link']})")

# VIX 遺꾩꽍
if vix_data:
    vix_color = "#3b82f6" if vix_data['change_pct'] >= 0 else "#10b981"
    vix_icon = "UP" if vix_data['change_pct'] >= 0 else "DOWN"
    vix_status = "Volatility rising (caution)" if vix_data['change_pct'] >= 0 else "Volatility falling (stabilizing)"
    
    with st.expander(f"🔴 **VIX (Fear Index)** - {vix_icon} {vix_data['change_pct']:+.2f}% ({vix_data['price']:.2f})", expanded=False):
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.markdown(f"""
            <div style="text-align: center; padding: 15px; background: rgba(239, 68, 68, 0.1); border-radius: 12px;">
                <p style="color: #ef4444; font-size: 0.9em; margin: 0;">Market Volatility</p>
                <p style="color: {vix_color}; font-size: 1.5em; font-weight: 700; margin: 5px 0;">{vix_status.split('(')[0].strip()}</p>
                <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">VIX {vix_data['price']:.1f}</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("**VIX Interpretation**")
            if vix_data['price'] <= 14:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;- Very low: overheated market (DEFCON condition)")
            elif vix_data['price'] <= 20:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;= Normal range: typical market volatility")
            elif vix_data['price'] <= 30:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;+ Elevated: unstable market conditions")
            else:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;+ Very high: extreme fear regime")
            
            st.markdown("**Investor Implication**")
            if vix_data['change_pct'] >= 0:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;⚠️ 변동성 증가 중 - 신중한 접근 권장")
            else:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;Volatility is decreasing: potential stabilization signal")

st.markdown("---")

# =====================================================================
# Portfolio history (Google Sheets integration)
# =====================================================================
if gs_available and is_personal_mode:
    with st.expander("📊 포트폴리오 히스토리", expanded=False):
        history_df, history_error = get_portfolio_history()
        
        if history_error:
            st.info(f"Notice: {history_error}")
        elif history_df is not None and len(history_df) > 0:
            # Portfolio value trend chart
            st.subheader("Portfolio Value Trend")
            
            # Prepare chart dataframe
            chart_df = history_df[['Date', 'TotalValue']].dropna().copy()
            chart_df = chart_df.sort_values('Date')
            
            if len(chart_df) > 0:
                # Period selector
                st.markdown("**Select Period**")
                period_options = ["All", "Last 1 week", "Last 1 month", "Last 3 months", "Last 6 months", "Last 1 year", "Custom range"]
                selected_period = st.selectbox("View Period", period_options, index=0, label_visibility="collapsed")
                
                # Apply period filter
                today = pd.Timestamp.now()
                if selected_period == "Last 1 week":
                    start_date = today - pd.Timedelta(days=7)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "Last 1 month":
                    start_date = today - pd.Timedelta(days=30)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "Last 3 months":
                    start_date = today - pd.Timedelta(days=90)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "Last 6 months":
                    start_date = today - pd.Timedelta(days=180)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "Last 1 year":
                    start_date = today - pd.Timedelta(days=365)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "Custom range":
                    col_date1, col_date2 = st.columns(2)
                    with col_date1:
                        min_date = chart_df['Date'].min().date() if len(chart_df) > 0 else today.date()
                        start_date = st.date_input("Start Date", value=min_date, min_value=min_date)
                    with col_date2:
                        max_date = chart_df['Date'].max().date() if len(chart_df) > 0 else today.date()
                        end_date = st.date_input("End Date", value=max_date, max_value=max_date)
                    filtered_df = chart_df[(chart_df['Date'].dt.date >= start_date) & (chart_df['Date'].dt.date <= end_date)]
                else:  # All
                    filtered_df = chart_df
                
                if len(filtered_df) > 0:
                    # Compute y-range dynamically with margin
                    min_val = filtered_df['TotalValue'].min()
                    max_val = filtered_df['TotalValue'].max()
                    value_range = max_val - min_val
                    
                    # Add 5% vertical padding
                    if value_range > 0:
                        y_min = min_val - (value_range * 0.05)
                        y_max = max_val + (value_range * 0.05)
                    else:
                        # Handle flat series
                        y_min = min_val * 0.95
                        y_max = max_val * 1.05
                    
                    # Plotly interactive chart
                    fig = go.Figure()
                    
                    # Add line trace
                    fig.add_trace(go.Scatter(
                        x=filtered_df['Date'],
                        y=filtered_df['TotalValue'],
                        mode='lines+markers',
                        name='Total Assets',
                        line=dict(color='#10b981', width=2),
                        marker=dict(size=6, color='#10b981'),
                        hovertemplate='<b>%{x|%Y-%m-%d %H:%M}</b><br>Total Assets: $%{y:,.2f}<extra></extra>'
                    ))
                    
                    # Mark highest/lowest points
                    max_idx = filtered_df['TotalValue'].idxmax()
                    min_idx = filtered_df['TotalValue'].idxmin()
                    
                    fig.add_trace(go.Scatter(
                        x=[filtered_df.loc[max_idx, 'Date']],
                        y=[filtered_df.loc[max_idx, 'TotalValue']],
                        mode='markers+text',
                        name='High',
                        marker=dict(size=12, color='#ef4444', symbol='triangle-up'),
                        text=[f"${filtered_df.loc[max_idx, 'TotalValue']:,.2f}"],
                        textposition='top center',
                        textfont=dict(color='#ef4444', size=11),
                        hovertemplate='<b>High</b><br>%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>'
                    ))
                    
                    fig.add_trace(go.Scatter(
                        x=[filtered_df.loc[min_idx, 'Date']],
                        y=[filtered_df.loc[min_idx, 'TotalValue']],
                        mode='markers+text',
                        name='Low',
                        marker=dict(size=12, color='#3b82f6', symbol='triangle-down'),
                        text=[f"${filtered_df.loc[min_idx, 'TotalValue']:,.2f}"],
                        textposition='bottom center',
                        textfont=dict(color='#3b82f6', size=11),
                        hovertemplate='<b>Low</b><br>%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>'
                    ))
                    
                    # Layout settings
                    fig.update_layout(
                        title=dict(
                            text=f"Portfolio Value Trend ({selected_period})",
                            font=dict(size=16, color='#f1f5f9')
                        ),
                        xaxis=dict(
                            title="Date",
                            gridcolor='rgba(148, 163, 184, 0.2)',
                            tickformat='%m/%d',
                            rangeslider=dict(visible=True, thickness=0.05),  # Bottom range slider
                        ),
                        yaxis=dict(
                            title="Asset Value (USD)",
                            gridcolor='rgba(148, 163, 184, 0.2)',
                            tickformat='$,.0f',
                            range=[y_min, y_max],  # Dynamic y-range
                        ),
                        plot_bgcolor='rgba(15, 23, 42, 0.8)',
                        paper_bgcolor='rgba(15, 23, 42, 0)',
                        font=dict(color='#94a3b8'),
                        hovermode='x unified',
                        showlegend=True,
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="right",
                            x=1,
                            font=dict(size=11)
                        ),
                        margin=dict(l=10, r=10, t=50, b=10),
                        height=450
                    )
                    
                    # Mode bar settings
                    fig.update_layout(
                        modebar=dict(
                            bgcolor='rgba(15, 23, 42, 0.8)',
                            color='#94a3b8',
                            activecolor='#10b981'
                        )
                    )
                    
                    st.plotly_chart(fig, width='stretch', config={
                        'displayModeBar': True,
                        'modeBarButtonsToAdd': ['drawline', 'eraseshape'],
                        'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
                        'displaylogo': False,
                        'toImageButtonOptions': {
                            'format': 'png',
                            'filename': 'fire25_portfolio_history',
                            'height': 600,
                            'width': 1200,
                            'scale': 2
                        }
                    })
                    
                    # Period statistics
                    st.markdown("---")
                    st.markdown("**Selected Period Stats**")
                    
                    period_first = filtered_df['TotalValue'].iloc[0]
                    period_last = filtered_df['TotalValue'].iloc[-1]
                    period_change = period_last - period_first
                    period_change_pct = (period_change / period_first) * 100 if period_first > 0 else 0
                    period_max = filtered_df['TotalValue'].max()
                    period_min = filtered_df['TotalValue'].min()
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Start", f"${period_first:,.2f}")
                    with col2:
                        st.metric("Current", f"${period_last:,.2f}", f"{period_change_pct:+.2f}%")
                    with col3:
                        st.metric("理쒓퀬", f"${period_max:,.2f}", f"+${period_max - period_first:,.2f}")
                    with col4:
                        st.metric("Low", f"${period_min:,.2f}", f"${period_min - period_first:,.2f}")
                    
                else:
                    st.warning("No data available for the selected period.")
            
            # Recent records table
            st.markdown("---")
            st.subheader("Recent Records")
            display_df = history_df.tail(10).sort_values('Date', ascending=False).copy()
            display_df['TotalValue'] = display_df['TotalValue'].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "-")
            display_df['Date'] = pd.to_datetime(display_df['Date']).dt.strftime('%Y-%m-%d %H:%M')
            st.dataframe(display_df, width='stretch', hide_index=True)
elif is_personal_mode and not gs_available:
    st.info("🔎 Personal Mode 히스토리를 보려면 Google Sheets 연동이 필요합니다.")
else:
    st.markdown("### 📊 포트폴리오 히스토리")
    st.markdown(
        """
        <div style="background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.35); border-radius: 10px; padding: 14px;">
            <p style="margin: 0; color: #e2e8f0; font-weight: 600;">📢 Public Mode 안내</p>
            <p style="margin: 8px 0 0 0; color: #94a3b8;">
                Public Mode에서는 개인 포트폴리오 히스토리를 저장/조회하지 않습니다.
                상세 히스토리 기능은 Personal Mode에서만 활성화됩니다.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("---")
st.markdown("""
<p style='text-align: center; color: #94a3b8; font-size: 0.9em;'>
    📚 TEAM FIRE 25 투자 매뉴얼 v5.10 기반<br>
    📡 데이터 출처: Yahoo Finance (15-20분 지연)<br>
    ⚠️ 본 대시보드는 투자 참고용이며, 투자 결정은 본인 책임입니다.</p>
""", unsafe_allow_html=True)

