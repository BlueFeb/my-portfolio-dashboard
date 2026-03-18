import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials
import json
import datetime
import pytz
import requests
import re
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 기본 설정 ---
st.set_page_config(page_title="내 포트폴리오", layout="wide", page_icon="💎")

is_dark_mode = st.sidebar.toggle("🌙 다크 모드 켜기", value=True)
auto_refresh = st.sidebar.toggle("🔄 실시간 자동 새로고침 (30초)", value=False)
st.sidebar.caption("자동 새로고침을 켜면 30초마다 시세를, 60초마다 총자산을 업데이트합니다.")

# 🚀 5대 자산군 리밸런싱 사이드바 (현금 100% 자동 맞춤)
st.sidebar.markdown("---")
st.sidebar.markdown("⚖️ **목표 자산 비중 설정 (%)**")
target_stock = st.sidebar.number_input("📈 주식 비중 (%)", min_value=0, max_value=100, value=50, step=1)
target_crypto = st.sidebar.number_input("🪙 코인 비중 (%)", min_value=0, max_value=100, value=10, step=1)
target_commodity = st.sidebar.number_input("🛢️ 원자재 비중 (%)", min_value=0, max_value=100, value=10, step=1)
target_bond = st.sidebar.number_input("📉 채권 비중 (%)", min_value=0, max_value=100, value=20, step=1)

target_cash = 100 - (target_stock + target_crypto + target_commodity + target_bond)

if target_cash < 0:
    st.sidebar.error(f"⚠️ 합계가 100%를 초과했습니다! (초과분: {abs(target_cash)}%)")
else:
    st.sidebar.info(f"💵 현금 비중: {target_cash}%\n(합계 100% 자동 계산)")

st.markdown("<h2 style='margin-top: -15px;'>💎 내 포트폴리오</h2>", unsafe_allow_html=True)

if is_dark_mode:
    bg_color, text_color = "#1E1E1E", "#F0F2F6"
    df_bg, df_text = "#2A2A2A", "#FFFFFF"
    border_color = "#444444"
    chart_template = "plotly_dark"
    pastel_colors = ['#FFB3BA', '#FFDFBA', '#FFFFBA', '#BAFFC9', '#BAE1FF', '#E8BAFF', '#FFC1C1', '#D6A2E8']
    line_color = '#FF99CC'
    profit_up_color, profit_down_color = '#FF9999', '#99CCFF' 
    p_up_bg, p_dn_bg = "rgba(255, 153, 153, 0.12)", "rgba(153, 204, 255, 0.12)"
    gold_highlight = '#FFD700' 
else:
    bg_color, text_color = "#F8F9FA", "#212529"
    df_bg, df_text = "#FFFFFF", "#212529"
    border_color = "#E0E0E0"
    chart_template = "plotly_white"
    pastel_colors = ['#FF8A98', '#FFB677', '#E5E570', '#85E39C', '#8AC4FF', '#C785FF', '#FF9B9B', '#C274D8']
    line_color = '#FF6699'
    profit_up_color, profit_down_color = '#E63946', '#457B9D'
    p_up_bg, p_dn_bg = "rgba(230, 57, 70, 0.08)", "rgba(69, 123, 157, 0.08)"
    gold_highlight = '#B8860B'

st.markdown(f"""
    <style>
    .stApp {{ background-color: {bg_color}; }}
    .stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp label, .stApp span {{
        color: {text_color} !important;
    }}
    [data-testid="stSidebar"] {{ background-color: {bg_color} !important; border-right: 1px solid {border_color}; }}
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label, [data-testid="stSidebar"] div {{
        color: {text_color} !important;
    }}
    [data-testid="stHeader"] {{ background-color: rgba(0,0,0,0); }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 2px; }}
    .stTabs [data-baseweb="tab"] {{ padding-top: 10px; padding-bottom: 10px; }}
    div.element-container:has(.row-widget-hook) + div[data-testid="stHorizontalBlock"] {{
        flex-wrap: nowrap !important;
        align-items: center !important;
    }}
    div.element-container:has(.row-widget-hook) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(1) {{ width: 75% !important; flex: 1 1 75% !important; min-width: 75% !important; }}
    div.element-container:has(.row-widget-hook) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2) {{ width: 25% !important; flex: 1 1 25% !important; min-width: 25% !important; }}
    [data-testid="stExpander"] {{ margin-top: -10px; }}
    </style>
""", unsafe_allow_html=True)

