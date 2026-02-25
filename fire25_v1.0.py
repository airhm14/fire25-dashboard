import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
import time
import requests

# =====================================================================
# 페이지 설정
# =====================================================================
st.set_page_config(
    page_title="TEAM FIRE 25 작전 통제실",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =====================================================================
# 커스텀 CSS (한국 스타일: 상승=빨강, 하락=파랑)
# =====================================================================
st.markdown("""
<style>
    /* 전체 배경 및 폰트 */
    .main { background-color: #0f172a; color: #f1f5f9; }
    
    /* 메트릭 카드 스타일 */
    div[data-testid="stMetricValue"] { font-size: 2.5em; font-weight: 700; }
    
    /* 상승 = 빨강 */
    .positive { color: #ef4444; }
    
    /* 하락 = 파랑 */
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
    
    /* 사이드바 스타일 */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
        border-right: 1px solid #334155;
    }
    
    /* 사이드바 내부 요소 */
    section[data-testid="stSidebar"] > div {
        background-color: transparent;
    }
    
    /* 사이드바 입력 필드 */
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
    
    /* 사이드바 숫자 입력 버튼 */
    section[data-testid="stSidebar"] button[kind="icon"] {
        background-color: #475569 !important;
        color: #cbd5e1 !important;
        border-radius: 4px !important;
    }
    
    section[data-testid="stSidebar"] button[kind="icon"]:hover {
        background-color: #10b981 !important;
        color: white !important;
    }
    
    /* 사이드바 레이블 */
    section[data-testid="stSidebar"] label {
        color: #cbd5e1 !important;
        font-weight: 600 !important;
    }
    
    /* 사이드바 서브헤더 */
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] h3 {
        color: #10b981 !important;
        border-bottom: 2px solid #10b981;
        padding-bottom: 8px;
        margin-bottom: 15px;
    }
    
    /* 사이드바 버튼 */
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
    
    /* 헤더 스타일 */
    h1, h2, h3 { 
        color: #10b981; 
        font-family: 'Arial Black', sans-serif; 
        text-shadow: 0 0 10px rgba(16, 185, 129, 0.3);
    }
</style>
""", unsafe_allow_html=True)

# =====================================================================
# 제목
# =====================================================================
# 한국 시간대 (UTC+9)
kst = timezone(timedelta(hours=9))
current_time_kst = datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S KST')

st.markdown("<h1 style='text-align: center;'>🛡️ TEAM FIRE 25 작전 통제실</h1>", unsafe_allow_html=True)
st.markdown(f"<p style='text-align: center; color: #94a3b8;'>마지막 업데이트: {current_time_kst}</p>", unsafe_allow_html=True)
st.markdown("---")

# =====================================================================
# Google Sheets 연동 함수
# =====================================================================
def get_google_sheets_client():
    """Google Sheets 클라이언트 생성"""
    try:
        from google.oauth2.service_account import Credentials
        import gspread
        
        # Streamlit Secrets에서 서비스 계정 정보 가져오기
        if "gcp_service_account" not in st.secrets:
            return None, "Google Sheets 연동이 설정되지 않았습니다."
        
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
        return None, "gspread 패키지가 설치되지 않았습니다."
    except Exception as e:
        return None, f"Google Sheets 연결 실패: {str(e)}"

def load_portfolio_from_sheets():
    """Google Sheets에서 최신 포트폴리오 데이터 불러오기"""
    client, error = get_google_sheets_client()
    if error:
        return None, error
    
    try:
        sheet_url = st.secrets.get("spreadsheet_url", "")
        if not sheet_url:
            return None, "스프레드시트 URL이 설정되지 않았습니다."
        
        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet("Portfolio")
        
        # 마지막 행 데이터 가져오기
        all_data = worksheet.get_all_values()
        if len(all_data) <= 1:  # 헤더만 있는 경우
            return None, "저장된 데이터가 없습니다."
        
        # 마지막 행
        last_row = all_data[-1]
        # 헤더: Date, QQQM, SCHD, IAU, SGOV, Cash, NewCash, TotalValue
        
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
    except gspread.WorksheetNotFound:
        return None, "Portfolio 시트를 찾을 수 없습니다."
    except Exception as e:
        return None, f"데이터 불러오기 실패: {str(e)}"

def save_portfolio_to_sheets(qqqm, schd, iau, sgov, cash, new_cash, total_value):
    """Google Sheets에 포트폴리오 데이터 저장"""
    client, error = get_google_sheets_client()
    if error:
        return False, error
    
    try:
        sheet_url = st.secrets.get("spreadsheet_url", "")
        if not sheet_url:
            return False, "스프레드시트 URL이 설정되지 않았습니다."
        
        spreadsheet = client.open_by_url(sheet_url)
        
        # Portfolio 시트 가져오기 (없으면 생성)
        try:
            worksheet = spreadsheet.worksheet("Portfolio")
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="Portfolio", rows=1000, cols=10)
            # 헤더 추가
            worksheet.append_row(["Date", "QQQM", "SCHD", "IAU", "SGOV", "Cash", "NewCash", "TotalValue"])
        
        # 현재 날짜/시간
        from datetime import datetime
        import pytz
        kst = pytz.timezone('Asia/Seoul')
        now = datetime.now(kst).strftime("%Y-%m-%d %H:%M")
        
        # 데이터 추가
        worksheet.append_row([now, qqqm, schd, iau, sgov, cash, new_cash, round(total_value, 2)])
        
        return True, "저장 완료!"
    except Exception as e:
        return False, f"저장 실패: {str(e)}"

def get_portfolio_history():
    """Google Sheets에서 포트폴리오 히스토리 가져오기"""
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
        
        # DataFrame으로 변환
        headers = all_data[0]
        data = all_data[1:]
        
        history_df = pd.DataFrame(data, columns=headers)
        history_df['TotalValue'] = pd.to_numeric(history_df['TotalValue'], errors='coerce')
        history_df['Date'] = pd.to_datetime(history_df['Date'], format='%Y-%m-%d %H:%M', errors='coerce')
        
        return history_df, None
    except Exception as e:
        return None, f"히스토리 불러오기 실패: {str(e)}"

# Google Sheets 연동 상태 확인
gs_available = "gcp_service_account" in st.secrets if hasattr(st, 'secrets') else False

# 저장된 데이터 불러오기 시도
saved_data = None
if gs_available:
    saved_data, load_error = load_portfolio_from_sheets()
    if load_error and "저장된 데이터가 없습니다" not in load_error:
        st.sidebar.warning(f"⚠️ {load_error}")

# =====================================================================
# 사이드바: 포트폴리오 입력
# =====================================================================
with st.sidebar:
    st.header("📊 포트폴리오 설정")
    
    # Google Sheets 연동 상태 표시
    if gs_available:
        if saved_data:
            st.success(f"☁️ 마지막 저장: {saved_data['date']}")
        else:
            st.info("☁️ Google Sheets 연동됨")
    
    st.subheader("보유 주식")
    
    # 저장된 값이 있으면 기본값으로 사용
    default_qqqm = saved_data['qqqm_qty'] if saved_data else 100.0
    default_schd = saved_data['schd_qty'] if saved_data else 50.0
    default_iau = saved_data['iau_qty'] if saved_data else 20.0
    default_sgov = saved_data['sgov_qty'] if saved_data else 30.0
    default_cash = saved_data['cash_deposit'] if saved_data else 2000.0
    default_new = 0.0  # 신규 자금은 항상 0으로 시작
    
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
    
    st.markdown("---")
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(147, 51, 234, 0.1) 100%);
        border: 2px solid #3b82f6;
        border-radius: 12px;
        padding: 15px;
        margin: 10px 0;
    ">
        <h3 style="color: #3b82f6; margin: 0 0 12px 0; font-size: 1.1em;">🎯 목표 비중</h3>
        <div style="font-size: 0.9em; line-height: 1.8;">
            <div style="display: flex; justify-content: space-between; margin: 5px 0;">
                <span style="color: #94a3b8;">QQQM</span>
                <span style="color: #10b981; font-weight: 700;">72%</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin: 5px 0;">
                <span style="color: #94a3b8;">SCHD</span>
                <span style="color: #3b82f6; font-weight: 700;">16%</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin: 5px 0;">
                <span style="color: #94a3b8;">IAU</span>
                <span style="color: #fbbf24; font-weight: 700;">2%</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin: 5px 0;">
                <span style="color: #94a3b8;">현금</span>
                <span style="color: #94a3b8; font-weight: 700;">10%</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # 버튼들
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        refresh_button = st.button("🔄 새로고침", use_container_width=True)
    with col_btn2:
        save_button = st.button("💾 저장", use_container_width=True, disabled=not gs_available)
    
    # 새로고침 버튼 클릭 시 캐시 삭제
    if refresh_button:
        st.cache_data.clear()
        st.success("✅ 캐시가 삭제되었습니다. 최신 데이터를 가져옵니다...")
        st.rerun()
    
    # 저장 버튼은 total_value 계산 후 처리 (아래에서 처리)
    if 'save_clicked' not in st.session_state:
        st.session_state.save_clicked = False
    if save_button:
        st.session_state.save_clicked = True

# =====================================================================
# 데이터 가져오기 함수
# =====================================================================
@st.cache_data(ttl=60)  # 60초 캐시
def get_stock_data(symbol, period="3mo"):
    """주식 데이터 가져오기 (가격 + 기술적 지표)"""
    import time
    
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep(retry_delay * attempt)
                
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period)
            
            if df.empty:
                if attempt < max_retries - 1:
                    continue
                return None
            
            # 이동평균선 계산
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            df['SMA_50'] = df['Close'].rolling(window=50).mean()
            df['SMA_100'] = df['Close'].rolling(window=100).mean()
            df['SMA_200'] = df['Close'].rolling(window=200).mean()
            
            # RSI 계산
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # 최신 데이터
            latest = df.iloc[-1]
            prev_close = df.iloc[-2]['Close'] if len(df) > 1 else latest['Close']
            
            return {
                'symbol': symbol,
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
                st.error(f"❌ {symbol} 데이터 가져오기 실패: {str(e)}")
                return None
    
    return None

# =====================================================================
# 데이터 로딩
# =====================================================================
with st.spinner('📡 실시간 데이터 수신 중...'):
    qqqm_data = get_stock_data('QQQM', period="1y")  # 200일선 계산을 위해 1년
    schd_data = get_stock_data('SCHD', period="1y")
    iau_data = get_stock_data('IAU', period="1y")
    sgov_data = get_stock_data('SGOV', period="1mo")  # SGOV 가격 조회
    vix_data = get_stock_data('^VIX', period="1mo")  # VIX는 1개월만

# Fear & Greed Index 가져오기
@st.cache_data(ttl=1800)  # 30분 캐시
def get_fear_greed_index():
    """CNN Fear & Greed Index 가져오기"""
    
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
                        'classification': fng.get('rating', 'Neutral'),
                        'previous': prev_close,
                        'source': 'CNN'
                    }
    except:
        pass
    
    # 방법 2: CNN 대체 엔드포인트
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
    
    # 데이터 없음
    return None

