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

SIDEBAR_SETTINGS_FILE = "sidebar_settings.json"

def load_sidebar_settings():
    defaults = {
        "dark_mode": True, 
        "auto_refresh": False,
        "stock": 50, 
        "crypto": 10, 
        "commodity": 10, 
        "bond": 20, 
        "show_drawdown": False
    }
    try:
        if os.path.exists(SIDEBAR_SETTINGS_FILE):
            with open(SIDEBAR_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
    except: pass
    return defaults

def save_sidebar_settings():
    try:
        with open(SIDEBAR_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "dark_mode": st.session_state.dark_mode,
                "auto_refresh": st.session_state.auto_refresh,
                "stock": st.session_state.target_stock,
                "crypto": st.session_state.target_crypto,
                "commodity": st.session_state.target_commodity,
                "bond": st.session_state.target_bond,
                "show_drawdown": st.session_state.show_drawdown
            }, f, ensure_ascii=False)
    except: pass

ss = load_sidebar_settings()

is_dark_mode = st.sidebar.toggle("🌙 다크 모드 켜기", value=ss["dark_mode"], key="dark_mode", on_change=save_sidebar_settings)
auto_refresh = st.sidebar.toggle("🔄 실시간 자동 새로고침 (30초)", value=ss["auto_refresh"], key="auto_refresh", on_change=save_sidebar_settings)
st.sidebar.caption("자동 새로고침을 켜면 30초마다 시세를, 60초마다 총자산을 업데이트합니다.")

st.sidebar.markdown("---")
st.sidebar.markdown("⚖️ **목표 자산 비중 설정 (%)**")
target_stock = st.sidebar.number_input("📈 주식 비중 (%)", min_value=0, max_value=100, value=ss["stock"], step=1, key="target_stock", on_change=save_sidebar_settings)
target_crypto = st.sidebar.number_input("🪙 코인 비중 (%)", min_value=0, max_value=100, value=ss["crypto"], step=1, key="target_crypto", on_change=save_sidebar_settings)
target_commodity = st.sidebar.number_input("🛢️ 원자재 비중 (%)", min_value=0, max_value=100, value=ss["commodity"], step=1, key="target_commodity", on_change=save_sidebar_settings)
target_bond = st.sidebar.number_input("📉 채권 비중 (%)", min_value=0, max_value=100, value=ss["bond"], step=1, key="target_bond", on_change=save_sidebar_settings)

target_cash = 100 - (target_stock + target_crypto + target_commodity + target_bond)

if target_cash < 0:
    st.sidebar.error(f"⚠️ 합계가 100%를 초과했습니다! (초과분: {abs(target_cash)}%)")
else:
    st.sidebar.info(f"💵 현금 비중: {target_cash}%\n(합계 100% 자동 계산)")

st.sidebar.markdown("---")
show_drawdown_table = st.sidebar.toggle("📊 주요 지수 ETF 낙폭 기준표 보기", value=ss["show_drawdown"], key="show_drawdown", on_change=save_sidebar_settings)

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
    .stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp label, .stApp span {{ color: {text_color} !important; }}
    [data-testid="stSidebar"] {{ background-color: {bg_color} !important; border-right: 1px solid {border_color}; }}
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label, [data-testid="stSidebar"] div {{ color: {text_color} !important; }}
    [data-testid="stHeader"] {{ background-color: rgba(0,0,0,0); }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 2px; }}
    .stTabs [data-baseweb="tab"] {{ padding-top: 10px; padding-bottom: 10px; }}
    div.element-container:has(.row-widget-hook) + div[data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap !important; align-items: center !important; }}
    div.element-container:has(.row-widget-hook) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(1) {{ width: 75% !important; flex: 1 1 75% !important; min-width: 75% !important; }}
    div.element-container:has(.row-widget-hook) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2) {{ width: 25% !important; flex: 1 1 25% !important; min-width: 25% !important; }}
    [data-testid="stExpander"] {{ margin-top: -10px; }}
    </style>