INDICATORS_CONFIG = {
    "🇰🇷 코스피": {"ticker": "KOSPI", "src": "naver_index", "prefix": "", "suffix": "", "inverse": False},
    "🇰🇷 코스닥": {"ticker": "KOSDAQ", "src": "naver_index", "prefix": "", "suffix": "", "inverse": False},
    "🇰🇷 삼성전자": {"ticker": "005930", "src": "naver_stock", "prefix": "", "suffix": "원", "inverse": False},
    "🇰🇷 SK하이닉스": {"ticker": "000660", "src": "naver_stock", "prefix": "", "suffix": "원", "inverse": False},
    "🇺🇸 S&P 500 선물": {"ticker": "ES=F", "src": "yahoo", "prefix": "", "suffix": "", "inverse": False},
    "🇺🇸 US Tech 100 선물": {"ticker": "NQ=F", "src": "yahoo", "prefix": "", "suffix": "", "inverse": False},
    "🇺🇸 다우존스 선물": {"ticker": "YM=F", "src": "yahoo", "prefix": "", "suffix": "", "inverse": False},
    "💾 반도체 (SOX)": {"ticker": "^SOX", "src": "yahoo", "prefix": "", "suffix": "", "inverse": False},
    "💱 원/달러": {"ticker": "KRW=X", "src": "yahoo", "prefix": "", "suffix": "원", "inverse": False},
    "💱 원/엔 (100엔)": {"ticker": "JPYKRW=X", "src": "yahoo", "prefix": "", "suffix": "원", "inverse": False},
    "💎 비트코인": {"ticker": "BTC-USD", "src": "yahoo", "prefix": "$", "suffix": "", "inverse": False},
    "💎 이더리움": {"ticker": "ETH-USD", "src": "yahoo", "prefix": "$", "suffix": "", "inverse": False},
    "🛢️ WTI 원유": {"ticker": "CL=F", "src": "yahoo", "prefix": "$", "suffix": "", "inverse": False},
    "🥇 금 선물": {"ticker": "GC=F", "src": "yahoo", "prefix": "$", "suffix": "", "inverse": False},
    "📈 10년물 국채 금리": {"ticker": "^TNX", "src": "yahoo", "prefix": "", "suffix": "%", "inverse": True}, 
    "🥶 미국 VIX": {"ticker": "^VIX", "src": "yahoo", "prefix": "", "suffix": "", "inverse": True},
    "🥶 한국 VKOSPI": {"ticker": "^VKOSPI", "src": "naver_vkospi", "prefix": "", "suffix": "", "inverse": True},
}

SETTINGS_FILE = "macro_settings.json"

def load_macro_settings():
    default_inds = ["🇰🇷 삼성전자", "🇰🇷 SK하이닉스", "🇰🇷 코스피", "🇺🇸 US Tech 100 선물", "💱 원/달러", "💎 비트코인"]
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                saved = data.get("indicators", [])
                valid_saved = [x for x in saved if x in INDICATORS_CONFIG]
                if valid_saved: return valid_saved
    except: pass
    return default_inds

def save_macro_settings(selected):
    try:
        with open(SETTINGS_FILE, "w") as f: json.dump({"indicators": selected}, f)
    except: pass

