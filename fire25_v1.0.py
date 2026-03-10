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
    tnx = get_market_data("^TNX", period="1mo")
    oil = get_market_data("CL=F", period="1mo")
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

tab1, tab2, tab3 = st.tabs([
    "내 자산 현황",
    "시장 현황",
    "거시경제 & 전략"
])

with tab1:
    st.header("내 자산 현황")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 자산", f"${total_value:,.2f}")
    c2.metric("QQQM", f"{qqqm_pct:.1f}%")
    c3.metric("SCHD", f"{schd_pct:.1f}%")
    c4.metric("IAU", f"{iau_pct:.1f}%")
    c5.metric("현금", f"{cash_pct:.1f}%")

    asset_table = pd.DataFrame({
        "자산": ["QQQM", "SCHD", "IAU", "SGOV", "예수금", "현금 합계"],
        "평가금": [qqqm_value, schd_value, iau_value, sgov_value, cash_deposit, total_cash],
        "비중(%)": [qqqm_pct, schd_pct, iau_pct, sgov_pct, deposit_pct, cash_pct],
        "목표 비중(%)": [72.0, 16.0, 2.0, None, None, 10.0],
    })
    st.dataframe(
        asset_table.style.format({"평가금": "${:,.2f}", "비중(%)": "{:.2f}", "목표 비중(%)": "{:.2f}"}),
        width='stretch',
        hide_index=True,
    )

    fig_alloc = go.Figure(data=[go.Pie(
        labels=['QQQM', 'SCHD', 'IAU', 'SGOV', '예수금'],
        values=[qqqm_value, schd_value, iau_value, sgov_value, cash_deposit],
        hole=0.45,
        marker=dict(colors=['#10b981', '#3b82f6', '#fbbf24', '#94a3b8', '#64748b']),
        textinfo='label+percent'
    )])
    fig_alloc.update_layout(
        height=360,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'),
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig_alloc, width='stretch', config={'displayModeBar': False})

    with st.expander("FIRE 확률 (간이)", expanded=False):
        hist_returns = pd.to_numeric(qqqm_data["df"]["Close"], errors="coerce").pct_change().dropna().values
        if len(hist_returns) > 10:
            sim_paths = simulate_monte_carlo_with_contributions(
                returns=hist_returns,
                years=20,
                simulations=400,
                initial_capital=float(max(total_value, 10000.0)),
                annual_investment=12000.0,
            )
            fire_prob = calculate_fire_probability(sim_paths, target_value=1000000.0)
            st.metric("FIRE 달성 확률", f"{fire_prob * 100:.1f}%")

