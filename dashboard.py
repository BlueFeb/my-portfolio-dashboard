import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import gspread
import plotly.express as px
import plotly.graph_objects as go
from oauth2client.service_account import ServiceAccountCredentials
import json
import datetime
import pytz
import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except ImportError:
    from requests.packages.urllib3.util.retry import Retry
import re
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 기본 설정 ---
st.set_page_config(page_title="내 포트폴리오", layout="wide", page_icon="💎")

SIDEBAR_SETTINGS_FILE = "sidebar_settings.json"

# 🔧 파일 쓰기 원자화: 쓰는 중 rerun이 겹쳐도 파일이 깨지지 않도록 tempfile + os.replace
def _atomic_write_json(path, data):
    """임시 파일에 쓰고 os.replace로 원자적 교체 (POSIX 보장)"""
    try:
        dir_name = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp_path = tempfile.mkstemp(
            prefix=os.path.basename(path) + ".",
            suffix=".tmp",
            dir=dir_name,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, path)
        except Exception:
            # 실패 시 임시 파일 정리
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            raise
    except Exception:
        pass

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
    except Exception:
        pass
    return defaults

def save_sidebar_settings():
    _atomic_write_json(SIDEBAR_SETTINGS_FILE, {
        "dark_mode": st.session_state.dark_mode,
        "auto_refresh": st.session_state.auto_refresh,
        "stock": st.session_state.target_stock,
        "crypto": st.session_state.target_crypto,
        "commodity": st.session_state.target_commodity,
        "bond": st.session_state.target_bond,
        "show_drawdown": st.session_state.show_drawdown
    })

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
# Retry 어댑터: 일시적 5xx/커넥션 에러 자동 재시도 (백오프 0.3s)
_retry_strategy = Retry(
    total=2,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD"]),
    raise_on_status=False,
)
_retry_adapter = HTTPAdapter(max_retries=_retry_strategy, pool_connections=10, pool_maxsize=20)

_naver_session = requests.Session()
_naver_session.mount("https://", _retry_adapter)
_naver_session.mount("http://", _retry_adapter)
_naver_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
    'Referer': 'https://m.stock.naver.com/',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
})

_yahoo_session = requests.Session()
_yahoo_session.mount("https://", _retry_adapter)
_yahoo_session.mount("http://", _retry_adapter)
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
    except Exception:
        pass
    return defaults

def _save_source_status(status):
    status["last_check"] = time.time()
    _atomic_write_json(SOURCE_STATUS_FILE, status)

# 세션 레벨 캐시 (st.session_state)
if "_src_status" not in st.session_state:
    st.session_state._src_status = _load_source_status()

_src = st.session_state._src_status

# 5분마다 죽은 소스 재시도
# 🔧 버그 수정: 리셋 후 last_check를 갱신하고 파일에도 저장해야 다음 rerun에서 다시 리셋되지 않음
if time.time() - _src.get("last_check", 0) > 300:
    _src["naver_ok"] = True
    _src["naver_legacy_ok"] = True
    _src["yahoo_v8_ok"] = True
    _save_source_status(_src)  # last_check 갱신 + 파일 반영


YAHOO_FALLBACK_MAP = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "005930": "005930.KS",
    "000660": "000660.KS",
}