def fetch_single_macro(name, info):
    try:
        if info["src"] == "naver_index":
            res = requests.get(f"https://polling.finance.naver.com/api/realtime/domestic/index/{info['ticker']}", timeout=3)
            data = res.json()['datas'][0]
            curr, change_pct = float(data['closePrice'].replace(',', '')), float(data['fluctuationsRatio'])
            change_val = float(data['compareToPreviousClosePrice'].replace(',', ''))
            if change_pct < 0: change_val = -change_val
            return name, {"current": curr, "change_pct": change_pct, "change_val": change_val}
        elif info["src"] == "naver_stock":
            res = requests.get(f"https://polling.finance.naver.com/api/realtime/domestic/stock/{info['ticker']}", timeout=3)
            data = res.json()['datas'][0]
            curr, change_pct = float(data['closePrice'].replace(',', '')), float(data['fluctuationsRatio'])
            change_val = float(data['compareToPreviousClosePrice'].replace(',', ''))
            if change_pct < 0: change_val = -change_val
            return name, {"current": curr, "change_pct": change_pct, "change_val": change_val}
        elif info["src"] == "naver_vkospi":
            res = requests.get("https://finance.naver.com/sise/sise_index.naver?code=VIXKOSPI", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            curr_match = re.search(r'<em id="now_value">([0-9.]+)</em>', res.text)
            if curr_match:
                curr = float(curr_match.group(1))
                chg_match = re.search(r'<span id="change_value_and_rate">[^\d]*([0-9.]+)[^\d]*<span', res.text)
                change_val = float(chg_match.group(1)) if chg_match else 0.0
                if "nv01" in res.text: change_val = -change_val
                prev = curr - change_val
                return name, {"current": curr, "change_pct": (change_val / prev) * 100 if prev > 0 else 0.0, "change_val": change_val}
            return name, None
        elif info["src"] == "yahoo":
            stock = yf.Ticker(info["ticker"])
            hist = stock.history(period="5d").dropna(subset=['Close'])
            if len(hist) >= 2:
                curr, prev = float(hist['Close'].iloc[-1]), float(hist['Close'].iloc[-2])
                if info["ticker"] == "JPYKRW=X": curr *= 100; prev *= 100
                change_val = curr - prev
                return name, {"current": curr, "change_pct": (change_val / prev) * 100 if prev != 0 else 0.0, "change_val": change_val}
            return name, None
    except: return name, None

@st.cache_data(ttl=30) 
def get_macro_indicators(selected_names_tuple):
    results = {}
    if not selected_names_tuple: return results
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_single_macro, name, INDICATORS_CONFIG[name]): name for name in selected_names_tuple}
        for future in as_completed(futures):
            name, res = future.result()
            results[name] = res
    return results

@st.cache_data(ttl=60)
def load_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = json.loads(st.secrets["google_credentials"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        SHEET_NAME = "MyPortfolio_DB" 
        df_tx = pd.DataFrame(client.open(SHEET_NAME).worksheet("거래내역").get_all_records())
        df_history = pd.DataFrame(client.open(SHEET_NAME).worksheet("일별기록").get_all_records())
        try: df_pnl = pd.DataFrame(client.open(SHEET_NAME).worksheet("실현손익").get_all_records())
        except: df_pnl = pd.DataFrame()
        return df_tx, df_history, df_pnl
    except Exception as e:
        st.error(f"⚠️ 구글 시트 연결 오류: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_raw, df_history_raw, df_pnl_raw = load_data()
df = df_raw.copy()
df_history = df_history_raw.copy()
df_pnl = df_pnl_raw.copy()

def fetch_single_price(ticker):
    try:
        if not ticker or not isinstance(ticker, str): return ticker, 0.0, 0.0
        if ticker.endswith('.KS') or ticker.endswith('.KQ'):
            code = ticker.split('.')[0]
            res = requests.get(f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}", timeout=3)
            data = res.json()['datas'][0]
            return ticker, float(data['closePrice'].replace(',', '')), float(data['fluctuationsRatio'])
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d").dropna(subset=['Close'])
        if len(hist) >= 2: return ticker, float(hist['Close'].iloc[-1]), ((float(hist['Close'].iloc[-1]) - float(hist['Close'].iloc[-2])) / float(hist['Close'].iloc[-2])) * 100
        elif len(hist) == 1: return ticker, float(hist['Close'].iloc[0]), 0.0
        return ticker, 0.0, 0.0
    except: return ticker, 0.0, 0.0

@st.cache_data(ttl=30)
def get_all_market_data(tickers_tuple):
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_single_price, t): t for t in tickers_tuple}
        for future in as_completed(futures):
            ticker, price, change = future.result()
            results[ticker] = (price, change)
    return results

def fetch_single_dividend(ticker):
    try:
        if not ticker or not isinstance(ticker, str): return ticker, pd.Series(dtype=float), None
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
        ex_date = None
        try: 
            info = stock.info
            if 'exDividendDate' in info and info['exDividendDate'] is not None:
                ex_date = datetime.datetime.fromtimestamp(info['exDividendDate']).strftime('%Y-%m-%d')
        except: pass
        divs = hist[hist['Dividends'] > 0]['Dividends'] if 'Dividends' in hist.columns else pd.Series(dtype=float)
        return ticker, divs, ex_date
    except: return ticker, pd.Series(dtype=float), None

@st.cache_data(ttl=86400) 
def get_all_dividend_history(tickers_tuple):
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_single_dividend, t): t for t in tickers_tuple}
        for future in as_completed(futures):
            ticker, divs, ex_date = future.result()
            results[ticker] = {"divs": divs, "ex_date": ex_date}
    return results

