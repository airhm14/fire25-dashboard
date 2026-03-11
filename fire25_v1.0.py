# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import logging
import re
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
from fire25.news_engine import get_news_brief
from fire25.ai_advisor import build_context, get_ai_advice
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


LOGGER = logging.getLogger(__name__)


def fmt_money(x):
    return f"${x:,.2f}" if x is not None else "-"


def fmt_num(x, d=2):
    return f"{x:,.{d}f}" if x is not None else "-"


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
    page_title="TEAM FIRE 25 대시보드",
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
            <p style="color: #94a3b8; margin-bottom: 30px;">대시보드에 접속하려면 비밀번호를 입력하세요.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input(
            "비밀번호",
            type="password",
            on_change=password_entered,
            key="password_input",
            placeholder="비밀번호를 입력하세요..."
        )
        
        if "password_correct" in st.session_state and not st.session_state["password_correct"]:
            st.error("비밀번호가 올바르지 않습니다")
        
        st.markdown("""
        <p style="text-align: center; color: #64748b; font-size: 0.85em; margin-top: 20px;">
            비밀번호는 Streamlit Secrets에서 설정됩니다.
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
    
    /* 상승 move = red */
    .positive { color: #ef4444; }
    
    /* 하락 move = blue */
    .negative { color: #3b82f6; }
    
    /* 경고 박스 */
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
            return None, "포트폴리오 워크시트를 찾을 수 없습니다. 저장 버튼을 한 번 눌러 생성하세요."
        return None, f"데이터 불러오기 실패: {error_msg}"

def save_portfolio_to_sheets(qqqm, schd, iau, sgov, cash, new_cash, total_value):
    """저장 portfolio data to Google Sheets."""
    client, error = get_google_sheets_client()
    if error:
        return False, error
    
    try:
        sheet_url = st.secrets.get("spreadsheet_url", "")
        if not sheet_url:
            return False, "스프레드시트 URL이 설정되지 않았습니다."
        
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
        
        return True, "저장 완료"
    except Exception as e:
        return False, f"저장 실패: {str(e)}"

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
            return None, "히스토리 데이터가 없습니다."
        
        # Convert rows into a DataFrame.
        headers = all_data[0]
        data = all_data[1:]
        
        history_df = pd.DataFrame(data, columns=headers)
        history_df['TotalValue'] = pd.to_numeric(history_df['TotalValue'], errors='coerce')
        history_df['Date'] = pd.to_datetime(history_df['Date'], format='%Y-%m-%d %H:%M', errors='coerce')
        
        return history_df, None
    except Exception as e:
        return None, f"히스토리 불러오기 실패: {str(e)}"

# Check Google Sheets connection state
gs_available = "gcp_service_account" in st.secrets if hasattr(st, 'secrets') else False

# =====================================================================
# Sidebar: portfolio inputs
# =====================================================================
portfolio_mode = "개인 모드"
is_personal_mode = True
sheets_saved_data = None

with st.sidebar:
    st.header("📊 포트폴리오 설정")

    portfolio_mode = st.radio(
        "포트폴리오 모드",
        ["개인 모드", "공개 모드"],
        index=0,
        help="개인: Google Sheets 연동 / 공개: 저장 없이 데모용",
    )
    is_personal_mode = portfolio_mode == "개인 모드"
    
    # Show Google Sheets status
    if is_personal_mode:
        if gs_available:
            sheets_saved_data, load_error = load_portfolio_from_sheets()
            if load_error and "저장된 데이터가 없습니다." not in load_error:
                st.warning(f"⚠️ {load_error}")
            elif sheets_saved_data:
                st.success(f"🟢 마지막 저장: {sheets_saved_data['date']}")
            else:
                st.info("☁️ Google Sheets 연결됨")
        else:
            st.info("☁️ Google Sheets 미연결")
    else:
        st.warning("📢 공개 모드: 개인 히스토리 저장/조회가 비활성화됩니다.")
    
    st.subheader("보유 자산")
    
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
    backtest_enabled = st.toggle("백테스트 (실험)", value=False)
    backtest_vol_adjust = st.toggle("변동성 조정 비중", value=False, disabled=not backtest_enabled)
    
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
                "<p style='text-align: center; margin-top: 6px;'><span style='background: #7c2d12; color: #ffedd5; border: 1px solid #fb923c; border-radius: 999px; padding: 2px 10px; font-size: 0.75em; font-weight: 700;'>데모</span></p>",
                unsafe_allow_html=True,
            )
    
    # 새로고침 button clears Streamlit cache.
    if refresh_button:
        st.cache_data.clear()
        st.success("캐시를 초기화했습니다. 최신 데이터를 불러오는 중입니다...")
        st.rerun()
    
    # Defer 저장 handling until total_value is computed.
    if 'save_clicked' not in st.session_state:
        st.session_state.save_clicked = False
    if save_button:
        st.session_state.save_clicked = True

if not is_personal_mode:
    st.info("공개 포트폴리오 모드: 입력한 포트폴리오 데이터는 저장되지 않습니다.")

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
            "거래량": [0.0],
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
    st.error("핵심 자산(QQQM) 데이터를 불러오지 못했습니다. 새로고침 후 다시 시도하세요.")
    st.stop()

if schd_data is None:
    st.warning("⚠️ SCHD 데이터 조회 실패로 중립 데이터로 대체합니다.")
    schd_data = _build_placeholder_asset("SCHD")

if iau_data is None:
    st.warning("⚠️ IAU 데이터 조회 실패로 중립 데이터로 대체합니다.")
    iau_data = _build_placeholder_asset("IAU")

# 공포 탐욕 지수 fetch (cached for 30 minutes)
@st.cache_data(ttl=1800)
def get_fear_greed_index():
    """Fetch CNN Fear and Greed Index."""
    
    # 방법 1: CNN 공식 API
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
                        'classification': fng.get('rating', '중립'),
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
                    'classification': data.get('rating', '중립'),
                    'previous': data.get('previous_close', None),
                    'source': 'CNN'
                }
    except:
        pass
    
    # Data unavailable
    return None

with st.spinner('공포·탐욕 지수 불러오는 중...'):
    fng_data = get_fear_greed_index()

# =====================================================================
# 2) Indicator Calculation
# =====================================================================

# SGOV price (use fallback when unavailable)
if sgov_data:
    sgov_price = sgov_data['price']
else:
    sgov_price = 100.50  # SGOV 기본 추정가

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
        st.sidebar.error(f"오류: {message}")
    st.session_state.save_clicked = False

# =====================================================================
# Sidebar: cash and source summary
# =====================================================================
with st.sidebar:
    st.markdown("---")
    st.markdown("### 현금성 자산")
    
    # SGOV snapshot
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("SGOV", f"{sgov_qty:,.2f}주")
    with col2:
        st.metric("현재가", f"${sgov_price:.2f}")
    
    st.markdown(f"**SGOV 평가금** :green[${sgov_value:,.2f}]")
    st.markdown(f"**예수금** ${cash_deposit:,.2f}")
    st.markdown(f"**현금성 자산 합계:** :blue[${total_cash:,.2f}]")
    
    if new_cash > 0:
        st.markdown("---")
        st.markdown(f"**+ 신규 자금:** :blue[${new_cash:,.2f}]")
        st.markdown(f"**입금 반영 총액:** :orange[${total_cash + new_cash:,.2f}]")

    st.markdown("---")
    st.markdown("### 데이터 소스")
    for display_name, symbol in [
        ("QQQM", "QQQM"),
        ("SCHD", "SCHD"),
        ("IAU", "IAU"),
        ("SGOV", "SGOV"),
        ("VIX(^VIX)", "^VIX"),
    ]:
        st.caption(f"{display_name}: {asset_source_label(symbol)}")
    st.caption(f"환율 기준: 1 USD = {fx_krw_per_usd:,.2f} KRW")

# =====================================================================
# Main dashboard (Decision-first terminal)
# =====================================================================

@st.cache_data(ttl=1800)
def fetch_news_brief(lookback_days=2, max_articles=20, region="US", asset_focus="growth"):
    """뉴스 기반 거시 브리핑 캐시 fetch."""
    try:
        return get_news_brief(
            lookback_days=lookback_days,
            max_articles=max_articles,
            region=region,
            asset_focus=asset_focus,
        )
    except Exception:
        return {
            "status": "fallback",
            "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "article_count": 0,
            "headline_summary": "뉴스 데이터를 불러오지 못해 지표 기반 요약을 우선 표시합니다.",
            "macro_drivers": [],
            "market_implication": "시장 방향은 아직 불확실합니다. 금리 흐름 확인이 필요합니다.",
            "portfolio_implication": "방어 비중을 유지하고 신호 확인 후 분할 접근이 유효합니다.",
            "asset_implications": {
                "QQQM": "성장주 변동성 확대 가능성을 점검하세요.",
                "SCHD": "배당 방어 역할을 확인하세요.",
                "IAU": "지정학 리스크 헤지 흐름을 확인하세요.",
                "SGOV": "현금 대기 전략 유효성을 점검하세요.",
            },
            "watch_points": ["미국 10년물 금리", "VIX 방향"],
            "sentiment_score": 0.0,
            "risk_level": "MODERATE",
            "risk_level_label": "보통",
            "core_article_count": 0,
            "secondary_article_count": 0,
            "articles": [],
            "brief_source": "rule_based",
        }


@st.cache_data(ttl=900)
def fetch_macro_market_metrics():
    """Fetch 10Y treasury and oil as macro dashboard inputs."""
    tnx = get_stock_data("^TNX", period="1mo")
    oil = get_stock_data("CL=F", period="1mo")
    return tnx, oil


def short_korean(text: str, max_sentences: int = 2) -> str:
    """Trim narrative into short dashboard-friendly Korean lines."""
    src = str(text or "").strip()
    if not src:
        return "데이터가 부족합니다."
    parts = [
        p.strip()
        for p in re.split(r"[.!?]\s*", src)
        if p.strip()
    ]
    if not parts:
        return src
    return "\n".join(parts[: max(1, int(max_sentences))])


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def detect_market_events(vix, fng, tnx, oil, brief) -> list[str]:
    """Detect macro shock events with robust null handling."""
    events: list[str] = []
    vix_value = _safe_float((vix or {}).get("price"), 20.0)
    oil_value = _safe_float((oil or {}).get("price"), 0.0)
    tnx_chg = _safe_float((tnx or {}).get("change_pct"), 0.0)
    fng_value = _safe_int((fng or {}).get("value"), 50)
    nb = brief if isinstance(brief, dict) else {}
    drivers = nb.get("macro_drivers", [])
    if not isinstance(drivers, list):
        drivers = []
    dom_categories = nb.get("dominant_categories", [])
    if not isinstance(dom_categories, list):
        dom_categories = []

    if vix_value > 30:
        events.append("VIX 상승 - 변동성 확대")
    if oil_value > 100:
        events.append("유가 급등 - 에너지 리스크")
    if "GEOPOLITICAL_CONFLICT" in dom_categories or any("지정학" in str(x) for x in drivers):
        events.append("지정학 충격 - 리스크오프 경계")
    if tnx_chg > 2.0:
        events.append("장기금리 급등 - 밸류에이션 압박")
    if fng_value <= 20:
        events.append("심리 급랭 - 공포 구간 진입")
    return events


def build_risk_radar(vix, fng, brief) -> dict[str, int]:
    """Build stable macro risk radar even with missing data."""
    vix_value = _safe_float((vix or {}).get("price"), 20.0)
    fng_value = _safe_int((fng or {}).get("value"), 50)
    nb = brief if isinstance(brief, dict) else {}
    drivers = nb.get("macro_drivers", [])
    if not isinstance(drivers, list):
        drivers = []
    dom_categories = nb.get("dominant_categories", [])
    if not isinstance(dom_categories, list):
        dom_categories = []

    geo_hint = any("지정학" in str(x) for x in drivers) or ("GEOPOLITICAL_CONFLICT" in dom_categories)
    infl_hint = ("INFLATION_PRESSURE" in dom_categories) or ("ENERGY_SUPPLY_RISK" in dom_categories)

    radar = defaultdict(int)
    radar["금리 리스크"] = min(100, max(0, int(vix_value * 2.2)))
    radar["인플레이션 리스크"] = min(100, 75 if infl_hint else 45)
    radar["지정학 리스크"] = 80 if geo_hint else 35
    radar["시장 스트레스"] = min(100, max(0, int((100 - fng_value) * 1.2)))
    return dict(radar)


news_brief = fetch_news_brief(lookback_days=2, max_articles=20, region="US", asset_focus="growth")
if not isinstance(news_brief, dict):
    news_brief = {}
market_news = news_brief.get("articles", []) if isinstance(news_brief, dict) else []
if not isinstance(market_news, list):
    market_news = []
macro_summary = summarize_macro_today(
    vix_data=vix_data,
    fng_data=fng_data,
    qqqm_data=qqqm_data,
    sgov_data=sgov_data,
    market_news=market_news,
    news_brief=news_brief,
)
if not isinstance(macro_summary, dict):
    macro_summary = {}
regime_info = detect_market_regime(
    qqqm_data["df"],
    vix_data["price"] if vix_data else None,
)
if not isinstance(regime_info, dict):
    regime_info = {}
tnx_data, oil_data = fetch_macro_market_metrics()
if not isinstance(tnx_data, dict):
    tnx_data = {}
if not isinstance(oil_data, dict):
    oil_data = {}

LOGGER.debug("news_brief keys: %s", list(news_brief.keys()))
LOGGER.debug("macro_summary keys: %s", list(macro_summary.keys()))

# Strategy/risk signals reused across tabs.
defcon_triggered = detect_defcon(vix_data["price"] if vix_data else None, qqqm_data.get("rsi"))
puddle_result = calculate_puddle_signal(qqqm_data["df"], cooldown_days=30)
puddle_stage = puddle_result.stage
shoulder_eval = evaluate_smart_shoulder(qqqm_data['df'], qqqm_pct)
smart_shoulder_triggered = bool(shoulder_eval['triggered'])

puddle_alert = puddle_result.alert
puddle_cooldown_active = puddle_result.cooldown_active
cooldown_info = puddle_result.cooldown_info or ""
rebalancing_needed = bool(shoulder_eval.get('rebalancing_needed'))

tab1, tab2, tab3 = st.tabs([
    "내 자산 현황",
    "시장 현황",
    "거시경제 & 전략",
])

# =====================================================================
# TAB 1 — 내 자산 현황
# =====================================================================
with tab1:
    st.header("내 자산 현황")

    # ── Portfolio summary metrics ──
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 자산", f"${total_value:,.2f}")
    c2.metric("QQQM", f"{qqqm_pct:.1f}%")
    c3.metric("SCHD", f"{schd_pct:.1f}%")
    c4.metric("IAU", f"{iau_pct:.1f}%")
    c5.metric("현금", f"{cash_pct:.1f}%")

    # ── Daily P&L (estimated) ──
    portfolio_change = (
        (qqqm_data['change_pct'] * 0.72)
        + (schd_data['change_pct'] * 0.16)
        + (iau_data['change_pct'] * 0.02)
    )
    portfolio_daily_change = total_value * (portfolio_change / 100)
    port_color = "#ef4444" if portfolio_change >= 0 else "#3b82f6"
    port_icon = "📈" if portfolio_change >= 0 else "📉"

    pc1, pc2 = st.columns(2)
    with pc1:
        st.markdown(f"""
        <div style="background:#1e293b; border:2px solid {port_color}; border-radius:12px; padding:18px; text-align:center;">
            <p style="color:#cbd5e1; font-size:0.9em; margin:0 0 6px 0;">오늘 수익률</p>
            <p style="color:{port_color}; font-size:2.2em; font-weight:800; margin:0;">{port_icon} {portfolio_change:+.2f}%</p>
        </div>""", unsafe_allow_html=True)
    with pc2:
        st.markdown(f"""
        <div style="background:#1e293b; border:2px solid {port_color}; border-radius:12px; padding:18px; text-align:center;">
            <p style="color:#cbd5e1; font-size:0.9em; margin:0 0 6px 0;">예상 손익</p>
            <p style="color:{port_color}; font-size:2.2em; font-weight:800; margin:0;">{'+'if portfolio_daily_change>=0 else ''}${portfolio_daily_change:,.2f}</p>
        </div>""", unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:#0f172a; border:1px solid #334155; border-radius:8px; padding:10px 14px; margin-top:12px;">
        <p style="color:#e2e8f0; font-size:0.92em; margin:0; text-align:center;">
            <span style="color:#10b981; font-weight:600;">QQQM</span> {qqqm_data['change_pct']:+.2f}% × 72%
            &nbsp;|&nbsp;
            <span style="color:#3b82f6; font-weight:600;">SCHD</span> {schd_data['change_pct']:+.2f}% × 16%
            &nbsp;|&nbsp;
            <span style="color:#fbbf24; font-weight:600;">IAU</span> {iau_data['change_pct']:+.2f}% × 2%
        </p>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Asset table with target diff ──
    asset_table = pd.DataFrame({
        'Asset': ['QQQM', 'SCHD', 'IAU', 'SGOV', '예수금', '현금 합계'],
        'Value': [qqqm_value, schd_value, iau_value, sgov_value, cash_deposit, total_cash],
        '현재 비중 (%)': [qqqm_pct, schd_pct, iau_pct, sgov_pct, deposit_pct, cash_pct],
        '목표 비중 (%)': ['72.00%', '16.00%', '2.00%', '-', '-', '10.00%'],
        '목표 대비 차이 (%p)': [
            f'{qqqm_pct - 72:+.2f}%p',
            f'{schd_pct - 16:+.2f}%p',
            f'{iau_pct - 2:+.2f}%p',
            '-', '-',
            f'{cash_pct - 10:+.2f}%p',
        ],
    })

    def _highlight_rows(row):
        if row['Asset'] == '현금 합계':
            return ['background-color: rgba(59, 130, 246, 0.1)'] * len(row)
        if row['Asset'] in ['SGOV', '예수금']:
            return ['background-color: rgba(148, 163, 184, 0.05)'] * len(row)
        return [''] * len(row)

    st.dataframe(
        asset_table.style.format({'Value': '${:,.2f}', '현재 비중 (%)': '{:.2f}%'}).apply(_highlight_rows, axis=1),
        width='stretch', hide_index=True,
    )

    # ── Pie chart ──
    fig_alloc = go.Figure(data=[go.Pie(
        labels=['QQQM', 'SCHD', 'IAU', 'SGOV', '예수금'],
        values=[qqqm_value, schd_value, iau_value, sgov_value, cash_deposit],
        hole=0.45,
        marker=dict(colors=['#10b981', '#3b82f6', '#fbbf24', '#94a3b8', '#64748b']),
        textinfo='label+percent',
        textfont=dict(size=11, color='white'),
        textposition='inside',
    )])
    fig_alloc.update_layout(
        height=380,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'),
        margin=dict(l=20, r=20, t=10, b=10),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=0, xanchor="center", x=0.5, font=dict(size=10)),
    )
    st.plotly_chart(fig_alloc, width='stretch', config={'displayModeBar': False})

    st.markdown("---")

    # ── Portfolio history ──
    from fire25.storage.portfolio_history import render_portfolio_history
    render_portfolio_history(gs_available, is_personal_mode)

    # ── FIRE Simulator ──
    with st.expander("FIRE 시뮬레이터", expanded=False):
        st.caption("과거 수익률을 기반으로 미래 포트폴리오 경로를 부트스트랩하여 장기 FIRE 달성 가능성을 추정합니다.")

        mc_col1, mc_col2, mc_col3 = st.columns(3)
        with mc_col1:
            mc_symbol = st.selectbox("시뮬레이션 종목", ["QQQM", "SPY", "VTI", "BTC-USD"], index=0, key="mc_sym")
        with mc_col2:
            mc_start_date = st.date_input("수익률 시작일", value=pd.Timestamp("2012-01-01").date(), key="mc_sd")
        with mc_col3:
            mc_years = st.slider("투자 기간 (년)", min_value=5, max_value=40, value=20, step=1, key="mc_yr")

        mc_col4, mc_col5, mc_col6 = st.columns(3)
        with mc_col4:
            mc_initial = st.number_input("초기 자본", min_value=1000.0, value=max(total_value, 10000.0), step=1000.0, key="mc_init")
        with mc_col5:
            mc_annual_inv = st.number_input("연간 투자금", min_value=0.0, value=12000.0, step=1000.0, key="mc_ann")
        with mc_col6:
            mc_target = st.number_input("목표 FIRE 자본", min_value=10000.0, value=1000000.0, step=10000.0, key="mc_tgt")

        mc_simulations = st.slider("시뮬레이션 수", min_value=200, max_value=5000, value=1000, step=100, key="mc_n")
        mc_run = st.button("FIRE 시뮬레이션 실행", width='stretch', key="mc_btn")

        if mc_run:
            with st.spinner("몬테카를로 FIRE 시뮬레이션 실행 중..."):
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
            sc1.metric("최종 중앙값", f"${mc_stats['median_final_value']:,.0f}")
            sc2.metric("5백분위", f"${mc_stats['5th_percentile']:,.0f}")
            sc3.metric("95백분위", f"${mc_stats['95th_percentile']:,.0f}")
            sc4.metric("FIRE 달성 확률", f"{fire_prob * 100:.1f}%")

            st.plotly_chart(plot_monte_carlo(sim_paths), width='stretch', config={"displayModeBar": False})

            final_values = sim_paths.iloc[-1].astype(float)
            fig_dist = go.Figure()
            fig_dist.add_trace(go.Histogram(x=final_values.values, nbinsx=50, marker_color="#3b82f6", opacity=0.85, name="최종 자산"))
            fig_dist.add_vline(x=float(mc_target), line_color="#ef4444", line_dash="dash", annotation_text="FIRE 목표")
            fig_dist.update_layout(
                height=300,
                xaxis=dict(title="최종 포트폴리오 가치 (USD)", gridcolor="rgba(148,163,184,0.2)"),
                yaxis=dict(title="건수", gridcolor="rgba(148,163,184,0.2)"),
                plot_bgcolor="rgba(30,41,59,0.5)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0"), margin=dict(l=40, r=20, t=20, b=20),
            )
            st.plotly_chart(fig_dist, width='stretch', config={"displayModeBar": False})

# =====================================================================
# TAB 2 — 시장 현황
# =====================================================================
with tab2:
    st.header("시장 현황")

    # ── Real-time quotes ──
    q1, q2, q3, q4 = st.columns(4)
    with q1:
        st.metric(label="QQQM (성장 코어)", value=f"${qqqm_data['price']:.2f}", delta=f"{qqqm_data['change_pct']:+.2f}%")
        st.markdown(f"<p style='font-size:0.85em; color:#94a3b8;'>거래량: {qqqm_data['volume']:,.0f}</p>", unsafe_allow_html=True)
    with q2:
        st.metric(label="SCHD (배당 코어)", value=f"${schd_data['price']:.2f}", delta=f"{schd_data['change_pct']:+.2f}%")
        st.markdown(f"<p style='font-size:0.85em; color:#94a3b8;'>거래량: {schd_data['volume']:,.0f}</p>", unsafe_allow_html=True)
    with q3:
        st.metric(label="IAU (금 ETF)", value=f"${iau_data['price']:.2f}", delta=f"{iau_data['change_pct']:+.2f}%")
        st.markdown(f"<p style='font-size:0.85em; color:#94a3b8;'>거래량: {iau_data['volume']:,.0f}</p>", unsafe_allow_html=True)
    with q4:
        if sgov_data:
            st.metric(label="SGOV (현금성 ETF)", value=f"${sgov_price:.2f}", delta=f"{sgov_data['change_pct']:+.2f}%")
        else:
            st.metric(label="SGOV (현금성 ETF)", value=f"${sgov_price:.2f}")
        st.markdown(f"<p style='font-size:0.85em; color:#94a3b8;'>보유: {sgov_qty:,.2f}주</p>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── VIX / Fear & Greed detailed cards ──
    col_vix, col_fng = st.columns(2)

    with col_vix:
        if vix_data:
            _vix_price = vix_data['price']
            _vix_chg = vix_data['change_pct']
            vix_color = "#10b981" if _vix_price <= 20 else ("#fbbf24" if _vix_price <= 30 else "#ef4444")
            vix_status = "안정" if _vix_price <= 14 else ("정상" if _vix_price <= 20 else ("주의" if _vix_price <= 30 else "위험"))
            defcon_warning = "⚠️ DEFCON 조건!" if _vix_price <= 14.0 else ""
            st.markdown(f"""
            <div style="background:#1e293b; border:2px solid {vix_color}; border-radius:12px; padding:20px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <p style="color:#94a3b8; font-size:0.9em; margin:0;">VIX (변동성 지수)</p>
                        <p style="color:{vix_color}; font-size:2.5em; font-weight:800; margin:5px 0;">{_vix_price:.2f}</p>
                        <p style="color:{'#ef4444' if _vix_chg > 0 else '#10b981'}; font-size:1em; margin:0;">
                            {'📈' if _vix_chg > 0 else '📉'} {_vix_chg:+.2f}%
                        </p>
                    </div>
                    <div style="text-align:right;">
                        <p style="color:{vix_color}; font-size:1.5em; font-weight:700; margin:0;">{vix_status}</p>
                        <p style="color:#ef4444; font-size:1em; font-weight:700; margin:5px 0;">{defcon_warning}</p>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)
        else:
            st.warning("VIX 데이터 없음")

    with col_fng:
        if fng_data:
            _fng_val = fng_data['value']
            if _fng_val >= 75:
                fng_color, fng_label, fng_icon, fng_advice = "#ef4444", "극단적 탐욕", "🔴", "시장 과열 주의"
            elif _fng_val >= 55:
                fng_color, fng_label, fng_icon, fng_advice = "#f97316", "탐욕", "🟡", "상승 추세"
            elif _fng_val >= 45:
                fng_color, fng_label, fng_icon, fng_advice = "#fbbf24", "중립", "🟡", "관망세"
            elif _fng_val >= 25:
                fng_color, fng_label, fng_icon, fng_advice = "#3b82f6", "공포", "🔵", "매수 기회 탐색"
            else:
                fng_color, fng_label, fng_icon, fng_advice = "#8b5cf6", "극단적 공포", "🔴", "역추세 매수 고려"
            prev_value = fng_data.get('previous')
            fng_change_str = ""
            if prev_value:
                try:
                    prev_val = int(prev_value)
                    fng_change = _fng_val - prev_val
                    fng_change_str = f"{'📈' if fng_change > 0 else '📉'} {fng_change:+d} (전일대비)"
                except Exception:
                    pass
            st.markdown(f"""
            <div style="background:#1e293b; border:2px solid {fng_color}; border-radius:12px; padding:20px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <p style="color:#94a3b8; font-size:0.9em; margin:0;">공포·탐욕 지수</p>
                        <p style="color:{fng_color}; font-size:2.5em; font-weight:800; margin:5px 0;">{_fng_val}</p>
                        <p style="color:#94a3b8; font-size:0.9em; margin:0;">{fng_change_str}</p>
                    </div>
                    <div style="text-align:right;">
                        <p style="font-size:1.8em; margin:0;">{fng_icon}</p>
                        <p style="color:{fng_color}; font-size:1.3em; font-weight:700; margin:5px 0;">{fng_label}</p>
                        <p style="color:#94a3b8; font-size:0.85em; margin:0;">{fng_advice}</p>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="background:#1e293b; border:2px solid #475569; border-radius:12px; padding:20px;">
                <p style="color:#94a3b8; font-size:0.9em; margin:0;">공포·탐욕 지수</p>
                <p style="color:#64748b; font-size:2.5em; font-weight:800; margin:5px 0;">N/A</p>
                <p style="color:#475569; font-size:0.85em; margin:0;">CNN 연결 실패</p>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Market regime ──
    regime_label_map = {"BULL": "🟢 상승장", "CORRECTION": "🟡 조정장", "BEAR": "🔴 하락장", "RECOVERY": "🔵 회복장"}
    regime_color_map = {"BULL": "#10b981", "CORRECTION": "#f59e0b", "BEAR": "#ef4444", "RECOVERY": "#3b82f6"}
    regime_raw = regime_info.get("regime", "CORRECTION")
    regime_conf = _safe_float(regime_info.get('confidence', 0.0), 0.0)
    r_label = regime_label_map.get(regime_raw, "🟡 조정장")
    r_color = regime_color_map.get(regime_raw, "#f59e0b")
    st.markdown(f"<span style='background:{r_color}; color:white; padding:6px 14px; border-radius:6px; font-weight:700;'>{r_label}</span>", unsafe_allow_html=True)
    st.caption(f"신뢰도: {regime_conf * 100:.1f}%")
    for item in regime_info.get("reason", []):
        st.markdown(f"- {item}")

    st.markdown("---")

    # ── Strategy condition cards (DEFCON / Puddle / Smart Shoulder) ──
    st.subheader("전략 조건 분석")

    if defcon_triggered:
        st.markdown(f"""
        <div class="warning-box">
            <div class="warning-title">⚠️ DEFCON 세이빙 발동</div>
            <p><strong>VIX:</strong> {vix_data['price']:.2f} (&le; 14.00)&nbsp;&nbsp;
            <strong>RSI:</strong> {qqqm_data['rsi']:.2f} (&ge; 70)</p>
            <p><strong>조치:</strong> 신규 자금 100%를 SGOV로 배분 (QQQM/SCHD/IAU 매수 차단)</p>
        </div>""", unsafe_allow_html=True)

    if puddle_alert:
        _stage_info = {
            1: {"name": "1단계: SMA50 하향 이탈", "color": "#fbbf24", "rate": 15},
            2: {"name": "2단계: SMA100 하향 이탈", "color": "#f97316", "rate": 35},
            3: {"name": "3단계: SMA200 하향 이탈", "color": "#ef4444", "rate": 50},
            4: {"name": "4단계: SMA200 회복", "color": "#10b981", "rate": 100},
        }
        _si = _stage_info.get(puddle_stage, _stage_info[1])
        _remaining_cash = sgov_value + cash_deposit
        _injection = compute_deployment(puddle_stage, _remaining_cash)
        st.markdown(f"""
        <div class="warning-box" style="border-color:{_si['color']};">
            <div class="warning-title" style="color:{_si['color']};">웅덩이 진입: {_si['name']}</div>
            <p><strong>현재가:</strong> ${qqqm_data['price']:.2f}</p>
            <p><strong>투입 비율:</strong> {_si['rate']}% &nbsp;|&nbsp; <strong>투입 금액:</strong> ${_injection:,.2f}</p>
            <p style="color:#10b981; font-weight:700;">신규 자금은 목표 비중 72/16/2/10으로 즉시 배분합니다.</p>
        </div>""", unsafe_allow_html=True)

    if puddle_cooldown_active and not puddle_alert:
        st.markdown(f"""
        <div class="info-box">
            <div class="warning-title">웅덩이 쿨다운 진행 중</div>
            <p><strong>현재가:</strong> ${qqqm_data['price']:.2f} (대기)</p>
            <p><strong>판단 근거:</strong> {cooldown_info if cooldown_info else "최근 30일 이내 신호 발생"}</p>
            <p style="color:#fbbf24;"><strong>조치:</strong> 다음 유효 신호를 대기합니다.</p>
        </div>""", unsafe_allow_html=True)

    if rebalancing_needed and not smart_shoulder_triggered:
        _excess = qqqm_pct - 72
        st.info(f"QQQM 과비중 감지: {qqqm_pct:.2f}% (초과 +{_excess:.2f}%p) — Smart Shoulder 트리거 대기")

    if smart_shoulder_triggered:
        _excess = qqqm_pct - 72
        st.error(f"Smart Shoulder 리밸런싱 발동: QQQM {qqqm_pct:.2f}% (초과 +{_excess:.2f}%p) → 72/16/2/10 복귀")

    # ── RSI / SMA indicator cards ──
    ic1, ic2, ic3 = st.columns(3)
    with ic1:
        _rsi = qqqm_data.get('rsi', 50.0)
        _rc = "#ef4444" if _rsi >= 70 else ("#3b82f6" if _rsi <= 30 else "#10b981")
        _rs = "과열" if _rsi >= 70 else ("과매도" if _rsi <= 30 else "중립")
        st.markdown(f"""
        <div style="text-align:center; padding:20px; background:linear-gradient(135deg,rgba(30,41,59,0.8),rgba(51,65,85,0.8)); border-radius:12px; border:2px solid {_rc};">
            <p style="font-size:0.9em; color:#cbd5e1; margin-bottom:8px; font-weight:600;">RSI(14)</p>
            <p style="font-size:2.5em; font-weight:700; color:{_rc}; margin:10px 0;">{_rsi:.2f}</p>
            <p style="font-size:1.1em; color:{_rc}; font-weight:600;">{_rs}</p>
        </div>""", unsafe_allow_html=True)
    with ic2:
        _sma20 = qqqm_data.get('sma_20', 0.0)
        _sc = "#10b981" if qqqm_data['price'] > _sma20 else "#fbbf24"
        _ss = "SMA20 상회" if qqqm_data['price'] > _sma20 else "SMA20 하회"
        st.markdown(f"""
        <div style="text-align:center; padding:20px; background:linear-gradient(135deg,rgba(30,41,59,0.8),rgba(51,65,85,0.8)); border-radius:12px; border:2px solid {_sc};">
            <p style="font-size:0.9em; color:#cbd5e1; margin-bottom:8px; font-weight:600;">SMA20</p>
            <p style="font-size:2.5em; font-weight:700; color:{_sc}; margin:10px 0;">${_sma20:.2f}</p>
            <p style="font-size:1.1em; color:{_sc}; font-weight:600;">{_ss}</p>
        </div>""", unsafe_allow_html=True)
    with ic3:
        _sma50 = qqqm_data.get('sma_50', 0.0)
        if pd.notna(_sma50) and qqqm_data['price'] > _sma50:
            _sc2, _ss2 = "#10b981", "SMA50 상회"
        elif pd.notna(_sma50):
            _sc2, _ss2 = "#ef4444", "SMA50 하회"
        else:
            _sc2, _ss2 = "#94a3b8", "데이터 부족"
        _sma50_d = f"${_sma50:.2f}" if pd.notna(_sma50) else "-"
        st.markdown(f"""
        <div style="text-align:center; padding:20px; background:linear-gradient(135deg,rgba(30,41,59,0.8),rgba(51,65,85,0.8)); border-radius:12px; border:2px solid {_sc2};">
            <p style="font-size:0.9em; color:#cbd5e1; margin-bottom:8px; font-weight:600;">SMA50</p>
            <p style="font-size:2.5em; font-weight:700; color:{_sc2}; margin:10px 0;">{_sma50_d}</p>
            <p style="font-size:1.1em; color:{_sc2}; font-weight:600;">{_ss2}</p>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    ic4, ic5, ic6 = st.columns(3)
    with ic4:
        _sma100 = qqqm_data.get('sma_100', 0.0)
        if pd.notna(_sma100) and qqqm_data['price'] > _sma100:
            _sc3, _ss3 = "#10b981", "SMA100 상회"
        elif pd.notna(_sma100):
            _sc3, _ss3 = "#f97316", "SMA100 하회"
        else:
            _sc3, _ss3 = "#94a3b8", "데이터 부족"
        _sma100_d = f"${_sma100:.2f}" if pd.notna(_sma100) else "-"
        st.markdown(f"""
        <div style="text-align:center; padding:20px; background:linear-gradient(135deg,rgba(30,41,59,0.8),rgba(51,65,85,0.8)); border-radius:12px; border:2px solid {_sc3};">
            <p style="font-size:0.9em; color:#cbd5e1; margin-bottom:8px; font-weight:600;">SMA100</p>
            <p style="font-size:2.5em; font-weight:700; color:{_sc3}; margin:10px 0;">{_sma100_d}</p>
            <p style="font-size:1.1em; color:{_sc3}; font-weight:600;">{_ss3}</p>
        </div>""", unsafe_allow_html=True)
    with ic5:
        _sma200 = qqqm_data.get('sma_200', 0.0)
        if pd.notna(_sma200) and qqqm_data['price'] > _sma200:
            _sc4, _ss4 = "#10b981", "SMA200 상회"
        elif pd.notna(_sma200):
            _sc4, _ss4 = "#ef4444", "SMA200 하회"
        else:
            _sc4, _ss4 = "#94a3b8", "데이터 부족"
        _sma200_d = f"${_sma200:.2f}" if pd.notna(_sma200) else "-"
        st.markdown(f"""
        <div style="text-align:center; padding:20px; background:linear-gradient(135deg,rgba(30,41,59,0.8),rgba(51,65,85,0.8)); border-radius:12px; border:2px solid {_sc4};">
            <p style="font-size:0.9em; color:#cbd5e1; margin-bottom:8px; font-weight:600;">SMA200</p>
            <p style="font-size:2.5em; font-weight:700; color:{_sc4}; margin:10px 0;">{_sma200_d}</p>
            <p style="font-size:1.1em; color:{_sc4}; font-weight:600;">{_ss4}</p>
        </div>""", unsafe_allow_html=True)
    with ic6:
        if puddle_stage == 0:
            _pt, _pc, _pi = "정상", "#10b981", "OK"
        elif puddle_stage == 1:
            _pt, _pc, _pi = "1단계 (SMA50)", "#fbbf24", "S1"
        elif puddle_stage == 2:
            _pt, _pc, _pi = "2단계 (SMA100)", "#f97316", "S2"
        elif puddle_stage == 3:
            _pt, _pc, _pi = "3단계 (SMA200)", "#ef4444", "S3"
        else:
            _pt, _pc, _pi = "4단계 (회복)", "#10b981", "S4"
        st.markdown(f"""
        <div style="text-align:center; padding:20px; background:linear-gradient(135deg,rgba(30,41,59,0.8),rgba(51,65,85,0.8)); border-radius:12px; border:2px solid {_pc};">
            <p style="font-size:0.9em; color:#cbd5e1; margin-bottom:8px; font-weight:600;">웅덩이 단계</p>
            <p style="font-size:2em; font-weight:700; color:{_pc}; margin:10px 0;">{_pi}</p>
            <p style="font-size:1.1em; color:{_pc}; font-weight:600;">{_pt}</p>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── QQQM candlestick + SMA chart ──
    st.subheader("QQQM 기술적 분석")
    fig_ohlc = go.Figure()
    fig_ohlc.add_trace(go.Candlestick(
        x=qqqm_data['df'].index,
        open=qqqm_data['df']['Open'], high=qqqm_data['df']['High'],
        low=qqqm_data['df']['Low'], close=qqqm_data['df']['Close'],
        name='QQQM', increasing_line_color='#ef4444', decreasing_line_color='#3b82f6',
    ))
    fig_ohlc.add_trace(go.Scatter(x=qqqm_data['df'].index, y=qqqm_data['df']['SMA_20'], name='SMA20', line=dict(color='#fbbf24', width=1.5)))
    fig_ohlc.add_trace(go.Scatter(x=qqqm_data['df'].index, y=qqqm_data['df']['SMA_50'], name='SMA50', line=dict(color='#3b82f6', width=2)))
    fig_ohlc.add_trace(go.Scatter(x=qqqm_data['df'].index, y=qqqm_data['df']['SMA_100'], name='SMA100', line=dict(color='#f97316', width=2)))
    fig_ohlc.add_trace(go.Scatter(x=qqqm_data['df'].index, y=qqqm_data['df']['SMA_200'], name='SMA200', line=dict(color='#ef4444', width=2.5)))
    fig_ohlc.update_layout(
        plot_bgcolor='rgba(30,41,59,0.5)', paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=500, hovermode='x unified',
        xaxis=dict(gridcolor='rgba(148,163,184,0.2)', showgrid=True),
        yaxis=dict(gridcolor='rgba(148,163,184,0.2)', showgrid=True, title='현재가 (USD)'),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    bgcolor='rgba(30,41,59,0.8)', bordercolor='#475569', borderwidth=1),
    )
    st.plotly_chart(fig_ohlc, width='stretch')

    # ── RSI chart ──
    fig_rsi = go.Figure()
    fig_rsi.add_trace(go.Scatter(x=qqqm_data['df'].index, y=qqqm_data['df']['RSI'], mode='lines', name='RSI(14)', line=dict(color='#10b981', width=2)))
    fig_rsi.add_hline(y=70, line_dash="dash", line_color="#ef4444", annotation_text="과열(70)")
    fig_rsi.add_hline(y=30, line_dash="dash", line_color="#3b82f6", annotation_text="과매도(30)")
    fig_rsi.update_layout(
        plot_bgcolor='rgba(30,41,59,0.5)', paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=300, hovermode='x unified',
        xaxis=dict(gridcolor='rgba(148,163,184,0.2)', showgrid=True),
        yaxis=dict(gridcolor='rgba(148,163,184,0.2)', showgrid=True, title='RSI', range=[0, 100]),
    )
    st.plotly_chart(fig_rsi, width='stretch')

    # ── Backtest ──
    if backtest_enabled:
        bt_stage_rates = {k: v for k, v in STAGE_DEPLOYMENT_RATES.items() if k in (1, 2, 3)}
        bt_fee_bps = 1.0
        bt_slippage_bps = 2.0
        bt_current_vol_factor = estimate_vol_factor(qqqm_data['df'])
        bt_result = run_backtest(
            qqqm_data['df'][['Open', 'Close', 'SMA_50', 'SMA_100', 'SMA_200']].copy(),
            initial_cash=10000.0, stage_rates=bt_stage_rates,
            vol_adjust=backtest_vol_adjust, buy_only=True,
            fee_bps=bt_fee_bps, slippage_bps=bt_slippage_bps,
        )
        st.markdown("---")
        st.subheader("백테스트 (실험)")
        st.caption("규칙: 신호는 D일 종가에 계산되고, D+1일 시가에 체결됩니다.")
        metrics_rows = [
            {"지표": "CAGR", "값": f"{bt_result.metrics.get('CAGR', 0.0) * 100:.2f}%"},
            {"지표": "총 수익률", "값": f"{bt_result.metrics.get('TotalReturn', 0.0) * 100:.2f}%"},
            {"지표": "비교군 수익률", "값": f"{bt_result.metrics.get('BenchmarkTotalReturn', 0.0) * 100:.2f}%"},
            {"지표": "최대 낙폭(MDD)", "값": f"{bt_result.metrics.get('MDD', 0.0) * 100:.2f}%"},
            {"지표": "샤프 지수", "값": f"{bt_result.metrics.get('Sharpe', 0.0):.2f}"},
            {"지표": "거래 횟수", "값": f"{int(bt_result.metrics.get('NumTrades', 0))}"},
        ]
        st.dataframe(pd.DataFrame(metrics_rows), width='stretch', hide_index=True)
        if not bt_result.equity_curve.empty:
            fig_bt = go.Figure()
            fig_bt.add_trace(go.Scatter(x=bt_result.equity_curve.index, y=bt_result.equity_curve.values, mode='lines', name='전략', line=dict(color='#10b981', width=2)))
            if not bt_result.benchmark_curve.empty:
                fig_bt.add_trace(go.Scatter(x=bt_result.benchmark_curve.index, y=bt_result.benchmark_curve.values, mode='lines', name='매수후보유', line=dict(color='#3b82f6', width=2, dash='dash')))
            fig_bt.update_layout(
                plot_bgcolor='rgba(30,41,59,0.5)', paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#e2e8f0'), height=320, hovermode='x unified',
                margin=dict(l=40, r=20, t=20, b=20),
            )
            st.plotly_chart(fig_bt, width='stretch', config={'displayModeBar': False})

            if not bt_result.trades.empty:
                st.caption(f"최근 거래 {min(20, len(bt_result.trades))}건")
                trades_view = bt_result.trades.sort_values("exec_date", ascending=False).head(20).copy()
                trades_view["signal_date"] = pd.to_datetime(trades_view["signal_date"]).dt.strftime("%Y-%m-%d")
                trades_view["exec_date"] = pd.to_datetime(trades_view["exec_date"]).dt.strftime("%Y-%m-%d")
                trades_view["action"] = trades_view["action"].map(lambda x: "매수" if x == "BUY" else str(x))
                trades_view["planned_cash"] = trades_view["planned_cash"].map(fmt_money)
                trades_view["fee"] = trades_view["fee"].map(fmt_money)
                trades_view["exec_price"] = trades_view["exec_price"].map(fmt_money)
                trades_view["shares_bought"] = trades_view["shares_bought"].map(lambda x: fmt_num(x, 2))
                trades_view["cash_after"] = trades_view["cash_after"].map(fmt_money)
                trades_view["shares_after"] = trades_view["shares_after"].map(lambda x: fmt_num(x, 2))
                if "vol_factor" in trades_view.columns:
                    trades_view["vol_factor"] = trades_view["vol_factor"].map(lambda x: fmt_num(x, 2) if x is not None else "-")
                trades_view = trades_view.rename(columns={
                    "signal_date": "신호일", "exec_date": "체결일", "stage": "단계",
                    "action": "동작", "planned_cash": "계획현금", "fee": "수수료",
                    "exec_price": "체결가", "shares_bought": "매수수량",
                    "cash_after": "잔여현금", "shares_after": "보유수량",
                    "vol_factor": "변동성", "reason": "판단근거",
                })
                display_cols = [c for c in ["신호일", "체결일", "단계", "동작", "계획현금", "수수료", "체결가", "매수수량", "보유수량", "잔여현금", "변동성", "판단근거"] if c in trades_view.columns]
                st.dataframe(trades_view[display_cols], width='stretch', hide_index=True)

    # ── Strategy Lab ──
    with st.expander("전략 연구실", expanded=False):
        st.caption("연구 모드: 단일 실행, 현금 비중 연구, 쿨다운 민감도, 다중 자산 검증")
        lab_modes = ["단일 실행", "현금 비중 연구", "쿨다운 연구", "다중 자산 검증"]
        lab_mode = st.selectbox("연구 모드", lab_modes, index=0, key="lab_mode")

        lc1, lc2, lc3 = st.columns(3)
        with lc1:
            lab_symbol = st.selectbox("종목", ["QQQM", "SPY", "VTI", "BTC-USD"], index=0, key="lab_sym")
        with lc2:
            lab_start_date = st.date_input("시작일", value=pd.Timestamp("2012-01-01").date(), key="lab_sd")
        with lc3:
            lab_initial_cash = st.number_input("초기 자본 (USD)", min_value=1000.0, value=10000.0, step=1000.0, key="lab_cash")

        lab_assets = st.multiselect("다중 자산 세트", ["QQQM", "SPY", "VTI", "BTC-USD"], default=["QQQM", "SPY", "VTI", "BTC-USD"], key="lab_assets")

        ctrl1, ctrl2 = st.columns(2)
        with ctrl1:
            lab_cash_ratio = st.slider("현금 비중", min_value=0.05, max_value=0.30, value=0.10, step=0.01, key="lab_cr")
        with ctrl2:
            lab_cooldown = st.slider("쿨다운 일수", min_value=10, max_value=60, value=30, step=1, key="lab_cd")

        with st.expander("단계별 투입 비율 (1/2/3)", expanded=False):
            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                lab_rate_1 = st.slider("1단계", 0.0, 1.0, float(STAGE_DEPLOYMENT_RATES[1]), 0.01, key="lr1")
            with rc2:
                lab_rate_2 = st.slider("2단계", 0.0, 1.0, float(STAGE_DEPLOYMENT_RATES[2]), 0.01, key="lr2")
            with rc3:
                lab_rate_3 = st.slider("3단계", 0.0, 1.0, float(STAGE_DEPLOYMENT_RATES[3]), 0.01, key="lr3")

        lab_stage_rates = {1: float(lab_rate_1), 2: float(lab_rate_2), 3: float(lab_rate_3)}
        rate_sum = lab_rate_1 + lab_rate_2 + lab_rate_3
        if rate_sum > 1.0:
            st.error(f"투입 비율 합계 > 1.0 (현재: {rate_sum:.2f})")

        lab_run = st.button("전략 연구 실행", width='stretch', key="lab_run")

        if lab_run and rate_sum <= 1.0:
            def _run_one(symbol, cooldown_days, cash_ratio):
                return run_strategy_backtest(
                    symbol=symbol, start_date=str(lab_start_date),
                    initial_cash=float(lab_initial_cash), cooldown_days=int(cooldown_days),
                    stage_rates=lab_stage_rates, cash_ratio=float(cash_ratio),
                )

            if lab_mode == "단일 실행":
                with st.spinner("전략 백테스트 실행 중..."):
                    lab_df = _run_one(lab_symbol, lab_cooldown, lab_cash_ratio)
                    lab_metrics = compute_backtest_metrics(lab_df)
                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                mc1.metric("총 수익률", f"{lab_metrics['Total Return'] * 100:.2f}%")
                mc2.metric("CAGR", f"{lab_metrics['CAGR'] * 100:.2f}%")
                mc3.metric("MDD", f"{lab_metrics['Max Drawdown'] * 100:.2f}%")
                mc4.metric("변동성", f"{lab_metrics['Volatility'] * 100:.2f}%")
                mc5.metric("Sharpe", f"{lab_metrics['Sharpe Ratio']:.2f}")
                st.plotly_chart(plot_backtest_results(lab_df), width='stretch', config={"displayModeBar": False})

            elif lab_mode == "현금 비중 연구":
                rows = []
                with st.spinner("현금 비중 연구..."):
                    for cr in [0.05, 0.10, 0.20, 0.30]:
                        m = compute_backtest_metrics(_run_one(lab_symbol, lab_cooldown, cr))
                        rows.append({"현금비중": cr, "CAGR": f"{m['CAGR']*100:.2f}%", "Sharpe": f"{m['Sharpe Ratio']:.2f}", "MDD": f"{m['Max Drawdown']*100:.2f}%"})
                st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

            elif lab_mode == "쿨다운 연구":
                rows = []
                with st.spinner("쿨다운 민감도..."):
                    for cd in [10, 20, 30, 40, 60]:
                        m = compute_backtest_metrics(_run_one(lab_symbol, cd, lab_cash_ratio))
                        rows.append({"쿨다운": cd, "CAGR": f"{m['CAGR']*100:.2f}%", "Sharpe": f"{m['Sharpe Ratio']:.2f}", "MDD": f"{m['Max Drawdown']*100:.2f}%"})
                st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

            else:  # 다중 자산 검증
                if not lab_assets:
                    st.warning("최소 1개 자산을 선택하세요.")
                else:
                    rows = []
                    with st.spinner("다중 자산 검증..."):
                        for sym in lab_assets:
                            m = compute_backtest_metrics(_run_one(sym, lab_cooldown, lab_cash_ratio))
                            rows.append({"자산": sym, "CAGR": f"{m['CAGR']*100:.2f}%", "Sharpe": f"{m['Sharpe Ratio']:.2f}", "MDD": f"{m['Max Drawdown']*100:.2f}%", "전략수익": f"{m['strategy_return']*100:.2f}%"})
                    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    # ── Execution plan ──
    st.markdown("---")
    st.subheader("실행 계획")
    _status_lines = []
    if defcon_triggered:
        _status_lines.append("DEFCON 세이빙 발동: 신규 자금을 SGOV로만 배분")
    if puddle_alert:
        _deploy_base = float(sgov_value + cash_deposit)
        _deploy_amount = compute_deployment(puddle_stage, _deploy_base)
        _status_lines.append(f"웅덩이 단계 {puddle_stage}: 기준자금=${_deploy_base:,.2f}, 권장 투입=${_deploy_amount:,.2f}")
    elif puddle_cooldown_active:
        _status_lines.append(f"웅덩이 쿨다운 진행 중: {cooldown_info or '최근 30일 이내'}")
    if smart_shoulder_triggered:
        _status_lines.append("스마트 숄더 발동: 리밸런싱 필요")
    if not _status_lines:
        _status_lines.append("핵심 전략 정상 운용 중")
    for _line in _status_lines:
        st.markdown(f"- {_line}")
    if new_cash > 0:
        st.caption(f"신규 자금: ${new_cash:,.2f} | 목표 비중: 72/16/2/10")

    # ── Market driver analysis ──
    @st.cache_data(ttl=1800)
    def get_market_summary(symbol):
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
        except Exception:
            pass
        return news_list

    def _interpret_asset(symbol, name, change_pct, news_list):
        if change_pct > 1.0:
            direction, detail = "강한 상승", "상승 모멘텀 확대"
        elif change_pct > 0.3:
            direction, detail = "상승", "완만한 상승"
        elif change_pct > -0.3:
            direction, detail = "보합", "제한적 움직임"
        elif change_pct > -1.0:
            direction, detail = "하락", "완만한 하락"
        else:
            direction, detail = "강한 하락", "하방 압력 확대"
        return {'direction': direction, 'detail': detail, 'news': (news_list or [])[:2]}

    with st.expander("오늘의 시장 동인", expanded=False):
        with st.spinner('시장 동인 분석 중...'):
            qqqm_news = get_market_summary('QQQM')
            schd_news = get_market_summary('SCHD')
            iau_news = get_market_summary('IAU')
            qqqm_an = _interpret_asset('QQQM', '나스닥 100', qqqm_data['change_pct'], qqqm_news)
            schd_an = _interpret_asset('SCHD', '배당 성장', schd_data['change_pct'], schd_news)
            iau_an = _interpret_asset('IAU', '금', iau_data['change_pct'], iau_news)

        for label, color, an, data in [
            ("QQQM (나스닥 100)", "#10b981", qqqm_an, qqqm_data),
            ("SCHD (배당 성장)", "#3b82f6", schd_an, schd_data),
            ("IAU (금)", "#fbbf24", iau_an, iau_data),
        ]:
            _ic = "📈" if data['change_pct'] >= 0 else "📉"
            st.markdown(f"**{label}** — {_ic} {data['change_pct']:+.2f}% | {an['direction']} ({an['detail']})")
            for n in an['news']:
                st.caption(f"  {n['title'][:60]}")

# =====================================================================
# TAB 3 — 거시경제 & 전략 (2-Layer: Facts + AI Orchestration)
# =====================================================================
with tab3:
    st.header("거시경제 & 전략")
    nb = news_brief if isinstance(news_brief, dict) else {}

    # =================================================================
    # A. 정보 레이어 — 엔진이 계산한 사실/원자료만 표시
    #    ※ 이 레이어에서 전략 제안 문장을 쓰지 않는다.
    # =================================================================
    st.markdown("""<p style='color:#64748b; font-size:0.85em; letter-spacing:0.05em;
        margin-bottom:4px;'>📊 <b>정보 레이어</b> — 엔진이 계산한 사실 데이터</p>""",
        unsafe_allow_html=True)

    # ── 1. 시장 이벤트 ──
    st.subheader("① 시장 이벤트")
    shock_events = detect_market_events(vix_data, fng_data, tnx_data, oil_data, nb)
    _label_map = {
        "POLICY_RATE_RISK": "금리 경로 리스크",
        "YIELD_PRESSURE": "장기금리 압력",
        "INFLATION_PRESSURE": "인플레이션 압력",
        "LABOR_SOFTNESS": "고용 둔화",
        "GROWTH_SLOWDOWN": "성장 둔화",
        "TECH_AI_SUPPORT": "AI/기술 모멘텀",
        "GEOPOLITICAL_CONFLICT": "지정학 갈등",
        "ENERGY_SUPPLY_RISK": "에너지 공급 리스크",
        "MARKET_STRESS": "시장 스트레스",
    }
    _top_cats = (nb.get("dominant_categories", []) or [])[:3]
    _event_items = [_label_map.get(c, c) for c in _top_cats]
    for ev in (shock_events or [])[:3]:
        if ev not in _event_items:
            _event_items.append(ev)
    if _event_items:
        _bullets = "".join(
            f"<li style='margin:4px 0;color:#e2e8f0;'>{e}</li>"
            for e in _event_items[:4]
        )
        st.markdown(f"""
        <div style="background:#1e293b;border-left:4px solid #f59e0b;border-radius:8px;padding:16px;">
            <ul style="margin:0;padding-left:20px;">{_bullets}</ul>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="background:#1e293b;border-left:4px solid #10b981;border-radius:8px;padding:16px;">
            <p style="color:#10b981;margin:0;">현재 주요 시장 이벤트가 감지되지 않았습니다.</p>
        </div>""", unsafe_allow_html=True)

    # ── 2. 리스크 레이더 ──
    st.subheader("② 리스크 레이더")
    radar = build_risk_radar(vix_data, fng_data, nb)
    _risk_cols = st.columns(4)
    _risk_names = ["금리 리스크", "인플레이션 리스크", "지정학 리스크", "시장 스트레스"]
    _risk_icons = ["📈", "🔥", "🌍", "⚡"]
    for _ri, (_rn, _ric) in enumerate(zip(_risk_names, _risk_icons)):
        with _risk_cols[_ri]:
            _rv = min(100, max(0, _safe_int(radar.get(_rn), 40)))
            _rc = "#ef4444" if _rv >= 70 else ("#f59e0b" if _rv >= 50 else "#10b981")
            st.markdown(f"""
            <div style="background:#1e293b;border-radius:8px;padding:12px;text-align:center;">
                <p style="font-size:1.2em;margin:0;">{_ric}</p>
                <p style="color:#94a3b8;font-size:0.8em;margin:4px 0;">{_rn}</p>
                <p style="color:{_rc};font-size:1.5em;font-weight:700;margin:0;">{_rv}</p>
            </div>""", unsafe_allow_html=True)
            st.progress(_rv / 100)

    # ── 3. 시장 레짐 / 핵심 지표 ──
    st.subheader("③ 시장 레짐 / 핵심 지표")
    _regime_label_map = {
        "BULL": "🟢 상승장", "CORRECTION": "🟡 조정장",
        "BEAR": "🔴 하락장", "RECOVERY": "🔵 회복장",
    }
    _regime_color_map = {
        "BULL": "#10b981", "CORRECTION": "#f59e0b",
        "BEAR": "#ef4444", "RECOVERY": "#3b82f6",
    }
    _regime_raw = regime_info.get("regime", "CORRECTION")
    _r_label = _regime_label_map.get(_regime_raw, "🟡 조정장")
    _r_color = _regime_color_map.get(_regime_raw, "#f59e0b")
    st.markdown(f"""
    <div style="background:#1e293b;border:2px solid {_r_color};border-radius:8px;
                padding:10px 16px;display:inline-block;margin-bottom:12px;">
        <span style="color:{_r_color};font-weight:700;font-size:1.1em;">{_r_label}</span>
    </div>""", unsafe_allow_html=True)

    _vix_p = _safe_float((vix_data or {}).get("price"), 20.0)
    _fng_v = _safe_int((fng_data or {}).get("value"), 50)
    _tny_p = _safe_float((tnx_data or {}).get("price"), 0.0)
    _oil_p = _safe_float((oil_data or {}).get("price"), 0.0)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("VIX", f"{_vix_p:.2f}")
    k2.metric("Fear & Greed", f"{_fng_v}")
    k3.metric("10Y 금리", f"{_tny_p:.2f}%")
    k4.metric("유가", f"${_oil_p:.2f}")

    st.markdown("---")

    # =================================================================
    # B. AI 오케스트레이션 레이어 — 사실을 요약/해석/전략으로 연결
    #    ※ 각 AI는 자기 역할만 수행한다 (중복 금지).
    #      Gemini → 이벤트 요약 | Claude → 거시 해석 | OpenAI → 전략 제안
    # =================================================================
    st.markdown("""<p style='color:#64748b; font-size:0.85em; letter-spacing:0.05em;
        margin-bottom:4px;'>🤖 <b>AI 오케스트레이션 레이어</b> — Gemini · Claude · OpenAI</p>""",
        unsafe_allow_html=True)

    if st.button("AI 분석 실행", width='stretch', key="ai_orch"):
        gemini_key = st.secrets.get("GEMINI_API_KEY", "")
        claude_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        openai_key = st.secrets.get("OPENAI_API_KEY", "")
        models_config = dict(st.secrets.get("models", {}))

        from fire25.ai.decision_context_builder import build_decision_context
        from fire25.ai.ai_router import run_all as ai_run_all
        from fire25.ai.ai_formatter import (
            format_gemini_section, format_claude_section, format_openai_section,
        )

        _qqqm_sma200 = _safe_float(qqqm_data.get("sma_200"), 0.0)
        _qqqm_price = _safe_float(qqqm_data.get("price"), 0.0)
        _sma200_gap = (
            (_qqqm_price - _qqqm_sma200) / _qqqm_sma200 * 100.0
            if _qqqm_sma200 > 0 else 0.0
        )
        _cash_level = "높음" if cash_pct >= 15 else ("중간" if cash_pct >= 8 else "낮음")

        decision_ctx = build_decision_context(
            portfolio_weight={
                "QQQM": round(qqqm_pct, 2), "SCHD": round(schd_pct, 2),
                "IAU": round(iau_pct, 2), "SGOV+현금": round(cash_pct, 2),
            },
            target_weight={"QQQM": 72.0, "SCHD": 16.0, "IAU": 2.0, "SGOV+현금": 10.0},
            cash_level=_cash_level,
            vix=_safe_float((vix_data or {}).get("price"), 20.0),
            fear_greed=_safe_int((fng_data or {}).get("value"), 50),
            qqqm_rsi=_safe_float(qqqm_data.get("rsi"), 50.0),
            qqqm_sma200_gap=round(_sma200_gap, 2),
            treasury_10y=_safe_float((tnx_data or {}).get("price"), 0.0),
            oil_price=_safe_float((oil_data or {}).get("price"), 0.0),
            regime=str(regime_info.get("regime", "CORRECTION")),
            macro_summary_text=short_korean(str(macro_summary.get("implication", "")), 2),
            news_summary_text=short_korean(str(nb.get("headline_summary", "")), 2),
            news_brief=nb,
            shock_events=shock_events,
            risk_radar=radar,
        )

        with st.spinner("AI 분석 중..."):
            ai_results = ai_run_all(
                decision_context=decision_ctx,
                articles=market_news,
                aggregated_signals=nb.get("aggregated_signals", {}),
                theme_info=nb.get("theme_info", {}),
                asset_focus="growth",
                openai_api_key=openai_key,
                claude_api_key=claude_key,
                gemini_api_key=gemini_key,
                models_config=models_config,
            )

        # ── 4. Gemini 이벤트 브리프 ──
        # 역할: 오늘 무슨 일이 있었는가? (이벤트 요약만, 해석 최소화)
        gf = format_gemini_section(ai_results["gemini"])
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#1e293b,#0f172a);
                    border:1px solid #3b82f6;border-radius:12px;padding:20px;margin-bottom:16px;">
            <div style="display:flex;align-items:center;margin-bottom:12px;">
                <span style="font-size:1.3em;margin-right:8px;">💎</span>
                <span style="color:#60a5fa;font-weight:700;font-size:1.1em;">Gemini 이벤트 브리프</span>
                <span style="color:#475569;font-size:0.8em;margin-left:auto;">{gf['source']} · {ai_results['gemini'].get('_model','')}</span>
            </div>
            <p style="color:#e2e8f0;margin:0;line-height:1.6;">{gf['headline']}</p>
        </div>""", unsafe_allow_html=True)

        # ── 5. Claude 거시 해석 ──
        # 역할: 그 일이 시장에 어떤 의미가 있는가? (거시 해석만, 전략 금지)
        cf = format_claude_section(ai_results["claude"])
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#1e293b,#0f172a);
                    border:1px solid #a855f7;border-radius:12px;padding:20px;margin-bottom:16px;">
            <div style="display:flex;align-items:center;margin-bottom:12px;">
                <span style="font-size:1.3em;margin-right:8px;">🔮</span>
                <span style="color:#c084fc;font-weight:700;font-size:1.1em;">Claude 거시 해석</span>
                <span style="color:#475569;font-size:0.8em;margin-left:auto;">{cf['source']} · {ai_results['claude'].get('_model','')}</span>
            </div>
            <p style="color:#e2e8f0;margin:0 0 8px;line-height:1.6;">{cf['macro_view']}</p>
            <p style="color:#f87171;font-size:0.9em;margin:4px 0;">⚠ 핵심 리스크: {cf['key_risk']}</p>
            <p style="color:#34d399;font-size:0.9em;margin:4px 0;">💡 기회 요인: {cf['opportunity']}</p>
        </div>""", unsafe_allow_html=True)

        # ── 6. OpenAI 오늘의 전략 ──
        # 역할: 그래서 지금 어떻게 대응할까? (전략의 최종 요약자)
        of = format_openai_section(ai_results["openai"])
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#1e293b,#0f172a);
                    border:1px solid #10b981;border-radius:12px;padding:20px;margin-bottom:8px;">
            <div style="display:flex;align-items:center;margin-bottom:12px;">
                <span style="font-size:1.3em;margin-right:8px;">🧠</span>
                <span style="color:#34d399;font-weight:700;font-size:1.1em;">OpenAI 오늘의 전략</span>
                <span style="color:#475569;font-size:0.8em;margin-left:auto;">{of['source']} · {ai_results['openai'].get('_model','')}</span>
            </div>
        </div>""", unsafe_allow_html=True)

        d1, d2, d3 = st.columns(3)
        d1.metric("하락 확률", f"{of['dip_probability']}%")
        d2.metric("리스크", of['risk_level'])
        d3.metric("신뢰도", of['confidence'])

        a1, a2 = st.columns(2)
        with a1:
            st.markdown(f"""
            <div style="background:#1e293b;border-radius:8px;padding:12px;margin-bottom:8px;">
                <p style="color:#94a3b8;font-size:0.8em;margin:0 0 4px;">오늘의 시장</p>
                <p style="color:#e2e8f0;margin:0;">{of.get('market_view','데이터 부족')}</p>
            </div>
            <div style="background:#1e293b;border-radius:8px;padding:12px;">
                <p style="color:#f59e0b;font-size:0.8em;margin:0 0 4px;">Shield 경보</p>
                <p style="color:#e2e8f0;margin:0;">{of.get('shield_alert','데이터 부족')}</p>
            </div>""", unsafe_allow_html=True)
        with a2:
            st.markdown(f"""
            <div style="background:#1e293b;border-radius:8px;padding:12px;margin-bottom:8px;">
                <p style="color:#3b82f6;font-size:0.8em;margin:0 0 4px;">웅줍 신호</p>
                <p style="color:#e2e8f0;margin:0;">{of.get('dip_signal','데이터 부족')}</p>
            </div>
            <div style="background:#1e293b;border-radius:8px;padding:12px;">
                <p style="color:#10b981;font-size:0.8em;margin:0 0 4px;">다음 액션</p>
                <p style="color:#e2e8f0;margin:0;">{of.get('action','데이터 부족')}</p>
            </div>""", unsafe_allow_html=True)

        # ── AI 상태 진단 ──
        def _status_dot(src, err):
            if src and src != "fallback":
                return "🟢", "정상"
            if err:
                return "🔴", str(err)
            return "🟡", "fallback"

        _g_dot, _g_msg = _status_dot(gf.get("_source"), gf.get("_debug_error"))
        _c_dot, _c_msg = _status_dot(cf.get("_source"), cf.get("_debug_error"))
        _o_dot, _o_msg = _status_dot(of.get("_source"), of.get("_debug_error"))
        with st.expander("AI 상태 진단", expanded=False):
            st.markdown(f"{_g_dot} **Gemini** (`{ai_results['gemini'].get('_model','')}`) — {_g_msg}")
            st.markdown(f"{_c_dot} **Claude** (`{ai_results['claude'].get('_model','')}`) — {_c_msg}")
            st.markdown(f"{_o_dot} **OpenAI** (`{ai_results['openai'].get('_model','')}`) — {_o_msg}")
            st.caption("🟢 정상 | 🟡 fallback (키 없음/SDK 없음) | 🔴 오류")

    st.markdown("---")

    # ── 7. 포트폴리오 관점 (엔진 원자료) ──
    st.subheader("⑦ 포트폴리오 관점")
    _aimp = nb.get("asset_implications", {}) if isinstance(nb.get("asset_implications"), dict) else {}
    _impact_rows = [
        {"자산": "QQQM", "관점": short_korean(_aimp.get("QQQM", "확인 필요"), 1)},
        {"자산": "SCHD", "관점": short_korean(_aimp.get("SCHD", "확인 필요"), 1)},
        {"자산": "IAU", "관점": short_korean(_aimp.get("IAU", "확인 필요"), 1)},
        {"자산": "SGOV", "관점": short_korean(_aimp.get("SGOV", "확인 필요"), 1)},
    ]
    st.dataframe(pd.DataFrame(_impact_rows), width='stretch', hide_index=True)

    # ── 8. 체크 포인트 ──
    st.subheader("⑧ 체크 포인트")
    _wp = nb.get("watch_points", [])
    if not isinstance(_wp, list):
        _wp = []
    for wp in (_wp or ["미국 10년물 금리", "VIX 방향", "유가 흐름"])[:4]:
        st.markdown(f"- {wp}")

    # ── 9. 대표 뉴스 보기 ──
    with st.expander("⑨ 대표 뉴스 보기", expanded=False):
        if market_news:
            for _ni in market_news[:5]:
                _nt = (_ni.get("title") or "").strip()
                _ns = (_ni.get("source") or "출처 미상").strip()
                if _nt:
                    st.markdown(f"- **{_nt}** ({_ns})")
        else:
            st.caption("수집된 뉴스가 없습니다.")

# Footer
# =====================================================================
st.markdown("---")
st.markdown("""
<p style='text-align: center; color: #94a3b8; font-size: 0.9em;'>
    📚 TEAM FIRE 25 투자 매뉴얼 v5.10 기반<br>
    📡 데이터 출처: Yahoo Finance (15-20분 지연)<br>
    ⚠️ 본 대시보드는 투자 참고용이며, 투자 결정은 본인 책임입니다.</p>
""", unsafe_allow_html=True)