with tab2:
    st.header("시장 현황")

    vix_val = _safe_float((vix_data or {}).get('price'), 20.0)
    vix_chg = _safe_float((vix_data or {}).get('change_pct'), 0.0)
    fng_val = _safe_int((fng_data or {}).get('value'), 50)
    tnx_val = _safe_float((tnx_data or {}).get('price'), 0.0)
    tnx_chg = _safe_float((tnx_data or {}).get('change_pct'), 0.0)
    oil_val = _safe_float((oil_data or {}).get('price'), 0.0)
    oil_chg = _safe_float((oil_data or {}).get('change_pct'), 0.0)

    mcol1, mcol2, mcol3, mcol4 = st.columns(4)
    mcol1.metric("VIX", f"{vix_val:.2f}", f"{vix_chg:+.2f}%")
    mcol2.metric("Fear & Greed", f"{fng_val}")
    mcol3.metric("미국 10Y 금리", f"{tnx_val:.2f}%", f"{tnx_chg:+.2f}%")
    mcol4.metric("유가(WTI)", f"${oil_val:.2f}", f"{oil_chg:+.2f}%")

    regime_raw = regime_info.get("regime", "CORRECTION")
    regime_conf = _safe_float(regime_info.get('confidence', 0.0), 0.0)
    st.markdown(f"**시장 국면**: `{regime_raw}` | 신뢰도 `{regime_conf * 100:.1f}%`")

    t1, t2, t3, t4 = st.columns(4)
    t1.metric("RSI", f"{qqqm_data.get('rsi', 50.0):.1f}")
    t2.metric("SMA50", f"${qqqm_data.get('sma_50', 0.0):.2f}")
    t3.metric("SMA100", f"${qqqm_data.get('sma_100', 0.0):.2f}")
    t4.metric("SMA200", f"${qqqm_data.get('sma_200', 0.0):.2f}")

    fig_px = go.Figure()
    fig_px.add_trace(go.Candlestick(
        x=qqqm_data['df'].index,
        open=qqqm_data['df']['Open'],
        high=qqqm_data['df']['High'],
        low=qqqm_data['df']['Low'],
        close=qqqm_data['df']['Close'],
        name='QQQM',
        increasing_line_color='#ef4444',
        decreasing_line_color='#3b82f6',
    ))
    fig_px.add_trace(go.Scatter(x=qqqm_data['df'].index, y=qqqm_data['df']['SMA_50'], name='SMA50', line=dict(color='#3b82f6')))
    fig_px.add_trace(go.Scatter(x=qqqm_data['df'].index, y=qqqm_data['df']['SMA_100'], name='SMA100', line=dict(color='#f97316')))
    fig_px.add_trace(go.Scatter(x=qqqm_data['df'].index, y=qqqm_data['df']['SMA_200'], name='SMA200', line=dict(color='#ef4444')))
    fig_px.update_layout(height=420, plot_bgcolor='rgba(30,41,59,0.5)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='#e2e8f0'))
    st.plotly_chart(fig_px, width='stretch', config={'displayModeBar': False})

with tab3:
    st.header("거시경제 & 전략")
    nb = news_brief if isinstance(news_brief, dict) else {}

    st.subheader("1 TODAY'S STRATEGY")
    risk_label = nb.get("risk_level_label", "보통")
    if risk_label == "높음":
        stance = "🛡 방어 우위"
        action = "💰 분할 매수 대기"
    elif risk_label == "낮음":
        stance = "✅ 위험선호"
        action = "📈 추세 점진 추종"
    else:
        stance = "⚖ 중립"
        action = "💰 신호 확인 후 분할 대응"
    st.markdown(f"**{stance}**  ")
    st.markdown(f"**{action}**")
    st.caption(short_korean(macro_summary.get("implication", ""), max_sentences=1))

    st.subheader("2 MARKET SHOCK ALERT")
    shock_events = detect_market_events(vix_data, fng_data, tnx_data, oil_data, nb)

    if shock_events:
        st.warning("⚠ MARKET EVENT\n" + "\n".join([f"- {x}" for x in shock_events[:3]]))
    else:
        st.success("현재 대형 매크로 충격 신호는 제한적입니다.")

    st.subheader("3 MACRO DASHBOARD")
    vix_price = _safe_float((vix_data or {}).get("price"), 20.0)
    oil_price = _safe_float((oil_data or {}).get("price"), 0.0)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("VIX", f"{vix_price:.2f}")
    k2.metric("Fear & Greed", f"{_safe_int((fng_data or {}).get('value'), 50)}")
    k3.metric("10Y Treasury", f"{_safe_float((tnx_data or {}).get('price'), 0.0):.2f}%")
    k4.metric("Oil", f"${oil_price:.2f}")

    st.subheader("4 RISK RADAR")
    radar = build_risk_radar(vix_data, fng_data, nb)
    st.write("금리 리스크")
    st.progress(_safe_int(radar.get("금리 리스크"), 40))
    st.write("인플레이션 리스크")
    st.progress(_safe_int(radar.get("인플레이션 리스크"), 40))
    st.write("지정학 리스크")
    st.progress(_safe_int(radar.get("지정학 리스크"), 35))
    st.write("시장 스트레스")
    st.progress(_safe_int(radar.get("시장 스트레스"), 40))

    st.subheader("5 TOP MARKET DRIVERS")
    drivers = nb.get("macro_drivers", [])
    if not isinstance(drivers, list):
        drivers = []
    label_map = {
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
    top_cats = (nb.get("dominant_categories", []) or ["OTHER"])[:3]
    if top_cats:
        for i, cat in enumerate(top_cats, start=1):
            st.markdown(f"{i}️⃣ {label_map.get(cat, '기타 이슈')}")
    else:
        st.info("현재 주요 거시 동인이 없습니다.")

    st.subheader("6 MARKET INTERPRETATION")
    st.markdown(short_korean(nb.get("market_implication", "시장 방향은 아직 불확실합니다. 금리 흐름 확인이 필요합니다."), max_sentences=2))

    st.subheader("7 PORTFOLIO IMPACT")
    asset_imp = nb.get("asset_implications", {}) if isinstance(nb.get("asset_implications"), dict) else {}
    impact_df = pd.DataFrame([
        {"자산": "QQQM", "관점": short_korean(asset_imp.get("QQQM", "성장주 변동성 확대 가능성을 점검하세요."), 1)},
        {"자산": "SCHD", "관점": short_korean(asset_imp.get("SCHD", "배당 방어 역할을 확인하세요."), 1)},
        {"자산": "IAU", "관점": short_korean(asset_imp.get("IAU", "지정학 리스크 헤지 흐름을 확인하세요."), 1)},
        {"자산": "SGOV", "관점": short_korean(asset_imp.get("SGOV", "현금 대기 전략 유효성을 점검하세요."), 1)},
    ])
    st.dataframe(impact_df, width='stretch', hide_index=True)

    st.subheader("8 WATCH POINTS")
    watch_points = nb.get("watch_points", [])
    if not isinstance(watch_points, list):
        watch_points = []
    for wp in (watch_points or ["미국 10년물 금리", "VIX 방향", "유가 100달러 유지 여부"])[:4]:
        st.markdown(f"- {wp}")

    st.subheader("9 NEWS SIGNAL")
    st.markdown(short_korean(nb.get("headline_summary", "뉴스 요약 데이터가 부족합니다."), max_sentences=2))
    st.caption(f"요약 엔진: {'Gemini' if nb.get('brief_source') == 'gemini' else '규칙 기반'}")

    st.markdown("---")
    st.subheader("AI 전략 어드바이저")
    if st.button("AI 전략 분석 실행", width='stretch'):
        api_key = st.secrets.get("OPENAI_API_KEY", "")
        qqqm_sma200 = _safe_float(qqqm_data.get("sma_200"), 0.0)
        qqqm_price = _safe_float(qqqm_data.get("price"), 0.0)
        sma200_gap = ((qqqm_price - qqqm_sma200) / qqqm_sma200 * 100.0) if qqqm_sma200 > 0 else 0.0
        cash_level = "높음" if cash_pct >= 15 else ("중간" if cash_pct >= 8 else "낮음")

        context = build_context(
            portfolio_weight={
                "QQQM": round(qqqm_pct, 2),
                "SCHD": round(schd_pct, 2),
                "IAU": round(iau_pct, 2),
                "SGOV+현금": round(cash_pct, 2),
            },
            target_weight={"QQQM": 72.0, "SCHD": 16.0, "IAU": 2.0, "SGOV+현금": 10.0},
            recent_buys=[],
            cash_level=cash_level,
            vix=_safe_float((vix_data or {}).get("price"), 20.0),
            fear_greed=_safe_float((fng_data or {}).get("value"), 50.0),
            qqqm_rsi=_safe_float(qqqm_data.get("rsi"), 50.0),
            qqqm_sma200_gap=round(sma200_gap, 2),
            treasury_10y=_safe_float((tnx_data or {}).get("price"), 0.0),
            oil_price=_safe_float((oil_data or {}).get("price"), 0.0),
            macro_summary=short_korean(str(macro_summary.get("implication", "")), 2),
            top_news_summary=short_korean(str(nb.get("headline_summary", "")), 2),
            market_regime=str(regime_raw),
        )

        advice = get_ai_advice(context=context, api_key=api_key)
        ai_source = str(advice.get("_ai_source", "fallback"))
        debug_error = advice.get("_debug_error", None)
        response_id = advice.get("_response_id")
        input_tokens = advice.get("_input_tokens")
        output_tokens = advice.get("_output_tokens")
        total_tokens = advice.get("_total_tokens")

        if ai_source == "openai":
            st.caption("AI 상태: OpenAI 응답")
        else:
            st.caption("AI 상태: fallback 응답")
            if debug_error:
                st.caption(f"디버그: {debug_error}")

        if response_id:
            st.caption(f"response_id: {response_id}")
        if total_tokens is not None:
            st.caption(f"토큰 사용량: input {input_tokens or 0} / output {output_tokens or 0} / total {total_tokens}")

        d1, d2, d3 = st.columns(3)
        with d1:
            dp = advice.get("dip_probability", 0)
            st.metric("Dip Probability", f"{dp}%")
        with d2:
            st.metric("Risk Level", advice.get("risk_level", "보통"))
        with d3:
            st.metric("AI Confidence", advice.get("confidence", "낮음"))

        a1, a2 = st.columns(2)
        with a1:
            st.markdown("**오늘 시장 해석**")
            st.info(advice.get("market_view", "데이터가 부족합니다."))
            st.markdown("**Shield 경보**")
            st.warning(advice.get("shield_alert", "데이터가 부족합니다."))
        with a2:
            st.markdown("**웅줍 신호**")
            st.info(advice.get("dip_signal", "데이터가 부족합니다."))
            st.markdown("**다음 액션**")
            st.success(advice.get("action", "데이터가 부족합니다."))

    if not market_news:
        st.warning("데이터를 불러오는 중입니다.")


# Legacy long-form rendering is kept below for reference but disabled.
st.stop()

# =====================================================================
# Main dashboard real-time quotes (legacy)
st.header("실시간 시세")

col1, col2, col3, col4 = st.columns(4)

with col1:
    change_class = 'positive' if qqqm_data['change'] >= 0 else 'negative'
    st.metric(
        label="QQQM (성장 코어)",
        value=f"${qqqm_data['price']:.2f}",
        delta=f"{qqqm_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>거래량: {qqqm_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col2:
    change_class = 'positive' if schd_data['change'] >= 0 else 'negative'
    st.metric(
        label="SCHD (배당 코어)",
        value=f"${schd_data['price']:.2f}",
        delta=f"{schd_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>거래량: {schd_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col3:
    change_class = 'positive' if iau_data['change'] >= 0 else 'negative'
    st.metric(
        label="IAU (금 ETF)",
        value=f"${iau_data['price']:.2f}",
        delta=f"{iau_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>거래량: {iau_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col4:
    if sgov_data:
        st.metric(
            label="SGOV (현금성 ETF)",
            value=f"${sgov_price:.2f}",
            delta=f"{sgov_data['change_pct']:+.2f}%"
        )
        st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>보유 수량: {sgov_qty:,.2f}주</p>", unsafe_allow_html=True)
    else:
        st.metric(label="SGOV (현금성 ETF)", value=f"${sgov_price:.2f}")
        st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>보유 수량: {sgov_qty:,.2f}주</p>", unsafe_allow_html=True)

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
                    <p style="color: #94a3b8; font-size: 0.9em; margin: 0;">공포·탐욕 지수</p>
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
                    <p style="color: #94a3b8; font-size: 0.9em; margin: 0;">공포·탐욕 지수</p>
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

st.header("📊 포트폴리오 요약")
sum_col1, sum_col2, sum_col3, sum_col4, sum_col5 = st.columns(5)
with sum_col1:
    st.metric("총 자산", f"${total_value:,.2f}")
with sum_col2:
    st.metric("QQQM", f"{qqqm_pct:.1f}%")
with sum_col3:
    st.metric("SCHD", f"{schd_pct:.1f}%")
with sum_col4:
    st.metric("IAU", f"{iau_pct:.1f}%")
with sum_col5:
    st.metric("현금", f"{cash_pct:.1f}%")

regime_info = detect_market_regime(
    qqqm_data["df"],
    vix_data["price"] if vix_data else None,
)

regime_label_map = {
    "BULL": "🟢 상승장",
    "CORRECTION": "🟡 조정장",
    "BEAR": "🔴 하락장",
    "RECOVERY": "🔵 회복장",
}
regime_color_map = {
    "BULL": "#10b981",
    "CORRECTION": "#f59e0b",
    "BEAR": "#ef4444",
    "RECOVERY": "#3b82f6",
}

current_regime = regime_info.get("regime", "CORRECTION")
current_regime_label = regime_label_map.get(current_regime, "🟡 조정장")
current_regime_color = regime_color_map.get(current_regime, "#f59e0b")
current_confidence = float(regime_info.get("confidence", 0.0))
current_reasons = regime_info.get("reason", [])

st.header("📊 시장 국면")
st.markdown(
    f"<span style='background: {current_regime_color}; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700;'>{current_regime_label}</span>",
    unsafe_allow_html=True,
)
st.caption(f"신뢰도: {current_confidence * 100:.1f}%")
for item in current_reasons:
    st.markdown(f"- {item}")


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
            "market_implication": "변동성 지표와 금리 흐름을 중심으로 보수적으로 대응하세요.",
            "portfolio_implication": "전략 신호와 현금성 자산 비중을 기준으로 단계적으로 대응하세요.",
            "asset_implications": {
                "QQQM": "금리와 변동성 민감도를 우선 점검하세요.",
                "SCHD": "배당/퀄리티 방어 특성을 점검하세요.",
                "IAU": "실질금리와 안전자산 수요를 확인하세요.",
                "SGOV": "현금성 완충 기능을 유지하세요.",
            },
            "watch_points": ["미국 10년물 금리 방향", "VIX 재상승 여부"],
            "sentiment_score": 0.0,
            "risk_level": "MODERATE",
            "risk_level_label": "보통",
            "core_article_count": 0,
            "secondary_article_count": 0,
            "articles": [],
            "brief_source": "rule_based",
        }


news_brief = fetch_news_brief(lookback_days=2, max_articles=20, region="US", asset_focus="growth")
market_news = news_brief.get("articles", []) if isinstance(news_brief, dict) else []

macro_summary = summarize_macro_today(
    vix_data=vix_data,
    fng_data=fng_data,
    qqqm_data=qqqm_data,
    sgov_data=sgov_data,
    market_news=market_news,
    news_brief=news_brief,
)

st.header("오늘의 거시경제 요약")
st.markdown(
    f"<span style='background: {macro_summary['color']}; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700;'>{macro_summary['regime_label']}</span>",
    unsafe_allow_html=True,
)
for line in macro_summary["bullets"]:
    st.markdown(f"- {line}")
st.caption(macro_summary["title"])
st.markdown(f"**시사점**: {macro_summary['implication']}")

st.subheader("📰 뉴스 기반 거시경제 브리핑")
nb = news_brief if isinstance(news_brief, dict) else {}

meta_col1, meta_col2, meta_col3, meta_col4 = st.columns(4)
meta_col1.metric("기준 시각", nb.get("as_of", "-"))
meta_col2.metric("기사 수", f"{nb.get('article_count', 0)}건")
meta_col3.metric("기사 수 (핵심/보조)", f"{nb.get('core_article_count', 0)} / {nb.get('secondary_article_count', 0)}")
meta_col4.metric("리스크 수준", nb.get("risk_level_label", "보통"))

engine_name = "Gemini" if nb.get("brief_source") == "gemini" else "규칙 기반"
st.caption(f"요약 엔진: {engine_name}")

st.markdown(f"**오늘의 뉴스 요약**: {nb.get('headline_summary', '뉴스 기반 요약을 생성하지 못했습니다.')}")

st.markdown("**시장 시사점**")
st.markdown(f"- {nb.get('market_implication', '시장 시사점을 계산하지 못했습니다.')}")

st.markdown("**포트폴리오 관점**")
st.markdown(f"- {nb.get('portfolio_implication', '전략 신호 중심의 보수적 운용을 유지하세요.')}")

st.markdown("**자산별 관점**")
asset_notes = nb.get("asset_implications", {}) if isinstance(nb.get("asset_implications"), dict) else {}
st.markdown(f"- QQQM: {asset_notes.get('QQQM', '금리와 변동성 민감도를 중심으로 점검하세요.')}")
st.markdown(f"- SCHD: {asset_notes.get('SCHD', '배당/퀄리티 방어 역할과 이익 전망 변화를 확인하세요.')}")
st.markdown(f"- IAU: {asset_notes.get('IAU', '실질금리와 안전자산 선호 흐름을 함께 점검하세요.')}")
st.markdown(f"- SGOV: {asset_notes.get('SGOV', '현금성 완충 자산으로 변동성 대응 여력을 유지하세요.')}")

st.markdown("**체크 포인트**")
watch_points = nb.get("watch_points", []) or ["미국 10년물 금리 방향", "VIX 재상승 여부"]
for point in watch_points[:4]:
    st.markdown(f"- {point}")

with st.expander("수집된 대표 뉴스 보기", expanded=False):
    if market_news:
        for item in market_news[:5]:
            title = (item.get("title") or "").strip()
            source = (item.get("source") or "출처 미상").strip()
            if title:
                st.markdown(f"- {title} ({source})")
    else:
        st.caption("현재 수집된 대표 뉴스가 없습니다.")

st.markdown("---")

# =====================================================================
# 3) Strategy Engine
# =====================================================================
# =====================================================================
# Strategy logic: Manual v5.10
# =====================================================================
st.header("전략 조건 분석")

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
        <div class="warning-title">⚠️ DEFCON 세이빙 발동</div>
        <p><strong>VIX:</strong> {vix_data['price']:.2f} (<= 14.00)</p>
        <p><strong>RSI:</strong> {qqqm_data['rsi']:.2f} (>= 70)</p>
        <p><strong>조치:</strong> 신규 자금 100%를 SGOV로 배분 (QQQM/SCHD/IAU 매수 차단)</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: #8b5cf6; font-size: 1.1em;">🔔 SGOV를 이미 매수한 경우</p>
        <div style="background: rgba(139, 92, 246, 0.1); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;"><strong>관찰:</strong> VIX &gt; 14 또는 RSI &lt; 70이면 DEFCON 해제</p>
            <p style="margin: 5px 0;"><strong>해제 후:</strong> 정상 비중(72/16/2/10)으로 복귀</p>
            <p style="margin: 5px 0;"><strong>기존 포지션:</strong> 보유 유지 (강제 매도 없음)</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

if puddle_alert:
    # Puddle stage guidance card
    stage_info = {
        1: {"name": "1단계: SMA50 하향 이탈", "color": "#fbbf24", "rate": 15, "desc": "완만한 조정 구간입니다. 보수적으로 분할 진입합니다."},
        2: {"name": "2단계: SMA100 하향 이탈", "color": "#f97316", "rate": 35, "desc": "깊은 조정 구간입니다. 계획대로 분할 진입합니다."},
        3: {"name": "3단계: SMA200 하향 이탈", "color": "#ef4444", "rate": 50, "desc": "고스트레스 구간입니다. 규율 있게 투입합니다."},
        4: {"name": "4단계: SMA200 회복", "color": "#10b981", "rate": 100, "desc": "회복이 확인되었습니다. 정상 비중으로 복귀합니다."}
    }
    
    info = stage_info[puddle_stage]
    
    # Dashboard policy: use current account snapshot only.
    # 백테스트s/simulations should track remaining_cash internally across events.
    remaining_cash = sgov_value + cash_deposit
    injection_amount = compute_deployment(puddle_stage, remaining_cash)
    cash_base = remaining_cash
    
    # Moving average labels
    sma_50_val = f"${qqqm_data['sma_50']:.2f}" if pd.notna(qqqm_data['sma_50']) else "-"
    sma_100_val = f"${qqqm_data['sma_100']:.2f}" if pd.notna(qqqm_data['sma_100']) else "-"
    sma_200_val = f"${qqqm_data['sma_200']:.2f}" if pd.notna(qqqm_data['sma_200']) else "-"
    
    # Next action guidance
    next_action_info = {
        1: {"next": "2단계 (SMA100 하향 이탈)", "watch": "SMA100", "next_rate": "35% 투입"},
        2: {"next": "3단계 (SMA200 하향 이탈)", "watch": "SMA200", "next_rate": "50% 투입"},
        3: {"next": "4단계 (SMA200 회복)", "watch": "SMA200 회복", "next_rate": "100% 투입"},
        4: {"next": "정상 운용", "watch": "포트폴리오 비중", "next_rate": "목표 비중 복귀"}
    }
    next_info = next_action_info[puddle_stage]
    
    st.markdown(f"""
    <div class="warning-box" style="border-color: {info['color']};">
        <div class="warning-title" style="color: {info['color']};">웅덩이 진입 구간: {info['name']}</div>
        <p style="color: #10b981; font-size: 0.9em;">30일 쿨다운이 해제되어 신규 신호 실행이 가능합니다.</p>
        <p><strong>현재가:</strong> ${qqqm_data['price']:.2f}</p>
        <p><strong>SMA50:</strong> {sma_50_val} | <strong>SMA100:</strong> {sma_100_val} | <strong>SMA200:</strong> {sma_200_val}</p>
        <p><strong>해석:</strong> {info['desc']}</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: {info['color']}; font-size: 1.1em;">현재 투입 계획 (v5.10)</p>
        <div style="background: rgba(251, 191, 36, 0.05); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;"><strong>현금성 자산:</strong> ${cash_base:,.2f}</p>
            <p style="margin: 5px 0;">구성: SGOV ${sgov_value:,.2f} + 예수금 ${cash_deposit:,.2f}</p>
            <p style="margin: 5px 0;"><strong>투입 비율:</strong> {info['rate']}%</p>
            <p style="margin: 5px 0; font-size: 1.2em; color: {info['color']};"><strong>투입 금액:</strong> ${injection_amount:,.2f}</p>
        </div>
        <p style="color: #10b981; font-weight: 700; margin-top: 10px;">신규 자금은 목표 비중 72/16/2/10으로 즉시 배분합니다.</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: #8b5cf6; font-size: 1.1em;">이번 투입 이후</p>
        <div style="background: rgba(139, 92, 246, 0.1); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;"><strong>다음 단계:</strong> {next_info['next']}</p>
            <p style="margin: 5px 0;"><strong>관찰:</strong> {next_info['watch']}</p>
            <p style="margin: 5px 0;"><strong>다음 비율:</strong> {next_info['next_rate']}</p>
            <p style="margin: 5px 0; color: #94a3b8;"><strong>신규 자금:</strong> 즉시 배분 (72/16/2/10).</p>
            <p style="margin: 5px 0; color: #94a3b8;"><strong>쿨다운:</strong> 동일 단계는 30일간 재발동되지 않습니다.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# Cooldown active while signal is blocked
if puddle_cooldown_active and not puddle_alert:
    st.markdown(f"""
    <div class="info-box">
        <div class="warning-title">웅덩이 쿨다운 진행 중</div>
        <p><strong>현재가:</strong> ${qqqm_data['price']:.2f} (대기)</p>
        <p><strong>판단 근거:</strong> {cooldown_info if cooldown_info else "최근 30일 이내 신호 발생"}</p>
        <hr style="border-color: rgba(251, 191, 36, 0.3); margin: 10px 0;">
        <p style="color: #fbbf24;"><strong>조치:</strong> 다음 유효 신호를 대기합니다 (중복 매수 방지).</p>
        <p style="color: #94a3b8; font-size: 0.9em;">신규 자금은 목표 비중에 따라 계속 즉시 배분됩니다.</p>
        <p style="color: #64748b; font-size: 0.85em;">쿨다운은 30일 후 만료됩니다.</p>
    </div>
    """, unsafe_allow_html=True)

if rebalancing_needed:
    excess = qqqm_pct - 72
    
    # Build explanation of pending trigger conditions.
    missing_conditions = []
    if not condition_2_below_sma20:
        missing_conditions.append("SMA20 하향 이탈")
    if not condition_3_after_high:
        missing_conditions.append("최근 고점 갱신")
    
    next_action_text = " + ".join(missing_conditions) if missing_conditions else "모든 조건 충족"
    status_20 = "SMA20 하회" if condition_2_below_sma20 else "SMA20 상회"
    status_high = "최근 고점 이후" if condition_3_after_high else "최근 고점 미확인"
    st.info(
        "QQQM 과비중 감지\n"
        f"- QQQM allocation: {qqqm_pct:.2f}% (target: 72%)\n"
        f"- Excess: +{excess:.2f}%p\n"
        f"- SMA20 status: {status_20}\n"
        f"- High update status: {status_high}\n"
        "- 현재 조치: Smart Shoulder 트리거 대기\n"
        f"- 다음 트리거 조건: {next_action_text}"
    )

if smart_shoulder_triggered:
    excess = qqqm_pct - 72
    st.error(
        "Smart Shoulder 리밸런싱 발동\n"
        f"- QQQM allocation: {qqqm_pct:.2f}% (target: 72%)\n"
        f"- Excess: +{excess:.2f}%p\n"
        f"- Condition 2: SMA20 하회 (${qqqm_data['sma_20']:.2f})\n"
        "- 조치: 포트폴리오를 72/16/2/10으로 리밸런싱"
    )

# RSI status
col1, col2, col3 = st.columns(3)

with col1:
    rsi_status = ""
    rsi_color = ""
    if qqqm_data['rsi'] >= 70:
        rsi_status = "과열"
        rsi_color = "#ef4444"
    elif qqqm_data['rsi'] <= 30:
        rsi_status = "과매도"
        rsi_color = "#3b82f6"
    else:
        rsi_status = "중립"
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
        sma_status = "SMA20 상회"
        sma_color = "#10b981"
    else:
        sma_status = "SMA20 하회"
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
        sma_status = "SMA50 상회"
        sma_color = "#10b981"
    elif pd.notna(qqqm_data['sma_50']):
        sma_status = "SMA50 하회"
        sma_color = "#ef4444"
    else:
        sma_status = "데이터 부족"
        sma_color = "#94a3b8"
    
    sma_50_display = f"${qqqm_data['sma_50']:.2f}" if pd.notna(qqqm_data['sma_50']) else "-"
    
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
        sma_status = "SMA100 상회"
        sma_color = "#10b981"
    elif pd.notna(qqqm_data['sma_100']):
        sma_status = "SMA100 하회"
        sma_color = "#f97316"
    else:
        sma_status = "데이터 부족"
        sma_color = "#94a3b8"
    
    sma_100_display = f"${qqqm_data['sma_100']:.2f}" if pd.notna(qqqm_data['sma_100']) else "-"
    
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
        sma_status = "SMA200 상회"
        sma_color = "#10b981"
    elif pd.notna(qqqm_data['sma_200']):
        sma_status = "SMA200 하회"
        sma_color = "#ef4444"
    else:
        sma_status = "데이터 부족"
        sma_color = "#94a3b8"
    
    sma_200_display = f"${qqqm_data['sma_200']:.2f}" if pd.notna(qqqm_data['sma_200']) else "-"
    
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
        stage_text = "정상"
        stage_color = "#10b981"
        stage_icon = "OK"
    elif puddle_stage == 1:
        stage_text = "1단계 (SMA50)"
        stage_color = "#fbbf24"
        stage_icon = "S1"
    elif puddle_stage == 2:
        stage_text = "2단계 (SMA100)"
        stage_color = "#f97316"
        stage_icon = "S2"
    elif puddle_stage == 3:
        stage_text = "3단계 (SMA200)"
        stage_color = "#ef4444"
        stage_icon = "S3"
    else:  # stage 4
        stage_text = "4단계 (회복)"
        stage_color = "#10b981"
        stage_icon = "S4"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {stage_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">웅덩이 단계</p>
        <p style="font-size: 2em; font-weight: 700; color: {stage_color}; margin: 10px 0;">{stage_icon}</p>
        <p style="font-size: 1.1em; color: {stage_color}; font-weight: 600;">{stage_text}</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# =====================================================================
# Portfolio allocation analysis
# =====================================================================
st.header("포트폴리오 비중")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("자산 구성")
    st.metric("총 자산", f"${total_value:,.2f}")
    
    portfolio_df = pd.DataFrame({
        'Asset': ['QQQM', 'SCHD', 'IAU', 'SGOV', '예수금', '현금 합계'],
        'Value': [qqqm_value, schd_value, iau_value, sgov_value, cash_deposit, total_cash],
        '현재 비중 (%)': [qqqm_pct, schd_pct, iau_pct, sgov_pct, deposit_pct, cash_pct],
        '목표 비중 (%)': ['72.00%', '16.00%', '2.00%', '-', '-', '10.00%'],
        '목표 대비 차이 (%p)': [
            f'{qqqm_pct - 72:+.2f}%p',
            f'{schd_pct - 16:+.2f}%p',
            f'{iau_pct - 2:+.2f}%p',
            '-',
            '-',
            f'{cash_pct - 10:+.2f}%p',
        ]
    })

    def highlight_rows(row):
        if row['Asset'] == '현금 합계':
            return ['background-color: rgba(59, 130, 246, 0.1)'] * len(row)
        if row['Asset'] in ['SGOV', '예수금']:
            return ['background-color: rgba(148, 163, 184, 0.05)'] * len(row)
        return [''] * len(row)

    st.dataframe(
        portfolio_df.style.format({
            'Value': '${:,.2f}',
            '현재 비중 (%)': '{:.2f}%',
        }).apply(highlight_rows, axis=1),
        width='stretch'
    )

with col2:
    st.subheader("비중 차트")
    
    # Pie chart (mobile-optimized layout)
    fig = go.Figure(data=[go.Pie(
        labels=['QQQM', 'SCHD', 'IAU', 'SGOV', '예수금'],
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
st.header("📊 QQQM 기술적 분석")

# 현재가 chart
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
        title='현재가 (USD)'
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

# 과열 / 과매도 lines
fig_rsi.add_hline(y=70, line_dash="dash", line_color="#ef4444", annotation_text="과열(70)")
fig_rsi.add_hline(y=30, line_dash="dash", line_color="#3b82f6", annotation_text="과매도(30)")

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
    st.header("백테스트 (실험)")
    st.caption("규칙: 신호는 D일 종가에 계산되고, D+1일 시가에 체결됩니다. 수수료 1bp, 슬리피지 2bp를 적용합니다.")
    st.markdown(f"""
    <div class="info-box">
        <div class="warning-title">가정</div>
        <p>신호 시점: D일 종가 기준 계산</p>
        <p>체결 시점: D+1일 시가 체결 (다음 거래일)</p>
        <p>4단계: 다음 거래일 시가에 잔여 현금 전액 투입</p>
        <p>단계별 비율(1/2/3): {bt_stage_rates} | 4단계: 100%</p>
        <p>변동성 보정: {'활성화' if backtest_vol_adjust else '비활성화'}</p>
        <p>수수료(bps): {bt_fee_bps:.1f} | 슬리피지(bps): {bt_slippage_bps:.1f}</p>
        <p>체결 모드: 롱 전용, 매수 전용</p>
    </div>
    """, unsafe_allow_html=True)

    if backtest_vol_adjust:
        st.caption(f"현재 추정 변동성 계수(QQQM): {bt_current_vol_factor:.2f}")

    metrics_rows = [
        {"지표": "CAGR", "값": f"{bt_result.metrics.get('CAGR', 0.0) * 100:.2f}%"},
        {"지표": "총 수익률", "값": f"{bt_result.metrics.get('TotalReturn', 0.0) * 100:.2f}%"},
        {"지표": "비교군 수익률", "값": f"{bt_result.metrics.get('BenchmarkTotalReturn', 0.0) * 100:.2f}%"},
        {"지표": "최대 낙폭(MDD)", "값": f"{bt_result.metrics.get('MDD', 0.0) * 100:.2f}%"},
        {"지표": "연환산 변동성", "값": f"{bt_result.metrics.get('Volatility', 0.0) * 100:.2f}%"},
        {"지표": "샤프 지수", "값": f"{bt_result.metrics.get('Sharpe', 0.0):.2f}"},
        {"지표": "거래 횟수", "값": f"{int(bt_result.metrics.get('NumTrades', 0))}"},
        {"지표": "최대 낙폭 구간", "값": str(bt_result.metrics.get('MaxDD_start_end', None))},
    ]
    st.dataframe(pd.DataFrame(metrics_rows), width='stretch', hide_index=True)

    if not bt_result.equity_curve.empty:
        fig_bt = go.Figure()
        fig_bt.add_trace(go.Scatter(
            x=bt_result.equity_curve.index,
            y=bt_result.equity_curve.values,
            mode='lines',
            name='전략 누적 자산',
            line=dict(color='#10b981', width=2),
        ))
        if not bt_result.benchmark_curve.empty:
            fig_bt.add_trace(go.Scatter(
                x=bt_result.benchmark_curve.index,
                y=bt_result.benchmark_curve.values,
                mode='lines',
                name='비교군(매수 후 보유)',
                line=dict(color='#3b82f6', width=2, dash='dash'),
            ))
        fig_bt.update_layout(
            plot_bgcolor='rgba(30, 41, 59, 0.5)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#e2e8f0'),
            xaxis=dict(gridcolor='rgba(148, 163, 184, 0.2)', showgrid=True),
            yaxis=dict(gridcolor='rgba(148, 163, 184, 0.2)', showgrid=True, title='누적 자산 (USD)'),
            height=320,
            hovermode='x unified',
            margin=dict(l=40, r=20, t=20, b=20),
        )
        st.plotly_chart(fig_bt, width='stretch', config={'displayModeBar': False})

        if not bt_result.trades.empty:
            latest_n = 20
            st.caption(f"거래: {len(bt_result.trades)} | 최근 {latest_n}")
            trades_view = bt_result.trades.sort_values("exec_date", ascending=False).head(latest_n).copy()
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
            trades_view = trades_view.rename(
                columns={
                    "signal_date": "신호 일자",
                    "exec_date": "체결 일자",
                    "stage": "단계",
                    "action": "동작",
                    "planned_cash": "계획 현금",
                    "fee": "수수료",
                    "exec_price": "체결 가격",
                    "shares_bought": "매수 수량",
                    "cash_after": "체결 후 현금",
                    "shares_after": "체결 후 수량",
                    "vol_factor": "변동성 계수",
                    "reason": "판단 근거",
                }
            )
            trades_view = trades_view[
                ["신호 일자", "체결 일자", "단계", "동작", "계획 현금", "수수료", "체결 가격", "매수 수량", "체결 후 수량", "체결 후 현금", "변동성 계수", "판단 근거"]
            ]
            st.dataframe(
                trades_view,
                width='stretch',
                hide_index=True,
            )

st.markdown("---")
st.header("전략 연구실")
st.caption("연구 모드: 단일 실행, 현금 비중 연구, 쿨다운 민감도, 다중 자산 검증")

lab_modes = ["단일 실행", "현금 비중 연구", "쿨다운 연구", "다중 자산 검증"]
lab_mode = st.selectbox("연구 모드", lab_modes, index=0)

lab_col1, lab_col2, lab_col3 = st.columns(3)
with lab_col1:
    lab_symbol = st.selectbox("종목", ["QQQM", "SPY", "VTI", "BTC-USD"], index=0)
with lab_col2:
    lab_start_date = st.date_input("시작일", value=pd.Timestamp("2012-01-01").date())
with lab_col3:
    lab_initial_cash = st.number_input("초기 자본 (USD)", min_value=1000.0, value=10000.0, step=1000.0)

lab_assets = st.multiselect("다중 자산 세트", ["QQQM", "SPY", "VTI", "BTC-USD"], default=["QQQM", "SPY", "VTI", "BTC-USD"])

ctrl_col1, ctrl_col2 = st.columns(2)
with ctrl_col1:
    lab_cash_ratio = st.slider("현금 비중", min_value=0.05, max_value=0.30, value=0.10, step=0.01)
with ctrl_col2:
    lab_cooldown = st.slider("쿨다운 일수", min_value=10, max_value=60, value=30, step=1)

with st.expander("단계별 투입 비율 (1/2/3)", expanded=False):
    rate_col1, rate_col2, rate_col3 = st.columns(3)
    with rate_col1:
        lab_rate_1 = st.slider("1단계 비율", min_value=0.0, max_value=1.0, value=float(STAGE_DEPLOYMENT_RATES[1]), step=0.01)
    with rate_col2:
        lab_rate_2 = st.slider("2단계 비율", min_value=0.0, max_value=1.0, value=float(STAGE_DEPLOYMENT_RATES[2]), step=0.01)
    with rate_col3:
        lab_rate_3 = st.slider("3단계 비율", min_value=0.0, max_value=1.0, value=float(STAGE_DEPLOYMENT_RATES[3]), step=0.01)

crisis_period = st.selectbox("급락장 분석 (선택)", ["없음", "2008", "2020", "2022"], index=0)

lab_stage_rates = {1: float(lab_rate_1), 2: float(lab_rate_2), 3: float(lab_rate_3)}
rate_sum = lab_rate_1 + lab_rate_2 + lab_rate_3
if rate_sum > 1.0:
    st.error(f"단계별 투입 비율 합계는 1.0 이하여야 합니다 (현재: {rate_sum:.2f})")


def _apply_crisis_filter(df: pd.DataFrame, period_label: str) -> pd.DataFrame:
    if period_label == "없음":
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


lab_run = st.button("전략 연구 실행", width='stretch')

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
            raise ValueError(f"급락장 필터 적용 후 데이터가 없습니다 ({crisis_period})")
        return out

    if lab_mode == "단일 실행":
        with st.spinner("전략 백테스트 실행 중..."):
            lab_df = _run_one(lab_symbol, lab_cooldown, lab_cash_ratio)
            lab_metrics = compute_backtest_metrics(lab_df)

        mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
        mcol1.metric("총 수익률", f"{lab_metrics['Total Return'] * 100:.2f}%")
        mcol2.metric("CAGR", f"{lab_metrics['CAGR'] * 100:.2f}%")
        mcol3.metric("최대 낙폭", f"{lab_metrics['Max Drawdown'] * 100:.2f}%")
        mcol4.metric("변동성", f"{lab_metrics['Volatility'] * 100:.2f}%")
        mcol5.metric("Sharpe", f"{lab_metrics['Sharpe Ratio']:.2f}")

        compare_df = pd.DataFrame(
            [
                {"구분": "전략", "수익률": f"{lab_metrics['strategy_return'] * 100:.2f}%"},
                {"구분": "매수 후 보유", "수익률": f"{lab_metrics['buy_hold_return'] * 100:.2f}%"},
            ]
        )
        st.dataframe(compare_df, width='stretch', hide_index=True)

        st.plotly_chart(plot_backtest_results(lab_df), width='stretch', config={"displayModeBar": False})

        deploy_df = lab_df[lab_df["deploy_cash"] > 0].copy()
        fig_dep = go.Figure()
        fig_dep.add_trace(go.Bar(x=deploy_df["date"], y=deploy_df["deploy_cash"], name="투입 현금", marker_color="#f59e0b"))
        fig_dep.update_layout(height=260, yaxis=dict(title="투입 현금 (USD)"), hovermode="x unified", margin=dict(l=40, r=20, t=20, b=20))
        st.plotly_chart(fig_dep, width='stretch', config={"displayModeBar": False})

        st.caption(f"행 수={len(lab_df)} | 종목={lab_symbol} | 쿨다운={lab_cooldown} | 현금비중={lab_cash_ratio:.2f} | 비율={lab_stage_rates} | 위기구간={crisis_period}")
        export_df = lab_df.copy()

    elif lab_mode == "현금 비중 연구":
        cash_grid = [0.05, 0.10, 0.20, 0.30]
        rows = []
        with st.spinner("현금 비중 연구 실행 중..."):
            for cr in cash_grid:
                run_df = _run_one(lab_symbol, lab_cooldown, cr)
                m = compute_backtest_metrics(run_df)
                rows.append(
                    {
                        "현금 비중": cr,
                        "CAGR": m["CAGR"],
                        "Sharpe": m["Sharpe Ratio"],
                        "최대 낙폭": m["Max Drawdown"],
                        "총 수익률": m["Total Return"],
                    }
                )
        cash_df = pd.DataFrame(rows)
        show_cash_df = cash_df.copy()
        show_cash_df["CAGR"] = show_cash_df["CAGR"].map(lambda x: f"{x * 100:.2f}%")
        show_cash_df["최대 낙폭"] = show_cash_df["최대 낙폭"].map(lambda x: f"{x * 100:.2f}%")
        show_cash_df["총 수익률"] = show_cash_df["총 수익률"].map(lambda x: f"{x * 100:.2f}%")
        st.dataframe(show_cash_df, width='stretch', hide_index=True)
        export_df = cash_df

    elif lab_mode == "쿨다운 연구":
        cooldown_grid = [10, 20, 30, 40, 60]
        rows = []
        with st.spinner("쿨다운 민감도 분석 실행 중..."):
            for cd in cooldown_grid:
                run_df = _run_one(lab_symbol, cd, lab_cash_ratio)
                m = compute_backtest_metrics(run_df)
                rows.append(
                    {
                        "쿨다운": cd,
                        "CAGR": m["CAGR"],
                        "Sharpe": m["Sharpe Ratio"],
                        "최대 낙폭": m["Max Drawdown"],
                        "총 수익률": m["Total Return"],
                    }
                )
        cooldown_df = pd.DataFrame(rows)
        st.dataframe(cooldown_df, width='stretch', hide_index=True)

        fig_cd = go.Figure()
        fig_cd.add_trace(go.Scatter(x=cooldown_df["쿨다운"], y=cooldown_df["CAGR"], mode="lines+markers", name="CAGR", line=dict(color="#10b981")))
        fig_cd.add_trace(go.Scatter(x=cooldown_df["쿨다운"], y=cooldown_df["총 수익률"], mode="lines+markers", name="총 수익률", line=dict(color="#3b82f6")))
        fig_cd.add_trace(go.Scatter(x=cooldown_df["쿨다운"], y=cooldown_df["Sharpe"], mode="lines+markers", name="Sharpe", line=dict(color="#f59e0b"), yaxis="y2"))
        fig_cd.update_layout(
            height=320,
            xaxis=dict(title="쿨다운 일수"),
            yaxis=dict(title="수익률", tickformat=".1%"),
            yaxis2=dict(title="Sharpe", overlaying="y", side="right"),
            hovermode="x unified",
            margin=dict(l=40, r=40, t=20, b=20),
        )
        st.plotly_chart(fig_cd, width='stretch', config={"displayModeBar": False})
        export_df = cooldown_df

    else:  # MULTI-ASSET VALIDATION
        if not lab_assets:
            st.warning("최소 1개 자산을 선택하세요.")
        else:
            rows = []
            with st.spinner("다중 자산 검증 실행 중..."):
                for sym in lab_assets:
                    run_df = _run_one(sym, lab_cooldown, lab_cash_ratio)
                    m = compute_backtest_metrics(run_df)
                    rows.append(
                        {
                            "자산": sym,
                            "CAGR": m["CAGR"],
                            "Sharpe": m["Sharpe Ratio"],
                            "최대 낙폭": m["Max Drawdown"],
                            "전략 수익률": m["strategy_return"],
                            "매수후보유 수익률": m["buy_hold_return"],
                        }
                    )
            multi_df = pd.DataFrame(rows)
            show_multi_df = multi_df.copy()
            for col in ["CAGR", "최대 낙폭", "전략 수익률", "매수후보유 수익률"]:
                show_multi_df[col] = show_multi_df[col].map(lambda x: f"{x * 100:.2f}%")
            st.dataframe(show_multi_df, width='stretch', hide_index=True)
            export_df = multi_df

    if export_df is not None and not export_df.empty:
        csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "연구 결과 내보내기",
            data=csv_bytes,
            file_name=f"strategy_lab_{lab_mode.lower().replace(' ', '_')}.csv",
            mime="text/csv",
            width='stretch',
        )

st.markdown("---")
st.header("📊 FIRE 시뮬레이터")
st.caption("과거 수익률을 기반으로 미래 포트폴리오 경로를 부트스트랩하여 장기 FIRE 달성 가능성을 추정합니다.")

mc_col1, mc_col2, mc_col3 = st.columns(3)
with mc_col1:
    mc_symbol = st.selectbox("시뮬레이션 종목", ["QQQM", "SPY", "VTI", "BTC-USD"], index=0)
with mc_col2:
    mc_start_date = st.date_input("시뮬레이션 수익률 시작일", value=pd.Timestamp("2012-01-01").date())
with mc_col3:
    mc_years = st.slider("투자 기간 (년)", min_value=5, max_value=40, value=20, step=1)

mc_col4, mc_col5, mc_col6 = st.columns(3)
with mc_col4:
    mc_initial = st.number_input("초기 자본", min_value=1000.0, value=max(total_value, 10000.0), step=1000.0)
with mc_col5:
    mc_annual_inv = st.number_input("연간 투자금", min_value=0.0, value=12000.0, step=1000.0)
with mc_col6:
    mc_target = st.number_input("목표 FIRE 자본", min_value=10000.0, value=1000000.0, step=10000.0)

mc_simulations = st.slider("시뮬레이션 수", min_value=200, max_value=5000, value=1000, step=100)
mc_run = st.button("FIRE 시뮬레이션 실행", width='stretch')

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
    fig_dist.add_trace(
        go.Histogram(
            x=final_values.values,
            nbinsx=50,
            marker_color="#3b82f6",
            opacity=0.85,
            name="최종 자산",
        )
    )
    fig_dist.add_vline(x=float(mc_target), line_color="#ef4444", line_dash="dash", annotation_text="FIRE 목표")
    fig_dist.update_layout(
        height=300,
        xaxis=dict(title="최종 포트폴리오 가치 (USD)", gridcolor="rgba(148, 163, 184, 0.2)"),
        yaxis=dict(title="건수", gridcolor="rgba(148, 163, 184, 0.2)"),
        plot_bgcolor="rgba(30, 41, 59, 0.5)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e2e8f0"),
        margin=dict(l=40, r=20, t=20, b=20),
    )
    st.plotly_chart(fig_dist, width='stretch', config={"displayModeBar": False})

    export_sim = sim_paths.copy()
    export_sim.insert(0, "day", export_sim.index)
    st.download_button(
        "시뮬레이션 결과 CSV 내보내기",
        data=export_sim.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"fire_simulator_{mc_symbol}_{mc_years}y_{mc_simulations}sims.csv",
        mime="text/csv",
        width='stretch',
    )

st.markdown("---")

# =====================================================================
# Execution plan status
# =====================================================================
st.header("실행 계획")
status_lines = []

if defcon_triggered:
    status_lines.append("DEFCON 세이빙 발동: 신규 자금을 SGOV로만 배분")

if puddle_alert:
    deploy_base = float(sgov_value + cash_deposit)
    deploy_amount = compute_deployment(puddle_stage, deploy_base)
    status_lines.append(
        f"웅덩이 단계 {puddle_stage} 신호: 기준자금=${deploy_base:,.2f}, 권장 투입액=${deploy_amount:,.2f}"
    )
elif puddle_cooldown_active:
    status_lines.append(f"웅덩이 쿨다운 진행 중: {cooldown_info if cooldown_info else '최근 30일 이내 신호 발생'}")

if smart_shoulder_triggered:
    status_lines.append("스마트 숄더 발동: 리밸런싱 필요")
elif rebalancing_needed:
    missing_text = " / ".join(shoulder_eval.get("reasons", [])) if shoulder_eval.get("reasons") else "추가 조건 필요"
    status_lines.append(f"⚠️ QQQM 77% 초과 대기: {missing_text}")

if not status_lines:
    status_lines.append("핵심 전략 정상 운용 중")

for line in status_lines:
    st.markdown(f"- {line}")

if new_cash > 0:
    st.caption(f"신규 자금: ${new_cash:,.2f} | 목표 비중: 72/16/2/10")

st.markdown("---")

# =====================================================================
# Footer separator
# =====================================================================
st.markdown("---")

# =====================================================================
# Portfolio market-driver analysis
# =====================================================================
st.header("오늘의 시장 동인")

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
        'AI/기술': {
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
        '경기/고용': {
            'keywords': ['job', 'jobs', 'employment', 'gdp', 'economy', 'economic', 'recession', 'growth', 'labor', 'unemployment', 'payroll', 'hire', 'hiring', 'layoff', 'worker'],
            'positive': ['strong', 'growth', 'add', 'robust', 'resilient', 'expand', 'hire'],
            'negative': ['weak', 'slow', 'recession', 'layoff', 'decline', 'contract', 'cut']
        },
        '안전자산': {
            'keywords': ['gold', 'silver', 'safe', 'haven', 'precious', 'metal', 'commodity', 'oil', 'crude', 'energy'],
            'positive': ['rally', 'surge', 'demand', 'rise', 'gain', 'climb', 'high'],
            'negative': ['fall', 'drop', 'decline', 'sell', 'low', 'slide', 'tumble']
        },
        '시장 심리': {
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
    
    # 현재가 direction
    if change_pct > 1.0:
        direction = "강한 상승"
        direction_detail = "상승 모멘텀 확대"
    elif change_pct > 0.3:
        direction = "상승"
        direction_detail = "완만한 상승"
    elif change_pct > -0.3:
        direction = "보합"
        direction_detail = "제한적 움직임"
    elif change_pct > -1.0:
        direction = "하락"
        direction_detail = "완만한 하락"
    else:
        direction = "강한 하락"
        direction_detail = "하방 압력 확대"
    
    # Key factors (up to 3)
    main_factors = []
    for f in factors[:3]:
        sentiment_icon = "+" if f['sentiment'] == 'positive' else ("-" if f['sentiment'] == 'negative' else "=")
        main_factors.append(f"{sentiment_icon} {f['category']}")
    
    # Fallback factors when news-based signals are sparse
    if not main_factors:
        if symbol == 'QQQM':
            if change_pct > 0.5:
                main_factors = ["+ 기술주 주도", "+ AI/반도체 수요"]
            elif change_pct < -0.5:
                main_factors = ["- 기술주 약세", "- 금리 부담 우려"]
            else:
                main_factors = ["= 기술주 혼조", "= 방향성 불명확"]
        elif symbol == 'SCHD':
            if change_pct > 0.5:
                main_factors = ["+ 배당주 강세", "+ 방어주 선호"]
            elif change_pct < -0.5:
                main_factors = ["- 배당주 약세", "- 성장주 로테이션"]
            else:
                main_factors = ["= 배당주 횡보", "= 배당수익 안정"]
        elif symbol == 'IAU':
            if change_pct > 0.5:
                main_factors = ["+ 금 강세", "+ 안전자산 수요", "+ 달러 약세"]
            elif change_pct < -0.5:
                main_factors = ["- 금 약세", "- 위험선호 로테이션", "- 달러 강세"]
            else:
                main_factors = ["= 금 횡보", "= 관망 흐름"]
        else:
            if change_pct > 0.5:
                main_factors = ["+ 시장 강세", "+ 매수 유입"]
            elif change_pct < -0.5:
                main_factors = ["- 시장 약세", "- 매도 압력"]
            else:
                main_factors = ["= 방향성 불명확", "= 관망 흐름"]
    
    return {
        'direction': direction,
        'direction_detail': direction_detail,
        'factors': main_factors,
        'news': news_list[:2] if news_list else []  # Top 2 headlines
    }

# Gather analysis inputs
with st.spinner('시장 동인 분석 중...'):
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
    
    qqqm_analysis = get_market_interpretation('QQQM', '나스닥 100', qqqm_data['change_pct'], qqqm_news)
    schd_analysis = get_market_interpretation('SCHD', '배당 성장', schd_data['change_pct'], schd_news)
    iau_analysis = get_market_interpretation('IAU', '금', iau_data['change_pct'], iau_news)

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
        market_mood = "강한 상승"
        mood_emoji = "BULL"
    elif portfolio_change > 0.5:
        market_mood = "상승"
        mood_emoji = "UP"
    elif portfolio_change > -0.5:
        market_mood = "중립"
        mood_emoji = "NEUTRAL"
    elif portfolio_change > -1.5:
        market_mood = "하락"
        mood_emoji = "DOWN"
    else:
        market_mood = "강한 하락"
        mood_emoji = "BEAR"
    
    # Extract top-2 key issues
    key_issues = []
    for f in all_factors[:2]:
        # Strip factor sign prefixes
        issue = f.replace("+ ", "").replace("- ", "").replace("= ", "")
        key_issues.append(issue)
    
    if key_issues:
        return f"{mood_emoji} {market_mood} | 주요 이슈: {', '.join(key_issues)}"
    else:
        return f"{mood_emoji} {market_mood}"

market_summary_text = generate_market_summary()

# Portfolio summary cards
col1, col2, col3 = st.columns([2, 2, 3])

with col1:
    st.markdown(f"""
    <div style="background: #1e293b; 
                border: 2px solid {port_color}; border-radius: 12px; padding: 20px; text-align: center;">
        <p style="color: #cbd5e1; font-size: 0.9em; margin: 0 0 8px 0;">오늘 수익률</p>
        <p style="color: {port_color}; font-size: 2.4em; font-weight: 800; margin: 0;">
            {port_icon} {portfolio_change:+.2f}%
        </p>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div style="background: #1e293b; 
                border: 2px solid {port_color}; border-radius: 12px; padding: 20px; text-align: center;">
        <p style="color: #cbd5e1; font-size: 0.9em; margin: 0 0 8px 0;">예상 손익</p>
        <p style="color: {port_color}; font-size: 2.4em; font-weight: 800; margin: 0;">
            {'+' if portfolio_daily_change >= 0 else ''}${portfolio_daily_change:,.2f}
        </p>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div style="background: #1e293b; 
                border: 2px solid #10b981; border-radius: 12px; padding: 20px;">
        <p style="color: #10b981; font-size: 0.9em; margin: 0 0 10px 0; font-weight: 600;">시장 심리 요약</p>
        <p style="color: #f1f5f9; font-size: 1.15em; font-weight: 700; margin: 0; line-height: 1.5;">
            {market_summary_text}
        </p>
    </div>
    """, unsafe_allow_html=True)

# Weight contribution details
st.markdown(f"""
<div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 12px 15px; margin-top: 15px;">
    <p style="color: #e2e8f0; font-size: 0.95em; margin: 0; text-align: center;">
        <span style="color: #10b981; font-weight: 600;">QQQM</span> {qqqm_data['change_pct']:+.2f}% x 72% &nbsp;&nbsp;|&nbsp;&nbsp; 
        <span style="color: #3b82f6; font-weight: 600;">SCHD</span> {schd_data['change_pct']:+.2f}% x 16% &nbsp;&nbsp;|&nbsp;&nbsp; 
        <span style="color: #fbbf24; font-weight: 600;">IAU</span> {iau_data['change_pct']:+.2f}% x 2%
    </p>
</div>
""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# =====================================================================
# Asset detail analysis
# =====================================================================
st.subheader("📊 자산 상세 분석")

# QQQM 遺꾩꽍
qqqm_color = "#ef4444" if qqqm_data['change_pct'] >= 0 else "#3b82f6"
qqqm_icon = "📈" if qqqm_data['change_pct'] >= 0 else "📉"

with st.expander(f"🟢 **QQQM (나스닥 100)** - {qqqm_icon} {qqqm_data['change_pct']:+.2f}% (${qqqm_data['price']:.2f})", expanded=True):
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background: rgba(16, 185, 129, 0.1); border-radius: 12px;">
            <p style="color: #10b981; font-size: 0.9em; margin: 0;">오늘 방향성</p>
            <p style="color: {qqqm_color}; font-size: 1.8em; font-weight: 700; margin: 5px 0;">{qqqm_analysis['direction']}</p>
            <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{qqqm_analysis['direction_detail']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("**주요 요인**")
        for factor in qqqm_analysis['factors']:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{factor}")
        
        if qqqm_analysis['news']:
            st.markdown("**관련 뉴스**")
            for news in qqqm_analysis['news']:
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;[{news['title'][:50]}...]({news['link']})")

# SCHD 遺꾩꽍
schd_color = "#ef4444" if schd_data['change_pct'] >= 0 else "#3b82f6"
schd_icon = "📈" if schd_data['change_pct'] >= 0 else "📉"

with st.expander(f"🔵 **SCHD (배당 성장)** - {schd_icon} {schd_data['change_pct']:+.2f}% (${schd_data['price']:.2f})", expanded=True):
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background: rgba(59, 130, 246, 0.1); border-radius: 12px;">
            <p style="color: #3b82f6; font-size: 0.9em; margin: 0;">오늘 방향성</p>
            <p style="color: {schd_color}; font-size: 1.8em; font-weight: 700; margin: 5px 0;">{schd_analysis['direction']}</p>
            <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{schd_analysis['direction_detail']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("**주요 요인**")
        for factor in schd_analysis['factors']:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{factor}")
        
        if schd_analysis['news']:
            st.markdown("**관련 뉴스**")
            for news in schd_analysis['news']:
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;[{news['title'][:50]}...]({news['link']})")

# IAU 遺꾩꽍
iau_color = "#ef4444" if iau_data['change_pct'] >= 0 else "#3b82f6"
iau_icon = "📈" if iau_data['change_pct'] >= 0 else "📉"

with st.expander(f"🟡 **IAU (금)** - {iau_icon} {iau_data['change_pct']:+.2f}% (${iau_data['price']:.2f})", expanded=True):
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background: rgba(251, 191, 36, 0.1); border-radius: 12px;">
            <p style="color: #fbbf24; font-size: 0.9em; margin: 0;">오늘 방향성</p>
            <p style="color: {iau_color}; font-size: 1.8em; font-weight: 700; margin: 5px 0;">{iau_analysis['direction']}</p>
            <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{iau_analysis['direction_detail']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("**주요 요인**")
        for factor in iau_analysis['factors']:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{factor}")
        
        if iau_analysis['news']:
            st.markdown("**관련 뉴스**")
            for news in iau_analysis['news']:
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;[{news['title'][:50]}...]({news['link']})")

# VIX 遺꾩꽍
if vix_data:
    vix_color = "#3b82f6" if vix_data['change_pct'] >= 0 else "#10b981"
    vix_icon = "상승" if vix_data['change_pct'] >= 0 else "하락"
    vix_status = "변동성 상승 (주의)" if vix_data['change_pct'] >= 0 else "변동성 하락 (안정화)"
    
    with st.expander(f"🔴 **VIX (공포 지수)** - {vix_icon} {vix_data['change_pct']:+.2f}% ({vix_data['price']:.2f})", expanded=False):
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.markdown(f"""
            <div style="text-align: center; padding: 15px; background: rgba(239, 68, 68, 0.1); border-radius: 12px;">
                <p style="color: #ef4444; font-size: 0.9em; margin: 0;">시장 변동성</p>
                <p style="color: {vix_color}; font-size: 1.5em; font-weight: 700; margin: 5px 0;">{vix_status.split('(')[0].strip()}</p>
                <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">VIX {vix_data['price']:.1f}</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("**VIX 해석**")
            if vix_data['price'] <= 14:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;- 매우 낮음: 과열 구간 (DEFCON 조건)")
            elif vix_data['price'] <= 20:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;= 정상 범위: 일반적 시장 변동성")
            elif vix_data['price'] <= 30:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;+ 높은 편: 불안정한 시장 상황")
            else:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;+ 매우 높음: 극단적 공포 국면")
            
            st.markdown("**투자자 시사점**")
            if vix_data['change_pct'] >= 0:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;⚠️ 변동성 증가 중 - 신중한 접근 권장")
            else:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;변동성 하락 중: 시장 안정화 신호 가능성")

st.markdown("---")

# =====================================================================
# Portfolio history (Google Sheets integration)
# =====================================================================
if gs_available and is_personal_mode:
    with st.expander("📊 포트폴리오 히스토리", expanded=False):
        history_df, history_error = get_portfolio_history()
        
        if history_error:
            st.info(f"안내: {history_error}")
        elif history_df is not None and len(history_df) > 0:
            # Portfolio value trend chart
            st.subheader("포트폴리오 가치 추이")
            
            # Prepare chart dataframe
            chart_df = history_df[['Date', 'TotalValue']].dropna().copy()
            chart_df = chart_df.sort_values('Date')
            
            if len(chart_df) > 0:
                # Period selector
                st.markdown("**기간 선택**")
                period_options = ["전체", "최근 1주", "최근 1개월", "최근 3개월", "최근 6개월", "최근 1년", "사용자 지정"]
                selected_period = st.selectbox("조회 기간", period_options, index=0, label_visibility="collapsed")
                
                # Apply period filter
                today = pd.Timestamp.now()
                if selected_period == "최근 1주":
                    start_date = today - pd.Timedelta(days=7)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "최근 1개월":
                    start_date = today - pd.Timedelta(days=30)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "최근 3개월":
                    start_date = today - pd.Timedelta(days=90)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "최근 6개월":
                    start_date = today - pd.Timedelta(days=180)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "최근 1년":
                    start_date = today - pd.Timedelta(days=365)
                    filtered_df = chart_df[chart_df['Date'] >= start_date]
                elif selected_period == "사용자 지정":
                    col_date1, col_date2 = st.columns(2)
                    with col_date1:
                        min_date = chart_df['Date'].min().date() if len(chart_df) > 0 else today.date()
                        start_date = st.date_input("시작일", value=min_date, min_value=min_date)
                    with col_date2:
                        max_date = chart_df['Date'].max().date() if len(chart_df) > 0 else today.date()
                        end_date = st.date_input("End Date", value=max_date, max_value=max_date)
                    filtered_df = chart_df[(chart_df['Date'].dt.date >= start_date) & (chart_df['Date'].dt.date <= end_date)]
                else:  # 전체
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
                        name='총 자산',
                        line=dict(color='#10b981', width=2),
                        marker=dict(size=6, color='#10b981'),
                        hovertemplate='<b>%{x|%Y-%m-%d %H:%M}</b><br>총 자산: $%{y:,.2f}<extra></extra>'
                    ))
                    
                    # Mark highest/lowest points
                    max_idx = filtered_df['TotalValue'].idxmax()
                    min_idx = filtered_df['TotalValue'].idxmin()
                    
                    fig.add_trace(go.Scatter(
                        x=[filtered_df.loc[max_idx, 'Date']],
                        y=[filtered_df.loc[max_idx, 'TotalValue']],
                        mode='markers+text',
                        name='고점',
                        marker=dict(size=12, color='#ef4444', symbol='triangle-up'),
                        text=[f"${filtered_df.loc[max_idx, 'TotalValue']:,.2f}"],
                        textposition='top center',
                        textfont=dict(color='#ef4444', size=11),
                        hovertemplate='<b>고점</b><br>%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>'
                    ))
                    
                    fig.add_trace(go.Scatter(
                        x=[filtered_df.loc[min_idx, 'Date']],
                        y=[filtered_df.loc[min_idx, 'TotalValue']],
                        mode='markers+text',
                        name='저점',
                        marker=dict(size=12, color='#3b82f6', symbol='triangle-down'),
                        text=[f"${filtered_df.loc[min_idx, 'TotalValue']:,.2f}"],
                        textposition='bottom center',
                        textfont=dict(color='#3b82f6', size=11),
                        hovertemplate='<b>저점</b><br>%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>'
                    ))
                    
                    # Layout settings
                    fig.update_layout(
                        title=dict(
                            text=f"포트폴리오 가치 추이 ({selected_period})",
                            font=dict(size=16, color='#f1f5f9')
                        ),
                        xaxis=dict(
                            title="날짜",
                            gridcolor='rgba(148, 163, 184, 0.2)',
                            tickformat='%m/%d',
                            rangeslider=dict(visible=True, thickness=0.05),  # Bottom range slider
                        ),
                        yaxis=dict(
                            title="자산 가치 (USD)",
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
                    st.markdown("**선택 기간 통계**")
                    
                    period_first = filtered_df['TotalValue'].iloc[0]
                    period_last = filtered_df['TotalValue'].iloc[-1]
                    period_change = period_last - period_first
                    period_change_pct = (period_change / period_first) * 100 if period_first > 0 else 0
                    period_max = filtered_df['TotalValue'].max()
                    period_min = filtered_df['TotalValue'].min()
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("시작", f"${period_first:,.2f}")
                    with col2:
                        st.metric("현재", f"${period_last:,.2f}", f"{period_change_pct:+.2f}%")
                    with col3:
                        st.metric("최고", f"${period_max:,.2f}", f"+${period_max - period_first:,.2f}")
                    with col4:
                        st.metric("최저", f"${period_min:,.2f}", f"${period_min - period_first:,.2f}")
                    
                else:
                    st.warning("선택한 기간에 데이터가 없습니다.")
            
            # Recent records table
            st.markdown("---")
            st.subheader("최근 기록")
            display_df = history_df.tail(10).sort_values('Date', ascending=False).copy()
            display_df['TotalValue'] = display_df['TotalValue'].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "-")
            display_df['Date'] = pd.to_datetime(display_df['Date']).dt.strftime('%Y-%m-%d %H:%M')
            st.dataframe(display_df, width='stretch', hide_index=True)
elif is_personal_mode and not gs_available:
    st.info("🔎 개인 모드 히스토리를 보려면 Google Sheets 연동이 필요합니다.")
else:
    st.markdown("### 📊 포트폴리오 히스토리")
    st.markdown(
        """
        <div style="background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.35); border-radius: 10px; padding: 14px;">
            <p style="margin: 0; color: #e2e8f0; font-weight: 600;">📢 공개 모드 안내</p>
            <p style="margin: 8px 0 0 0; color: #94a3b8;">
                공개 모드에서는 개인 포트폴리오 히스토리를 저장/조회하지 않습니다.
                상세 히스토리 기능은 개인 모드에서만 활성화됩니다.
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