st.markdown('<div class="row-widget-hook"></div>', unsafe_allow_html=True)
col_title, col_setting = st.columns([7, 3])

if "macro_selector" not in st.session_state: st.session_state.macro_selector = load_macro_settings()
def on_macro_change(): save_macro_settings(st.session_state.macro_selector)

with col_title:
    st.markdown("<div style='font-size: 16px; font-weight: bold; margin-top: 5px;'>🌐 글로벌 매크로 전광판</div>", unsafe_allow_html=True)

with col_setting:
    try:
        with st.popover("⚙️ 설정", use_container_width=True):
            st.multiselect("최대 9개 선택", options=list(INDICATORS_CONFIG.keys()), key="macro_selector", max_selections=9, on_change=on_macro_change, label_visibility="collapsed")
    except AttributeError:
        with st.expander("⚙️ 설정"):
            st.multiselect("최대 9개 선택", options=list(INDICATORS_CONFIG.keys()), key="macro_selector", max_selections=9, on_change=on_macro_change, label_visibility="collapsed")

if not st.session_state.macro_selector: st.caption("선택된 지표가 없습니다. 위의 설정 창을 열어 지표를 추가해 주세요.")
else:
    macro_data = get_macro_indicators(tuple(st.session_state.macro_selector))
    html_cards = '<div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; margin-bottom: 20px;">'
    for name in st.session_state.macro_selector:
        data = macro_data.get(name)
        info = INDICATORS_CONFIG[name]
        prefix, suffix = info["prefix"], info["suffix"]
        
        if data is not None:
            curr, d_val, d_pct = data["current"], data["change_val"], data["change_pct"]
            color = profit_up_color if (d_val > 0 and not info["inverse"]) or (d_val < 0 and info["inverse"]) else profit_down_color if d_val != 0 else text_color
            format_str = ",.0f" if info["src"] == "naver_stock" else ",.1f" if "비트코인" in name else ",.2f"
            html_cards += f'<div style="flex: 1 1 calc(25% - 8px); min-width: 105px; background-color: {df_bg}; border: 1px solid {border_color}; border-radius: 8px; padding: 10px 5px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">'
            html_cards += f'<div style="font-size: 11px; color: gray; margin-bottom: 4px;">{name}</div>'
            html_cards += f'<div style="font-size: 15px; font-weight: bold; color: {text_color}; margin-bottom: 2px;">{prefix}{curr:{format_str}}{suffix}</div>'
            html_cards += f'<div style="font-size: 11px; font-weight: bold; color: {color};">{d_val:+,.2f} ({d_pct:+.2f}%)</div></div>'
        else:
            html_cards += f'<div style="flex: 1 1 calc(25% - 8px); min-width: 105px; background-color: {df_bg}; border: 1px solid {border_color}; border-radius: 8px; padding: 10px 5px; text-align: center; opacity: 0.6;"><div style="font-size: 11px; color: gray; margin-bottom: 4px;">{name}</div><div style="font-size: 13px; font-weight: bold; color: gray; margin-bottom: 2px;">데이터 지연</div><div style="font-size: 11px; color: gray;">-</div></div>'
    html_cards += '</div>'
    st.markdown(html_cards, unsafe_allow_html=True)
st.markdown("---")

