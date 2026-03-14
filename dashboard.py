import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. 기본 설정 (모바일 최적화 레이아웃) ---
st.set_page_config(page_title="나만의 포트폴리오", layout="wide", page_icon="🌙")

# 모바일에서는 제목 크기를 살짝 줄이는 꼼수(HTML)
st.markdown("<h2 style='text-align: center;'>🌙 내 손안의 포트폴리오</h2>", unsafe_allow_html=True)

GOOGLE_JSON_FILE = "secrets.json" 
SHEET_NAME = "MyPortfolio_DB" 

@st.cache_data(ttl=60)
def load_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_JSON_FILE, scope)
    client = gspread.authorize(creds)
    sheet_tx = client.open(SHEET_NAME).worksheet("거래내역")
    sheet_history = client.open(SHEET_NAME).worksheet("일별기록")
    
    df_tx = pd.DataFrame(sheet_tx.get_all_records())
    df_history = pd.DataFrame(sheet_history.get_all_records())
    return df_tx, df_history

df, df_history = load_data()

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

    realtime_prices, daily_changes, total_values_krw, total_costs_krw, profit_pcts, profit_amounts = [], [], [], [], [], []

    for index, row in holdings.iterrows():
        ticker = row['티커']
        currency = row['통화']
        qty = row['계산용수량']
        avg_price = row['평균매입단가']
        
        current_price, daily_change = get_market_data(ticker)
        realtime_prices.append(current_price)
        daily_changes.append(daily_change)
        
        rate = usd_krw_price if currency == "USD" else 1
        eval_krw = current_price * qty * rate 
        cost_krw = avg_price * qty * rate     
        
        total_values_krw.append(eval_krw)
        total_costs_krw.append(cost_krw)
        
        profit_amt = eval_krw - cost_krw
        profit_amounts.append(profit_amt)
        profit_pct = ((current_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0.0
        profit_pcts.append(profit_pct)

    holdings['현재가'] = realtime_prices
    holdings['평가금액(원)'] = total_values_krw
    holdings['평가손익(원)'] = profit_amounts
    holdings['수익률(%)'] = profit_pcts

    # ==========================================
    # 🌟 모바일 최적화: 총 자산 지표 (중앙 정렬)
    # ==========================================
    total_asset = sum(total_values_krw)
    total_cost = sum(total_costs_krw)
    total_profit = total_asset - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0

    st.metric(
        label="💰 총 자산 (원화 환산)", 
        value=f"{total_asset:,.0f} 원", 
        delta=f"총 평가손익: {total_profit:,.0f} 원 ({total_profit_pct:,.2f}%)"
    )
    st.markdown("---")

    # ==========================================
    # 🌟 모바일 최적화: 파이 차트 (폰트 크기 확대 & 범례 숨김)
    # ==========================================
    # 모바일은 화면이 좁으므로 컬럼을 나누지 않고 세로로 크게 배치하는 것이 더 깔끔합니다.
    st.markdown("**🥧 자산군 비중**")
    pastel_colors = px.colors.qualitative.Pastel

    asset_group = holdings.groupby('자산군')['평가금액(원)'].sum().reset_index()
    fig1 = px.pie(asset_group, values='평가금액(원)', names='자산군', hole=0.4, color_discrete_sequence=pastel_colors)
    fig1.update_traces(textposition='inside', textinfo='percent+label', textfont_size=15) # 폰트 크기 15로 확대
    fig1.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False) # 범례 숨김(공간 확보)
    st.plotly_chart(fig1, use_container_width=True)

    st.markdown("**🍩 개별 종목 비중**")
    fig2 = px.pie(holdings, values='평가금액(원)', names='종목명', color_discrete_sequence=pastel_colors)
    fig2.update_traces(textposition='inside', textinfo='percent+label', textfont_size=13, insidetextorientation='radial')
    fig2.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")

    # ==========================================
    # 🌟 모바일 최적화: 테이블 (핵심 정보만 보이게)
    # ==========================================
    st.markdown("**📋 보유 자산 상세 및 수익률**")
    
    # 모바일에서는 너무 많은 열이 있으면 가로 스크롤이 길어집니다. 핵심 열만 남깁니다.
    display_df = holdings[['종목명', '보유수량', '수익률(%)', '평가손익(원)', '평가금액(원)']].copy() if '보유수량' in holdings.columns else holdings[['종목명', '계산용수량', '수익률(%)', '평가손익(원)', '평가금액(원)']].copy()
    display_df.rename(columns={'계산용수량': '수량'}, inplace=True)

    def color_pastel(val):
        color = '#99ccff' if val < 0 else '#ff9999' if val > 0 else '#e1e1e1'
        return f'color: {color}; font-weight: bold;'

    st.dataframe(
        display_df.style
        .format({
            '수량': '{:,.1f}',
            '수익률(%)': '{:,.2f}%',
            '평가손익(원)': '{:,.0f}',
            '평가금액(원)': '{:,.0f}'
        })
        .map(color_pastel, subset=['수익률(%)', '평가손익(원)']),
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    # ==========================================
    # 🌟 시간에 따른 자산 총액
    # ==========================================
    st.markdown("**📈 자산 총액 변동 추이**")
    if not df_history.empty:
        fig3 = px.line(df_history, x='날짜', y='총자산(KRW)', markers=True, color_discrete_sequence=['#ffb6c1'])
        fig3.update_layout(margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.caption("아직 '일별기록' 시트에 데이터가 없습니다.")