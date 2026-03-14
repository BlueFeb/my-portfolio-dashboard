import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials
import json

# --- 1. 기본 설정 ---
st.set_page_config(page_title="나만의 포트폴리오", layout="wide", page_icon="🌙")

# --- 2. 🌟 모드 전환 스위치 및 테마 디자인 설정 ---
# 제목과 스위치를 같은 줄에 배치하기 위해 화면을 8:2 비율로 나눕니다.
col1, col2 = st.columns([8, 2])
with col1:
    st.markdown("<h2 style='margin-top: -15px;'>🌙 내 손안의 포트폴리오</h2>", unsafe_allow_html=True)
with col2:
    is_dark_mode = st.toggle("다크 모드 켜기", value=True)

# 모드에 따른 컬러 스킴 세팅
if is_dark_mode:
    bg_color, text_color = "#1E1E1E", "#F0F2F6"
    df_bg, df_text = "#2A2A2A", "#FFFFFF"
    chart_template = "plotly_dark"
    # 다크모드용 밝은 파스텔톤
    pastel_colors = ['#FFB3BA', '#FFDFBA', '#FFFFBA', '#BAFFC9', '#BAE1FF', '#E8BAFF']
    line_color = '#FF99CC'
    profit_up_color, profit_down_color = '#FF9999', '#99CCFF' # 상승 빨강(파스텔), 하락 파랑(파스텔)
else:
    bg_color, text_color = "#F8F9FA", "#212529"
    df_bg, df_text = "#FFFFFF", "#212529"
    chart_template = "plotly_white"
    # 라이트모드용 약간 진한 파스텔톤 (가독성을 위해)
    pastel_colors = ['#FF8A98', '#FFB677', '#E5E570', '#85E39C', '#8AC4FF', '#C785FF']
    line_color = '#FF6699'
    profit_up_color, profit_down_color = '#E63946', '#457B9D' # 상승 짙은 빨강, 하락 짙은 파랑

# 앱 전체 배경 및 텍스트 색상을 강제로 바꾸는 마법의 CSS 주사
st.markdown(f"""
    <style>
    .stApp {{ background-color: {bg_color}; }}
    .stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp label, .stApp span {{
        color: {text_color} !important;
    }}
    [data-testid="stHeader"] {{ background-color: rgba(0,0,0,0); }}
    </style>
""", unsafe_allow_html=True)