with st.spinner('📡 Fear & Greed Index 조회 중...'):
    fng_data = get_fear_greed_index()

# 데이터 검증
if not all([qqqm_data, schd_data, iau_data]):
    st.error("⚠️ 일부 데이터를 가져오지 못했습니다. 새로고침 버튼을 눌러주세요.")
    st.stop()

# SGOV 가격 (데이터 없으면 기본값 사용)
if sgov_data:
    sgov_price = sgov_data['price']
else:
    sgov_price = 100.50  # SGOV 기본 추정가

# SGOV 평가액 계산 (수량 × 현재가)
sgov_value = sgov_qty * sgov_price

# 총 현금 계산
total_cash = sgov_value + cash_deposit

# =====================================================================
# 포트폴리오 계산
# =====================================================================
qqqm_value = qqqm_qty * qqqm_data['price']
schd_value = schd_qty * schd_data['price']
iau_value = iau_qty * iau_data['price']
total_value = qqqm_value + schd_value + iau_value + total_cash

qqqm_pct = (qqqm_value / total_value) * 100 if total_value > 0 else 0
schd_pct = (schd_value / total_value) * 100 if total_value > 0 else 0
iau_pct = (iau_value / total_value) * 100 if total_value > 0 else 0
cash_pct = (total_cash / total_value) * 100 if total_value > 0 else 0

# SGOV와 예수금 개별 비중
sgov_pct = (sgov_value / total_value) * 100 if total_value > 0 else 0
deposit_pct = (cash_deposit / total_value) * 100 if total_value > 0 else 0

# =====================================================================
# Google Sheets 저장 처리
# =====================================================================
if st.session_state.get('save_clicked', False) and gs_available:
    success, message = save_portfolio_to_sheets(
        qqqm_qty, schd_qty, iau_qty, sgov_qty, 
        cash_deposit, new_cash, total_value
    )
    if success:
        st.sidebar.success(f"✅ {message}")
    else:
        st.sidebar.error(f"❌ {message}")
    st.session_state.save_clicked = False

# =====================================================================
# 사이드바: 현금 현황 표시 (데이터 로딩 후)
# =====================================================================
with st.sidebar:
    st.markdown("---")
    st.markdown("### 💰 현금성 자산 현황")
    
    # SGOV 정보 표시
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("SGOV", f"{sgov_qty:.0f}주")
    with col2:
        st.metric("현재가", f"${sgov_price:.2f}")
    
    st.markdown(f"**SGOV 평가액:** :green[${sgov_value:,.2f}]")
    st.markdown(f"**예수금:** ${cash_deposit:,.2f}")
    st.markdown(f"**현금성 자산 합계:** :blue[${total_cash:,.2f}]")
    
    if new_cash > 0:
        st.markdown("---")
        st.markdown(f"**+ 신규 자금:** :blue[${new_cash:,.2f}]")
        st.markdown(f"**투입 가능 총액:** :orange[${total_cash + new_cash:,.2f}]")

# =====================================================================
# 메인 대시보드: 실시간 가격
# =====================================================================
st.header("💹 실시간 시세")

col1, col2, col3, col4 = st.columns(4)

