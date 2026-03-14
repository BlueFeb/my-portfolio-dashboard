import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials
import json

# --- 1. 기본 설정 ---
st.set_page_config(page_title="나만의 포트폴리오", layout="wide", page_icon="🌙")

col1, col2 = st.columns([8, 2])
with col1:
    st.markdown("<h2 style='margin-top: -15px;'>🌙 내 포트폴리오</h2>", unsafe_allow_html=True)
with col2:
    is_dark_mode = st.toggle("다크 모드 켜기", value=True)

if is_dark_mode:
    bg_color, text_color = "#1E1E1E", "#F0F2F6"
    df_bg, df_text = "#2A2A2A", "#FFFFFF"
    chart_template = "plotly_dark"
    pastel_colors = ['#FFB3BA', '#FFDFBA', '#FFFFBA', '#BAFFC9', '#BAE1FF', '#E8BAFF']
    line_color = '#FF99CC'
    profit_up_color, profit_down_color = '#FF9999', '#99CCFF' 
else:
    bg_color, text_color = "#F8F9FA", "#212529"
    df_bg, df_text = "#FFFFFF", "#212529"
    chart_template = "plotly_white"
    pastel_colors = ['#FF8A98', '#FFB677', '#E5E570', '#85E39C', '#8AC4FF', '#C785FF']
    line_color = '#FF6699'
    profit_up_color, profit_down_color = '#E63946', '#457B9D'

st.markdown(f"""
    <style>
    .stApp {{ background-color: {bg_color}; }}
    .stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp label, .stApp span {{
        color: {text_color} !important;
    }}
    [data-testid="stHeader"] {{ background-color: rgba(0,0,0,0); }}
    </style>
""", unsafe_allow_html=True)

# --- 2. 구글 시트 데이터 로드 ---
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
        
        # 🌟 새로 만든 '실현손익' 시트도 불러옵니다
        try:
            sheet_pnl = client.open(SHEET_NAME).worksheet("실현손익")
            df_pnl = pd.DataFrame(sheet_pnl.get_all_records())
        except:
            df_pnl = pd.DataFrame() # 시트가 없으면 빈 데이터 반환
            
        df_tx = pd.DataFrame(sheet_tx.get_all_records())
        df_history = pd.DataFrame(sheet_history.get_all_records())
        return df_tx, df_history, df_pnl
    except Exception as e:
        st.error(f"⚠️ 데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df, df_history, df_pnl = load_data()

@st.cache_data(ttl=60)
def get_market_data(ticker):
    try:
        if not ticker: return 0.0, 0.0
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d").dropna(subset=['Close'])
        if len(hist) >= 2:
            return float(hist['Close'].iloc[-1]), ((float(hist['Close'].iloc[-1]) - float(hist['Close'].iloc[-2])) / float(hist['Close'].iloc[-2])) * 100
        elif len(hist) == 1:
            return float(hist['Close'].iloc[0]), 0.0
        return 0.0, 0.0
    except: return 0.0, 0.0

if df.empty:
    st.info("아직 거래 내역이 없습니다.")
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

    holdings['평가금액(원)'] = total_values_krw
    holdings['평가손익(원)'] = profit_amounts
    holdings['수익률(%)'] = profit_pcts

    total_asset = sum(total_values_krw)
    total_cost = sum(total_costs_krw)
    total_profit = total_asset - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0

    st.metric(label="💰 총 자산 (원화 환산)", value=f"{total_asset:,.0f} 원", delta=f"총 평가손익: {total_profit:,.0f} 원 ({total_profit_pct:,.2f}%)")
    st.markdown("---")

    # 🌟 [신규] 실현 손익 탭 화면
    st.markdown("**💸 실현 손익 (매도 수익 달력)**")
    
    if not df_pnl.empty and '실현손익(원)' in df_pnl.columns:
        df_pnl['날짜'] = pd.to_datetime(df_pnl['날짜'])
        df_pnl['월'] = df_pnl['날짜'].dt.strftime('%Y-%m')
        df_pnl['연'] = df_pnl['날짜'].dt.strftime('%Y')

        # 스마트폰에서 누르기 편한 3개의 탭 생성
        tab1, tab2, tab3 = st.tabs(["일별 수익", "월별 수익", "연별 수익"])

        def plot_pnl_bar(data, x_col, title):
            # 값이 양수면 빨강계열(파스텔), 음수면 파랑계열(파스텔) 지정
            colors = [profit_up_color if val > 0 else profit_down_color for val in data['실현손익(원)']]
            fig = px.bar(data, x=x_col, y='실현손익(원)', text_auto='.2s')
            fig.update_traces(marker_color=colors, textfont_size=12, textangle=0, textposition="outside", cliponaxis=False)
            fig.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

        with tab1:
            daily_pnl = df_pnl.groupby(df_pnl['날짜'].dt.strftime('%m-%d'))['실현손익(원)'].sum().reset_index()
            plot_pnl_bar(daily_pnl, '날짜', '일별')
        with tab2:
            monthly_pnl = df_pnl.groupby('월')['실현손익(원)'].sum().reset_index()
            plot_pnl_bar(monthly_pnl, '월', '월별')
        with tab3:
            yearly_pnl = df_pnl.groupby('연')['실현손익(원)'].sum().reset_index()
            plot_pnl_bar(yearly_pnl, '연', '연별')
    else:
        st.caption("아직 매도 기록(실현손익)이 없습니다.")

    st.markdown("---")

    st.markdown("**🥧 자산군 및 종목 비중**")
    fig1 = px.pie(holdings.groupby('자산군')['평가금액(원)'].sum().reset_index(), values='평가금액(원)', names='자산군', hole=0.4, color_discrete_sequence=pastel_colors)
    fig1.update_traces(textposition='inside', textinfo='percent+label', textfont_size=15)
    fig1.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig1, use_container_width=True)

    st.markdown("---")

    st.markdown("**📋 보유 자산 상세 (열 제목 터치 시 정렬 ↕️)**")
    display_df = holdings[['종목명', '계산용수량', '수익률(%)', '평가금액(원)', '평가손익(원)']].copy()
    display_df.rename(columns={'계산용수량': '수량', '수익률(%)': '수익률', '평가금액(원)': '평가액', '평가손익(원)': '손익'}, inplace=True)

    def style_table(val):
        if isinstance(val, (int, float)):
            color = profit_up_color if val > 0 else profit_down_color if val < 0 else text_color
            return f'color: {color}; font-weight: bold;'
        return ''

    st.dataframe(
        display_df.style
        .set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '12px'})
        .format({'수량': '{:,.1f}', '수익률': '{:,.2f}%', '평가액': '{:,.0f}', '손익': '{:,.0f}'})
        .map(style_table, subset=['수익률', '손익']),
        use_container_width=True, hide_index=True
    )
