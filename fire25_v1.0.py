import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
import time
import requests
from bs4 import BeautifulSoup

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
# 사이드바: 포트폴리오 입력
# =====================================================================
with st.sidebar:
    st.header("📊 포트폴리오 설정")
    
    st.subheader("보유 주식")
    qqqm_qty = st.number_input("QQQM 수량", min_value=0.0, value=100.0, step=1.0, format="%.2f")
    schd_qty = st.number_input("SCHD 수량", min_value=0.0, value=50.0, step=1.0, format="%.2f")
    iau_qty = st.number_input("IAU 수량", min_value=0.0, value=20.0, step=1.0, format="%.2f")
    
    st.subheader("보유 현금")
    sgov_value = st.number_input("SGOV 평가액 (USD)", min_value=0.0, value=3000.0, step=100.0, format="%.2f", 
                                  help="단기국채 ETF (SGOV) 보유 금액")
    cash_deposit = st.number_input("예수금 (USD)", min_value=0.0, value=2000.0, step=100.0, format="%.2f",
                                    help="증권계좌 현금 (바로 투자 가능한 자금)")
    
    st.markdown("---")
    st.subheader("💰 신규 자금")
    new_cash = st.number_input("월급/추가 입금 (USD)", min_value=0.0, value=0.0, step=100.0, format="%.2f",
                                help="이번 달 투입할 신규 자금 (월급, 보너스 등)")
    
    # 총 현금 계산
    total_cash = sgov_value + cash_deposit
    
    st.markdown("---")
    
    # 현금 현황 표시 (HTML 대신 Streamlit 컴포넌트 사용)
    st.markdown("### 💰 현금 현황")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("SGOV", f"${sgov_value:,.2f}")
    with col2:
        st.metric("예수금", f"${cash_deposit:,.2f}")
    
    st.markdown(f"**기존 현금:** ${total_cash:,.2f}")
    
    if new_cash > 0:
        st.markdown(f"**+ 신규 자금:** :blue[${new_cash:,.2f}]")
        st.markdown(f"**투입 가능 총액:** :orange[${total_cash + new_cash:,.2f}]")
    
    st.info("💡 값 변경 후 화면을 스크롤하면 자동으로 계산이 업데이트됩니다")
    
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
                <span style="color: #10b981; font-weight: 700;">70%</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin: 5px 0;">
                <span style="color: #94a3b8;">SCHD</span>
                <span style="color: #3b82f6; font-weight: 700;">15%</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin: 5px 0;">
                <span style="color: #94a3b8;">IAU</span>
                <span style="color: #fbbf24; font-weight: 700;">5%</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin: 5px 0;">
                <span style="color: #94a3b8;">현금</span>
                <span style="color: #94a3b8; font-weight: 700;">10%</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    refresh_button = st.button("🔄 데이터 새로고침", use_container_width=True)
    
    # 새로고침 버튼 클릭 시 캐시 삭제
    if refresh_button:
        st.cache_data.clear()
        st.success("✅ 캐시가 삭제되었습니다. 최신 데이터를 가져옵니다...")
        st.rerun()

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
    qqqm_data = get_stock_data('QQQM')
    schd_data = get_stock_data('SCHD')
    iau_data = get_stock_data('IAU')
    vix_data = get_stock_data('^VIX', period="1mo")  # VIX는 1개월만