with col1:
    change_class = 'positive' if qqqm_data['change'] >= 0 else 'negative'
    st.metric(
        label="QQQM (성장 엔진)",
        value=f"${qqqm_data['price']:.2f}",
        delta=f"{qqqm_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>거래량: {qqqm_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col2:
    change_class = 'positive' if schd_data['change'] >= 0 else 'negative'
    st.metric(
        label="SCHD (배당 성장)",
        value=f"${schd_data['price']:.2f}",
        delta=f"{schd_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>거래량: {schd_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col3:
    change_class = 'positive' if iau_data['change'] >= 0 else 'negative'
    st.metric(
        label="IAU (금)",
        value=f"${iau_data['price']:.2f}",
        delta=f"{iau_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>거래량: {iau_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col4:
    if sgov_data:
        st.metric(
            label="SGOV (현금성)",
            value=f"${sgov_price:.2f}",
            delta=f"{sgov_data['change_pct']:+.2f}%"
        )
        st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>보유: {sgov_qty:.0f}주</p>", unsafe_allow_html=True)
    else:
        st.metric(label="SGOV (현금성)", value=f"${sgov_price:.2f}")
        st.markdown(f"<p style='font-size: 0.85em; color: #94a3b8;'>보유: {sgov_qty:.0f}주</p>", unsafe_allow_html=True)

# 시장 심리 지표 (VIX + Fear & Greed)
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
        
        # 색상 및 한글 변환
        if fng_value >= 75:
            fng_color = "#ef4444"
            fng_label = "극단적 탐욕"
            fng_icon = "🔥"
            fng_advice = "시장 과열 주의"
        elif fng_value >= 55:
            fng_color = "#f97316"
            fng_label = "탐욕"
            fng_icon = "😀"
            fng_advice = "상승 추세"
        elif fng_value >= 45:
            fng_color = "#fbbf24"
            fng_label = "중립"
            fng_icon = "😐"
            fng_advice = "관망세"
        elif fng_value >= 25:
            fng_color = "#3b82f6"
            fng_label = "공포"
            fng_icon = "😰"
            fng_advice = "매수 기회 탐색"
        else:
            fng_color = "#8b5cf6"
            fng_label = "극단적 공포"
            fng_icon = "😱"
            fng_advice = "적극 매수 고려"
        
        # 전일 대비 변화
        prev_value = fng_data.get('previous')
        if prev_value:
            try:
                prev_val = int(prev_value)
                fng_change = fng_value - prev_val
                fng_change_str = f"{'📈' if fng_change > 0 else '📉'} {fng_change:+d} (전일比)"
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
                    <p style="font-size: 1.8em; margin: 0;">❓</p>
                    <p style="color: #64748b; font-size: 1.3em; font-weight: 700; margin: 5px 0;">데이터 없음</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# =====================================================================
# 핵심 로직: 매뉴얼 V5.10
# =====================================================================
st.header("🎯 작전 상황 분석")

# 데프콘 트리거 체크
defcon_triggered = False
if vix_data and vix_data['price'] <= 14.0 and qqqm_data['rsi'] >= 70:
    defcon_triggered = True

# 웅덩이 4단계 체크 (V5.10) - 30일 쿨다운 적용
puddle_stage = 0
puddle_alert = False
puddle_cooldown_active = False  # 쿨다운 중인지 여부
cooldown_info = ""  # 쿨다운 상세 정보

# 30일 쿨다운 체크 함수
def check_30day_cooldown(df, sma_column, direction='below'):
    """
    지난 30일 동안 동일한 이동평균선 돌파가 있었는지 확인
    direction: 'below' = 하향돌파, 'above' = 상향돌파
    Returns: (is_cooldown, days_since_signal)
        - is_cooldown: True if 쿨다운 중 (30일 내 동일 신호 있음)
        - days_since_signal: 마지막 신호 이후 일수 (없으면 None)
    """
    if len(df) < 32 or sma_column not in df.columns:
        return False, None
    
    # 최근 30일 데이터 (오늘 제외)
    recent_30d = df.iloc[-31:-1]  # 30일 전 ~ 어제
    
    last_signal_idx = None
    
    for i in range(len(recent_30d) - 1):
        current_close = recent_30d.iloc[i]['Close']
        next_close = recent_30d.iloc[i + 1]['Close']
        current_sma = recent_30d.iloc[i][sma_column]
        next_sma = recent_30d.iloc[i + 1][sma_column]
        
        if pd.isna(current_sma) or pd.isna(next_sma):
            continue
        
        if direction == 'below':
            # 하향돌파: 이전에 위에 있다가 아래로
            if current_close >= current_sma and next_close < next_sma:
                last_signal_idx = i + 1  # 더 최근 신호로 업데이트
        else:  # 'above'
            # 상향돌파: 이전에 아래에 있다가 위로
            if current_close < current_sma and next_close >= next_sma:
                last_signal_idx = i + 1
    
    if last_signal_idx is not None:
        # 30일 데이터에서의 인덱스를 일수로 변환
        days_since = len(recent_30d) - 1 - last_signal_idx
        return True, days_since
    
    return False, None

# 현재 위치 파악 (어떤 이동평균선 아래인지)
below_50 = pd.notna(qqqm_data['sma_50']) and qqqm_data['price'] < qqqm_data['sma_50']
below_100 = pd.notna(qqqm_data['sma_100']) and qqqm_data['price'] < qqqm_data['sma_100']
below_200 = pd.notna(qqqm_data['sma_200']) and qqqm_data['price'] < qqqm_data['sma_200']

# 200일선 상향돌파 체크 (4단계) + 30일 쿨다운
if len(qqqm_data['df']) >= 2:
    prev_close = qqqm_data['df'].iloc[-2]['Close']
    prev_sma200 = qqqm_data['df'].iloc[-2]['SMA_200']
    if pd.notna(prev_sma200) and pd.notna(qqqm_data['sma_200']):
        was_below_200 = prev_close < prev_sma200
        is_above_200 = qqqm_data['price'] > qqqm_data['sma_200']
        if was_below_200 and is_above_200:
            is_cooldown, days_since = check_30day_cooldown(qqqm_data['df'], 'SMA_200', 'above')
            if not is_cooldown:
                puddle_stage = 4
                puddle_alert = True
            else:
                puddle_cooldown_active = True
                cooldown_info = f"200일선 상향돌파 ({days_since}일 전 발생)"

# 하락 단계 체크 (1~3단계) + 30일 쿨다운
# 중요: 가장 깊은 단계(200일선)부터 체크
if puddle_stage == 0:
    if below_200:
        # 3단계: 200일선 아래
        is_cooldown, days_since = check_30day_cooldown(qqqm_data['df'], 'SMA_200', 'below')
        if not is_cooldown:
            puddle_stage = 3
            puddle_alert = True
        else:
            puddle_cooldown_active = True
            cooldown_info = f"200일선 하향돌파 ({days_since}일 전 발생)"
    elif below_100:
        # 2단계: 100일선 아래 (but 200일선 위)
        is_cooldown, days_since = check_30day_cooldown(qqqm_data['df'], 'SMA_100', 'below')
        if not is_cooldown:
            puddle_stage = 2
            puddle_alert = True
        else:
            puddle_cooldown_active = True
            cooldown_info = f"100일선 하향돌파 ({days_since}일 전 발생)"
    elif below_50:
        # 1단계: 50일선 아래 (but 100일선 위)
        is_cooldown, days_since = check_30day_cooldown(qqqm_data['df'], 'SMA_50', 'below')
        if not is_cooldown:
            puddle_stage = 1
            puddle_alert = True
        else:
            puddle_cooldown_active = True
            cooldown_info = f"50일선 하향돌파 ({days_since}일 전 발생)"

# Smart Shoulder 발동 조건 체크 (V5.10: 3가지 모두 충족 시)
# 1. QQQM 비중 > 77%
# 2. QQQM 현재가 < 20일 이동평균선 (하향돌파)
# 3. 최근 전고점 갱신 후 (상승장 이후)

# 조건 1: QQQM 비중 > 77%
condition_1_over_77 = qqqm_pct > 77

# 조건 2: QQQM 현재가 < 20일선
condition_2_below_sma20 = False
if pd.notna(qqqm_data['sma_20']):
    condition_2_below_sma20 = qqqm_data['price'] < qqqm_data['sma_20']

# 조건 3: 최근 전고점 갱신 후 (최근 20일 내 52주 신고가 달성 여부)
condition_3_after_high = False
if len(qqqm_data['df']) >= 252:  # 1년 데이터 필요
    # 최근 52주(252거래일) 최고가
    high_52w = qqqm_data['df']['High'].tail(252).max()
    # 최근 20일 내에 52주 신고가를 달성했는지 확인
    recent_20d_high = qqqm_data['df']['High'].tail(20).max()
    # 최근 20일 고점이 52주 고점의 99% 이상이면 "전고점 갱신 후"로 판단
    if recent_20d_high >= high_52w * 0.99:
        condition_3_after_high = True

# Smart Shoulder 발동 여부 (3가지 모두 충족)
smart_shoulder_triggered = condition_1_over_77 and condition_2_below_sma20 and condition_3_after_high

# 단순 리밸런싱 필요 여부 (비중만 초과, Smart Shoulder 조건 미충족)
rebalancing_needed = condition_1_over_77 and not smart_shoulder_triggered

# 경고 표시
if defcon_triggered:
    st.markdown(f"""
    <div class="warning-box">
        <div class="warning-title">🚨 DEFCON 세이빙 발동!</div>
        <p><strong>VIX:</strong> {vix_data['price']:.2f} (≤ 14.00)</p>
        <p><strong>RSI:</strong> {qqqm_data['rsi']:.2f} (≥ 70)</p>
        <p><strong>조치:</strong> 신규 자금 100% SGOV 투입 (QQQM/SCHD/IAU 매수 금지)</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: #8b5cf6; font-size: 1.1em;">🔮 이미 SGOV 투입했다면? 다음 액션</p>
        <div style="background: rgba(139, 92, 246, 0.1); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;">• <strong>감시:</strong> VIX > 14 또는 RSI < 70 되면 DEFCON 해제</p>
            <p style="margin: 5px 0;">• <strong>해제 후:</strong> 정상 투자 재개 (목표 비중 72/16/2/10)</p>
            <p style="margin: 5px 0;">• <strong>기존 포지션:</strong> 유지 (매도 금지)</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

if puddle_alert:
    # 웅덩이 단계별 정보
    stage_info = {
        1: {"name": "1단계: 50일선 하향돌파", "color": "#fbbf24", "rate": 15, "desc": "가벼운 조정, 보수적 접근"},
        2: {"name": "2단계: 100일선 하향돌파", "color": "#f97316", "rate": 35, "desc": "본격적인 조정 구간, 적극적 매수 기회"},
        3: {"name": "3단계: 200일선 하향돌파", "color": "#ef4444", "rate": 50, "desc": "심각한 조정/약세장, 신중하게 접근"},
        4: {"name": "4단계: 200일선 상향돌파", "color": "#10b981", "rate": 100, "desc": "바닥 확인 완료, 회복 초입 공격 매수!"}
    }
    
    info = stage_info[puddle_stage]
    
    # 현금성 자산 = SGOV + 예수금 (V5.10 기준)
    cash_base = sgov_value + cash_deposit
    injection_amount = cash_base * (info["rate"] / 100)
    
    # 이동평균선 값들
    sma_50_val = f"${qqqm_data['sma_50']:.2f}" if pd.notna(qqqm_data['sma_50']) else "N/A"
    sma_100_val = f"${qqqm_data['sma_100']:.2f}" if pd.notna(qqqm_data['sma_100']) else "N/A"
    sma_200_val = f"${qqqm_data['sma_200']:.2f}" if pd.notna(qqqm_data['sma_200']) else "N/A"
    
    # 다음 액션 설명 (이미 투입했다면)
    next_action_info = {
        1: {"next": "2단계 (100일선 하향돌파)", "watch": "100일선", "next_rate": "남은 현금의 35%"},
        2: {"next": "3단계 (200일선 하향돌파)", "watch": "200일선", "next_rate": "남은 현금의 50%"},
        3: {"next": "4단계 (200일선 상향돌파)", "watch": "200일선 회복", "next_rate": "남은 현금 100%"},
        4: {"next": "정상 운영", "watch": "포트폴리오 비중", "next_rate": "목표 비중대로"}
    }
    next_info = next_action_info[puddle_stage]
    
    st.markdown(f"""
    <div class="warning-box" style="border-color: {info['color']};">
        <div class="warning-title" style="color: {info['color']};">🚨 웅덩이 매수 구간: {info['name']}</div>
        <p style="color: #10b981; font-size: 0.9em;">✅ 30일 쿨다운 통과 - 신규 신호!</p>
        <p><strong>현재가:</strong> ${qqqm_data['price']:.2f}</p>
        <p><strong>50일선:</strong> {sma_50_val} | <strong>100일선:</strong> {sma_100_val} | <strong>200일선:</strong> {sma_200_val}</p>
        <p><strong>판단:</strong> {info['desc']}</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: {info['color']}; font-size: 1.1em;">💰 현재 투입 전략 (V5.10)</p>
        <div style="background: rgba(251, 191, 36, 0.05); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;">• <strong>현금성 자산:</strong> ${cash_base:,.2f}</p>
            <p style="margin: 5px 0;">  └─ SGOV: ${sgov_value:,.2f} + 예수금: ${cash_deposit:,.2f}</p>
            <p style="margin: 5px 0;">• <strong>투입 비율:</strong> {info['rate']}%</p>
            <p style="margin: 5px 0; font-size: 1.2em; color: {info['color']};">• <strong>투입 금액:</strong> ${injection_amount:,.2f}</p>
        </div>
        <p style="color: #10b981; font-weight: 700; margin-top: 10px;">💡 + 신규 자금도 함께 투입 (목표 비중 72/16/2/10)</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: #8b5cf6; font-size: 1.1em;">🔮 이미 투입했다면? 다음 액션</p>
        <div style="background: rgba(139, 92, 246, 0.1); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;">• <strong>다음 단계:</strong> {next_info['next']}</p>
            <p style="margin: 5px 0;">• <strong>감시 포인트:</strong> {next_info['watch']}</p>
            <p style="margin: 5px 0;">• <strong>다음 투입률:</strong> {next_info['next_rate']}</p>
            <p style="margin: 5px 0; color: #94a3b8;">• <strong>신규 자금:</strong> 발생 시 즉시 투입 (72/16/2/10)</p>
            <p style="margin: 5px 0; color: #94a3b8;">• <strong>쿨다운:</strong> 30일 후 동일 단계 재발동 가능</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# 쿨다운 중일 때 (이동평균선 아래이지만 30일 내 이미 신호 발생)
if puddle_cooldown_active and not puddle_alert:
    # 현재 어떤 이동평균선 아래인지 확인
    current_below = ""
    if pd.notna(qqqm_data['sma_200']) and qqqm_data['price'] < qqqm_data['sma_200']:
        current_below = "200일선"
    elif pd.notna(qqqm_data['sma_100']) and qqqm_data['price'] < qqqm_data['sma_100']:
        current_below = "100일선"
    elif pd.notna(qqqm_data['sma_50']) and qqqm_data['price'] < qqqm_data['sma_50']:
        current_below = "50일선"
    
    if current_below:
        st.markdown(f"""
        <div class="info-box">
            <div class="warning-title">⏱️ 웅덩이 쿨다운 중 ({current_below} 하향)</div>
            <p><strong>현재가:</strong> ${qqqm_data['price']:.2f} (이동평균선 아래)</p>
            <p><strong>쿨다운 사유:</strong> {cooldown_info if cooldown_info else "30일 내 동일 신호 발생"}</p>
            <hr style="border-color: rgba(251, 191, 36, 0.3); margin: 10px 0;">
            <p style="color: #fbbf24;"><strong>📋 조치:</strong> 추가 투입 대기 (중복 매수 방지)</p>
            <p style="color: #94a3b8; font-size: 0.9em;">💡 신규 자금은 평시대로 투입 (72/16/2/10)</p>
            <p style="color: #64748b; font-size: 0.85em;">⏰ 쿨다운 해제: 30일 경과 후 동일 단계 재발동 가능</p>
        </div>
        """, unsafe_allow_html=True)

if rebalancing_needed:
    excess = qqqm_pct - 72
    
    # 다음 액션 조건 설명 생성
    missing_conditions = []
    if not condition_2_below_sma20:
        missing_conditions.append("20일선 하향돌파")
    if not condition_3_after_high:
        missing_conditions.append("전고점 갱신")
    
    next_action_text = " + ".join(missing_conditions) if missing_conditions else "조건 충족"
    
    st.markdown(f"""
    <div class="info-box">
        <div class="warning-title">⚠️ QQQM 비중 초과 (77% 이상)</div>
        <p><strong>QQQM 현재 비중:</strong> {qqqm_pct:.2f}% (목표: 72%)</p>
        <p><strong>초과:</strong> +{excess:.2f}%p</p>
        <p><strong>20일선 상태:</strong> {'❌ 하향돌파' if condition_2_below_sma20 else '✅ 20일선 위'}</p>
        <p><strong>전고점 상태:</strong> {'⚠️ 최근 신고가 갱신' if condition_3_after_high else '✅ 신고가 미갱신'}</p>
        <hr style="border-color: rgba(251, 191, 36, 0.3); margin: 10px 0;">
        <p style="color: #10b981;"><strong>📋 현재 조치:</strong> 상승장 중이므로 Smart Shoulder 대기</p>
        <hr style="border-color: rgba(251, 191, 36, 0.3); margin: 10px 0;">
        <p style="font-weight: 700; color: #8b5cf6; font-size: 1em;">🔮 다음 액션</p>
        <div style="background: rgba(139, 92, 246, 0.1); padding: 10px; border-radius: 6px; margin: 8px 0;">
            <p style="margin: 3px 0; font-size: 0.95em;">• <strong>Smart Shoulder 발동 조건:</strong> {next_action_text} 시</p>
            <p style="margin: 3px 0; font-size: 0.95em;">• <strong>신규 자금:</strong> 평시대로 투입 (72/16/2/10)</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

if smart_shoulder_triggered:
    excess = qqqm_pct - 72
    st.markdown(f"""
    <div class="warning-box">
        <div class="warning-title">🚨 Smart Shoulder 발동!</div>
        <p><strong>QQQM 현재 비중:</strong> {qqqm_pct:.2f}% (목표: 72%)</p>
        <p><strong>초과:</strong> +{excess:.2f}%p</p>
        <p>✅ 조건 1: QQQM > 77% 충족</p>
        <p>✅ 조건 2: 20일선 하향돌파 (${qqqm_data['sma_20']:.2f})</p>
        <p>✅ 조건 3: 최근 전고점 갱신 후</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 10px 0;">
        <p style="color: #ef4444;"><strong>📋 조치:</strong> 전체 자산을 72/16/2/10으로 리밸런싱</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 10px 0;">
        <p style="font-weight: 700; color: #8b5cf6; font-size: 1em;">🔮 리밸런싱 완료 후 다음 액션</p>
        <div style="background: rgba(139, 92, 246, 0.1); padding: 10px; border-radius: 6px; margin: 8px 0;">
            <p style="margin: 3px 0; font-size: 0.95em;">• <strong>완료 후:</strong> 정상 운영 복귀</p>
            <p style="margin: 3px 0; font-size: 0.95em;">• <strong>신규 자금:</strong> 목표 비중대로 투입 (72/16/2/10)</p>
            <p style="margin: 3px 0; font-size: 0.95em;">• <strong>감시:</strong> QQQM 77% 다시 초과 시 재발동</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# RSI 상태 표시
col1, col2, col3 = st.columns(3)

with col1:
    rsi_status = ""
    rsi_color = ""
    if qqqm_data['rsi'] >= 70:
        rsi_status = "🔥 과열 (매수금지)"
        rsi_color = "#ef4444"
    elif qqqm_data['rsi'] <= 30:
        rsi_status = "❄️ 침체 (기회)"
        rsi_color = "#3b82f6"
    else:
        rsi_status = "✅ 정상"
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
        sma_status = "✅ 20일선 위"
        sma_color = "#10b981"
    else:
        sma_status = "⚠️ 20일선 아래"
        sma_color = "#fbbf24"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {sma_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">20일 이동평균선</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {sma_color}; margin: 10px 0;">${qqqm_data['sma_20']:.2f}</p>
        <p style="font-size: 1.1em; color: {sma_color}; font-weight: 600;">{sma_status}</p>
    </div>
    """, unsafe_allow_html=True)

with col3:
    sma_status = ""
    sma_color = ""
    if pd.notna(qqqm_data['sma_50']) and qqqm_data['price'] > qqqm_data['sma_50']:
        sma_status = "✅ 50일선 위"
        sma_color = "#10b981"
    elif pd.notna(qqqm_data['sma_50']):
        sma_status = "🚨 50일선 아래"
        sma_color = "#ef4444"
    else:
        sma_status = "⏳ 데이터 부족"
        sma_color = "#94a3b8"
    
    sma_50_display = f"${qqqm_data['sma_50']:.2f}" if pd.notna(qqqm_data['sma_50']) else "N/A"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {sma_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">50일 이동평균선</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {sma_color}; margin: 10px 0;">{sma_50_display}</p>
        <p style="font-size: 1.1em; color: {sma_color}; font-weight: 600;">{sma_status}</p>
    </div>
    """, unsafe_allow_html=True)

# 추가 지표 행: 100일선, 200일선, 웅덩이 단계
st.markdown("<br>", unsafe_allow_html=True)
col4, col5, col6 = st.columns(3)

with col4:
    sma_status = ""
    sma_color = ""
    if pd.notna(qqqm_data['sma_100']) and qqqm_data['price'] > qqqm_data['sma_100']:
        sma_status = "✅ 100일선 위"
        sma_color = "#10b981"
    elif pd.notna(qqqm_data['sma_100']):
        sma_status = "🚨 100일선 아래"
        sma_color = "#f97316"
    else:
        sma_status = "⏳ 데이터 부족"
        sma_color = "#94a3b8"
    
    sma_100_display = f"${qqqm_data['sma_100']:.2f}" if pd.notna(qqqm_data['sma_100']) else "N/A"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {sma_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">100일 이동평균선</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {sma_color}; margin: 10px 0;">{sma_100_display}</p>
        <p style="font-size: 1.1em; color: {sma_color}; font-weight: 600;">{sma_status}</p>
    </div>
    """, unsafe_allow_html=True)

with col5:
    sma_status = ""
    sma_color = ""
    if pd.notna(qqqm_data['sma_200']) and qqqm_data['price'] > qqqm_data['sma_200']:
        sma_status = "✅ 200일선 위"
        sma_color = "#10b981"
    elif pd.notna(qqqm_data['sma_200']):
        sma_status = "🚨 200일선 아래"
        sma_color = "#ef4444"
    else:
        sma_status = "⏳ 데이터 부족"
        sma_color = "#94a3b8"
    
    sma_200_display = f"${qqqm_data['sma_200']:.2f}" if pd.notna(qqqm_data['sma_200']) else "N/A"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {sma_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">200일 이동평균선</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {sma_color}; margin: 10px 0;">{sma_200_display}</p>
        <p style="font-size: 1.1em; color: {sma_color}; font-weight: 600;">{sma_status}</p>
    </div>
    """, unsafe_allow_html=True)

with col6:
    # 웅덩이 단계 표시
    if puddle_stage == 0:
        stage_text = "정상"
        stage_color = "#10b981"
        stage_icon = "✅"
    elif puddle_stage == 1:
        stage_text = "1단계 (50일선)"
        stage_color = "#fbbf24"
        stage_icon = "⚠️"
    elif puddle_stage == 2:
        stage_text = "2단계 (100일선)"
        stage_color = "#f97316"
        stage_icon = "🔶"
    elif puddle_stage == 3:
        stage_text = "3단계 (200일선↓)"
        stage_color = "#ef4444"
        stage_icon = "🚨"
    else:  # stage 4
        stage_text = "4단계 (200일선↑)"
        stage_color = "#10b981"
        stage_icon = "🚀"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {stage_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">웅덩이 단계</p>
        <p style="font-size: 2em; font-weight: 700; color: {stage_color}; margin: 10px 0;">{stage_icon}</p>
        <p style="font-size: 1.1em; color: {stage_color}; font-weight: 600;">{stage_text}</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# =====================================================================
# 포트폴리오 비중 분석
# =====================================================================
st.header("📊 포트폴리오 현황")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("자산 구성")
    st.metric("총 자산", f"${total_value:,.2f}")
    
    portfolio_df = pd.DataFrame({
        '종목': ['QQQM', 'SCHD', 'IAU', 'SGOV', '예수금', '총 현금'],
        '평가액': [qqqm_value, schd_value, iau_value, sgov_value, cash_deposit, total_cash],
        '현재 비중 (%)': [qqqm_pct, schd_pct, iau_pct, sgov_pct, deposit_pct, cash_pct],
        '목표 비중 (%)': [72, 16, 2, '-', '-', 10],
        '차이 (%p)': [qqqm_pct - 72, schd_pct - 16, iau_pct - 2, '-', '-', cash_pct - 10]
    })
    
    # 스타일 적용을 위한 함수
    def highlight_rows(row):
        if row['종목'] == '총 현금':
            return ['background-color: rgba(59, 130, 246, 0.1)'] * len(row)
        elif row['종목'] in ['SGOV', '예수금']:
            return ['background-color: rgba(148, 163, 184, 0.05)'] * len(row)
        return [''] * len(row)
    
    st.dataframe(
        portfolio_df.style.format({
            '평가액': '${:,.2f}',
            '현재 비중 (%)': '{:.2f}%',
            '목표 비중 (%)': lambda x: x if isinstance(x, str) else f'{x:.2f}%',
            '차이 (%p)': lambda x: x if isinstance(x, str) else f'{x:+.2f}%p'
        }).apply(highlight_rows, axis=1),
        use_container_width=True
    )

with col2:
    st.subheader("비중 시각화")
    
    # 파이 차트
    fig = go.Figure(data=[go.Pie(
        labels=['QQQM', 'SCHD', 'IAU', 'SGOV', '예수금'],
        values=[qqqm_value, schd_value, iau_value, sgov_value, cash_deposit],
        hole=0.4,
        marker=dict(colors=['#10b981', '#3b82f6', '#fbbf24', '#94a3b8', '#64748b']),
        textinfo='label+percent',
        textfont=dict(size=14, color='white'),
        hovertemplate='<b>%{label}</b><br>$%{value:,.2f}<br>%{percent}<extra></extra>'
    )])
    
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'),
        height=400,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.1
        )
    )
    
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# =====================================================================
# 기술적 차트
# =====================================================================
st.header("📈 QQQM 기술적 분석")

# 가격 차트
fig = go.Figure()

# 캔들스틱
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

# 이동평균선
fig.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['SMA_20'],
    mode='lines',
    name='20일선',
    line=dict(color='#fbbf24', width=1.5)
))

fig.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['SMA_50'],
    mode='lines',
    name='50일선',
    line=dict(color='#3b82f6', width=2)
))