""", unsafe_allow_html=True)

# ============================================================
# ⚡ 속도 최적화 핵심: 적응형 소스 선택 + 배치 API + 커넥션 풀링
# ============================================================

# 🔧 requests.Session으로 커넥션 재사용 (TCP handshake 절감)
_naver_session = requests.Session()
_naver_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Referer': 'https://finance.naver.com/',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
})

_yahoo_session = requests.Session()
_yahoo_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
})

# 🔧 적응형 소스 선택: 어떤 API가 살아있는지 기억
SOURCE_STATUS_FILE = "source_status.json"

def _load_source_status():
    """마지막으로 성공한 소스를 기억 (앱 재시작 시에도 유지)"""
    defaults = {"naver_ok": True, "naver_legacy_ok": True, "yahoo_v8_ok": True, "last_check": 0}
    try:
        if os.path.exists(SOURCE_STATUS_FILE):
            with open(SOURCE_STATUS_FILE, "r") as f:
                data = json.load(f)
                defaults.update(data)
    except: pass
    return defaults

def _save_source_status(status):
    try:
        status["last_check"] = time.time()
        with open(SOURCE_STATUS_FILE, "w") as f:
            json.dump(status, f)
    except: pass

# 세션 레벨 캐시 (st.session_state)
if "_src_status" not in st.session_state:
    st.session_state._src_status = _load_source_status()

_src = st.session_state._src_status

# 5분마다 죽은 소스 재시도
if time.time() - _src.get("last_check", 0) > 300:
    _src["naver_ok"] = True
    _src["naver_legacy_ok"] = True
    _src["yahoo_v8_ok"] = True


YAHOO_FALLBACK_MAP = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "005930": "005930.KS",
    "000660": "000660.KS",
}

INDICATORS_CONFIG = {
    "🇰🇷 코스피": {"ticker": "KOSPI", "src": "naver_index", "prefix": "", "suffix": ""},
    "🇰🇷 코스닥": {"ticker": "KOSDAQ", "src": "naver_index", "prefix": "", "suffix": ""},
    "🇰🇷 삼성전자": {"ticker": "005930", "src": "naver_stock", "prefix": "", "suffix": "원"},
    "🇰🇷 SK하이닉스": {"ticker": "000660", "src": "naver_stock", "prefix": "", "suffix": "원"},
    "🇺🇸 S&P 500 선물": {"ticker": "ES=F", "src": "yahoo", "prefix": "", "suffix": ""},
    "🇺🇸 US Tech 100 선물": {"ticker": "NQ=F", "src": "yahoo", "prefix": "", "suffix": ""},
    "🇺🇸 다우존스 선물": {"ticker": "YM=F", "src": "yahoo", "prefix": "", "suffix": ""},
    "💾 반도체 (SOX)": {"ticker": "^SOX", "src": "yahoo", "prefix": "", "suffix": ""},
    "💱 원/달러": {"ticker": "KRW=X", "src": "yahoo", "prefix": "", "suffix": "원"},
    "💱 원/엔 (100엔)": {"ticker": "JPYKRW=X", "src": "yahoo", "prefix": "", "suffix": "원"},
    "💎 비트코인": {"ticker": "BTC-USD", "src": "yahoo", "prefix": "$", "suffix": ""},
    "💎 이더리움": {"ticker": "ETH-USD", "src": "yahoo", "prefix": "$", "suffix": ""},
    "🛢️ WTI 원유": {"ticker": "CL=F", "src": "yahoo", "prefix": "$", "suffix": ""},
    "🥇 금 선물": {"ticker": "GC=F", "src": "yahoo", "prefix": "$", "suffix": ""},
    "📈 10년물 국채 금리": {"ticker": "^TNX", "src": "yahoo", "prefix": "", "suffix": "%"}, 
    "🥶 미국 VIX": {"ticker": "^VIX", "src": "yahoo", "prefix": "", "suffix": ""},
    "🥶 한국 VKOSPI": {"ticker": "^VKOSPI", "src": "naver_vkospi", "prefix": "", "suffix": ""},
}

MACRO_SETTINGS_FILE = "macro_settings.json"

def load_macro_settings():
    default_inds = ["🇰🇷 삼성전자", "🇰🇷 SK하이닉스", "🇰🇷 코스피", "🇺🇸 US Tech 100 선물", "💱 원/달러", "💎 비트코인"]
    try:
        if os.path.exists(MACRO_SETTINGS_FILE):
            with open(MACRO_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                saved = data.get("indicators", [])
                valid_saved = [x for x in saved if x in INDICATORS_CONFIG]
                if valid_saved: return valid_saved
    except: pass
    return default_inds

def save_macro_settings(selected):
    try:
        with open(MACRO_SETTINGS_FILE, "w", encoding="utf-8") as f: 
            json.dump({"indicators": selected}, f, ensure_ascii=False)
    except: pass


# ============================================================
# ⚡ Yahoo Finance 배치 API — 여러 종목을 1번의 HTTP 호출로
# ============================================================

def _yahoo_batch_quotes(tickers, timeout=4):
    """Yahoo v8 API로 여러 종목 한 번에 조회 — HTTP 1회"""
    if not tickers:
        return {}
    symbols = ",".join(tickers)
    url = f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
    try:
        res = _yahoo_session.get(url, timeout=timeout)
        res.raise_for_status()
        data = res.json()
        results = {}
        for q in data.get("quoteResponse", {}).get("result", []):
            sym = q["symbol"]
            curr = float(q.get("regularMarketPrice", 0))
            prev = float(q.get("regularMarketPreviousClose", 0) or q.get("previousClose", 0))
            results[sym] = (curr, prev)
        return results
    except Exception:
        return {}

def _yahoo_batch_chart(tickers, timeout=4):
    """Yahoo v8 chart API 개별 조회 폴백 (배치 실패 시)"""
    results = {}
    def _fetch_one(t):
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{t}?range=2d&interval=1d"
            res = _yahoo_session.get(url, timeout=timeout)
            res.raise_for_status()
            meta = res.json()['chart']['result'][0]['meta']
            curr = float(meta['regularMarketPrice'])
            prev = float(meta['chartPreviousClose'])
            return t, (curr, prev)
        except:
            return t, None

    with ThreadPoolExecutor(max_workers=min(len(tickers), 10)) as ex:
        for t, val in ex.map(lambda t: _fetch_one(t), tickers):
            if val:
                results[t] = val
    return results


# ============================================================
# ⚡ 네이버 금융 — 타임아웃 축소 + 즉시 폴백
# ============================================================

def _naver_stock_fast(code):
    """네이버 개별종목 — 타임아웃 1.5초"""
    url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
    res = _naver_session.get(url, timeout=1.5)
    res.raise_for_status()
    d = res.json()['datas'][0]
    curr = float(d['closePrice'].replace(',', ''))
    cpct = float(d['fluctuationsRatio'])
    cval = abs(float(str(d['compareToPreviousClosePrice']).replace(',', '')))
    if cpct < 0: cval = -cval
    return curr, cpct, cval

def _naver_index_fast(code):
    """네이버 지수 — 타임아웃 1.5초"""
    url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
    res = _naver_session.get(url, timeout=1.5)
    res.raise_for_status()
    d = res.json()['datas'][0]
    curr = float(d['closePrice'].replace(',', ''))
    cpct = float(d['fluctuationsRatio'])
    cval = abs(float(str(d['compareToPreviousClosePrice']).replace(',', '')))
    if cpct < 0: cval = -cval
    return curr, cpct, cval

def _naver_legacy_fast(code, svc="SERVICE_INDEX"):
    """네이버 레거시 — 타임아웃 1.5초"""
    url = f"https://polling.finance.naver.com/api/realtime?query={svc}:{code}"
    res = _naver_session.get(url, timeout=1.5)
    res.raise_for_status()
    areas = res.json()['result'].get('areas', [])
    if areas and areas[0].get('datas'):
        d = areas[0]['datas'][0]
        curr = float(str(d.get('nv', d.get('closePrice', '0'))).replace(',', ''))
        cval = float(str(d.get('cv', d.get('compareToPreviousClosePrice', '0'))).replace(',', ''))
        cpct = float(str(d.get('cr', d.get('fluctuationsRatio', '0'))).replace(',', ''))
        return curr, cpct, cval
    raise ValueError("empty")


# ============================================================
# ⚡ 통합 시세 조회 — 적응형 + 배치
# ============================================================

def _fetch_kr_adaptive(code, is_index=False):
    """한국 종목/지수 적응형 조회: 살아있는 소스만 시도"""
    # 네이버 신규 API
    if _src.get("naver_ok", True):
        try:
            fn = _naver_index_fast if is_index else _naver_stock_fast
            return fn(code)
        except Exception:
            _src["naver_ok"] = False

    # 네이버 레거시 API
    if _src.get("naver_legacy_ok", True):
        try:
            svc = "SERVICE_INDEX" if is_index else "SERVICE_ITEM"
            return _naver_legacy_fast(code, svc)
        except Exception:
            _src["naver_legacy_ok"] = False

    # Yahoo Finance 폴백
    yahoo_ticker = YAHOO_FALLBACK_MAP.get(code)
    if yahoo_ticker:
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}?range=2d&interval=1d"
            res = _yahoo_session.get(url, timeout=3)
            res.raise_for_status()
            meta = res.json()['chart']['result'][0]['meta']
            curr = float(meta['regularMarketPrice'])
            prev = float(meta['chartPreviousClose'])
            cval = curr - prev
            cpct = (cval / prev * 100) if prev else 0
            return curr, cpct, cval
        except Exception:
            pass

    return None, None, None


def fetch_single_macro(name, info):
    """매크로 지표 단일 조회 — 적응형 폴백"""
    try:
        if info["src"] in ("naver_index", "naver_stock"):
            is_idx = info["src"] == "naver_index"
            curr, cpct, cval = _fetch_kr_adaptive(info['ticker'], is_idx)
            if curr is not None:
                return name, {"current": curr, "change_pct": cpct, "change_val": cval}
            return name, None

        elif info["src"] == "naver_vkospi":
            try:
                res = _naver_session.get(
                    "https://finance.naver.com/sise/sise_index.naver?code=VIXKOSPI", timeout=2)
                m = re.search(r'<em id="now_value">([0-9.]+)</em>', res.text)
                if m:
                    curr = float(m.group(1))
                    cm = re.search(r'<span id="change_value_and_rate">[^\d]*([0-9.]+)[^\d]*<span', res.text)
                    rv = float(cm.group(1)) if cm else 0.0
                    cval = -rv if "nv01" in res.text else rv
                    prev = curr - cval
                    cpct = (cval / prev * 100) if prev > 0 else 0
                    return name, {"current": curr, "change_pct": cpct, "change_val": cval}
            except: pass
            return name, None

        elif info["src"] == "yahoo":
            # Yahoo 종목은 배치에서 이미 처리됨 — 여기는 단독 폴백
            try:
                url = f"https://query2.finance.yahoo.com/v8/finance/chart/{info['ticker']}?range=2d&interval=1d"
                res = _yahoo_session.get(url, timeout=3)
                res.raise_for_status()
                meta = res.json()['chart']['result'][0]['meta']
                curr = float(meta['regularMarketPrice'])
                prev = float(meta['chartPreviousClose'])
            except:
                try:
                    t = yf.Ticker(info['ticker'])
                    fi = t.fast_info
                    curr, prev = float(fi['lastPrice']), float(fi['previousClose'])
                except:
                    return name, None

            if info["ticker"] == "JPYKRW=X":
                curr *= 100; prev *= 100
            cval = curr - prev
            cpct = (cval / prev * 100) if prev else 0
            return name, {"current": curr, "change_pct": cpct, "change_val": cval}
    except:
        return name, None


@st.cache_data(ttl=30)
def get_macro_indicators(selected_names_tuple):
    """⚡ 매크로 전광판 — Yahoo 배치 + 네이버 병렬"""
    results = {}
    if not selected_names_tuple:
        return results

    # 1단계: Yahoo 종목들 배치 조회 (1회 HTTP)
    yahoo_names = [n for n in selected_names_tuple if INDICATORS_CONFIG[n]["src"] == "yahoo"]
    yahoo_tickers = [INDICATORS_CONFIG[n]["ticker"] for n in yahoo_names]

    yahoo_batch = {}
    if yahoo_tickers:
        yahoo_batch = _yahoo_batch_quotes(yahoo_tickers, timeout=3)
        # 배치 실패 시 개별 chart API 폴백
        missing = [t for t in yahoo_tickers if t not in yahoo_batch]
        if missing:
            yahoo_batch.update(_yahoo_batch_chart(missing, timeout=3))

    for name in yahoo_names:
        ticker = INDICATORS_CONFIG[name]["ticker"]
        if ticker in yahoo_batch:
            curr, prev = yahoo_batch[ticker]
            if INDICATORS_CONFIG[name]["ticker"] == "JPYKRW=X":
                curr *= 100; prev *= 100
            cval = curr - prev
            cpct = (cval / prev * 100) if prev else 0
            results[name] = {"current": curr, "change_pct": cpct, "change_val": cval}
        else:
            results[name] = None

    # 2단계: 네이버/VKOSPI 종목들 병렬 조회
    naver_names = [n for n in selected_names_tuple if INDICATORS_CONFIG[n]["src"] != "yahoo"]
    if naver_names:
        with ThreadPoolExecutor(max_workers=6) as executor:
            futs = {executor.submit(fetch_single_macro, n, INDICATORS_CONFIG[n]): n for n in naver_names}
            for fut in as_completed(futs):
                name, res = fut.result()
                results[name] = res

    # 소스 상태 저장
    _save_source_status(_src)
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


# ============================================================
# ⚡ 포트폴리오 시세 — Yahoo 배치 + 네이버 배치
# ============================================================

def fetch_single_price(ticker):
    """개별 종목 시세 (배치 실패 시 폴백용)"""
    try:
        if not ticker or not isinstance(ticker, str): return ticker, 0.0, 0.0
        if ticker.endswith('.KS') or ticker.endswith('.KQ'):
            code = ticker.split('.')[0]
            curr, cpct, _ = _fetch_kr_adaptive(code, is_index=False)
            if curr is not None:
                return ticker, curr, cpct
            return ticker, 0.0, 0.0
        # Yahoo
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?range=2d&interval=1d"
            res = _yahoo_session.get(url, timeout=3)
            res.raise_for_status()
            meta = res.json()['chart']['result'][0]['meta']
            curr = float(meta['regularMarketPrice'])
            prev = float(meta['chartPreviousClose'])
            return ticker, curr, ((curr - prev) / prev * 100) if prev else 0
        except:
            try:
                fi = yf.Ticker(ticker).fast_info
                curr, prev = float(fi['lastPrice']), float(fi['previousClose'])
                return ticker, curr, ((curr - prev) / prev * 100) if prev else 0
            except:
                return ticker, 0.0, 0.0
    except:
        return ticker, 0.0, 0.0


@st.cache_data(ttl=30)
def get_all_market_data(tickers_tuple):
    """⚡ 전종목 시세 — 배치 우선, 누락분만 개별"""
    results = {}
    tickers = list(tickers_tuple)

    # 한국 종목 / 해외 종목 분리
    kr_tickers = [t for t in tickers if t.endswith('.KS') or t.endswith('.KQ')]
    yahoo_tickers = [t for t in tickers if t not in kr_tickers]

    # 1) Yahoo 배치 (1회 HTTP)
    if yahoo_tickers:
        batch = _yahoo_batch_quotes(yahoo_tickers, timeout=3)
        if not batch:
            batch = _yahoo_batch_chart(yahoo_tickers, timeout=3)
        for t in yahoo_tickers:
            if t in batch:
                curr, prev = batch[t]
                cpct = ((curr - prev) / prev * 100) if prev else 0
                results[t] = (curr, cpct)
            # 누락분은 아래에서 처리

    # 2) 한국 종목 병렬 (네이버 적응형)
    if kr_tickers:
        with ThreadPoolExecutor(max_workers=min(len(kr_tickers), 6)) as ex:
            futs = {ex.submit(fetch_single_price, t): t for t in kr_tickers}
            for fut in as_completed(futs):
                t, price, change = fut.result()
                results[t] = (price, change)

    # 3) 누락된 Yahoo 종목 개별 폴백
    missing = [t for t in yahoo_tickers if t not in results]
    if missing:
        with ThreadPoolExecutor(max_workers=min(len(missing), 6)) as ex:
            futs = {ex.submit(fetch_single_price, t): t for t in missing}
            for fut in as_completed(futs):
                t, price, change = fut.result()
                results[t] = (price, change)

    _save_source_status(_src)
    return results


def fetch_single_dividend(ticker):
    try:
        if not ticker or not isinstance(ticker, str) or ticker == "KRW=X": 
            return ticker, pd.Series(dtype=float), None, None
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
        ex_date = None
        try: 
            info = stock.info
            if 'exDividendDate' in info and info['exDividendDate'] is not None:
                ed_dt = datetime.datetime.fromtimestamp(info['exDividendDate'])
                ex_date = ed_dt.strftime('%Y-%m-%d')
        except: pass
        
        divs = hist[hist['Dividends'] > 0]['Dividends'] if 'Dividends' in hist.columns else pd.Series(dtype=float)
        last_div_date = divs.index[-1] if not divs.empty else None
        
        return ticker, divs, ex_date, last_div_date
    except: return ticker, pd.Series(dtype=float), None, None

@st.cache_data(ttl=86400) 
def get_all_dividend_history(tickers_tuple):
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_single_dividend, t): t for t in tickers_tuple}
        for future in as_completed(futures):
            ticker, divs, ex_date, last_div_date = future.result()
            results[ticker] = {"divs": divs, "ex_date": ex_date, "last_div_date": last_div_date}
    return results

def interpret_indicator(title, actual, forecast):
    if not actual or str(actual) == '-': return "⏳ 발표 대기중"
    if not forecast or str(forecast) == '-': return "➖ 단순 발표 (예상치 없음)"
    try:
        act_val = float(re.sub(r'[^\d.-]', '', str(actual)))
        for_val = float(re.sub(r'[^\d.-]', '', str(forecast)))
    except: return "✅ 발표 완료"
    
    diff = act_val - for_val
    t = title.lower()
    
    if any(w in t for w in ["cpi", "pce", "ppi", "inflation", "price", "물가", "index"]):
        if diff > 0: return "🔻 예상 상회 (인플레 우려/악재)"
        elif diff < 0: return "🔺 예상 하회 (인플레 둔화/호재)"
        else: return "➖ 예상 부합"
    elif any(w in t for w in ["gdp", "pmi", "payroll", "employment", "주문", "판매", "sales", "생산", "manufacturing", "sentiment", "confidence"]):
        if diff > 0: return "🔺 예상 상회 (경제 탄탄/호재)"
        elif diff < 0: return "🔻 예상 하회 (경제 부진/악재)"
        else: return "➖ 예상 부합"
    elif any(w in t for w in ["unemployment", "실업", "jobless", "claims"]):
        if diff > 0: return "🔻 예상 상회 (고용 둔화/악재)"
        elif diff < 0: return "🔺 예상 하회 (고용 탄탄/호재)"
        else: return "➖ 예상 부합"
    if diff > 0: return "🔺 예상 상회"
    elif diff < 0: return "🔻 예상 하회"
    else: return "➖ 예상 부합"

@st.cache_data(ttl=300) 
def get_economic_calendar():
    try:
        kst = pytz.timezone('Asia/Seoul')
        now = datetime.datetime.now(kst)
        
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        res = _yahoo_session.get(url, timeout=5)
        
        if res.status_code != 200: return pd.DataFrame()
        events = res.json()
        
        records = []
        for ev in events:
            country = ev.get('country', '')
            impact = ev.get('impact', '')
            if country not in ['USD', 'KRW'] or impact not in ['High', 'Medium']: continue
            
            try:
                ev_dt = datetime.datetime.fromisoformat(ev['date']).astimezone(kst)
                title = ev.get('title', '')
                actual = str(ev.get('actual', '')).strip()
                forecast = str(ev.get('forecast', '')).strip()
                previous = str(ev.get('previous', '')).strip()
                
                if not actual or actual == 'None': actual = '-'
                if not forecast or forecast == 'None': forecast = '-'
                if not previous or previous == 'None': previous = '-'
                
                if ev_dt <= now:
                    status = "🔄 집계중" if actual == '-' else "✅ 완료"
                else:
                    status = "⏳ 예정"
                    
                interpretation = interpret_indicator(title, actual, forecast)
                
                records.append({
                    "상태": status,
                    "일시": ev_dt.strftime('%m-%d %H:%M'),
                    "국가": "🇺🇸 USD" if country == 'USD' else "🇰🇷 KRW",
                    "중요도": "🔥 높음" if impact == 'High' else "⭐ 중간",
                    "지표명": title,
                    "실제": actual,
                    "예상": forecast,
                    "이전": previous,
                    "AI 해석": interpretation
                })
            except: continue
            
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values(by="일시", ascending=False)
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_high_prices(tickers_tuple):
    high_prices = {}
    for ticker in tickers_tuple:
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            high_prices[ticker] = float(hist['High'].max())
        except: high_prices[ticker] = 0.0
    return high_prices

def fetch_current_prices_for_drawdown(tickers_tuple):
    current_prices = {}
    with ThreadPoolExecutor(max_workers=len(tickers_tuple)) as executor:
        futures = {executor.submit(fetch_single_price, t): t for t in tickers_tuple}
        for future in as_completed(futures):
            ticker, price, _ = future.result()
            current_prices[ticker] = price
    return current_prices

def create_drawdown_table(current_prices, high_prices):
    drawdown_data = []
    tickers_map = {
        "SPY": "S&P (SPY)",
        "QQQ": "나스닥 (QQQ)",
        "MAGS": "빅7 (MAGS)",
        "SOXX": "반도체 (SOXX)",
        "000660.KS": "하이닉스",
        "GLD": "금 (GLD)"
    }
    
    levels = [-5, -10, -15, -20, -25, -30, -35, -40]
    
    def format_price(val, ticker):
        return f"{val:,.0f}" if ticker.endswith('.KS') else f"${val:,.2f}"

    for ticker, name in tickers_map.items():
        curr_price = current_prices.get(ticker, 0.0)
        high_price = high_prices.get(ticker, 0.0)
        if high_price == 0.0 or curr_price == 0.0: continue
        
        drawdown_pct = ((curr_price - high_price) / high_price) * 100
        
        record = {
            "티커": ticker,
            "종목": name,
            "하락률": f"{drawdown_pct:.1f}%",
            "현재가": format_price(curr_price, ticker),
        }
        for l in levels:
            record[f"{l}%"] = format_price(high_price * (1 + l/100), ticker)
            
        record["_curr_raw"] = curr_price
        record["_high_raw"] = high_price
        drawdown_data.append(record)
        
    return pd.DataFrame(drawdown_data)

def style_drawdown_table(df):
    display_df = df.drop(columns=['_curr_raw', '_high_raw'])
    
    def get_styles(data):
        styles_df = pd.DataFrame('', index=display_df.index, columns=display_df.columns)
        levels = [-5, -10, -15, -20, -25, -30, -35, -40]
        
        for i in data.index:
            curr = data.loc[i, '_curr_raw']
            high = data.loc[i, '_high_raw']
            
            closest_col = None
            min_diff = float('inf')
            
            for l in levels:
                col = f"{l}%"
                if col in styles_df.columns:
                    level_price = high * (1 + l/100)
                    diff = abs(curr - level_price)
                    if diff < min_diff:
                        min_diff = diff
                        closest_col = col
            
            if closest_col:
                styles_df.loc[i, closest_col] = 'background-color: #E63946; color: white; font-weight: bold; border-radius: 4px;'
            
            styles_df.loc[i, '하락률'] = 'font-weight: bold; color: #457B9D;'
            styles_df.loc[i, '현재가'] = 'color: #3A86FF; font-weight: bold; background-color: rgba(58, 134, 255, 0.05);' 
            
        return styles_df
        
    return display_df.style.apply(lambda x: get_styles(df), axis=None).set_properties(**{'text-align': 'center'})


# -------------------------- UI 렌더링 --------------------------

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
            color = profit_up_color if d_val > 0 else profit_down_color if d_val < 0 else text_color
            
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
        
    df['자산군'] = df['자산군'].astype(str).str.strip().replace('', '주식').fillna('주식')
    df['종목명'] = df['종목명'].astype(str).str.strip().replace('', '알수없음').fillna('알수없음')
    df['티커'] = df['티커'].astype(str).str.strip()
    df['통화'] = df['통화'].astype(str).str.strip().str.upper()
    df['거래종류'] = df['거래종류'].astype(str).str.strip()

    df['수량'] = pd.to_numeric(df['수량'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['거래단가'] = pd.to_numeric(df['거래단가'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['계산용수량'] = df.apply(lambda x: x['수량'] if x['거래종류'] == '매수' else -x['수량'], axis=1)
    
    holdings = df.groupby(['자산군', '종목명', '티커', '통화'])['계산용수량'].sum().reset_index()
    holdings = holdings[holdings['계산용수량'] > 0].copy()

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
    holdings['평가액(만원)'] = (pd.Series(total_values_krw, index=holdings.index) / 10000).fillna(0).astype(int)

    total_asset = sum(total_values_krw)
    total_cost = sum(total_costs_krw)
    total_profit = total_asset - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0

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

    if show_drawdown_table:
        st.markdown("**📊 주요 지수 ETF 낙폭 기준표 (투자 전략)**")
        with st.spinner("최근 1년 최고가 데이터를 분석 중입니다..."):
            tickers_tuple = ("SPY", "QQQ", "MAGS", "SOXX", "000660.KS", "GLD")
            high_prices = fetch_high_prices(tickers_tuple)
            current_prices = fetch_current_prices_for_drawdown(tickers_tuple)
            
            drawdown_df = create_drawdown_table(current_prices, high_prices)
            
            if not drawdown_df.empty:
                styled_drawdown_df = style_drawdown_table(drawdown_df)
                st.dataframe(styled_drawdown_df, use_container_width=True, hide_index=True)
                st.caption("※ 파란색 텍스트는 '현재가'이며, 붉은색 강조 셀은 현재 주가와 가장 근접한 낙폭 구간(타점)을 자동으로 찾아 표시합니다.")
            else:
                st.info("데이터를 불러올 수 없습니다.")
        st.markdown("---")

    st.markdown("**📊 포트폴리오 시각화**")
    tab_chart1, tab_chart2, tab_chart3 = st.tabs(["🥧 자산 비중", "📈 자산 추이", "📊 실현 손익"])

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
            
    st.markdown("---")

    st.markdown("**📋 상세 데이터**")
    tab_data1, tab_data3, tab_data4, tab_rebal = st.tabs(["📊 자산 상세", "🔮 이벤트 캘린더", "📅 글로벌 경제 지표", "⚖️ 리밸런싱 계산기"])

    with tab_data1:
        display_df = holdings[['종목명', '계산용수량', '수익률(%)', '평가액(원)', '손익(원)']].copy()
        display_df.rename(columns={'계산용수량': '수량', '수익률(%)': '수익률', '평가액(원)': '평가액', '손익(원)': '손익'}, inplace=True)
        
        day_changes = []
        for _, row in holdings.iterrows():
            _, change_pct = market_data_dict.get(row['티커'], (0.0, 0.0))
            day_changes.append(change_pct)
        display_df['전일비(%)'] = day_changes
        display_df['비중(%)'] = (holdings['평가액(원)'].values / total_asset * 100) if total_asset > 0 else 0.0
        display_df = display_df[['종목명', '수량', '비중(%)', '전일비(%)', '수익률', '평가액', '손익']]
        
        def style_table(val):
            if isinstance(val, (int, float)):
                color = profit_up_color if val > 0 else profit_down_color if val < 0 else text_color
                return f'color: {color}; font-weight: bold;'
            return ''
        st.dataframe(
            display_df.style
            .set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '14px'})
            .format({'수량': '{:,.1f}', '비중(%)': '{:,.1f}%', '전일비(%)': '{:+,.2f}%', '수익률': '{:,.2f}%', '평가액': '{:,.0f}', '손익': '{:,.0f}'})
            .map(style_table, subset=['수익률', '손익', '전일비(%)']),
            use_container_width=True, hide_index=True
        )
            
    with tab_data3:
        kst = pytz.timezone('Asia/Seoul')
        now = datetime.datetime.now(kst)
        today_str = now.strftime('%Y-%m-%d')
        next_6_months = [(now.year + (now.month + i - 1) // 12, (now.month + i - 1) % 12 + 1) for i in range(1, 7)]
            
        expected_records, calendar_records = [], []
        total_6_months_krw = 0.0
        
        with st.spinner("데이터를 분석 중입니다... (최초 1회만 로딩)"):
            unique_tickers_for_div = tuple(holdings['티커'].unique())
            all_div_history = get_all_dividend_history(unique_tickers_for_div)

            for _, row in holdings.iterrows():
                ticker, name, qty, curr = row['티커'], row['종목명'], row['계산용수량'], row['통화']
                div_info = all_div_history.get(ticker, {"divs": pd.Series(dtype=float), "ex_date": None, "last_div_date": None})
                divs, ex_date, last_div_date = div_info["divs"], div_info["ex_date"], div_info["last_div_date"]
                
                added_to_calendar = False
                if ex_date and ex_date >= today_str: 
                    calendar_records.append({"종목명": name, "티커": ticker, "구분": "✅ 확정", "날짜": ex_date, "내용": "배당락일"})
                    added_to_calendar = True
                
                if not added_to_calendar and not divs.empty and last_div_date is not None:
                    try:
                        if len(divs) >= 18: days_to_add = 30
                        elif len(divs) >= 6: days_to_add = 91
                        else: days_to_add = 365
                        
                        est_date = last_div_date + datetime.timedelta(days=days_to_add)
                        while est_date.strftime('%Y-%m-%d') < today_str:
                            est_date += datetime.timedelta(days=days_to_add)
                            
                        if est_date <= now + datetime.timedelta(days=180):
                            calendar_records.append({"종목명": name, "티커": ticker, "구분": "🤔 예상(AI)", "날짜": est_date.strftime('%Y-%m-%d'), "내용": "배당락일 (추정)"})
                    except: pass

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

        st.markdown("**📅 주요 종목 이벤트 캘린더 (오늘 이후)**")
        if calendar_records:
            cal_df = pd.DataFrame(calendar_records).sort_values("날짜", ascending=True)
            st.dataframe(cal_df.style.set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '13px'}), use_container_width=True, hide_index=True)
            st.caption("※ '✅ 확정'은 야후 파이낸스 공식 발표 날짜이며, '🤔 예상(AI)'은 과거 2년치 지급 주기를 분석하여 추정한 날짜입니다.")
        else:
            st.info("📌 현재 기준(오늘 이후)으로 다가오는 배당락일/이벤트 일정이 없습니다.")
        st.markdown("---")

        if expected_records:
            next_div_df = pd.DataFrame(expected_records)
            st.markdown(f"**📈 향후 6개월 누적 예상 배당금:** 약 {int(total_6_months_krw):,.0f} 원 <span style='font-size:12px; color:gray;'>(오늘 환율 적용)</span>", unsafe_allow_html=True)
            fig_next = px.bar(next_div_df, x='연월', y='환산 예상금액(원)', color='종목명', hover_data={'예상 배당금': ':.2f', '통화': True}, color_discrete_sequence=pastel_colors)
            fig_next.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=20, b=10, l=10, r=10), barmode='stack')
            st.plotly_chart(fig_next, use_container_width=True)
            st.caption("※ 과거 배당 패턴을 분석한 결과이며, 데이터 제공 지연으로 누락될 수 있습니다.")

    with tab_data4:
        st.markdown("**📅 이번 주 주요 경제 지표 (미국/한국, ⭐️중간 이상 중요도)**")
        eco_df = get_economic_calendar()
        if not eco_df.empty:
            def highlight_status(val):
                if val == "✅ 완료": return f'color: {profit_up_color}; font-weight: bold;'
                elif val == "🔄 집계중": return f'color: {gold_highlight}; font-weight: bold;'
                elif val == "⏳ 예정": return f'color: gray;'
                return ''
            
            st.dataframe(
                eco_df.style
                .set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '13px'})
                .map(highlight_status, subset=['상태']),
                use_container_width=True, hide_index=True
            )
            st.caption("※ 정보는 ForexFactory 데이터를 기반으로 최신화됩니다.")
        else:
            st.info("이번 주 예정된 주요 지표가 없거나, 외부 데이터 서버 지연으로 불러올 수 없습니다.")

    with tab_rebal:
        if target_cash >= 0 and total_asset > 0:
            st.markdown("<div style='font-size: 13px; color: gray; margin-bottom: 10px;'>💡 사이드바에서 설정한 목표 비중으로 맞추기 위한 매매 지침입니다.</div>", unsafe_allow_html=True)
            def style_rebal(val):
                if isinstance(val, str):
                    if "매수" in val: return f'color: {profit_up_color}; font-weight: bold;'
                    elif "매도" in val: return f'color: {profit_down_color}; font-weight: bold;'
                return ''
            
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
            
            st.dataframe(
                rebal_df.style
                .set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '14px', 'text-align': 'center'})
                .format({'현재 비중': '{:.1f}%', '목표 비중': '{:.1f}%', '현재액(원)': '{:,.0f}', '목표액(원)': '{:,.0f}', '필요 금액(원)': '{:,.0f}'})
                .map(style_rebal, subset=['Action']),
                use_container_width=True, hide_index=True
            )
        else:
            st.caption("좌측 ⚙️ 사이드바를 열어 목표 자산 비중 수치를 올바르게 입력해 주세요.")

    # 데이터 소스 상태 (디버깅용)
    with st.expander("🔧 데이터 소스 상태"):
        nv = "✅" if _src.get("naver_ok") else "❌"
        nvl = "✅" if _src.get("naver_legacy_ok") else "❌"
        st.caption(f"네이버 신규: {nv} | 레거시: {nvl} | 5분마다 재시도 | Yahoo 배치: 항상 활성")

if auto_refresh:
    time.sleep(30)
    st.rerun()