# 데이터 검증
if not all([qqqm_data, schd_data, iau_data]):
    st.error("⚠️ 일부 데이터를 가져오지 못했습니다. 새로고침 버튼을 눌러주세요.")
    st.stop()

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
    st.markdown(f"<p style='font-size: 0.9em; color: #94a3b8;'>거래량: {qqqm_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col2:
    change_class = 'positive' if schd_data['change'] >= 0 else 'negative'
    st.metric(
        label="SCHD (배당 성장)",
        value=f"${schd_data['price']:.2f}",
        delta=f"{schd_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.9em; color: #94a3b8;'>거래량: {schd_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col3:
    change_class = 'positive' if iau_data['change'] >= 0 else 'negative'
    st.metric(
        label="IAU (금)",
        value=f"${iau_data['price']:.2f}",
        delta=f"{iau_data['change_pct']:+.2f}%"
    )
    st.markdown(f"<p style='font-size: 0.9em; color: #94a3b8;'>거래량: {iau_data['volume']:,.0f}</p>", unsafe_allow_html=True)

with col4:
    if vix_data:
        st.metric(
            label="VIX (공포 지수)",
            value=f"{vix_data['price']:.2f}",
            delta=f"{vix_data['change_pct']:+.2f}%"
        )
        if vix_data['price'] <= 14.0:
            st.markdown("<p style='color: #ef4444; font-weight: 700;'>⚠️ Defcon 조건</p>", unsafe_allow_html=True)
    else:
        st.warning("VIX 데이터 없음")

st.markdown("---")

# =====================================================================
# 핵심 로직: 매뉴얼 V5.6
# =====================================================================
st.header("🎯 작전 상황 분석")

# 데프콘 트리거 체크
defcon_triggered = False
if vix_data and vix_data['price'] <= 14.0 and qqqm_data['rsi'] >= 70:
    defcon_triggered = True

# 50일선 붕괴 체크
puddle_alert = qqqm_data['price'] < qqqm_data['sma_50']

# 리밸런싱 체크
rebalancing_needed = qqqm_pct > 75

# 경고 표시
if defcon_triggered:
    st.markdown(f"""
    <div class="warning-box">
        <div class="warning-title">🚨 DEFCON 세이빙 발동!</div>
        <p><strong>VIX:</strong> {vix_data['price']:.2f} (≤ 14.00)</p>
        <p><strong>RSI:</strong> {qqqm_data['rsi']:.2f} (≥ 70)</p>
        <p><strong>조치:</strong> 신규 월급을 SGOV로만 투입하세요</p>
    </div>
    """, unsafe_allow_html=True)

if puddle_alert:
    distance_pct = ((qqqm_data['price'] - qqqm_data['sma_50']) / qqqm_data['sma_50']) * 100
    
    # 투입 가능한 자금 계산 (실시간)
    sgov_minimum = total_value * 0.07  # 총 자산의 7%
    available_sgov = max(0, sgov_value - sgov_minimum)  # SGOV 7% 초과분
    injection_30 = available_sgov * 0.30  # SGOV 초과분의 30%
    injection_total = injection_30 + cash_deposit  # 예수금 전액 활용 가능
    
    # 각 항목의 비중 계산
    sgov_excess_pct = ((sgov_value - sgov_minimum) / total_value) * 100 if total_value > 0 else 0
    
    st.markdown(f"""
    <div class="warning-box">
        <div class="warning-title">🚨 50일선 붕괴! 웅덩이 매수 구간</div>
        <p><strong>현재가:</strong> ${qqqm_data['price']:.2f}</p>
        <p><strong>50일선:</strong> ${qqqm_data['sma_50']:.2f}</p>
        <p><strong>괴리율:</strong> {distance_pct:.2f}%</p>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p style="font-weight: 700; color: #fbbf24; font-size: 1.1em;">💰 투입 가능 자금 (실시간 계산):</p>
        <div style="background: rgba(251, 191, 36, 0.05); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;">• <strong>총 자산:</strong> ${total_value:,.2f}</p>
            <p style="margin: 5px 0;">• <strong>SGOV 보유:</strong> ${sgov_value:,.2f} <span style="color: #10b981;">({sgov_pct:.2f}%)</span></p>
            <p style="margin: 5px 0;">• <strong>SGOV 최소 (7%):</strong> ${sgov_minimum:,.2f}</p>
            <p style="margin: 5px 0;">• <strong>SGOV 초과분:</strong> ${available_sgov:,.2f} <span style="color: #fbbf24;">({sgov_excess_pct:.2f}% 유지)</span></p>
        </div>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 10px 0;">
        <div style="background: rgba(16, 185, 129, 0.05); padding: 12px; border-radius: 6px; margin: 10px 0;">
            <p style="margin: 5px 0;">• <strong>SGOV 30% 투입:</strong> <span style="color: #10b981; font-weight: 700;">${injection_30:,.2f}</span></p>
            <p style="margin: 5px 0; font-size: 0.9em; color: #94a3b8;">  └ ${available_sgov:,.2f} × 30% = ${injection_30:,.2f}</p>
            <p style="margin: 5px 0;">• <strong>예수금 전액:</strong> <span style="color: #10b981; font-weight: 700;">${cash_deposit:,.2f}</span></p>
            <p style="margin: 8px 0; padding-top: 8px; border-top: 1px solid rgba(16, 185, 129, 0.2);">• <strong>총 투입 가능:</strong> <span style="color: #10b981; font-size: 1.3em; font-weight: 700;">${injection_total:,.2f}</span></p>
        </div>
        <hr style="border-color: rgba(239, 68, 68, 0.3); margin: 15px 0;">
        <p><strong>📋 조치:</strong></p>
        <p>• <strong>1단계:</strong> SGOV 초과분의 30% 투입 (${injection_30:,.2f})</p>
        <p>• <strong>2단계:</strong> 예수금 활용 검토 (${cash_deposit:,.2f} 가용)</p>
        <p style="color: #10b981; font-weight: 700; margin-top: 10px;">💡 QQQM 약 {(injection_total / qqqm_data['price']):.1f}주 매수 가능</p>
    </div>
    """, unsafe_allow_html=True)

if rebalancing_needed:
    excess = qqqm_pct - 70
    st.markdown(f"""
    <div class="info-box">
        <div class="warning-title">⚠️ 리밸런싱 필요</div>
        <p><strong>QQQM 현재 비중:</strong> {qqqm_pct:.2f}% (목표: 70%)</p>
        <p><strong>초과:</strong> +{excess:.2f}%p</p>
        <p><strong>조치:</strong> Smart Shoulder 프로토콜 대기 또는 수동 조정</p>
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
    if qqqm_data['price'] > qqqm_data['sma_50']:
        sma_status = "✅ 50일선 위"
        sma_color = "#10b981"
    else:
        sma_status = "🚨 50일선 아래"
        sma_color = "#ef4444"
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%); border-radius: 12px; border: 2px solid {sma_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);">
        <p style="font-size: 0.9em; color: #cbd5e1; margin-bottom: 8px; font-weight: 600;">50일 이동평균선</p>
        <p style="font-size: 2.5em; font-weight: 700; color: {sma_color}; margin: 10px 0;">${qqqm_data['sma_50']:.2f}</p>
        <p style="font-size: 1.1em; color: {sma_color}; font-weight: 600;">{sma_status}</p>
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
        '목표 비중 (%)': [70, 15, 5, '-', '-', 10],
        '차이 (%p)': [qqqm_pct - 70, schd_pct - 15, iau_pct - 5, '-', '-', cash_pct - 10]
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
is_puddle = puddle_alert  # 50일선 붕괴
is_defcon = defcon_triggered  # Defcon 발동
has_new_cash = new_cash > 0  # 신규 자금
needs_rebalancing = qqqm_pct > 75  # Smart Shoulder

# 매매 계획 생성
st.subheader("🎯 현재 상황 진단")

situation_badges = []
if is_defcon:
    situation_badges.append("🚨 <span style='background: #ef4444; color: white; padding: 4px 12px; border-radius: 4px; font-weight: 700;'>DEFCON 발동</span>")
if is_puddle:
    situation_badges.append("🚨 <span style='background: #ef4444; color: white; padding: 4px 12px; border-radius: 4px; font-weight: 700;'>50일선 붕괴</span>")
if needs_rebalancing:
    situation_badges.append("⚠️ <span style='background: #fbbf24; color: white; padding: 4px 12px; border-radius: 4px; font-weight: 700;'>리밸런싱 필요</span>")
if has_new_cash:
    situation_badges.append("💰 <span style='background: #3b82f6; color: white; padding: 4px 12px; border-radius: 4px; font-weight: 700;'>신규 자금 ${:,.0f}</span>".format(new_cash))

if situation_badges:
    st.markdown(" ".join(situation_badges), unsafe_allow_html=True)
else:
    st.markdown("<span style='background: #10b981; color: white; padding: 4px 12px; border-radius: 4px; font-weight: 700;'>✅ 정상 운영</span>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# 우선순위 1: Defcon 발동 중
if is_defcon:
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
                <p style="color: #94a3b8; font-size: 0.9em; margin-top: 10px;">💡 Defcon 해제 후 정상 배분으로 전환</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("💡 신규 자금이 없습니다. 월급/추가 입금 시 SGOV로만 투입하세요.")

# 우선순위 2: 50일선 붕괴 (웅덩이)
elif is_puddle:
    st.markdown("""
    <div class="warning-box">
        <div class="warning-title">🚨 우선순위 1: 웅덩이 매수</div>
        <p style="font-size: 1.1em; margin: 15px 0;"><strong>📋 조치 사항:</strong></p>
        <ol style="line-height: 2;">
            <li><strong>1단계: SGOV 초과분 30% 투입</strong></li>
            <li><strong>2단계: 예수금 활용</strong></li>
            <li><strong>3단계: 신규 자금 투입</strong></li>
        </ol>
    </div>
    """, unsafe_allow_html=True)
    
    # 웅덩이 대응 계산
    sgov_minimum = total_value * 0.07
    available_sgov = max(0, sgov_value - sgov_minimum)
    injection_sgov = available_sgov * 0.30
    injection_deposit = cash_deposit
    injection_new = new_cash
    total_injection = injection_sgov + injection_deposit + injection_new
    
    # SGOV 주가 정보 가져오기
    try:
        sgov_ticker = yf.Ticker("SGOV")
        sgov_price = sgov_ticker.history(period='1d')['Close'].iloc[-1]
        sgov_shares_total = sgov_value / sgov_price if sgov_price > 0 else 0
        sgov_shares_to_sell = injection_sgov / sgov_price if sgov_price > 0 else 0
    except:
        sgov_price = 93.5  # 대략적인 SGOV 가격
        sgov_shares_total = sgov_value / sgov_price
        sgov_shares_to_sell = injection_sgov / sgov_price
    
    # 투입 가능 자금 표시
    st.success("💰 투입 가능 자금")
    
    st.write("**자금 구성:**")
    st.write(f"• SGOV 보유: ${sgov_value:,.2f} (약 {sgov_shares_total:.1f}주 @ ${sgov_price:.2f})")
    st.write(f"  └─ 최소 유지 (7%): ${sgov_minimum:,.2f}")
    st.write(f"  └─ 사용 가능: ${available_sgov:,.2f}")
    st.write(f"• **SGOV 30% 매도: {sgov_shares_to_sell:.1f}주 = ${injection_sgov:,.2f}**")
    st.write(f"• 예수금 전액: ${injection_deposit:,.2f}")
    if has_new_cash:
        st.write(f"• 신규 자금: ${injection_new:,.2f}")
    st.markdown("---")
    st.write(f"**총 투입 가능: :green[${total_injection:,.2f}]**")
    
    st.markdown("")
    st.info("📊 매수 전략")
    st.write(f"• QQQM 70%: ${total_injection * 0.70:,.2f} (약 {(total_injection * 0.70 / qqqm_data['price']):.1f}주)")
    st.write(f"• SCHD 15%: ${total_injection * 0.15:,.2f} (약 {(total_injection * 0.15 / schd_data['price']):.1f}주)")
    st.write(f"• IAU 5%: ${total_injection * 0.05:,.2f} (약 {(total_injection * 0.05 / iau_data['price']):.1f}주)")
    st.write(f"• SGOV 10%: ${total_injection * 0.10:,.2f}")

# 우선순위 3: Smart Shoulder (리밸런싱)
elif needs_rebalancing:
    st.markdown("""
    <div class="info-box">
        <div class="warning-title">⚠️ 우선순위 1: Smart Shoulder 리밸런싱</div>
        <p style="font-size: 1.1em; margin: 15px 0;"><strong>QQQM 비중 초과 (75% 돌파)</strong></p>
    </div>
    """, unsafe_allow_html=True)
    
    # 초과분 계산
    excess_pct = qqqm_pct - 70
    excess_value = total_value * (excess_pct / 100)
    excess_qty = excess_value / qqqm_data['price']
    
    st.error("🔴 매도 필요")
    st.write(f"**QQQM 매도:** {excess_qty:.1f}주")
    st.write(f"• 매도 금액: ${excess_value:,.2f}")
    st.write(f"• 조정 후 비중: {qqqm_pct:.1f}% → 70%")
    
    st.markdown("")
    st.info("💰 매도 대금 재배분")
    st.write(f"• SCHD: ${excess_value * 0.60:,.2f} (약 {(excess_value * 0.60 / schd_data['price']):.1f}주)")
    st.write(f"• IAU: ${excess_value * 0.20:,.2f} (약 {(excess_value * 0.20 / iau_data['price']):.1f}주)")
    st.write(f"• SGOV: ${excess_value * 0.20:,.2f}")
    
    if has_new_cash:
        st.markdown("")
        st.warning(f"💰 신규 자금 배분 (${new_cash:,.2f})")
        st.write("QQQM 비중이 높으므로 SCHD/IAU/SGOV 위주 배분")
        st.write(f"• SCHD: ${new_cash * 0.60:,.2f} (약 {(new_cash * 0.60 / schd_data['price']):.1f}주)")
        st.write(f"• IAU: ${new_cash * 0.20:,.2f} (약 {(new_cash * 0.20 / iau_data['price']):.1f}주)")
        st.write(f"• SGOV: ${new_cash * 0.20:,.2f}")

# 정상 상황: 월급 배분
elif has_new_cash:
    st.markdown("""
    <div class="success-box">
        <div style="font-size: 1.2em; font-weight: 700; color: #10b981; margin-bottom: 10px;">✅ 정상 운영: 목표 비중대로 투자</div>
        <p>현재 포트폴리오가 안정적입니다. 신규 자금을 목표 비중대로 배분하세요.</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.success(f"💰 신규 자금 배분 (${new_cash:,.2f})")
    
    st.write("**매수 계획:**")
    st.write(f"• QQQM 70%: ${new_cash * 0.70:,.2f} (약 {(new_cash * 0.70 / qqqm_data['price']):.1f}주)")
    st.write(f"• SCHD 15%: ${new_cash * 0.15:,.2f} (약 {(new_cash * 0.15 / schd_data['price']):.1f}주)")
    st.write(f"• IAU 5%: ${new_cash * 0.05:,.2f} (약 {(new_cash * 0.05 / iau_data['price']):.1f}주)")
    st.write(f"• SGOV 10%: ${new_cash * 0.10:,.2f}")
    
    st.info(f"""💡 **투자 후 예상 비중**  
    QQQM: {((qqqm_value + new_cash * 0.70) / (total_value + new_cash) * 100):.1f}% | 
    SCHD: {((schd_value + new_cash * 0.15) / (total_value + new_cash) * 100):.1f}% | 
    IAU: {((iau_value + new_cash * 0.05) / (total_value + new_cash) * 100):.1f}%""")

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
# 경제 뉴스 섹션
# =====================================================================
st.header("📰 실시간 경제 뉴스")

@st.cache_data(ttl=1800)  # 30분 캐시
def get_market_news():
    """Investing.com에서 시장 뉴스 가져오기"""
    news_items = []
    
    # Investing.com 뉴스 URL들
    urls = {
        'QQQM/나스닥': 'https://www.investing.com/news/stock-market-news',
        'S&P 500': 'https://www.investing.com/news/stock-market-news',
        'VIX/변동성': 'https://www.investing.com/news/stock-market-news'
    }
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        for category, url in urls.items():
            try:
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Investing.com 뉴스 항목 찾기
                    articles = soup.find_all('article', class_='js-article-item', limit=3)
                    
                    for article in articles:
                        try:
                            title_elem = article.find('a', class_='title')
                            if title_elem:
                                title = title_elem.get_text(strip=True)
                                link = 'https://www.investing.com' + title_elem.get('href', '')
                                
                                # 시간 정보
                                time_elem = article.find('time')
                                if time_elem and time_elem.get('datetime'):
                                    timestamp = datetime.fromisoformat(time_elem['datetime'].replace('Z', '+00:00'))
                                else:
                                    timestamp = datetime.now()
                                
                                news_items.append({
                                    'title': title,
                                    'publisher': 'Investing.com',
                                    'link': link,
                                    'timestamp': timestamp,
                                    'category': category
                                })
                        except Exception as e:
                            continue
            except Exception as e:
                continue
                
    except Exception as e:
        st.warning(f"⚠️ 뉴스 수집 중 오류: {str(e)}")
    
    # Yahoo Finance 백업 (Investing.com 실패 시)
    if len(news_items) < 3:
        try:
            # QQQM 뉴스
            qqqm_ticker = yf.Ticker('QQQM')
            if hasattr(qqqm_ticker, 'news') and qqqm_ticker.news:
                for item in qqqm_ticker.news[:3]:
                    news_items.append({
                        'title': item.get('title', 'No title'),
                        'publisher': item.get('publisher', 'Unknown'),
                        'link': item.get('link', '#'),
                        'timestamp': datetime.fromtimestamp(item.get('providerPublishTime', 0)),
                        'category': 'QQQM/나스닥'
                    })
        except:
            pass
    
    # 시간순 정렬
    news_items.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return news_items[:8]  # 최대 8개

def translate_news_summary(title):
    """뉴스 제목 간단 한글 요약"""
    # 주요 키워드 번역
    keywords = {
        # 상승 관련
        'rally': '상승',
        'rallies': '급등',
        'surge': '급등',
        'surges': '급등',
        'jump': '상승',
        'jumps': '급등',
        'gain': '상승',
        'gains': '상승',
        'rise': '상승',
        'rises': '상승',
        'soar': '급등',
        'soars': '급등',
        'climb': '상승',
        'climbs': '상승',
        'high': '고점',
        'highs': '고점',
        'record': '신기록',
        'all-time high': '사상 최고',
        'beat': '상회',
        'beats': '상회',
        'top': '초과',
        'tops': '초과',
        
        # 하락 관련
        'fall': '하락',
        'falls': '하락',
        'drop': '하락',
        'drops': '급락',
        'plunge': '급락',
        'plunges': '급락',
        'tumble': '하락',
        'tumbles': '급락',
        'slide': '하락',
        'slides': '하락',
        'decline': '하락',
        'declines': '하락',
        'sink': '하락',
        'sinks': '급락',
        'crash': '폭락',
        'crashes': '폭락',
        'selloff': '매도',
        'sell-off': '매도세',
        'correction': '조정',
        'pullback': '조정',
        'low': '저점',
        'lows': '저점',
        
        # 시장 관련
        'stock': '주식',
        'stocks': '주식',
        'market': '시장',
        'markets': '시장',
        'wall street': '월가',
        'dow': '다우',
        's&p': 'S&P',
        'nasdaq': '나스닥',
        'tech': '기술주',
        'shares': '주가',
        'investors': '투자자',
        'traders': '거래자',
        'earnings': '실적',
        'profit': '수익',
        'profits': '수익',
        'revenue': '매출',
        
        # Fed 관련
        'fed': '연준',
        'federal reserve': '연방준비제도',
        'rate': '금리',
        'rates': '금리',
        'interest': '금리',
        'inflation': '인플레이션',
        'policy': '정책',
        'decision': '결정',
        'cut': '인하',
        'cuts': '인하',
        'hike': '인상',
        'hikes': '인상',
        'hold': '동결',
        'holds': '동결',
        
        # 기타
        'outlook': '전망',
        'forecast': '예측',
        'data': '데이터',
        'report': '보고서',
        'warning': '경고',
        'worry': '우려',
        'worries': '우려',
        'concern': '우려',
        'concerns': '우려',
        'fear': '공포',
        'fears': '공포',
        'volatility': '변동성',
        'vix': 'VIX',
        'uncertainty': '불확실성'
    }
    
    title_lower = title.lower()
    summary_parts = []
    
    # 키워드 찾기
    for eng, kor in keywords.items():
        if eng in title_lower:
            if kor not in summary_parts:
                summary_parts.append(kor)
    
    # 요약 생성
    if summary_parts:
        summary = ' | '.join(summary_parts[:3])  # 최대 3개 키워드
        return f"💬 {summary}"
    else:
        return ""

# 뉴스 가져오기
with st.spinner('📡 최신 뉴스 수집 중...'):
    market_news = get_market_news()

if market_news:
    col1, col2 = st.columns(2)
    
    for idx, news in enumerate(market_news):
        with col1 if idx % 2 == 0 else col2:
            # 시간 포맷팅
            time_diff = datetime.now() - news['timestamp']
            if time_diff.days > 0:
                time_str = f"{time_diff.days}일 전"
            elif time_diff.seconds >= 3600:
                time_str = f"{time_diff.seconds // 3600}시간 전"
            else:
                time_str = f"{time_diff.seconds // 60}분 전"
            
            # 카테고리 색상 이모지
            category_icons = {
                'QQQM/나스닥': '🟢',
                'S&P 500': '🔵',
                'VIX/변동성': '🔴',
                'SCHD': '🟡'
            }
            icon = category_icons.get(news['category'], '⚪')
            
            # 한글 요약 생성
            korean_summary = translate_news_summary(news['title'])
            
            # 뉴스 카드 표시
            with st.container():
                col_cat, col_time = st.columns([3, 1])
                with col_cat:
                    st.markdown(f"**{icon} {news['category']}**")
                with col_time:
                    st.markdown(f"*{time_str}*")
                
                if korean_summary:
                    st.info(korean_summary)
                
                st.markdown(f"[{news['title']}]({news['link']})")
                st.caption(f"📌 {news['publisher']}")
                st.markdown("---")
else:
    st.info("💡 뉴스를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.")

st.markdown("---")
st.markdown("""
<p style='text-align: center; color: #94a3b8; font-size: 0.9em;'>
    📚 TEAM FIRE 25 투자 매뉴얼 V5.6 기반<br>
    ⚡ 데이터 출처: Yahoo Finance (15-20분 지연)<br>
    ⚠️ 본 대시보드는 투자 참고용이며, 투자 결정은 본인 책임입니다
</p>
""", unsafe_allow_html=True)