# --- 3. 구글 시트 데이터 로드 (Secrets 사용) ---
@st.cache_data(ttl=60)
def load_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = json.loads(st.secrets["google_credentials"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        SHEET_NAME = "MyPortfolio_DB" 
        sheet_tx = client.open(SHEET_NAME).worksheet("거래내역")
        sheet_history = client.open(SHEET_NAME).worksheet("일별기록")
        
        df_tx = pd.DataFrame(sheet_tx.get_all_records())
        df_history = pd.DataFrame(sheet_history.get_all_records())
        return df_tx, df_history
    except Exception as e:
        st.error(f"⚠️ 데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame(), pd.DataFrame()

df, df_history = load_data()

# --- 4. 실시간 가격 정보 가져오기 ---
@st.cache_data(ttl=60)
def get_market_data(ticker):
    try:
        if not ticker: return 0.0, 0.0
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d").dropna(subset=['Close'])
        if len(hist) >= 2:
            current_price = float(hist['Close'].iloc[-1])
            prev_price = float(hist['Close'].iloc[-2])
            daily_change = ((current_price - prev_price) / prev_price) * 100
            return current_price, daily_change
        elif len(hist) == 1:
            return float(hist['Close'].iloc[0]), 0.0
        return 0.0, 0.0
    except Exception:
        return 0.0, 0.0

# --- 5. 메인 화면 출력 ---
if df.empty:
    st.info("아직 거래 내역이 없습니다. 텔레그램으로 거래를 기록해주세요!")
else:
    df['계산용수량'] = df.apply(lambda x: x['수량'] if x['거래종류'] == '매수' else -x['수량'], axis=1)
    holdings = df.groupby(['자산군', '종목명', '티커', '통화'])['계산용수량'].sum().reset_index()
    holdings = holdings[holdings['계산용수량'] > 0].copy()

    buy_df = df[df['거래종류'] == '매수'].copy()
    buy_df['결제금액'] = buy_df['수량'] * buy_df['거래단가']
    avg_cost_df = buy_df.groupby(['종목명', '티커'])[['결제금액', '수량']].sum().reset_index()
    avg_cost_df['평균매입단가'] = avg_cost_df['결제금액'] / avg_cost_df['수량']
    
    holdings = pd.merge(holdings, avg_cost_df[['종목명', '티커', '평균매입단가']], on=['종목명', '티커'], how='left')
    holdings['평균매입단가'] = holdings['평균매입단가'].fillna(0)

    usd_krw_price, _ = get_market_data("KRW=X")
    st.caption(f"💱 실시간 환율: 1 USD = {usd_krw_price:,.2f} KRW")

    realtime_prices, total_values_krw, total_costs_krw, profit_pcts, profit_amounts = [], [], [], [], []

    for index, row in holdings.iterrows():
        current_price, _ = get_market_data(row['티커'])
        realtime_prices.append(current_price)
        
        rate = usd_krw_price if row['통화'] == "USD" else 1
        eval_krw = current_price * row['계산용수량'] * rate 
        cost_krw = row['평균매입단가'] * row['계산용수량'] * rate     
        
        total_values_krw.append(eval_krw)
        total_costs_krw.append(cost_krw)
        profit_amounts.append(eval_krw - cost_krw)
        profit_pcts.append(((current_price - row['평균매입단가']) / row['평균매입단가'] * 100) if row['평균매입단가'] > 0 else 0.0)

    holdings['현재가'] = realtime_prices
    holdings['평가금액(원)'] = total_values_krw
    holdings['평가손익(원)'] = profit_amounts
    holdings['수익률(%)'] = profit_pcts

    # 총 자산 지표 
    total_asset = sum(total_values_krw)
    total_cost = sum(total_costs_krw)
    total_profit = total_asset - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0

    st.metric(
        label="💰 총 자산 (원화 환산)", 
        value=f"{total_asset:,.0f} 원", 
        delta=f"평가손익: {total_profit:,.0f} 원 ({total_profit_pct:,.2f}%)"
    )
    st.markdown("---")

    # 🌟 차트 출력 (토글 상태에 따라 색상 자동 변경)
    st.markdown("**🥧 자산군 및 종목 비중**")
    
    fig1 = px.pie(holdings.groupby('자산군')['평가금액(원)'].sum().reset_index(), values='평가금액(원)', names='자산군', hole=0.4, color_discrete_sequence=pastel_colors)
    fig1.update_traces(textposition='inside', textinfo='percent+label', textfont_size=15)
    fig1.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig1, use_container_width=True)

    fig2 = px.pie(holdings, values='평가금액(원)', names='종목명', color_discrete_sequence=pastel_colors)
    fig2.update_traces(textposition='inside', textinfo='percent+label', textfont_size=13)
    fig2.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")

    # 🌟 테이블 출력 (토글 상태에 따라 글씨 및 배경 변경)
    st.markdown("**📋 보유 자산 상세**")
    display_df = holdings[['종목명', '계산용수량', '수익률(%)', '평가금액(원)']].copy()
    display_df.rename(columns={'계산용수량': '수량'}, inplace=True)

    # 수익률에 따른 색상 함수 (모드별 색상 적용)
    def style_table(val):
        if isinstance(val, float):
            color = profit_up_color if val > 0 else profit_down_color if val < 0 else text_color
            return f'color: {color}; font-weight: bold;'
        return ''

    st.dataframe(
        display_df.style
        .set_properties(**{'background-color': df_bg, 'color': df_text})
        .format({'수량': '{:,.1f}', '수익률(%)': '{:,.2f}%', '평가금액(원)': '{:,.0f}'})
        .map(style_table, subset=['수익률(%)']),
        use_container_width=True, hide_index=True
    )

    st.markdown("---")

    # 자산 추이 그래프
    st.markdown("**📈 자산 총액 변동 추이**")
    if not df_history.empty:
        fig3 = px.line(df_history, x='날짜', y=df_history.columns[1], markers=True)
        fig3.update_traces(line_color=line_color, marker_color=line_color)
        fig3.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig3, use_container_width=True)
