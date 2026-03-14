import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. 기본 설정 ---
st.set_page_config(page_title="나만의 포트폴리오", layout="wide", page_icon="🌙")
st.markdown("<h2 style='text-align: center;'>🌙 내 손안의 포트폴리오</h2>", unsafe_allow_html=True)

# 🌟 중요: 이제 파일명이 아니라 Streamlit Secrets(비밀금고)를 직접 사용합니다.
@st.cache_data(ttl=60)
def load_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # 🔥 [수정된 부분] 파일 이름 대신 st.secrets 데이터를 딕셔너리로 변환하여 인증합니다.
    # st.secrets 자체가 dict 형태이므로 바로 전달하면 됩니다.
    try:
        creds = ServiceAccountCredentials.from_json_key(dict(st.secrets), scope)
        client = gspread.authorize(creds)
        
        # 구글 시트 연결
        SHEET_NAME = "MyPortfolio_DB" 
        sheet_tx = client.open(SHEET_NAME).worksheet("거래내역")
        sheet_history = client.open(SHEET_NAME).worksheet("일별기록")
        
        df_tx = pd.DataFrame(sheet_tx.get_all_records())
        df_history = pd.DataFrame(sheet_history.get_all_records())
        return df_tx, df_history
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame(), pd.DataFrame()

# 데이터 로드
df, df_history = load_data()

# --- 이후 실시간 가격 및 그래프 출력 코드는 이전과 동일합니다 ---
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
    st.info("아직 거래 내역이 없거나 데이터를 불러올 수 없습니다. 텔레그램 기록과 시트 권한을 확인해주세요!")
else:
    # (여기에 이전 대시보드 코드의 시각화 로직이 이어집니다)
    # 계산 로직 및 plotly 차트 출력...
    # (공간 절약을 위해 생략하지만, 기존 dashboard.py 하단부를 그대로 붙여넣으시면 됩니다)
    
    # --- 생략된 하단 로직은 이전 답변의 '모바일 최적화 코드'를 참고하세요 ---
    # 총 자산 지표, 파이 차트, 보유 자산 테이블 등등...
    # ...
    # (기존 코드를 그대로 유지하되, load_data 함수만 위와 같이 바뀐 것이 핵심입니다!)