fig.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['SMA_100'],
    mode='lines',
    name='100일선',
    line=dict(color='#f97316', width=2)
))

fig.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['SMA_200'],
    mode='lines',
    name='200일선',
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
        title='가격 (USD)'
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

st.plotly_chart(fig, use_container_width=True)

# RSI 차트
fig_rsi = go.Figure()

fig_rsi.add_trace(go.Scatter(
    x=qqqm_data['df'].index,
    y=qqqm_data['df']['RSI'],
    mode='lines',
    name='RSI(14)',
    line=dict(color='#10b981', width=2)
))

# 과매수/과매도 라인
fig_rsi.add_hline(y=70, line_dash="dash", line_color="#ef4444", annotation_text="과열(70)")
fig_rsi.add_hline(y=30, line_dash="dash", line_color="#3b82f6", annotation_text="침체(30)")

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

st.plotly_chart(fig_rsi, use_container_width=True)

st.markdown("---")

# =====================================================================
# 매매 실행 계획 (상황별)
# =====================================================================
st.header("📋 매매 실행 계획")

st.markdown("""
<div style="background: rgba(59, 130, 246, 0.1); border: 2px solid #3b82f6; border-radius: 8px; padding: 15px; margin-bottom: 20px;">
    <p style="color: #3b82f6; font-weight: 700;">💡 실전 매매 가이드</p>
    <p style="font-size: 0.9em; color: #cbd5e1;">현재 시장 상황과 신규 자금을 고려한 구체적인 매수/매도 전략을 제시합니다.</p>
</div>
""", unsafe_allow_html=True)