def _get_yahoo_ticker_for_kr(code):
    """한국 종목 코드 → Yahoo 티커 변환 (동적)"""
    if code in YAHOO_FALLBACK_MAP:
        return YAHOO_FALLBACK_MAP[code]
    # 6자리 종목코드 → .KS (코스피 기본, 코스닥은 .KQ이지만 .KS로도 대부분 작동)
    if code.isdigit() and len(code) == 6:
        return f"{code}.KS"
    return None

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
    
    # 1순위: 파일 (가장 최신)
    try:
        if os.path.exists(MACRO_SETTINGS_FILE):
            with open(MACRO_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                saved = data.get("indicators", [])
                valid_saved = [x for x in saved if x in INDICATORS_CONFIG]
                if valid_saved: return valid_saved
    except Exception:
        pass
    
    # 2순위: URL query_params (앱 재부팅/ephemeral filesystem 대응)
    try:
        qp = st.query_params
        if "indicators" in qp:
            decoded = json.loads(qp["indicators"])
            valid = [x for x in decoded if x in INDICATORS_CONFIG]
            if valid: return valid
    except Exception:
        pass
    
    return default_inds

def save_macro_settings(selected):
    # 파일 저장 (원자적)
    _atomic_write_json(MACRO_SETTINGS_FILE, {"indicators": selected})
    # URL query_params 백업 (앱 재부팅 시에도 유지)
    try:
        st.query_params["indicators"] = json.dumps(selected, ensure_ascii=False)
    except Exception:
        pass


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
        except Exception:
            return t, None

    if not tickers:
        return results
    with ThreadPoolExecutor(max_workers=min(len(tickers), 10)) as ex:
        futs = {ex.submit(_fetch_one, t): t for t in tickers}
        for fut in as_completed(futs):
            t, val = fut.result()
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
    # 🔧 compareToPreviousClosePrice는 응답에 따라 부호 포함/미포함이 섞일 수 있음
    # → 절대값 취한 뒤 cpct의 부호로 결정 (cpct=0이면 0 유지)
    raw_cval = float(str(d['compareToPreviousClosePrice']).replace(',', ''))
    cval = abs(raw_cval)
    if cpct < 0:
        cval = -cval
    elif cpct == 0:
        cval = 0.0
    return curr, cpct, cval

def _naver_index_fast(code):
    """네이버 지수 — 타임아웃 1.5초"""
    url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
    res = _naver_session.get(url, timeout=1.5)
    res.raise_for_status()
    d = res.json()['datas'][0]
    curr = float(d['closePrice'].replace(',', ''))
    cpct = float(d['fluctuationsRatio'])
    raw_cval = float(str(d['compareToPreviousClosePrice']).replace(',', ''))
    cval = abs(raw_cval)
    if cpct < 0:
        cval = -cval
    elif cpct == 0:
        cval = 0.0
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

    # Yahoo Finance 폴백 (v8 API → yfinance 순서)
    yahoo_ticker = _get_yahoo_ticker_for_kr(code)
    if yahoo_ticker:
        # 1차: v8 chart API
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
        # 2차: yfinance 라이브러리 (최종 폴백)
        try:
            fi = yf.Ticker(yahoo_ticker).fast_info
            curr = float(fi['lastPrice'])
            prev = float(fi['previousClose'])
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
                # VKOSPI는 데스크톱 HTML 파싱이므로 데스크톱 UA 사용
                _desktop_headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                    'Referer': 'https://finance.naver.com/',
                }
                res = requests.get(
                    "https://finance.naver.com/sise/sise_index.naver?code=VIXKOSPI",
                    headers=_desktop_headers, timeout=2)
                m = re.search(r'<em id="now_value">([0-9.]+)</em>', res.text)
                if m:
                    curr = float(m.group(1))
                    # 🔧 nv01 검색 범위를 change_value_and_rate 섹션 내부로 제한
                    # (페이지 다른 위치의 nv01로 인한 부호 오판 방지)
                    change_section = re.search(
                        r'<span id="change_value_and_rate">(.*?)</span>\s*</span>',
                        res.text, flags=re.DOTALL
                    )
                    section_text = change_section.group(1) if change_section else ""
                    cm = re.search(r'([0-9.]+)', section_text)
                    rv = float(cm.group(1)) if cm else 0.0
                    cval = -rv if "nv01" in section_text else rv
                    prev = curr - cval
                    cpct = (cval / prev * 100) if prev > 0 else 0
                    return name, {"current": curr, "change_pct": cpct, "change_val": cval}
            except Exception:
                pass
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
            except Exception:
                try:
                    t = yf.Ticker(info['ticker'])
                    fi = t.fast_info
                    curr, prev = float(fi['lastPrice']), float(fi['previousClose'])
                except Exception:
                    return name, None

            if info["ticker"] == "JPYKRW=X":
                curr *= 100; prev *= 100
            cval = curr - prev
            cpct = (cval / prev * 100) if prev else 0
            return name, {"current": curr, "change_pct": cpct, "change_val": cval}
    except Exception:
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
        # 🔧 st.secrets 미설정 방어 (친절한 에러)
        if "google_credentials" not in st.secrets:
            st.error("⚠️ Streamlit secrets에 'google_credentials' 키가 설정되지 않았습니다. "
                     "Streamlit Cloud > Settings > Secrets에서 서비스 계정 JSON을 추가해 주세요.")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        creds_dict = json.loads(st.secrets["google_credentials"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        SHEET_NAME = "MyPortfolio_DB"
        spreadsheet = client.open(SHEET_NAME)

        # batch_get: 3개 시트를 1회 API 호출로 가져옴 (순차 호출 대비 ~1-2초 절감)
        ws_tx = spreadsheet.worksheet("거래내역")
        ws_history = spreadsheet.worksheet("일별기록")
        try:
            ws_pnl = spreadsheet.worksheet("실현손익")
        except gspread.exceptions.WorksheetNotFound:
            ws_pnl = None

        # batch_get으로 한 번에 가져오기
        ranges_to_fetch = [ws_tx.title, ws_history.title]
        if ws_pnl:
            ranges_to_fetch.append(ws_pnl.title)

        all_data = spreadsheet.values_batch_get(ranges_to_fetch)
        value_ranges = all_data.get('valueRanges', [])

        def _values_to_df(values_list):
            if not values_list:
                return pd.DataFrame()
            headers = values_list[0]
            rows = values_list[1:]
            max_cols = len(headers)
            # 열 수 맞추기: 짧으면 빈 문자열 패딩, 길면 잘라냄
            normalized = [r[:max_cols] if len(r) >= max_cols else r + [''] * (max_cols - len(r)) for r in rows]
            return pd.DataFrame(normalized, columns=headers)

        df_tx = _values_to_df(value_ranges[0].get('values', [])) if len(value_ranges) > 0 else pd.DataFrame()
        df_history = _values_to_df(value_ranges[1].get('values', [])) if len(value_ranges) > 1 else pd.DataFrame()
        df_pnl = _values_to_df(value_ranges[2].get('values', [])) if len(value_ranges) > 2 else pd.DataFrame()

        return df_tx, df_history, df_pnl
    except json.JSONDecodeError as e:
        st.error(f"⚠️ 구글 서비스 계정 JSON 파싱 오류: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("⚠️ 'MyPortfolio_DB' 시트를 찾을 수 없습니다. 시트 이름과 서비스 계정 공유 권한을 확인해 주세요.")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
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
            if curr is not None and curr > 0:
                return ticker, curr, cpct
            # _fetch_kr_adaptive에 YAHOO_FALLBACK_MAP에 없는 종목이면 직접 yfinance
            try:
                fi = yf.Ticker(ticker).fast_info
                curr = float(fi['lastPrice'])
                prev = float(fi['previousClose'])
                return ticker, curr, ((curr - prev) / prev * 100) if prev else 0
            except Exception:
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
        except Exception:
            try:
                fi = yf.Ticker(ticker).fast_info
                curr, prev = float(fi['lastPrice']), float(fi['previousClose'])
                return ticker, curr, ((curr - prev) / prev * 100) if prev else 0
            except Exception:
                return ticker, 0.0, 0.0
    except Exception:
        return ticker, 0.0, 0.0


@st.cache_data(ttl=300)
def get_usd_krw_rate():
    """환율 조회 — 5분 TTL (시세 30초보다 길게)"""
    try:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/KRW=X?range=2d&interval=1d"
        res = _yahoo_session.get(url, timeout=3)
        res.raise_for_status()
        meta = res.json()['chart']['result'][0]['meta']
        rate = float(meta['regularMarketPrice'])
        prev = float(meta['chartPreviousClose'])
        if rate > 0:
            return rate, ((rate - prev) / prev * 100) if prev else 0
    except Exception:
        pass
    try:
        fi = yf.Ticker("KRW=X").fast_info
        rate = float(fi['lastPrice'])
        prev = float(fi['previousClose'])
        if rate > 0:
            return rate, ((rate - prev) / prev * 100) if prev else 0
    except Exception:
        pass
    return 1400.0, 0.0


@st.cache_data(ttl=30)
def get_all_market_data(tickers_tuple):
    """⚡ 전종목 시세 — Yahoo 배치(한국+해외 통합) + 네이버 병렬"""
    results = {}
    tickers = list(tickers_tuple)

    # 한국 종목 / 해외 종목 분리
    kr_tickers = [t for t in tickers if t.endswith('.KS') or t.endswith('.KQ')]
    yahoo_tickers = [t for t in tickers if t not in kr_tickers]

    # 1) Yahoo 배치: 해외 + 한국 종목 한꺼번에 (1회 HTTP)
    all_yahoo_batch_tickers = yahoo_tickers + kr_tickers
    batch = {}
    if all_yahoo_batch_tickers:
        batch = _yahoo_batch_quotes(all_yahoo_batch_tickers, timeout=4)
        missing_batch = [t for t in all_yahoo_batch_tickers if t not in batch]
        if missing_batch:
            batch.update(_yahoo_batch_chart(missing_batch, timeout=3))

    for t in yahoo_tickers:
        if t in batch:
            curr, prev = batch[t]
            cpct = ((curr - prev) / prev * 100) if prev else 0
            results[t] = (curr, cpct)

    for t in kr_tickers:
        if t in batch:
            curr, prev = batch[t]
            cpct = ((curr - prev) / prev * 100) if prev else 0
            results[t] = (curr, cpct)

    # 2) 한국 종목 중 Yahoo 배치에 없는 것 → 네이버 적응형 개별
    kr_missing = [t for t in kr_tickers if t not in results or results[t][0] <= 0]
    if kr_missing:
        with ThreadPoolExecutor(max_workers=min(len(kr_missing), 6)) as ex:
            futs = {ex.submit(fetch_single_price, t): t for t in kr_missing}
            for fut in as_completed(futs):
                t, price, change = fut.result()
                if price > 0:
                    results[t] = (price, change)

    # 3) 해외 종목 누락분 개별 폴백
    yahoo_missing = [t for t in yahoo_tickers if t not in results or results[t][0] <= 0]
    if yahoo_missing:
        with ThreadPoolExecutor(max_workers=min(len(yahoo_missing), 6)) as ex:
            futs = {ex.submit(fetch_single_price, t): t for t in yahoo_missing}
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
                # 🔧 타임존 안전 변환: UTC 기준으로 파싱 → KST로 변환 후 날짜 추출
                # (로컬 타임존에 의존하던 기존 fromtimestamp()는 Streamlit Cloud(UTC)에서
                #  한국 날짜와 하루 차이 발생 가능)
                ed_dt = datetime.datetime.fromtimestamp(
                    info['exDividendDate'], tz=datetime.timezone.utc
                ).astimezone(pytz.timezone('Asia/Seoul'))
                ex_date = ed_dt.strftime('%Y-%m-%d')
        except Exception:
            pass
        
        divs = hist[hist['Dividends'] > 0]['Dividends'] if 'Dividends' in hist.columns else pd.Series(dtype=float)
        last_div_date = divs.index[-1] if not divs.empty else None
        
        return ticker, divs, ex_date, last_div_date
    except Exception:
        return ticker, pd.Series(dtype=float), None, None

@st.cache_data(ttl=86400) 
def get_all_dividend_history(tickers_tuple):
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_single_dividend, t): t for t in tickers_tuple}
        for future in as_completed(futures):
            ticker, divs, ex_date, last_div_date = future.result()
            results[ticker] = {"divs": divs, "ex_date": ex_date, "last_div_date": last_div_date}
    return results


# ============================================================
# 💰 자금흐름 자동 추론 (입금/출금 자동 감지)
# ============================================================
# 규칙:
#   • 입금: 매도 없이(가용 매도대금 부족) 30만원 이상 매수 → 부족분을 입금으로 감지
#   • 출금: 매도 후 영업일 기준 2일 이상 재투자 없음 → 가상잔고를 출금으로 감지
#   • 시작원금 = 시작일 총자산 − 시작일 실현손익(배당 포함)
#   • 3/14 이전 거래는 무시 (사용자 투자 시작일 기준)
# ============================================================

DEPOSIT_THRESHOLD_KRW = 300_000        # 입금 판정 최소 금액
WITHDRAW_BDAYS_THRESHOLD = 2           # 출금 판정 영업일 기준

def infer_cash_flows(df_tx, df_pnl, usd_krw_rate, start_date):
    """
    거래내역 + 실현손익으로부터 입금/출금 이벤트를 자동 추론한다.

    Parameters
    ----------
    df_tx : pd.DataFrame
        거래내역 원본 (정규화 전/후 모두 OK)
    df_pnl : pd.DataFrame
        실현손익 원본 (배당 포함)
    usd_krw_rate : float
        현재 USD/KRW 환율 (과거 거래도 이 환율로 단순 환산)
    start_date : pd.Timestamp
        시뮬레이션 시작일 (naive datetime). 이 날짜 이전 거래는 무시.

    Returns
    -------
    events_df : pd.DataFrame
        columns = ['날짜', '구분', '금액(원)', '메모']
        구분 ∈ {'입금', '출금'}
    """
    empty = pd.DataFrame(columns=['날짜', '구분', '금액(원)', '메모'])

    if df_tx is None or df_tx.empty:
        return empty

    # ---- 거래내역 파싱 ----
    tx = df_tx.copy()
    needed_cols = ['날짜', '거래종류', '수량', '거래단가', '통화', '종목명']
    for c in needed_cols:
        if c not in tx.columns:
            tx[c] = '' if c in ('거래종류', '통화', '종목명') else 0

    tx['날짜'] = pd.to_datetime(tx['날짜'], errors='coerce', utc=False)
    if getattr(tx['날짜'].dtype, 'tz', None) is not None:
        tx['날짜'] = tx['날짜'].dt.tz_localize(None)
    tx = tx.dropna(subset=['날짜'])

    # 시작일 이전/당일 거래 제거 — 시작일 당일까지는 이미 start_capital에 반영됨
    # (시작원금 = 시작일 총자산 − 시작일 실현손익)
    tx = tx[tx['날짜'] > start_date].copy()
    if tx.empty:
        return empty

    tx['수량'] = pd.to_numeric(tx['수량'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    tx['거래단가'] = pd.to_numeric(tx['거래단가'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    tx['거래종류'] = tx['거래종류'].astype(str).str.strip()
    tx['통화'] = tx['통화'].astype(str).str.upper().str.strip()
    tx['금액_원'] = tx['수량'] * tx['거래단가'] * tx['통화'].map(
        lambda c: usd_krw_rate if c == 'USD' else 1.0
    )

    # ---- 실현손익(배당 포함) 파싱 ----
    # 배당/매도 수익금은 "가상잔고"에 추가로 쌓임
    pnl_events = []  # list of (날짜, 금액_원)
    if df_pnl is not None and not df_pnl.empty and '실현손익(원)' in df_pnl.columns:
        pnl = df_pnl.copy()
        pnl['날짜'] = pd.to_datetime(pnl['날짜'], errors='coerce', utc=False)
        if getattr(pnl['날짜'].dtype, 'tz', None) is not None:
            pnl['날짜'] = pnl['날짜'].dt.tz_localize(None)
        pnl['실현손익(원)'] = pd.to_numeric(pnl['실현손익(원)'], errors='coerce').fillna(0)
        pnl = pnl.dropna(subset=['날짜'])
        # 시작일 당일 배당은 이미 start_capital 계산에서 차감됨 → 시뮬레이션에서는 제외
        pnl = pnl[pnl['날짜'] > start_date]
        # 배당은 가상잔고에 추가, 매도 실현손익은 이미 매도 거래 금액에 반영되므로
        # 여기서는 "배당만" 추가 현금 유입으로 취급
        if '분류' in pnl.columns:
            dividends = pnl[pnl['분류'].astype(str).str.strip() == '배당']
        elif '매도수량' in pnl.columns:
            # 분류 컬럼이 없으면 매도수량=0인 행을 배당으로 간주
            _ms = pd.to_numeric(pnl['매도수량'], errors='coerce').fillna(1)
            dividends = pnl[_ms == 0]
        else:
            dividends = pnl.iloc[0:0]

        for _, r in dividends.iterrows():
            curr = str(r.get('통화', 'KRW')).upper().strip() if '통화' in pnl.columns else 'KRW'
            # 실현손익 시트의 '실현손익(원)'은 이미 원화라고 가정 (구조 정의상 '원')
            # 단, USD 배당이 원화로 변환되어 기록됐는지 확인 필요. 현재는 원화값 그대로 사용
            amt = float(r['실현손익(원)'])
            if amt > 0:
                pnl_events.append((pd.Timestamp(r['날짜']).normalize(), amt))

    # ---- 이벤트를 날짜별로 집계 ----
    # 같은 날: 배당 입금 → 매도 → 매수 순서로 처리 (가용현금 우선 확보)
    tx['날짜_only'] = tx['날짜'].dt.normalize()

    # 모든 이벤트 날짜 수집
    all_dates = sorted(set(tx['날짜_only'].unique()) | set(d for d, _ in pnl_events))

    # 날짜별 배당금, 매도금, 매수금
    sells_by_date = tx[tx['거래종류'] == '매도'].groupby('날짜_only')['금액_원'].sum()
    buys_by_date = tx[tx['거래종류'] == '매수'].groupby('날짜_only')['금액_원'].sum()
    dividends_by_date = {}
    for d, a in pnl_events:
        dividends_by_date[d] = dividends_by_date.get(d, 0.0) + a

    # ---- 시뮬레이션 ----
    virtual_cash = 0.0
    last_sell_date = None  # 마지막 "잔금이 남은" 매도 날짜
    events = []

    for d in all_dates:
        # 1) 배당 입금 (가상잔고 증가)
        if d in dividends_by_date:
            virtual_cash += dividends_by_date[d]

        # 2) 매도 (가상잔고 증가)
        if d in sells_by_date.index:
            virtual_cash += float(sells_by_date.loc[d])
            last_sell_date = d  # 매도 발생 → 타이머 리셋

        # 3) 매수 (가상잔고 차감, 부족시 입금 감지)
        if d in buys_by_date.index:
            buy_amt = float(buys_by_date.loc[d])
            if buy_amt <= virtual_cash + 1e-6:
                # 정상 재투자
                virtual_cash -= buy_amt
            else:
                shortage = buy_amt - virtual_cash
                if shortage >= DEPOSIT_THRESHOLD_KRW:
                    # 입금 감지
                    events.append({
                        '날짜': d,
                        '구분': '입금',
                        '금액(원)': round(shortage),
                        '메모': f"매수 {buy_amt:,.0f}원 − 가용현금 {virtual_cash:,.0f}원"
                    })
                # 부족분이 임계값 미만이면 "노이즈로 간주, 그냥 0으로"
                virtual_cash = 0.0
            # 매수가 발생하면 마지막 매도 타이머 의미 없음 (재투자됨)
            if virtual_cash < DEPOSIT_THRESHOLD_KRW:
                last_sell_date = None

        # 4) 출금 감지: 매도 후 영업일 2일 이상 미재투자 & 가상잔고 존재
        if last_sell_date is not None and virtual_cash >= DEPOSIT_THRESHOLD_KRW:
            # d로부터 last_sell_date까지 영업일 수 계산
            bdays_passed = len(pd.bdate_range(last_sell_date, d)) - 1  # 매도일 제외
            if bdays_passed >= WITHDRAW_BDAYS_THRESHOLD:
                # 출금 확정: 잔고 전체를 출금으로 기록
                events.append({
                    '날짜': d,
                    '구분': '출금',
                    '금액(원)': round(virtual_cash),
                    '메모': f"매도 후 {bdays_passed}영업일 재투자 없음"
                })
                virtual_cash = 0.0
                last_sell_date = None

    # 시뮬레이션 종료 시점에 남은 가상잔고: 
    # 오늘 기준으로도 영업일 2일 넘게 미재투자면 출금으로 확정, 아니면 보류
    if virtual_cash >= DEPOSIT_THRESHOLD_KRW and last_sell_date is not None:
        today = pd.Timestamp(datetime.datetime.now(pytz.timezone('Asia/Seoul')).date())
        bdays_passed = len(pd.bdate_range(last_sell_date, today)) - 1
        if bdays_passed >= WITHDRAW_BDAYS_THRESHOLD:
            events.append({
                '날짜': today,
                '구분': '출금',
                '금액(원)': round(virtual_cash),
                '메모': f"매도 후 {bdays_passed}영업일 재투자 없음 (현재 시점)"
            })

    if not events:
        return empty

    return pd.DataFrame(events).sort_values('날짜').reset_index(drop=True)


def compute_capital_timeline(df_history_sorted, events_df, start_capital):
    """
    일별 누적원금 시리즈를 생성한다.

    Parameters
    ----------
    df_history_sorted : pd.DataFrame
        '날짜' 컬럼이 있는 일별기록 (날짜순 정렬됨)
    events_df : pd.DataFrame
        infer_cash_flows 결과
    start_capital : float
        시작원금 (원)

    Returns
    -------
    pd.Series (index=날짜, value=해당 날짜까지의 누적원금)
    """
    if df_history_sorted.empty:
        return pd.Series(dtype=float)

    # 날짜별 순 자금유입 (입금 +, 출금 −)
    if events_df is None or events_df.empty:
        delta_by_date = pd.Series(dtype=float)
    else:
        ev = events_df.copy()
        ev['부호있는금액'] = ev.apply(
            lambda r: r['금액(원)'] if r['구분'] == '입금' else -r['금액(원)'],
            axis=1
        )
        delta_by_date = ev.groupby('날짜')['부호있는금액'].sum()

    # 일별기록의 각 날짜에 대해 "그 날짜까지의 누적유입" 계산
    dates = df_history_sorted['날짜']
    capitals = []
    cum_inflow = 0.0
    event_dates_sorted = sorted(delta_by_date.index) if not delta_by_date.empty else []
    event_idx = 0
    for d in dates:
        # 해당 날짜까지의 모든 이벤트 누적
        while event_idx < len(event_dates_sorted) and event_dates_sorted[event_idx] <= d:
            cum_inflow += float(delta_by_date.loc[event_dates_sorted[event_idx]])
            event_idx += 1
        capitals.append(start_capital + cum_inflow)

    return pd.Series(capitals, index=dates.values)


def interpret_indicator(title, actual, forecast):
    if not actual or str(actual) == '-': return "⏳ 발표 대기중"
    if not forecast or str(forecast) == '-': return "➖ 단순 발표 (예상치 없음)"
    try:
        act_val = float(re.sub(r'[^\d.-]', '', str(actual)))
        for_val = float(re.sub(r'[^\d.-]', '', str(forecast)))
    except Exception:
        return "✅ 발표 완료"
    
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
            except Exception:
                continue
            
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values(by="일시", ascending=False)
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_high_prices(tickers_tuple):
    """1년 최고가 조회 — 병렬화 (6종목 × ~1초 → ~1초)"""
    high_prices = {}
    if not tickers_tuple:
        return high_prices

    def _fetch_one(ticker):
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            if hist is None or hist.empty or 'High' not in hist.columns:
                return ticker, 0.0
            return ticker, float(hist['High'].max())
        except Exception:
            return ticker, 0.0

    with ThreadPoolExecutor(max_workers=max(1, min(len(tickers_tuple), 10))) as ex:
        futs = {ex.submit(_fetch_one, t): t for t in tickers_tuple}
        for fut in as_completed(futs):
            t, hp = fut.result()
            high_prices[t] = hp
    return high_prices

def fetch_current_prices_for_drawdown(tickers_tuple):
    current_prices = {}
    if not tickers_tuple:
        return current_prices
    # 🔧 max_workers=0 방어 (빈 튜플 시 ValueError 방지) + 상한 설정
    workers = max(1, min(len(tickers_tuple), 10))
    with ThreadPoolExecutor(max_workers=workers) as executor:
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
    
    def get_styles(_ignored):
        # 🔧 df(raw 값 포함)를 클로저로 사용 — display_df에는 _raw 컬럼이 없으므로
        # pandas가 건네주는 data 대신 외부 df를 의도적으로 참조
        styles_df = pd.DataFrame('', index=display_df.index, columns=display_df.columns)
        levels = [-5, -10, -15, -20, -25, -30, -35, -40]
        
        for i in df.index:
            curr = df.loc[i, '_curr_raw']
            high = df.loc[i, '_high_raw']
            
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
        
    return display_df.style.apply(get_styles, axis=None).set_properties(**{'text-align': 'center'})


# -------------------------- UI 렌더링 --------------------------

st.markdown('<div class="row-widget-hook"></div>', unsafe_allow_html=True)
col_title, col_setting = st.columns([7, 3])

# 🔧 전광판 종목/순서 초기화 방지
# Streamlit은 절전/reconnect 시 session_state를 초기화함
# → 파일을 source of truth로 두고, session_state가 비면 파일에서 복원
# → key="macro_selector"를 쓰면 Streamlit이 위젯 값을 session_state에 자동 반영
# → 위젯 렌더링 전에 session_state에 값을 넣어두면 그것이 위젯 초기값이 됨
if "macro_selector" not in st.session_state:
    st.session_state.macro_selector = load_macro_settings()
elif not st.session_state.macro_selector:
    # 빈 리스트로 초기화된 경우 (절전 복귀 등) → 파일에서 복원
    _file_saved = load_macro_settings()
    if _file_saved:
        st.session_state.macro_selector = _file_saved

def on_macro_change(): save_macro_settings(st.session_state.macro_selector)

with col_title:
    st.markdown("<div style='font-size: 16px; font-weight: bold; margin-top: 5px;'>🌐 글로벌 매크로 전광판</div>", unsafe_allow_html=True)

with col_setting:
    try:
        with st.popover("⚙️ 설정", use_container_width=True):
            st.multiselect(
                "최대 9개 선택",
                options=list(INDICATORS_CONFIG.keys()),
                key="macro_selector",
                max_selections=9,
                on_change=on_macro_change,
                label_visibility="collapsed"
            )
    except AttributeError:
        with st.expander("⚙️ 설정"):
            st.multiselect(
                "최대 9개 선택",
                options=list(INDICATORS_CONFIG.keys()),
                key="macro_selector",
                max_selections=9,
                on_change=on_macro_change,
                label_visibility="collapsed"
            )

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
        
    import unicodedata
    
    def _normalize_str_col(series):
        """유니코드 정규화 + 모든 종류의 공백 통일 + strip"""
        return (series.astype(str)
                .apply(lambda s: unicodedata.normalize('NFC', s))  # 유니코드 정규화
                .str.replace(r'\s+', ' ', regex=True)  # 연속/특수 공백 → 일반 공백 1개
                .str.strip())

    df['자산군'] = _normalize_str_col(df['자산군']).replace('', '주식')
    df['종목명'] = _normalize_str_col(df['종목명']).replace('', '알수없음')
    df['티커'] = _normalize_str_col(df['티커'])
    df['통화'] = _normalize_str_col(df['통화']).str.upper()
    df['거래종류'] = _normalize_str_col(df['거래종류'])

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
    # KRW=X는 별도 5분 캐시로 분리 (불필요한 갱신 절감)
    if "KRW=X" in unique_tickers:
        unique_tickers.remove("KRW=X")
    market_data_dict = get_all_market_data(tuple(unique_tickers))

    usd_krw_price, usd_krw_change = get_usd_krw_rate()
    market_data_dict["KRW=X"] = (usd_krw_price, usd_krw_change)
    if usd_krw_price <= 0.0: usd_krw_price = 1400.0

    realtime_prices, total_values_krw, total_costs_krw, profit_pcts, profit_amounts = [], [], [], [], []
    _price_failed_tickers = []
    for index, row in holdings.iterrows():
        current_price, _ = market_data_dict.get(row['티커'], (0.0, 0.0))
        
        # 🔧 가격 0원 방어: 매입단가로 대체 (−100% 표시 방지)
        if current_price <= 0 and row['평균매입단가'] > 0:
            current_price = row['평균매입단가']
            _price_failed_tickers.append(row['종목명'])
        
        realtime_prices.append(current_price)
        rate = usd_krw_price if row['통화'] == "USD" else 1
        eval_krw = current_price * row['계산용수량'] * rate 
        cost_krw = row['평균매입단가'] * row['계산용수량'] * rate     
        
        total_values_krw.append(eval_krw)
        total_costs_krw.append(cost_krw)
        profit_amounts.append(eval_krw - cost_krw)
        profit_pcts.append(((current_price - row['평균매입단가']) / row['평균매입단가'] * 100) if row['평균매입단가'] > 0 else 0.0)

    if _price_failed_tickers:
        st.warning(f"⚠️ 시세 조회 실패 → 매입단가로 대체 중: {', '.join(_price_failed_tickers)} (네이버/Yahoo 모두 응답 없음)")

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
            df_h = df_history.copy()
            # naive datetime64로 통일
            df_h['날짜'] = pd.to_datetime(df_h['날짜'], errors='coerce', utc=False)
            if getattr(df_h['날짜'].dtype, 'tz', None) is not None:
                df_h['날짜'] = df_h['날짜'].dt.tz_localize(None)
            df_h = df_h.dropna(subset=['날짜']).sort_values('날짜').reset_index(drop=True)
            df_h['총자산(원)'] = pd.to_numeric(df_h[df_h.columns[1]], errors='coerce').fillna(0)

            # ---- 시작일 및 시작원금 계산 ----
            # 시작일 = 일별기록의 첫 날 (3/14 가정)
            start_date = df_h['날짜'].iloc[0]

            # 시작일 당일의 실현손익(배당 포함) 합계
            start_day_realized = 0.0
            if not df_pnl_raw.empty and '실현손익(원)' in df_pnl_raw.columns:
                _p = df_pnl_raw.copy()
                _p['날짜'] = pd.to_datetime(_p['날짜'], errors='coerce', utc=False)
                if getattr(_p['날짜'].dtype, 'tz', None) is not None:
                    _p['날짜'] = _p['날짜'].dt.tz_localize(None)
                _p['실현손익(원)'] = pd.to_numeric(_p['실현손익(원)'], errors='coerce').fillna(0)
                _p = _p.dropna(subset=['날짜'])
                # 시작일 당일 실현손익만
                start_day_realized = float(
                    _p[_p['날짜'].dt.normalize() == start_date.normalize()]['실현손익(원)'].sum()
                )

            # 시작원금 = 시작일 총자산 − 시작일 당일 실현손익
            start_capital = max(float(df_h['총자산(원)'].iloc[0]) - start_day_realized, 1.0)

            # ---- 자금흐름 자동 추론 ----
            events_df = infer_cash_flows(
                df_raw, df_pnl_raw,
                usd_krw_rate=usd_krw_price,
                start_date=start_date
            )

            # ---- 오늘 실시간 자산을 마지막 점으로 추가 ----
            kst_now = datetime.datetime.now(pytz.timezone('Asia/Seoul'))
            today_date = pd.Timestamp(kst_now.date())
            last_record_date = df_h['날짜'].iloc[-1] if not df_h.empty else None
            if last_record_date is not None and today_date > last_record_date and total_asset > 0:
                today_row = pd.DataFrame({
                    '날짜': [today_date],
                    '총자산(원)': [total_asset],
                })
                for col in df_h.columns:
                    if col not in today_row.columns:
                        today_row[col] = np.nan
                df_h = pd.concat([df_h, today_row[df_h.columns]], ignore_index=True)

            df_h['총자산(만원)'] = df_h['총자산(원)'] / 10000

            # ---- 누적원금 시리즈 생성 (계단선) ----
            capital_series = compute_capital_timeline(df_h[['날짜']], events_df, start_capital)
            df_h['누적원금(원)'] = capital_series.values
            df_h['누적원금(만원)'] = df_h['누적원금(원)'] / 10000

            # ---- 성과 계산 ----
            df_h['수익(원)'] = df_h['총자산(원)'] - df_h['누적원금(원)']
            df_h['수익률(%)'] = (df_h['수익(원)'] / df_h['누적원금(원)'] * 100).replace([np.inf, -np.inf], 0).fillna(0)

            # ---- MDD: 수익률 기준으로 계산 (입금/출금으로 인한 거짓 낙폭 방지) ----
            df_h['수익률_고점(%)'] = df_h['수익률(%)'].cummax()
            df_h['낙폭(%)'] = df_h['수익률(%)'] - df_h['수익률_고점(%)']
            mdd_pct = float(df_h['낙폭(%)'].min()) if not df_h.empty else 0.0
            mdd_idx = df_h['낙폭(%)'].idxmin() if not df_h.empty else None
            mdd_date = df_h.loc[mdd_idx, '날짜'].strftime('%Y-%m-%d') if mdd_idx is not None else '-'

            peak_return = float(df_h['수익률(%)'].max()) if not df_h.empty else 0.0
            peak_idx = df_h['수익률(%)'].idxmax() if not df_h.empty else None
            peak_date = df_h.loc[peak_idx, '날짜'].strftime('%Y-%m-%d') if peak_idx is not None else '-'

            # ---- 현재 시점 성과 ----
            curr_total = float(df_h['총자산(원)'].iloc[-1])
            curr_capital = float(df_h['누적원금(원)'].iloc[-1])
            curr_profit = curr_total - curr_capital
            curr_return_pct = (curr_profit / curr_capital * 100) if curr_capital > 0 else 0.0

            # 실현손익 누적 (정보성 지표용)
            cumul_realized = 0.0
            if not df_pnl_raw.empty and '실현손익(원)' in df_pnl_raw.columns:
                _p2 = df_pnl_raw.copy()
                _p2['날짜'] = pd.to_datetime(_p2['날짜'], errors='coerce', utc=False)
                if getattr(_p2['날짜'].dtype, 'tz', None) is not None:
                    _p2['날짜'] = _p2['날짜'].dt.tz_localize(None)
                _p2['실현손익(원)'] = pd.to_numeric(_p2['실현손익(원)'], errors='coerce').fillna(0)
                _p2 = _p2.dropna(subset=['날짜'])
                cumul_realized = float(_p2[_p2['날짜'] >= start_date]['실현손익(원)'].sum())
            unrealized = curr_profit - cumul_realized

            # 감지된 입금/출금 횟수
            n_deposits = int((events_df['구분'] == '입금').sum()) if not events_df.empty else 0
            n_withdrawals = int((events_df['구분'] == '출금').sum()) if not events_df.empty else 0

            # ---- 지표 카드 ----
            cols_metric = st.columns(4)
            with cols_metric[0]:
                deposit_label = f"입금 {n_deposits}회" if n_deposits > 0 else "추가 투입 없음"
                if n_withdrawals > 0:
                    deposit_label += f" / 출금 {n_withdrawals}회"
                st.metric("💰 누적 원금", f"{curr_capital/10000:,.0f}만원", delta=deposit_label, delta_color="off")
            with cols_metric[1]:
                sign = "+" if curr_profit >= 0 else ""
                st.metric("📈 총 수익", f"{sign}{curr_profit/10000:,.0f}만원",
                          delta=f"미실현 {unrealized/10000:+,.0f}만 / 실현 {cumul_realized/10000:+,.0f}만",
                          delta_color="off")
            with cols_metric[2]:
                st.metric("📊 수익률", f"{curr_return_pct:+,.2f}%",
                          delta=f"고점 {peak_return:+.1f}% ({peak_date})",
                          delta_color="off")
            with cols_metric[3]:
                st.metric("📉 MDD", f"{mdd_pct:,.2f}%p",
                          delta=f"{mdd_date}", delta_color="inverse")

            # ---- 차트 ----
            # 수익/손실 영역 분리를 위해 누적원금 선과 총자산 선 사이를 채색
            # Plotly는 fill='tonexty'로 직전 trace와의 영역 채움
            profit_fill = "rgba(255, 153, 153, 0.18)" if is_dark_mode else "rgba(230, 57, 70, 0.12)"
            loss_fill = "rgba(153, 204, 255, 0.18)" if is_dark_mode else "rgba(69, 123, 157, 0.12)"

            fig_line = go.Figure()

            # 1) 누적원금 (계단선) - 기준선 역할, 먼저 그림
            fig_line.add_trace(go.Scatter(
                x=df_h['날짜'], y=df_h['누적원금(만원)'],
                mode='lines', name='누적 원금',
                line=dict(color=gold_highlight, width=2, shape='hv'),  # hv = 계단식
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>누적 원금: %{y:,.0f}만원<extra></extra>',
            ))

            # 2) 총자산선 — 누적원금선과의 영역을 채움 (tonexty)
            # 수익 구간(자산 > 원금)과 손실 구간 구분을 위해 두 번 그림
            df_h_profit = df_h['총자산(만원)'].where(df_h['총자산(원)'] >= df_h['누적원금(원)'], df_h['누적원금(만원)'])
            df_h_loss = df_h['총자산(만원)'].where(df_h['총자산(원)'] < df_h['누적원금(원)'], df_h['누적원금(만원)'])

            # 수익 영역 (위쪽) — 연한 초록/분홍
            fig_line.add_trace(go.Scatter(
                x=df_h['날짜'], y=df_h_profit,
                mode='none', name='수익 구간',
                fill='tonexty', fillcolor=profit_fill,
                hoverinfo='skip', showlegend=False,
            ))

            # 3) 누적원금을 다시 그리되 손실 채색용 앵커로 사용
            fig_line.add_trace(go.Scatter(
                x=df_h['날짜'], y=df_h['누적원금(만원)'],
                mode='lines', line=dict(color='rgba(0,0,0,0)', width=0),
                hoverinfo='skip', showlegend=False,
            ))
            # 손실 영역 (아래쪽)
            fig_line.add_trace(go.Scatter(
                x=df_h['날짜'], y=df_h_loss,
                mode='none', name='손실 구간',
                fill='tonexty', fillcolor=loss_fill,
                hoverinfo='skip', showlegend=False,
            ))

            # 4) 총자산 실선 (메인)
            fig_line.add_trace(go.Scatter(
                x=df_h['날짜'], y=df_h['총자산(만원)'],
                mode='lines+markers', name='총 자산',
                line=dict(color=line_color, width=2.5),
                marker=dict(color=line_color, size=4),
                customdata=np.stack([df_h['수익률(%)'], df_h['수익(원)']/10000], axis=-1),
                hovertemplate=(
                    '<b>%{x|%Y-%m-%d}</b><br>'
                    '총자산: %{y:,.0f}만원<br>'
                    '수익: %{customdata[1]:+,.0f}만원 (%{customdata[0]:+.2f}%)<extra></extra>'
                ),
            ))

            # 5) 마지막 점 강조 (현재 위치)
            if not df_h.empty:
                last_x = df_h['날짜'].iloc[-1]
                last_y = df_h['총자산(만원)'].iloc[-1]
                fig_line.add_trace(go.Scatter(
                    x=[last_x], y=[last_y],
                    mode='markers+text', showlegend=False,
                    marker=dict(color=line_color, size=11, line=dict(color='white', width=2)),
                    text=[f" {last_y:,.0f}만 ({curr_return_pct:+.1f}%)"],
                    textposition='middle right',
                    textfont=dict(color=line_color, size=12, family="Arial Black"),
                    hoverinfo='skip',
                ))

            # 6) 입금/출금 이벤트 annotation (차트 상단)
            if not events_df.empty:
                for _, ev in events_df.iterrows():
                    ev_date = ev['날짜']
                    ev_type = ev['구분']
                    ev_amt = ev['금액(원)'] / 10000
                    # 이벤트 날짜가 차트 범위 밖이면 스킵
                    if ev_date < df_h['날짜'].iloc[0] or ev_date > df_h['날짜'].iloc[-1]:
                        continue
                    arrow_color = profit_up_color if ev_type == '입금' else profit_down_color
                    symbol = '▲' if ev_type == '입금' else '▼'
                    fig_line.add_annotation(
                        x=ev_date, y=1, yref='paper',
                        text=f"{symbol} {ev_type} {ev_amt:,.0f}만",
                        showarrow=False,
                        font=dict(color=arrow_color, size=10, family="Arial Black"),
                        bgcolor="rgba(0,0,0,0.3)" if is_dark_mode else "rgba(255,255,255,0.8)",
                        bordercolor=arrow_color, borderwidth=1, borderpad=2,
                        yshift=5,
                    )
                    # 해당 날짜 수직선
                    fig_line.add_vline(x=ev_date, line_dash="dot", line_color=arrow_color, opacity=0.3)

            # 7) MDD 발생 지점 마커
            if mdd_idx is not None and mdd_pct < -0.01:
                mdd_x = df_h.loc[mdd_idx, '날짜']
                mdd_y = df_h.loc[mdd_idx, '총자산(만원)']
                fig_line.add_trace(go.Scatter(
                    x=[mdd_x], y=[mdd_y],
                    mode='markers', showlegend=False,
                    marker=dict(color=profit_down_color, size=10, symbol='triangle-down',
                                line=dict(color='white', width=1.5)),
                    hovertemplate=f'<b>MDD {mdd_pct:.2f}%p</b><br>{mdd_date}<extra></extra>',
                ))

            fig_line.update_layout(
                template=chart_template,
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(t=50, b=10, l=10, r=80),  # 오른쪽 여백 늘려서 마지막 라벨 표시
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis=dict(title="만원", tickformat=",.0f"),
                xaxis=dict(
                    type='date',
                    rangeselector=dict(
                        buttons=list([
                            dict(count=1, label="1M", step="month", stepmode="backward"),
                            dict(count=3, label="3M", step="month", stepmode="backward"),
                            dict(count=6, label="6M", step="month", stepmode="backward"),
                            dict(count=1, label="1Y", step="year", stepmode="backward"),
                            dict(step="all", label="All"),
                        ]),
                        bgcolor="rgba(80,80,80,0.3)" if is_dark_mode else "rgba(230,230,230,0.8)",
                        font=dict(size=10),
                    ),
                ),
                hovermode='x unified',
            )
            st.plotly_chart(fig_line, use_container_width=True)

            # ---- 자동 감지된 자금흐름 expander ----
            with st.expander(f"🔍 자동 감지된 자금흐름 ({len(events_df)}건)"):
                if events_df.empty:
                    st.caption("감지된 입금/출금이 없습니다. (전액 재투자 흐름)")
                else:
                    display_ev = events_df.copy()
                    display_ev['날짜'] = display_ev['날짜'].dt.strftime('%Y-%m-%d')
                    display_ev['금액(원)'] = display_ev['금액(원)'].apply(lambda v: f"{v:+,.0f}" if v else "0")
                    # 입금은 + 부호, 출금은 − 부호 명시
                    def _signed(row):
                        amt = row['금액(원)'].replace(',', '').replace('+', '')
                        if row['구분'] == '출금':
                            return f"−{amt}" if not amt.startswith('-') else amt
                        return f"+{amt}"
                    display_ev['금액(원)'] = display_ev.apply(_signed, axis=1)
                    st.dataframe(
                        display_ev,
                        use_container_width=True, hide_index=True,
                    )
                st.caption(
                    f"📌 **감지 규칙**: "
                    f"매도 없이 **{DEPOSIT_THRESHOLD_KRW:,.0f}원 이상** 매수 시 부족분을 입금으로, "
                    f"매도 후 **영업일 {WITHDRAW_BDAYS_THRESHOLD}일 이상** 재투자 없으면 잔액을 출금으로 판정합니다. "
                    f"USD 거래는 현재 환율({usd_krw_price:,.1f}원)로 단순 환산했습니다."
                )

            st.caption(
                "※ **수익률** = (총자산 − 누적원금) ÷ 누적원금. "
                "입금/출금은 수익으로 집계되지 않고 원금 계단선(금색)에 반영됩니다. "
                "**MDD**는 수익률 기준으로 계산하여 입금/출금으로 인한 거짓 낙폭을 배제합니다."
            )

    with tab_chart3:
        # 🔧 df_pnl은 이후 다른 탭에서도 참조될 수 있으므로 파괴적 변환 방지
        # → df_pnl_raw에서 별도 복사본(df_pnl_chart)을 만들어 이 탭에서만 사용
        if not df_pnl_raw.empty and '실현손익(원)' in df_pnl_raw.columns:
            df_pnl_chart = df_pnl_raw.copy()
            df_pnl_chart['실현손익(원)'] = pd.to_numeric(df_pnl_chart['실현손익(원)'], errors='coerce').fillna(0)
            df_pnl_chart['분류'] = df_pnl_chart.apply(lambda x: x['분류'] if str(x.get('분류', '')).strip() != '' else ('배당' if x.get('매도수량', 1) == 0 else '매도'), axis=1)
            df_pnl_chart['차트분류'] = df_pnl_chart.apply(lambda x: f"{x['분류']} ({'해외' if x.get('통화')=='USD' else '국내'})", axis=1)
            df_pnl_chart['실현손익_차트용(만원)'] = (df_pnl_chart['실현손익(원)'] / 10000).fillna(0).astype(int)
            
            period = st.radio("보기 옵션", ["월별", "연별", "일별"], horizontal=True, label_visibility="collapsed")
            df_pnl_chart['날짜'] = pd.to_datetime(df_pnl_chart['날짜'], errors='coerce')
            df_pnl_chart = df_pnl_chart.dropna(subset=['날짜'])
            df_pnl_chart['일자'] = df_pnl_chart['날짜'].dt.strftime('%Y-%m-%d')
            df_pnl_chart['월'] = df_pnl_chart['날짜'].dt.strftime('%Y-%m')
            df_pnl_chart['연'] = df_pnl_chart['날짜'].dt.strftime('%Y')
            
            def plot_pnl_bar(data, x_col):
                color_map = {'매도 (국내)': '#FF6B6B', '매도 (해외)': '#FFA07A', '배당 (국내)': '#4DABF7', '배당 (해외)': '#51CF66'}
                fig = px.bar(data, x=x_col, y='실현손익_차트용(만원)', color='차트분류', text='실현손익_차트용(만원)', color_discrete_map=color_map)
                fig.update_traces(texttemplate='%{text:,.0f}', textposition="outside", cliponaxis=False)
                fig.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10), barmode='relative', legend_title_text='')
                st.plotly_chart(fig, use_container_width=True)

            if period == "월별": plot_pnl_bar(df_pnl_chart.groupby(['월', '차트분류'])['실현손익_차트용(만원)'].sum().reset_index(), '월')
            elif period == "연별": plot_pnl_bar(df_pnl_chart.groupby(['연', '차트분류'])['실현손익_차트용(만원)'].sum().reset_index(), '연')
            else: plot_pnl_bar(df_pnl_chart.groupby(['일자', '차트분류'])['실현손익_차트용(만원)'].sum().reset_index(), '일자')
            
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
                ticker, name, qty, currency = row['티커'], row['종목명'], row['계산용수량'], row['통화']
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
                        # 🔧 극단적으로 과거인 last_div_date에서 무한/과도 루프 방지 (상한 120회)
                        _max_iter = 120
                        _iter = 0
                        while est_date.strftime('%Y-%m-%d') < today_str and _iter < _max_iter:
                            est_date += datetime.timedelta(days=days_to_add)
                            _iter += 1
                            
                        if est_date <= now + datetime.timedelta(days=180):
                            calendar_records.append({"종목명": name, "티커": ticker, "구분": "🤔 예상(AI)", "날짜": est_date.strftime('%Y-%m-%d'), "내용": "배당락일 (추정)"})
                    except Exception:
                        pass

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
                        rate = usd_krw_price if currency == 'USD' else 1.0
                        expected_krw = expected_div * rate
                        total_6_months_krw += expected_krw
                        expected_records.append({'연월': f"{y}년 {m:02d}월", '종목명': name, '수량': qty, '통화': currency, '예상 주당배당금': dps, '예상 배당금': expected_div, '환산 예상금액(원)': expected_krw})

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
        st.caption(f"네이버 신규: {nv} | 레거시: {nvl} | Yahoo 배치+yfinance 폴백: 항상 활성")
        if not _src.get("naver_ok") and not _src.get("naver_legacy_ok"):
            st.caption("⚠️ 네이버 API 모두 차단 상태 → Yahoo Finance(yfinance)로 한국 종목 조회 중. 5분 후 네이버 재시도.")

if auto_refresh:
    # Streamlit 1.37+의 st.fragment(run_every=) 지원 여부 확인
    # 전체 rerun이 필요한 구조이므로 기존 방식 유지하되, sleep 중 UI 차단을 최소화
    _refresh_placeholder = st.empty()
    _refresh_placeholder.caption("🔄 30초 후 자동 새로고침...")
    time.sleep(30)
    _refresh_placeholder.empty()
    st.rerun()
