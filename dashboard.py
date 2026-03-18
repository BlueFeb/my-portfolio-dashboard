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
        if not ticker or not isinstance(ticker, str) or ticker == "KRW=X": 
            return ticker, pd.Series(dtype=float), None
            
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
        
        ex_date = None
        try: 
            info = stock.info
            if 'exDividendDate' in info and info['exDividendDate'] is not None:
                ed_dt = datetime.datetime.fromtimestamp(info['exDividendDate'])
                ed_str = ed_dt.strftime('%Y-%m-%d')
                
                # 💡 오직 오늘 기준 '미래' 또는 '오늘' 날짜인 경우에만 캘린더에 추가!
                kst = pytz.timezone('Asia/Seoul')
                today_str = datetime.datetime.now(kst).strftime('%Y-%m-%d')
                if ed_str >= today_str:
                    ex_date = ed_str
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

    # 🚀 [요청 반영] 가장 깔끔한 이전 버전 롤백 & 손익만 크기/색상/뱃지로 완벽 강조!
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
        <span style="display: inline-block; background-color: {profit_bg}; padding: 6px 14px; border-radius: 8px; border: 1.5px solid {profit_color};">
            <span style="font-size: 22px; font-weight: 800; color: {profit_color};">
                {sign_t}{total_profit:,.0f} 원 ({sign_t}{total_profit_pct:,.2f}%)
            </span>
        </span>
    </div>
    """, unsafe_allow_html=True)

    if target_cash >= 0 and total_asset > 0:
        asset_classes = {"주식": 0.0, "코인": 0.0, "원자재": 0.0, "채권": 0.0, "현금": 0.0}
        for _, row in holdings.iterrows():
            ac = row['자산군']
            if ac in asset_classes: asset_classes[ac] += row['평가액(원)']
            else: asset_classes["기타"] = asset_classes.get("기타", 0.0) + row['평가액(원)']
        
        rebal_data = []
        target_dict = {"주식": target_stock, "코인": target_crypto, "원자재": target_commodity, "채권": target_bond, "현금": target_cash}
        for ac, target_pct in target_dict.items():
            curr_val = asset_classes.get(ac, 0.0)
            curr_pct = (curr_val / total_asset) * 100 if total_asset > 0 else 0
            target_val = total_asset * (target_pct / 100)
            diff_val = target_val - curr_val
            action = "🟢 매수" if diff_val > 0 else "🔴 매도" if diff_val < 0 else "유지"
            action_val = abs(diff_val) if diff_val != 0 else 0.0
            rebal_data.append({"자산군": ac, "현재 비중": curr_pct, "목표 비중": target_pct, "현재액(원)": curr_val, "목표액(원)": target_val, "Action": action, "필요 금액(원)": action_val})
        rebal_df = pd.DataFrame(rebal_data)

    st.markdown("---")

    st.markdown("**📊 포트폴리오 시각화**")
    tab_chart1, tab_chart2, tab_chart3, tab_rebal = st.tabs(["🥧 자산 비중", "📈 자산 추이", "📊 실현 손익", "⚖️ 리밸런싱 계산기"])

    with tab_chart1:
        pc1, pc2 = st.columns(2)
        text_font_setting = dict(color='black', size=20, family="sans-serif")
        with pc1:
            fig1 = px.pie(holdings.groupby('자산군')['평가액(만원)'].sum().reset_index(), values='평가액(만원)', names='자산군', hole=0.4, color_discrete_sequence=pastel_colors)
            fig1.update_traces(textposition='inside', texttemplate='<b>%{label}</b><br><b>%{percent:.1%}</b>', textfont=text_font_setting)
            fig1.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig1, use_container_width=True)
        with pc2:
            holdings_positive = holdings[holdings['평가액(만원)'] > 0].copy()
            if not holdings_positive.empty:
                fig_sun = px.sunburst(holdings_positive, path=['자산군', '종목명'], values='평가액(만원)', color_discrete_sequence=pastel_colors)
                fig_sun.update_traces(textinfo='label+percent entry', textfont=dict(color='black', size=15))
                fig_sun.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig_sun, use_container_width=True)

    with tab_chart2:
        if not df_history.empty and df_history.shape[1] >= 2:
            df_history['총자산(만원)'] = pd.to_numeric(df_history[df_history.columns[1]], errors='coerce').fillna(0) / 10000
            fig_line = px.line(df_history, x='날짜', y='총자산(만원)', markers=True)
            fig_line.update_traces(line_color=line_color, marker_color=line_color)
            fig_line.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_line, use_container_width=True)

    with tab_chart3:
        if not df_pnl.empty and '실현손익(원)' in df_pnl.columns:
            df_pnl['실현손익(원)'] = pd.to_numeric(df_pnl['실현손익(원)'], errors='coerce').fillna(0)
            df_pnl['분류'] = df_pnl.apply(lambda x: x['분류'] if str(x.get('분류', '')).strip() != '' else ('배당' if x.get('매도수량', 1) == 0 else '매도'), axis=1)
            df_pnl['차트분류'] = df_pnl.apply(lambda x: f"{x['분류']} ({'해외' if x.get('통화')=='USD' else '국내'})", axis=1)
            df_pnl['실현손익_차트용(만원)'] = (df_pnl['실현손익(원)'] / 10000).fillna(0).astype(int)
            
            period = st.radio("보기 옵션", ["월별", "연별", "일별"], horizontal=True, label_visibility="collapsed")
            df_pnl['날짜'] = pd.to_datetime(df_pnl['날짜'], errors='coerce')
            df_pnl = df_pnl.dropna(subset=['날짜'])
            df_pnl['일자'], df_pnl['월'], df_pnl['연'] = df_pnl['날짜'].dt.strftime('%m-%d'), df_pnl['날짜'].dt.strftime('%Y-%m'), df_pnl['날짜'].dt.strftime('%Y')
            
            def plot_pnl_bar(data, x_col):
                color_map = {'매도 (국내)': '#FF6B6B', '매도 (해외)': '#FFA07A', '배당 (국내)': '#4DABF7', '배당 (해외)': '#51CF66'}
                fig = px.bar(data, x=x_col, y='실현손익_차트용(만원)', color='차트분류', text='실현손익_차트용(만원)', color_discrete_map=color_map)
                fig.update_traces(texttemplate='%{text:,.0f}', textposition="outside", cliponaxis=False)
                fig.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10), barmode='relative', legend_title_text='')
                st.plotly_chart(fig, use_container_width=True)

            if period == "월별": plot_pnl_bar(df_pnl.groupby(['월', '차트분류'])['실현손익_차트용(만원)'].sum().reset_index(), '월')
            elif period == "연별": plot_pnl_bar(df_pnl.groupby(['연', '차트분류'])['실현손익_차트용(만원)'].sum().reset_index(), '연')
            else: plot_pnl_bar(df_pnl.groupby(['일자', '차트분류'])['실현손익_차트용(만원)'].sum().reset_index(), '일자')
    
    with tab_rebal:
        if target_cash >= 0 and total_asset > 0:
            st.markdown("<div style='font-size: 13px; color: gray; margin-bottom: 10px;'>💡 사이드바에서 설정한 목표 비중으로 맞추기 위한 매매 지침입니다.</div>", unsafe_allow_html=True)
            def style_rebal(val):
                if isinstance(val, str):
                    if "매수" in val: return f'color: {profit_up_color}; font-weight: bold;'
                    elif "매도" in val: return f'color: {profit_down_color}; font-weight: bold;'
                return ''
            st.dataframe(
                rebal_df.style
                .set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '14px', 'text-align': 'center'})
                .format({'현재 비중': '{:.1f}%', '목표 비중': '{:.1f}%', '현재액(원)': '{:,.0f}', '목표액(원)': '{:,.0f}', '필요 금액(원)': '{:,.0f}'})
                .map(style_rebal, subset=['Action']),
                use_container_width=True, hide_index=True
            )
        else:
            st.caption("좌측 ⚙️ 사이드바를 열어 목표 자산 비중 수치를 올바르게 입력해 주세요.")

    st.markdown("---")

    st.markdown("**📋 상세 데이터**")
    tab_data1, tab_data3 = st.tabs(["📊 자산 상세", "🔮 향후 배당 & 이벤트 캘린더"])

    with tab_data1:
        display_df = holdings[['종목명', '계산용수량', '수익률(%)', '평가액(원)', '손익(원)']].copy()
        display_df.rename(columns={'계산용수량': '수량', '수익률(%)': '수익률', '평가액(원)': '평가액', '손익(원)': '손익'}, inplace=True)
        def style_table(val):
            if isinstance(val, (int, float)):
                color = profit_up_color if val > 0 else profit_down_color if val < 0 else text_color
                return f'color: {color}; font-weight: bold;'
            return ''
        st.dataframe(
            display_df.style
            .set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '14px'})
            .format({'수량': '{:,.1f}', '수익률': '{:,.2f}%', '평가액': '{:,.0f}', '손익': '{:,.0f}'})
            .map(style_table, subset=['수익률', '손익']),
            use_container_width=True, hide_index=True
        )
            
    with tab_data3:
        kst = pytz.timezone('Asia/Seoul')
        now = datetime.datetime.now(kst)
        today_str = now.strftime('%Y-%m-%d')
        next_6_months = [(now.year + (now.month + i - 1) // 12, (now.month + i - 1) % 12 + 1) for i in range(1, 7)]
            
        expected_records, calendar_records = [], []
        total_6_months_krw = 0.0
        
        with st.spinner("데이터를 스캔 중입니다... (최초 1회만 약간의 로딩이 발생합니다)"):
            unique_tickers_for_div = tuple(holdings['티커'].unique())
            all_div_history = get_all_dividend_history(unique_tickers_for_div)

            for _, row in holdings.iterrows():
                ticker, name, qty, curr = row['티커'], row['종목명'], row['계산용수량'], row['통화']
                div_info = all_div_history.get(ticker, {"divs": pd.Series(dtype=float), "ex_date": None})
                divs, ex_date = div_info["divs"], div_info["ex_date"]
                
                if divs.empty: continue
                is_monthly = len(divs) >= 18
                
                for y, m in next_6_months:
                    dps = 0.0
                    if is_monthly: dps = float(divs.iloc[-1]) 
                    else:
                        month_divs = divs[divs.index.month == m]
                        if not month_divs.empty: dps = float(month_divs.iloc[-1])
                            
                    if dps > 0:
                        expected_div = dps * qty
                        rate = usd_krw_price if curr == 'USD' else 1.0
                        expected_krw = expected_div * rate
                        total_6_months_krw += expected_krw
                        expected_records.append({'연월': f"{y}년 {m:02d}월", '종목명': name, '수량': qty, '통화': curr, '예상 주당배당금': dps, '예상 배당금': expected_div, '환산 예상금액(원)': expected_krw})

        # 🚀 [요청 반영] 미래 이벤트 캘린더 안내 및 UI 처리
        st.markdown("**📅 [예정] 주요 종목 이벤트 캘린더 (오늘 이후)**")
        if calendar_records:
            cal_df = pd.DataFrame(calendar_records).sort_values("날짜", ascending=True)
            st.dataframe(cal_df.style.set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '13px'}), use_container_width=True, hide_index=True)
        else:
            st.info("📌 현재 야후 파이낸스 기준으로 공식 확정/발표된 다가오는 이벤트(배당락일 등) 일정이 없습니다.\n(기업은 보통 배당락일 2~4주 전에 공식 날짜를 발표합니다.)")
        st.markdown("---")

        if expected_records:
            next_div_df = pd.DataFrame(expected_records)
            st.markdown(f"**📈 향후 6개월 누적 예상 배당금:** 약 {int(total_6_months_krw):,.0f} 원 <span style='font-size:12px; color:gray;'>(오늘 환율 적용)</span>", unsafe_allow_html=True)
            fig_next = px.bar(next_div_df, x='연월', y='환산 예상금액(원)', color='종목명', hover_data={'예상 배당금': ':.2f', '통화': True}, color_discrete_sequence=pastel_colors)
            fig_next.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=20, b=10, l=10, r=10), barmode='stack')
            st.plotly_chart(fig_next, use_container_width=True)
            st.caption("※ 과거 배당 패턴을 분석한 결과이며, 데이터 제공 지연으로 누락될 수 있습니다.")

if auto_refresh:
    time.sleep(30)
    st.rerun()