# 상황 판단
is_puddle = puddle_alert  # 웅덩이 발생 (30일 쿨다운 통과)
is_cooldown = puddle_cooldown_active and not puddle_alert  # 쿨다운 중
is_defcon = defcon_triggered  # Defcon 발동
has_new_cash = new_cash > 0  # 신규 자금
is_smart_shoulder = smart_shoulder_triggered  # Smart Shoulder 발동 (V5.10: 3가지 조건 모두 충족)
is_over_77 = condition_1_over_77  # QQQM 비중만 77% 초과 (Smart Shoulder 미발동)

# 매매 계획 생성
st.subheader("🎯 현재 상황 진단")

situation_badges = []
if is_defcon:
    situation_badges.append("🚨 <span style='background: #ef4444; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700; display: inline-block; margin: 4px 0;'>DEFCON 발동</span>")
if is_puddle:
    stage_colors = {1: "#fbbf24", 2: "#f97316", 3: "#ef4444", 4: "#10b981"}
    stage_names = {1: "1단계(50일선)", 2: "2단계(100일선)", 3: "3단계(200일선↓)", 4: "4단계(200일선↑)"}
    situation_badges.append(f"🚨 <span style='background: {stage_colors[puddle_stage]}; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700; display: inline-block; margin: 4px 0;'>웅덩이 {stage_names[puddle_stage]}</span>")
elif is_cooldown:
    situation_badges.append("⏱️ <span style='background: #64748b; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700; display: inline-block; margin: 4px 0;'>웅덩이 쿨다운 중</span>")
if is_smart_shoulder:
    situation_badges.append("🚨 <span style='background: #ef4444; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700; display: inline-block; margin: 4px 0;'>Smart Shoulder 발동</span>")
elif is_over_77:
    situation_badges.append("⚠️ <span style='background: #fbbf24; color: #1e293b; padding: 6px 14px; border-radius: 6px; font-weight: 700; display: inline-block; margin: 4px 0;'>QQQM 77%↑ (대기)</span>")
if has_new_cash:
    situation_badges.append("💰 <span style='background: #3b82f6; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700; display: inline-block; margin: 4px 0;'>신규 자금 ${:,.0f}</span>".format(new_cash))

if situation_badges:
    # 각 배지를 줄바꿈으로 분리하여 세로로 표시 (모바일 대응)
    badges_html = "<div style='display: flex; flex-direction: column; gap: 8px; align-items: flex-start;'>"
    for badge in situation_badges:
        badges_html += f"<div>{badge}</div>"
    badges_html += "</div>"
    st.markdown(badges_html, unsafe_allow_html=True)