if df.empty:
    st.info("아직 거래 내역이 없습니다. 텔레그램 봇으로 거래를 기록해 주세요.")
else:
    for col in ['수량', '거래단가', '거래종류', '자산군', '종목명', '티커', '통화']:
        if col not in df.columns: df[col] = 0 if col in ['수량', '거래단가'] else ""
    df['수량'] = pd.to_numeric(df['수량'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['거래단가'] = pd.to_numeric(df['거래단가'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['계산용수량'] = df.apply(lambda x: x['수량'] if str(x['거래종류']).strip() == '매수' else -x['수량'], axis=1)
    
    holdings = df.groupby(['자산군', '종목명', '티커', '통화'])['계산용수량'].sum().reset_index()
    holdings = holdings[holdings['계산용수량'] > 0].copy()
    holdings['자산군'] = holdings['자산군'].replace('', '주식').fillna('주식') 
    holdings['종목명'] = holdings['종목명'].replace('', '알수없음').fillna('알수없음')

    buy_df = df[df['거래종류'] == '매수'].copy()
    buy_df['결제금액'] = buy_df['수량'] * buy_df['거래단가']
    avg_cost_df = buy_df.groupby(['종목명', '티커'])[['결제금액', '수량']].sum().reset_index()
    avg_cost_df['평균매입단가'] = (avg_cost_df['결제금액'] / avg_cost_df['수량']).replace([np.inf, -np.inf], 0).fillna(0)
    
    holdings = pd.merge(holdings, avg_cost_df[['종목명', '티커', '평균매입단가']], on=['종목명', '티커'], how='left')
    holdings['평균매입단가'] = holdings['평균매입단가'].fillna(0)

    unique_tickers = list(holdings['티커'].unique())
    if "KRW=X" not in unique_tickers: unique_tickers.append("KRW=X")
    market_data_dict = get_all_market_data(tuple(unique_tickers))

    usd_krw_price = market_data_dict.get("KRW=X", (1450.0, 0.0))[0]
    if usd_krw_price <= 0.0: usd_krw_price = 1450.0

    realtime_prices, total_values_krw, total_costs_krw, profit_pcts, profit_amounts = [], [], [], [], []
    for index, row in holdings.iterrows():
        current_price, _ = market_data_dict.get(row['티커'], (0.0, 0.0))
        realtime_prices.append(current_price)
        rate = usd_krw_price if row['통화'] == "USD" else 1
        eval_krw = current_price * row['계산용수량'] * rate 
        cost_krw = row['평균매입단가'] * row['계산용수량'] * rate     
        
        total_values_krw.append(eval_krw)
        total_costs_krw.append(cost_krw)
        profit_amounts.append(eval_krw - cost_krw)
        profit_pcts.append(((current_price - row['평균매입단가']) / row['평균매입단가'] * 100) if row['평균매입단가'] > 0 else 0.0)

    holdings['평가액(원)'] = total_values_krw
    holdings['손익(원)'] = profit_amounts
    holdings['수익률(%)'] = profit_pcts
    holdings['평가액(만원)'] = (pd.Series(total_values_krw) / 10000).fillna(0).astype(int)

    total_asset = sum(total_values_krw)
    total_cost = sum(total_costs_krw)
    total_profit = total_asset - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0

    # 🚀 [업데이트] 이전 폼으로 복귀 & 손익 부분 뱃지(Badge) 형태 강조
    if total_profit > 0:
        profit_color = profit_up_color
        profit_bg = p_up_bg
    elif total_profit < 0:
        profit_color = profit_down_color
        profit_bg = p_dn_bg
    else:
        profit_color = text_color
        profit_bg = "transparent"
        
    sign_t = "+" if total_profit > 0 else ""

    st.markdown(f"""
    <div style="padding: 10px 0px 20px 0px;">
        <p style="font-size: 15px; color: gray; margin-bottom: 0px; font-weight: 600;">💰 총 자산 (원)</p>
        <p style="font-size: 40px; font-weight: 800; margin-top: 0px; margin-bottom: 12px; color: {text_color}; letter-spacing: -0.5px;">{total_asset:,.0f}</p>
        <span style="