else:
    st.markdown("<span style='background: #10b981; color: white; padding: 6px 14px; border-radius: 6px; font-weight: 700;'>✅ 정상 운영</span>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# 우선순위 1: Defcon 발동 중
if is_defcon:
    # DEFCON + 웅덩이 동시 발생 체크
    if is_puddle:
        st.markdown(f"""
        <div class="warning-box">
            <div class="warning-title">🚨 DEFCON + 웅덩이 동시 발생!</div>
            <p style="font-size: 1.1em; margin: 15px 0;"><strong>📋 특수 상황 대응 (V5.10)</strong></p>
        </div>
        """, unsafe_allow_html=True)
        
        if puddle_stage <= 2:  # 1~2단계
            st.markdown("""
            <div style="background: rgba(251, 191, 36, 0.1); border-left: 4px solid #fbbf24; padding: 15px; margin: 10px 0; border-radius: 8px;">
                <p style="font-weight: 700; color: #fbbf24;">웅덩이 1~2단계 (50일선/100일선):</p>
                <ul style="margin: 10px 0;">
                    <li><strong>신규 자금:</strong> 100% SGOV 투입</li>
                    <li><strong>기존 현금:</strong> 웅덩이 매수에 사용 가능</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)
            
            if has_new_cash:
                st.info(f"💰 신규 자금 ${new_cash:,.2f} → SGOV 투입")
            
            # 기존 현금으로 웅덩이 매수
            import math
            stage_info = {1: 15, 2: 35}
            rate = stage_info[puddle_stage]
            cash_base = sgov_value + cash_deposit
            injection = cash_base * (rate / 100)
            
            st.warning(f"📊 기존 현금으로 웅덩이 매수 ({rate}%)")
            st.write(f"• 현금성 자산: ${cash_base:,.2f}")
            st.write(f"• 투입 금액: ${injection:,.2f}")
            
        else:  # 3단계 이후
            st.markdown("""
            <div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; padding: 15px; margin: 10px 0; border-radius: 8px;">
                <p style="font-weight: 700; color: #ef4444;">웅덩이 3단계 이후 (200일선):</p>
                <ul style="margin: 10px 0;">
                    <li><strong>신규 자금:</strong> 목표 비중대로 투입 (72/16/2/10)</li>
                    <li><strong>기존 현금:</strong> 웅덩이 매수에 사용</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)
            
            if has_new_cash:
                import math
                qqqm_shares = math.floor(new_cash * 0.72 / qqqm_data['price'])
                schd_shares = math.floor(new_cash * 0.16 / schd_data['price'])
                iau_shares = math.floor(new_cash * 0.02 / iau_data['price'])
                sgov_amount = new_cash * 0.10
                
                st.success(f"💰 신규 자금 배분 (${new_cash:,.2f})")
                st.write(f"• QQQM: {qqqm_shares}주")
                st.write(f"• SCHD: {schd_shares}주")
                st.write(f"• IAU: {iau_shares}주")
                st.write(f"• SGOV: ${sgov_amount:,.2f}")
    else:
        # 순수 DEFCON (웅덩이 없음)
        st.markdown("""
        <div class="warning-box">
            <div class="warning-title">🚨 우선순위 1: DEFCON 세이빙</div>
            <p style="font-size: 1.1em; margin: 15px 0;"><strong>📋 조치 사항:</strong></p>
            <ol style="line-height: 2;">
                <li><strong>신규 자금 → 100% SGOV 투입</strong></li>
                <li><strong>기존 포지션 → 유지 (매도 금지)</strong></li>
                <li><strong>예수금 → 동결 (긴급용으로만 사용)</strong></li>
            </ol>
        </div>
        """, unsafe_allow_html=True)
        
        if has_new_cash:
            st.markdown(f"""
            <div style="background: rgba(59, 130, 246, 0.1); border-left: 4px solid #3b82f6; border-radius: 8px; padding: 20px; margin: 15px 0;">
                <p style="font-size: 1.2em; font-weight: 700; color: #3b82f6; margin-bottom: 15px;">💰 신규 자금 배분</p>
                <div style="background: rgba(15, 23, 42, 0.5); border-radius: 8px; padding: 15px; margin: 10px 0;">
                    <p style="font-size: 1.1em; margin: 10px 0;"><strong>SGOV 매수:</strong> <span style="color: #10b981; font-size: 1.3em; font-weight: 700;">${new_cash:,.2f}</span></p>
                    <p style="color: #94a3b8; font-size: 0.9em; margin-top: 10px;">💡 DEFCON 해제 후 정상 배분으로 전환</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("💡 신규 자금이 없습니다. 월급/추가 입금 시 SGOV로만 투입하세요.")

# 우선순위 2: 웅덩이 (4단계 시스템)
elif is_puddle:
    stage_info = {
        1: {"name": "1단계: 50일선 하향돌파", "rate": 15, "desc": "현금성 자산의 15% 투입"},
        2: {"name": "2단계: 100일선 하향돌파", "rate": 35, "desc": "남은 현금의 35% 투입"},
        3: {"name": "3단계: 200일선 하향돌파", "rate": 50, "desc": "남은 현금의 50% 투입"},
        4: {"name": "4단계: 200일선 상향돌파", "rate": 100, "desc": "남은 현금 전부 투입 (100%)"}
    }
    
    info = stage_info[puddle_stage]
    
    st.markdown(f"""
    <div class="warning-box">
        <div class="warning-title">🚨 우선순위 1: 웅덩이 매수 - {info['name']}</div>
        <p style="font-size: 1.1em; margin: 15px 0;"><strong>📋 {info['desc']}</strong></p>
        <p style="color: #94a3b8;">현금성 자산 = SGOV + 예수금</p>
    </div>
    """, unsafe_allow_html=True)
    
    # 웅덩이 대응 계산 (V5.10)
    import math
    
    # 현금성 자산 = SGOV + 예수금
    cash_base = sgov_value + cash_deposit
    injection_rate = info["rate"] / 100
    injection_amount = cash_base * injection_rate
    
    # SGOV에서 매도할 금액 계산 (예수금 먼저 사용, 부족하면 SGOV 매도)
    if injection_amount <= cash_deposit:
        # 예수금만으로 충분
        use_deposit = injection_amount
        sgov_sell_amount = 0
        sgov_shares_to_sell = 0
    else:
        # 예수금 전액 + SGOV 일부 매도
        use_deposit = cash_deposit
        sgov_sell_amount = injection_amount - cash_deposit
        sgov_shares_to_sell = math.ceil(sgov_sell_amount / sgov_price)
        sgov_sell_amount = sgov_shares_to_sell * sgov_price  # 실제 매도 금액
    
    # 총 투입 금액 (신규 자금 포함)
    total_injection = use_deposit + sgov_sell_amount + new_cash
    
    # 매수 계획 (목표 비중 72/16/2/10)
    qqqm_shares = math.floor(total_injection * 0.72 / qqqm_data['price'])
    schd_shares = math.floor(total_injection * 0.16 / schd_data['price'])
    iau_shares = math.floor(total_injection * 0.02 / iau_data['price'])
    sgov_buy_amount = total_injection * 0.10
    
    # 실제 매수 금액
    qqqm_buy_amount = qqqm_shares * qqqm_data['price']
    schd_buy_amount = schd_shares * schd_data['price']
    iau_buy_amount = iau_shares * iau_data['price']
    
    # 투입 가능 자금 표시
    st.success("💰 투입 자금 계산")
    
    st.write("**현금성 자산:**")
    st.write(f"• SGOV: {sgov_qty:.0f}주 × ${sgov_price:.2f} = ${sgov_value:,.2f}")
    st.write(f"• 예수금: ${cash_deposit:,.2f}")
    st.write(f"• **현금성 자산 합계: ${cash_base:,.2f}**")
    st.markdown("---")
    
    st.write(f"**{info['rate']}% 투입 = ${injection_amount:,.2f}**")
    if sgov_shares_to_sell > 0:
        st.write(f"• 예수금 사용: ${use_deposit:,.2f}")
        st.write(f"• **SGOV 매도: {sgov_shares_to_sell}주** = ${sgov_sell_amount:,.2f}")
    else:
        st.write(f"• 예수금에서 사용: ${use_deposit:,.2f}")
    
    if has_new_cash:
        st.write(f"• 신규 자금 추가: ${new_cash:,.2f}")
    
    st.markdown("---")
    st.write(f"**총 투입 가능: :green[${total_injection:,.2f}]**")
    
    st.markdown("")
    st.info("📊 매수 전략 (목표 비중 72/16/2/10)")
    st.write(f"• **QQQM (72%): {qqqm_shares}주** = ${qqqm_buy_amount:,.2f}")
    st.write(f"• **SCHD (16%): {schd_shares}주** = ${schd_buy_amount:,.2f}")
    st.write(f"• **IAU (2%): {iau_shares}주** = ${iau_buy_amount:,.2f}")
    st.write(f"• **SGOV (10%): ${sgov_buy_amount:,.2f}**")
    
    # 실제 사용 금액 합계
    total_actual_use = qqqm_buy_amount + schd_buy_amount + iau_buy_amount + sgov_buy_amount
    remaining = total_injection - total_actual_use
    st.caption(f"💡 실제 사용: ${total_actual_use:,.2f} | 잔액: ${remaining:,.2f} (예수금 보관)")
    
    # 투입 후 남은 현금 표시
    remaining_cash = cash_base - injection_amount
    st.markdown("---")
    st.write(f"**투입 후 남은 현금: ${remaining_cash:,.2f}**")
    if puddle_stage < 4:
        st.caption(f"💡 다음 단계 발생 시 이 금액 기준으로 추가 투입")

# 우선순위 3: Smart Shoulder (V5.10: 3가지 조건 모두 충족 시)
elif is_smart_shoulder:
    st.markdown("""
    <div class="warning-box">
        <div class="warning-title">🚨 우선순위 1: Smart Shoulder 발동!</div>
        <p style="font-size: 1.1em; margin: 15px 0;"><strong>3가지 조건 모두 충족 (V5.10)</strong></p>
        <p>✅ QQQM 비중 > 77%</p>
        <p>✅ QQQM < 20일선 (하향돌파)</p>
        <p>✅ 최근 전고점 갱신 후</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 10px 0;">
        <p style="color: #ef4444;"><strong>📋 조치:</strong> 전체 자산을 목표 비중(72/16/2/10)으로 리밸런싱</p>
    </div>
    """, unsafe_allow_html=True)
    
    import math
    
    # 목표 금액 계산 (신규 자금 포함)
    total_with_new = total_value + new_cash
    
    target_qqqm_value = total_with_new * 0.72
    target_schd_value = total_with_new * 0.16
    target_iau_value = total_with_new * 0.02
    target_cash_value = total_with_new * 0.10
    
    # 현재 vs 목표 차이
    diff_qqqm = target_qqqm_value - qqqm_value
    diff_schd = target_schd_value - schd_value
    diff_iau = target_iau_value - iau_value
    diff_cash = target_cash_value - total_cash
    
    st.subheader("📊 리밸런싱 계획")
    
    # 현재 상태
    st.write("**현재 포트폴리오:**")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("QQQM", f"${qqqm_value:,.0f}", f"{qqqm_pct:.1f}%")
    with col2:
        st.metric("SCHD", f"${schd_value:,.0f}", f"{schd_pct:.1f}%")
    with col3:
        st.metric("IAU", f"${iau_value:,.0f}", f"{iau_pct:.1f}%")
    with col4:
        st.metric("현금", f"${total_cash:,.0f}", f"{cash_pct:.1f}%")
    
    if has_new_cash:
        st.info(f"💰 신규 자금 포함: ${new_cash:,.2f} → 총 자산: ${total_with_new:,.2f}")
    
    st.markdown("---")
    
    # 목표 상태
    st.write("**목표 포트폴리오 (72/16/2/10):**")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("QQQM", f"${target_qqqm_value:,.0f}", "72%")
    with col2:
        st.metric("SCHD", f"${target_schd_value:,.0f}", "16%")
    with col3:
        st.metric("IAU", f"${target_iau_value:,.0f}", "2%")
    with col4:
        st.metric("현금", f"${target_cash_value:,.0f}", "10%")
    
    st.markdown("---")
    
    # 매매 계획
    st.write("**📋 매매 실행 계획:**")
    
    # QQQM (매도 필요)
    if diff_qqqm < 0:
        qqqm_sell_shares = math.ceil(abs(diff_qqqm) / qqqm_data['price'])
        qqqm_sell_value = qqqm_sell_shares * qqqm_data['price']
        st.error(f"🔴 **QQQM 매도: {qqqm_sell_shares}주** = ${qqqm_sell_value:,.2f}")
    else:
        qqqm_buy_shares = math.floor(diff_qqqm / qqqm_data['price'])
        if qqqm_buy_shares > 0:
            qqqm_buy_value = qqqm_buy_shares * qqqm_data['price']
            st.success(f"🟢 **QQQM 매수: {qqqm_buy_shares}주** = ${qqqm_buy_value:,.2f}")
        else:
            st.write("⚪ QQQM: 유지")
    
    # SCHD (매수 필요)
    if diff_schd > 0:
        schd_buy_shares = math.floor(diff_schd / schd_data['price'])
        if schd_buy_shares > 0:
            schd_buy_value = schd_buy_shares * schd_data['price']
            st.success(f"🟢 **SCHD 매수: {schd_buy_shares}주** = ${schd_buy_value:,.2f}")
        else:
            st.write("⚪ SCHD: 유지")
    else:
        schd_sell_shares = math.ceil(abs(diff_schd) / schd_data['price'])
        if schd_sell_shares > 0:
            schd_sell_value = schd_sell_shares * schd_data['price']
            st.error(f"🔴 **SCHD 매도: {schd_sell_shares}주** = ${schd_sell_value:,.2f}")
        else:
            st.write("⚪ SCHD: 유지")
    
    # IAU (매수 필요)
    if diff_iau > 0:
        iau_buy_shares = math.floor(diff_iau / iau_data['price'])
        if iau_buy_shares > 0:
            iau_buy_value = iau_buy_shares * iau_data['price']
            st.success(f"🟢 **IAU 매수: {iau_buy_shares}주** = ${iau_buy_value:,.2f}")
        else:
            st.write("⚪ IAU: 유지")
    else:
        iau_sell_shares = math.ceil(abs(diff_iau) / iau_data['price'])
        if iau_sell_shares > 0:
            iau_sell_value = iau_sell_shares * iau_data['price']
            st.error(f"🔴 **IAU 매도: {iau_sell_shares}주** = ${iau_sell_value:,.2f}")
        else:
            st.write("⚪ IAU: 유지")
    
    # 현금 (SGOV)
    if diff_cash > 0:
        st.success(f"🟢 **SGOV/현금 증가:** ${diff_cash:,.2f}")
    elif diff_cash < 0:
        sgov_sell_shares = math.ceil(abs(diff_cash) / sgov_price)
        sgov_sell_value = sgov_sell_shares * sgov_price
        st.error(f"🔴 **SGOV 매도: {sgov_sell_shares}주** = ${sgov_sell_value:,.2f}")
    else:
        st.write("⚪ 현금: 유지")
    
    st.markdown("---")
    st.caption("💡 매도는 올림, 매수는 내림 적용 | 잔액은 예수금 보관")

# QQQM 77% 초과하지만 Smart Shoulder 미발동 (상승장)
elif is_over_77:
    st.markdown("""
    <div class="info-box">
        <div class="warning-title">⚠️ QQQM 비중 초과 (상승장 대기)</div>
        <p style="font-size: 1.1em; margin: 15px 0;"><strong>Smart Shoulder 조건 미충족</strong></p>
        <p style="color: #10b981;">상승장에서는 77% 넘어도 OK! 하락 전환 시에만 조정</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.write(f"**현재 QQQM 비중:** {qqqm_pct:.1f}%")
    st.write(f"**20일선 상태:** {'❌ 하향돌파' if condition_2_below_sma20 else '✅ 20일선 위 (${:.2f})'.format(qqqm_data['sma_20'])}")
    st.write(f"**전고점 상태:** {'⚠️ 최근 신고가 갱신' if condition_3_after_high else '✅ 신고가 미갱신'}")
    
    if has_new_cash:
        st.markdown("")
        st.success(f"💰 신규 자금 배분 - 평시 운영 (${new_cash:,.2f})")
        st.write("Smart Shoulder 미발동 → 목표 비중대로 배분")
        
        import math
        # 평시 비율 72/16/2/10
        new_qqqm_shares = math.floor(new_cash * 0.72 / qqqm_data['price'])
        new_schd_shares = math.floor(new_cash * 0.16 / schd_data['price'])
        new_iau_shares = math.floor(new_cash * 0.02 / iau_data['price'])
        new_sgov_value = new_cash * 0.10
        
        new_qqqm_value = new_qqqm_shares * qqqm_data['price']
        new_schd_value = new_schd_shares * schd_data['price']
        new_iau_value = new_iau_shares * iau_data['price']
        
        st.write(f"• **QQQM (72%): {new_qqqm_shares}주** = ${new_qqqm_value:,.2f}")
        st.write(f"• **SCHD (16%): {new_schd_shares}주** = ${new_schd_value:,.2f}")
        st.write(f"• **IAU (2%): {new_iau_shares}주** = ${new_iau_value:,.2f}")
        st.write(f"• **SGOV (10%): ${new_sgov_value:,.2f}**")
        
        new_total_use = new_qqqm_value + new_schd_value + new_iau_value + new_sgov_value
        new_remaining = new_cash - new_total_use
        st.caption(f"💡 실제 사용: ${new_total_use:,.2f} | 잔액: ${new_remaining:,.2f}")

# 정상 상황: 월급 배분
elif has_new_cash:
    st.markdown("""
    <div class="success-box">
        <div style="font-size: 1.2em; font-weight: 700; color: #10b981; margin-bottom: 10px;">✅ 정상 운영: 목표 비중대로 투자</div>
        <p>현재 포트폴리오가 안정적입니다. 신규 자금을 목표 비중대로 배분하세요.</p>
    </div>
    """, unsafe_allow_html=True)
    
    import math
    
    # 매수는 내림
    normal_qqqm_shares = math.floor(new_cash * 0.72 / qqqm_data['price'])
    normal_schd_shares = math.floor(new_cash * 0.16 / schd_data['price'])
    normal_iau_shares = math.floor(new_cash * 0.02 / iau_data['price'])
    normal_sgov_value = new_cash * 0.10
    
    # 실제 금액
    normal_qqqm_value = normal_qqqm_shares * qqqm_data['price']
    normal_schd_value = normal_schd_shares * schd_data['price']
    normal_iau_value = normal_iau_shares * iau_data['price']
    
    st.success(f"💰 신규 자금 배분 (${new_cash:,.2f})")
    
    st.write("**매수 계획 (실행 가능한 주식 수):**")
    st.write(f"• **QQQM: {normal_qqqm_shares}주** = ${normal_qqqm_value:,.2f}")
    st.write(f"• **SCHD: {normal_schd_shares}주** = ${normal_schd_value:,.2f}")
    st.write(f"• **IAU: {normal_iau_shares}주** = ${normal_iau_value:,.2f}")
    st.write(f"• **SGOV: ${normal_sgov_value:,.2f}**")
    
    normal_total_use = normal_qqqm_value + normal_schd_value + normal_iau_value + normal_sgov_value
    normal_remaining = new_cash - normal_total_use
    st.caption(f"💡 실제 사용: ${normal_total_use:,.2f} | 잔액: ${normal_remaining:,.2f}")
    
    st.info(f"""💡 **투자 후 예상 비중**  
    QQQM: {((qqqm_value + normal_qqqm_value) / (total_value + normal_total_use) * 100):.1f}% | 
    SCHD: {((schd_value + normal_schd_value) / (total_value + normal_total_use) * 100):.1f}% | 
    IAU: {((iau_value + normal_iau_value) / (total_value + normal_total_use) * 100):.1f}%""")

# 정상 상황: 신규 자금 없음
else:
    st.markdown("""
    <div class="success-box">
        <div style="font-size: 1.2em; font-weight: 700; color: #10b981; margin-bottom: 10px;">✅ 포트폴리오 유지</div>
        <p>현재 상태가 양호합니다. 특별한 조치가 필요하지 않습니다.</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.info("💡 월급이나 추가 자금 입금 시 왼쪽 사이드바에서 금액을 입력하면 자동으로 배분 전략이 표시됩니다.")

st.markdown("---")

# =====================================================================
# 푸터
# =====================================================================
st.markdown("---")

# =====================================================================
# 포트폴리오 등락 원인 분석
# =====================================================================
st.header("📊 오늘의 시장 동향")

@st.cache_data(ttl=1800)  # 30분 캐시
def get_market_summary(symbol):
    """Yahoo Finance에서 종목 관련 뉴스 가져오기"""
    news_list = []
    try:
        ticker = yf.Ticker(symbol)
        
        # 방법 1: ticker.news 시도
        news = None
        try:
            news = ticker.news
        except:
            pass
        
        # 방법 2: get_news() 메서드 시도
        if not news:
            try:
                news = ticker.get_news()
            except:
                pass
        
        if news and len(news) > 0:
            for item in news[:5]:
                title = item.get('title', '') or item.get('headline', '')
                if title:
                    news_list.append({
                        'title': title,
                        'publisher': item.get('publisher', '') or item.get('source', ''),
                        'link': item.get('link', '') or item.get('url', '#')
                    })
        
        return news_list
    except Exception as e:
        # 디버깅용: 에러 발생 시 빈 리스트 반환
        return news_list

def get_broader_market_news():
    """시장 전체 뉴스 가져오기 (SPY, QQQ 기반)"""
    all_news = []
    for symbol in ['SPY', 'QQQ', '^GSPC']:
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news if hasattr(ticker, 'news') else []
            if news:
                for item in news[:3]:
                    title = item.get('title', '')
                    if title and title not in [n['title'] for n in all_news]:
                        all_news.append({
                            'title': title,
                            'publisher': item.get('publisher', ''),
                            'link': item.get('link', '#')
                        })
        except:
            continue
    return all_news[:5]

def analyze_market_sentiment(change_pct, news_list):
    """시장 심리 및 원인 상세 분석"""
    
    # 상세 키워드 카테고리
    keyword_categories = {
        '연준/금리': {
            'keywords': ['fed', 'federal', 'reserve', 'rate', 'rates', 'interest', 'powell', 'fomc', 'cut', 'hike', 'dovish', 'hawkish', 'monetary', 'treasury', 'yield', 'bond'],
            'positive': ['cut', 'dovish', 'lower', 'ease', 'pause'],
            'negative': ['hike', 'hawkish', 'higher', 'raise', 'surge']
        },
        '실적/기업': {
            'keywords': ['earnings', 'revenue', 'profit', 'guidance', 'beat', 'miss', 'outlook', 'forecast', 'results', 'quarter', 'q1', 'q2', 'q3', 'q4', 'eps', 'sales'],
            'positive': ['beat', 'strong', 'surge', 'record', 'exceeded', 'top', 'raise'],
            'negative': ['miss', 'weak', 'disappoint', 'below', 'cut', 'lower', 'warn']
        },
        'AI/기술': {
            'keywords': ['ai', 'artificial', 'intelligence', 'nvidia', 'nvda', 'chip', 'chips', 'semiconductor', 'tech', 'apple', 'aapl', 'microsoft', 'msft', 'google', 'googl', 'amazon', 'amzn', 'meta', 'tesla', 'tsla', 'software', 'cloud', 'data', 'center'],
            'positive': ['surge', 'boom', 'growth', 'demand', 'breakthrough', 'rally', 'soar', 'jump'],
            'negative': ['concern', 'bubble', 'overvalued', 'decline', 'fall', 'drop', 'selloff']
        },
        '인플레이션': {
            'keywords': ['inflation', 'cpi', 'pce', 'price', 'consumer', 'cost', 'spending'],
            'positive': ['cool', 'ease', 'slow', 'lower', 'decline', 'fall', 'drop'],
            'negative': ['rise', 'hot', 'sticky', 'higher', 'surge', 'jump', 'accelerate']
        },
        '지정학/무역': {
            'keywords': ['tariff', 'china', 'chinese', 'trade', 'war', 'geopolitical', 'russia', 'ukraine', 'sanction', 'tension', 'europe', 'asia', 'import', 'export', 'trump', 'biden'],
            'positive': ['deal', 'ease', 'resolve', 'agreement', 'peace', 'relief'],
            'negative': ['tension', 'escalate', 'threat', 'risk', 'war', 'tariff', 'sanction', 'conflict']
        },
        '경기/고용': {
            'keywords': ['job', 'jobs', 'employment', 'gdp', 'economy', 'economic', 'recession', 'growth', 'labor', 'unemployment', 'payroll', 'hire', 'hiring', 'layoff', 'worker'],
            'positive': ['strong', 'growth', 'add', 'robust', 'resilient', 'expand', 'hire'],
            'negative': ['weak', 'slow', 'recession', 'layoff', 'decline', 'contract', 'cut']
        },
        '금/안전자산': {
            'keywords': ['gold', 'silver', 'safe', 'haven', 'precious', 'metal', 'commodity', 'oil', 'crude', 'energy'],
            'positive': ['rally', 'surge', 'demand', 'rise', 'gain', 'climb', 'high'],
            'negative': ['fall', 'drop', 'decline', 'sell', 'low', 'slide', 'tumble']
        },
        '시장심리': {
            'keywords': ['rally', 'selloff', 'sell-off', 'bull', 'bear', 'volatility', 'vix', 'fear', 'optimism', 'sentiment', 'investor', 'market', 'stock', 'stocks', 'wall', 'street', 'dow', 'nasdaq', 's&p', 'index'],
            'positive': ['rally', 'bull', 'optimism', 'confidence', 'buy', 'gain', 'rise', 'surge', 'record', 'high'],
            'negative': ['selloff', 'sell-off', 'bear', 'fear', 'panic', 'sell', 'crash', 'plunge', 'tumble', 'drop', 'fall', 'low']
        }
    }
    
    all_titles = ' '.join([n['title'] for n in news_list]).lower() if news_list else ''
    
    detected_factors = []
    
    for category, data in keyword_categories.items():
        # 카테고리 키워드 검색
        category_found = False
        matched_keyword = None
        for kw in data['keywords']:
            if kw in all_titles:
                category_found = True
                matched_keyword = kw
                break
        
        if category_found:
            # 긍정/부정 판단
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
    """종합적인 시장 해석 생성"""
    
    factors = analyze_market_sentiment(change_pct, news_list)
    
    # 등락 방향
    if change_pct > 1.0:
        direction = "강세"
        direction_detail = "큰 폭 상승"
    elif change_pct > 0.3:
        direction = "상승"
        direction_detail = "소폭 상승"
    elif change_pct > -0.3:
        direction = "보합"
        direction_detail = "변동 제한적"
    elif change_pct > -1.0:
        direction = "하락"
        direction_detail = "소폭 하락"
    else:
        direction = "약세"
        direction_detail = "큰 폭 하락"
    
    # 주요 요인 정리
    main_factors = []
    for f in factors[:3]:  # 최대 3개
        sentiment_icon = "🔺" if f['sentiment'] == 'positive' else ("🔻" if f['sentiment'] == 'negative' else "➖")
        main_factors.append(f"{sentiment_icon} {f['category']}")
    
    # 기본 해석 (요인 없을 때) - 종목별 특성 반영
    if not main_factors:
        if symbol == 'QQQM':
            if change_pct > 0.5:
                main_factors = ["🔺 기술주 강세", "🔺 AI/반도체 수요"]
            elif change_pct < -0.5:
                main_factors = ["🔻 기술주 약세", "🔻 금리 상승 우려"]
            else:
                main_factors = ["➖ 기술주 혼조", "➖ 방향성 탐색 중"]
        elif symbol == 'SCHD':
            if change_pct > 0.5:
                main_factors = ["🔺 배당주 강세", "🔺 안전자산 선호"]
            elif change_pct < -0.5:
                main_factors = ["🔻 배당주 약세", "🔻 성장주 쏠림"]
            else:
                main_factors = ["➖ 배당주 보합", "➖ 수익률 안정"]
        elif symbol == 'IAU':
            if change_pct > 0.5:
                main_factors = ["🔺 금 강세", "🔺 안전자산 수요", "🔺 달러 약세"]
            elif change_pct < -0.5:
                main_factors = ["🔻 금 약세", "🔻 위험선호 심리", "🔻 달러 강세"]
            else:
                main_factors = ["➖ 금 보합", "➖ 관망세"]
        else:
            if change_pct > 0.5:
                main_factors = ["🔺 시장 강세", "🔺 매수세 유입"]
            elif change_pct < -0.5:
                main_factors = ["🔻 시장 약세", "🔻 매도세 우위"]
            else:
                main_factors = ["➖ 방향성 없음", "➖ 관망세"]
    
    return {
        'direction': direction,
        'direction_detail': direction_detail,
        'factors': main_factors,
        'news': news_list[:2] if news_list else []  # 상위 2개 뉴스
    }

# 데이터 수집
with st.spinner('📡 시장 동향 분석 중...'):
    qqqm_news = get_market_summary('QQQM')
    schd_news = get_market_summary('SCHD')
    iau_news = get_market_summary('IAU')
    
    # 개별 종목 뉴스가 없으면 시장 전체 뉴스 사용
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
    schd_analysis = get_market_interpretation('SCHD', '배당주', schd_data['change_pct'], schd_news)
    iau_analysis = get_market_interpretation('IAU', '금', iau_data['change_pct'], iau_news)

# =====================================================================
# 포트폴리오 요약 (상단에 배치)
# =====================================================================
portfolio_change = (
    (qqqm_data['change_pct'] * 0.72) + 
    (schd_data['change_pct'] * 0.16) + 
    (iau_data['change_pct'] * 0.02)
)
portfolio_daily_change = total_value * (portfolio_change / 100)

# 색상 결정 (한국식: 상승=빨강, 하락=파랑)
port_color = "#ef4444" if portfolio_change >= 0 else "#3b82f6"
port_bg = "rgba(239, 68, 68, 0.05)" if portfolio_change >= 0 else "rgba(59, 130, 246, 0.05)"
port_icon = "📈" if portfolio_change >= 0 else "📉"

# 시장 한줄 요약 생성
def generate_market_summary():
    # 주요 요인 수집
    all_factors = []
    for analysis in [qqqm_analysis, schd_analysis, iau_analysis]:
        for f in analysis['factors']:
            if f not in all_factors:
                all_factors.append(f)
    
    # 시장 방향 판단
    if portfolio_change > 1.5:
        market_mood = "강한 상승장"
        mood_emoji = "🚀"
    elif portfolio_change > 0.5:
        market_mood = "상승장"
        mood_emoji = "📈"
    elif portfolio_change > -0.5:
        market_mood = "혼조세"
        mood_emoji = "➖"
    elif portfolio_change > -1.5:
        market_mood = "하락장"
        mood_emoji = "📉"
    else:
        market_mood = "강한 하락장"
        mood_emoji = "🔻"
    
    # 주요 이슈 추출 (첫 2개)
    key_issues = []
    for f in all_factors[:2]:
        # 이모지 제거하고 텍스트만
        issue = f.replace("🔺 ", "").replace("🔻 ", "").replace("➖ ", "")
        key_issues.append(issue)
    
    if key_issues:
        return f"{mood_emoji} {market_mood} | 주요 이슈: {', '.join(key_issues)}"
    else:
        return f"{mood_emoji} {market_mood}"

market_summary_text = generate_market_summary()

# 포트폴리오 요약 카드
col1, col2, col3 = st.columns([2, 2, 3])

with col1:
    st.markdown(f"""
    <div style="background: #1e293b; 
                border: 2px solid {port_color}; border-radius: 12px; padding: 20px; text-align: center;">
        <p style="color: #cbd5e1; font-size: 0.9em; margin: 0 0 8px 0;">오늘의 수익률</p>
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
            {'+' if portfolio_daily_change >= 0 else ''}${portfolio_daily_change:,.0f}
        </p>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div style="background: #1e293b; 
                border: 2px solid #10b981; border-radius: 12px; padding: 20px;">
        <p style="color: #10b981; font-size: 0.9em; margin: 0 0 10px 0; font-weight: 600;">📋 시장 한줄 요약</p>
        <p style="color: #f1f5f9; font-size: 1.15em; font-weight: 700; margin: 0; line-height: 1.5;">
            {market_summary_text}
        </p>
    </div>
    """, unsafe_allow_html=True)

# 세부 내역
st.markdown(f"""
<div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 12px 15px; margin-top: 15px;">
    <p style="color: #e2e8f0; font-size: 0.95em; margin: 0; text-align: center;">
        <span style="color: #10b981; font-weight: 600;">QQQM</span> {qqqm_data['change_pct']:+.2f}% × 72% &nbsp;&nbsp;|&nbsp;&nbsp; 
        <span style="color: #3b82f6; font-weight: 600;">SCHD</span> {schd_data['change_pct']:+.2f}% × 16% &nbsp;&nbsp;|&nbsp;&nbsp; 
        <span style="color: #fbbf24; font-weight: 600;">IAU</span> {iau_data['change_pct']:+.2f}% × 2%
    </p>
</div>
""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# =====================================================================
# 종목별 상세 분석
# =====================================================================
st.subheader("📈 종목별 상세 분석")

# QQQM 분석
qqqm_color = "#ef4444" if qqqm_data['change_pct'] >= 0 else "#3b82f6"
qqqm_icon = "📈" if qqqm_data['change_pct'] >= 0 else "📉"

with st.expander(f"🟢 **QQQM (나스닥 100)** — {qqqm_icon} {qqqm_data['change_pct']:+.2f}% (${qqqm_data['price']:.2f})", expanded=True):
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background: rgba(16, 185, 129, 0.1); border-radius: 12px;">
            <p style="color: #10b981; font-size: 0.9em; margin: 0;">오늘의 방향</p>
            <p style="color: {qqqm_color}; font-size: 1.8em; font-weight: 700; margin: 5px 0;">{qqqm_analysis['direction']}</p>
            <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{qqqm_analysis['direction_detail']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("**📌 주요 영향 요인**")
        for factor in qqqm_analysis['factors']:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{factor}")
        
        if qqqm_analysis['news']:
            st.markdown("**📰 관련 뉴스**")
            for news in qqqm_analysis['news']:
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;• [{news['title'][:50]}...]({news['link']})")

# SCHD 분석
schd_color = "#ef4444" if schd_data['change_pct'] >= 0 else "#3b82f6"
schd_icon = "📈" if schd_data['change_pct'] >= 0 else "📉"

with st.expander(f"🔵 **SCHD (배당 성장)** — {schd_icon} {schd_data['change_pct']:+.2f}% (${schd_data['price']:.2f})", expanded=True):
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background: rgba(59, 130, 246, 0.1); border-radius: 12px;">
            <p style="color: #3b82f6; font-size: 0.9em; margin: 0;">오늘의 방향</p>
            <p style="color: {schd_color}; font-size: 1.8em; font-weight: 700; margin: 5px 0;">{schd_analysis['direction']}</p>
            <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{schd_analysis['direction_detail']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("**📌 주요 영향 요인**")
        for factor in schd_analysis['factors']:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{factor}")
        
        if schd_analysis['news']:
            st.markdown("**📰 관련 뉴스**")
            for news in schd_analysis['news']:
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;• [{news['title'][:50]}...]({news['link']})")

# IAU 분석
iau_color = "#ef4444" if iau_data['change_pct'] >= 0 else "#3b82f6"
iau_icon = "📈" if iau_data['change_pct'] >= 0 else "📉"

with st.expander(f"🟡 **IAU (금)** — {iau_icon} {iau_data['change_pct']:+.2f}% (${iau_data['price']:.2f})", expanded=True):
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background: rgba(251, 191, 36, 0.1); border-radius: 12px;">
            <p style="color: #fbbf24; font-size: 0.9em; margin: 0;">오늘의 방향</p>
            <p style="color: {iau_color}; font-size: 1.8em; font-weight: 700; margin: 5px 0;">{iau_analysis['direction']}</p>
            <p style="color: #94a3b8; font-size: 0.85em; margin: 0;">{iau_analysis['direction_detail']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("**📌 주요 영향 요인**")
        for factor in iau_analysis['factors']:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{factor}")
        
        if iau_analysis['news']:
            st.markdown("**📰 관련 뉴스**")
            for news in iau_analysis['news']:
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;• [{news['title'][:50]}...]({news['link']})")

# VIX 분석
if vix_data:
    vix_color = "#3b82f6" if vix_data['change_pct'] >= 0 else "#10b981"
    vix_icon = "⚠️" if vix_data['change_pct'] >= 0 else "✅"
    vix_status = "변동성 증가 (주의)" if vix_data['change_pct'] >= 0 else "변동성 감소 (안정)"
    
    with st.expander(f"🔴 **VIX (공포지수)** — {vix_icon} {vix_data['change_pct']:+.2f}% ({vix_data['price']:.2f})", expanded=False):
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
            st.markdown("**📌 VIX 해석**")
            if vix_data['price'] <= 14:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;🔻 매우 낮음 - 시장 안정 (DEFCON 조건)")
            elif vix_data['price'] <= 20:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;➖ 정상 범위 - 일반적인 변동성")
            elif vix_data['price'] <= 30:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;🔺 높음 - 불안정한 시장")
            else:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;🔺 매우 높음 - 극심한 공포")
            
            st.markdown("**📌 투자 시사점**")
            if vix_data['change_pct'] >= 0:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;⚠️ 변동성 증가 중 - 신중한 접근 권장")
            else:
                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;✅ 변동성 감소 중 - 시장 안정화 신호")

st.markdown("---")

# =====================================================================
# 포트폴리오 히스토리 (Google Sheets 연동 시)
# =====================================================================
if gs_available:
    with st.expander("📈 포트폴리오 히스토리", expanded=False):
        history_df, history_error = get_portfolio_history()
        
        if history_error:
            st.info(f"ℹ️ {history_error}")
        elif history_df is not None and len(history_df) > 0:
            # 자산 추이 차트
            st.subheader("💰 총 자산 추이")
            
            # 차트 데이터 준비
            chart_df = history_df[['Date', 'TotalValue']].dropna()
            if len(chart_df) > 1:
                st.line_chart(chart_df.set_index('Date')['TotalValue'])
            
            # 최근 기록 테이블
            st.subheader("📋 최근 기록")
            display_df = history_df.tail(10).sort_values('Date', ascending=False)
            display_df['TotalValue'] = display_df['TotalValue'].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "-")
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            # 통계
            if len(history_df) > 1:
                total_values = history_df['TotalValue'].dropna()
                if len(total_values) > 1:
                    first_value = total_values.iloc[0]
                    last_value = total_values.iloc[-1]
                    change = last_value - first_value
                    change_pct = (change / first_value) * 100 if first_value > 0 else 0
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("첫 기록", f"${first_value:,.0f}")
                    with col2:
                        st.metric("현재", f"${last_value:,.0f}")
                    with col3:
                        st.metric("변화", f"${change:,.0f}", f"{change_pct:+.1f}%")

st.markdown("---")
st.markdown("""
<p style='text-align: center; color: #94a3b8; font-size: 0.9em;'>
    📚 TEAM FIRE 25 투자 매뉴얼 V5.10 기반<br>
    ⚡ 데이터 출처: Yahoo Finance (15-20분 지연)<br>
    ⚠️ 본 대시보드는 투자 참고용이며, 투자 결정은 본인 책임입니다
</p>
""", unsafe_allow_html=True)
