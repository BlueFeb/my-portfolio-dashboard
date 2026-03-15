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

# --- 1. 기본 설정 ---
st.set_page_config(page_title="내 포트폴리오", layout="wide", page_icon="💎")

col1, col2 = st.columns([8, 2])
with col1:
    st.markdown("<h2 style='margin-top: -15px;'>💎 내 포트폴리오</h2>", unsafe_allow_html=True)
with col2:
    is_dark_mode = st.toggle("다크 모드 켜기", value=True)

if is_dark_mode:
    bg_color, text_color = "#1E1E1E", "#F0F2F6"
    df_bg, df_text = "#2A2A2A", "#FFFFFF"
    chart_template = "plotly_dark"
    pastel_colors = ['#FFB3BA', '#FFDFBA', '#FFFFBA', '#BAFFC9', '#BAE1FF', '#E8BAFF', '#FFC1C1', '#D6A2E8']
    line_color = '#FF99CC'
    profit_up_color, profit_down_color = '#FF9999', '#99CCFF' 
    gold_highlight = '#FFD700' 
else:
    bg_color, text_color = "#F8F9FA", "#212529"
    df_bg, df_text = "#FFFFFF", "#212529"
    chart_template = "plotly_white"
    pastel_colors = ['#FF8A98', '#FFB677', '#E5E570', '#85E39C', '#8AC4FF', '#C785FF', '#FF9B9B', '#C274D8']
    line_color = '#FF6699'
    profit_up_color, profit_down_color = '#E63946', '#457B9D'
    gold_highlight = '#B8860B'

st.markdown(f"""
    <style>
    .stApp {{ background-color: {bg_color}; }}
    .stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp label, .stApp span {{
        color: {text_color} !important;
    }}
    [data-testid="stHeader"] {{ background-color: rgba(0,0,0,0); }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 2px; }}
    .stTabs [data-baseweb="tab"] {{ padding-top: 10px; padding-bottom: 10px; }}
    /* 🌟 모바일 콤팩트 전광판을 위한 CSS 마법 (위아래 여백 깎기 & 글씨 크기 최적화) */
    [data-testid="metric-container"] {{ padding: 10px; }}
    [data-testid="stMetricValue"] {{ font-size: 1.2rem; font-weight: bold; }}
    [data-testid="stMetricDelta"] {{ font-size: 0.85rem; }}
    </style>
""", unsafe_allow_html=True)

# --- 2. 🌟 [신규] 글로벌 매크로 전광판 데이터 로드 (에러 철통 방어) ---
@st.cache_data(ttl=300) # 5분간 데이터 캐싱 (야후 API 차단 방지)
def get_macro_indicators():
    tickers = {
        "코스피": "^KS11",
        "나스닥 선물": "NQ=F",
        "반도체 (SOX)": "^SOX",
        "원/달러": "KRW=X",
        "이더리움": "ETH-USD",
        "미국 공포 (VIX)": "^VIX",
        "한국 공포 (VKOSPI)": "^VKOSPI"
    }
    results = {}
    for name, ticker in tickers.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d").dropna(subset=['Close'])
            if len(hist) >= 2:
                curr = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2])
                results[name] = {"current": curr, "change_pct": ((curr - prev) / prev) * 100, "change_val": curr - prev}
            elif len(hist) == 1:
                results[name] = {"current": float(hist['Close'].iloc[0]), "change_pct": 0.0, "change_val": 0.0}
            else: results[name] = None
        except: results[name] = None
    return results

# --- 3. 데이터 로드 및 1차 무결점 정제 ---
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
        try:
            df_pnl = pd.DataFrame(client.open(SHEET_NAME).worksheet("실현손익").get_all_records())
        except: df_pnl = pd.DataFrame()
            
        return df_tx, df_history, df_pnl
    except Exception as e:
        st.error(f"⚠️ 구글 시트 연결 오류: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# 🚨 캐시 반환 객체를 직접 수정하지 않도록 깊은 복사(Copy) 적용
df_raw, df_history_raw, df_pnl_raw = load_data()
df = df_raw.copy()
df_history = df_history_raw.copy()
df_pnl = df_pnl_raw.copy()

@st.cache_data(ttl=60)
def get_market_data(ticker):
    try:
        if not ticker or not isinstance(ticker, str): return 0.0, 0.0
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d").dropna(subset=['Close'])
        if len(hist) >= 2: return float(hist['Close'].iloc[-1]), ((float(hist['Close'].iloc[-1]) - float(hist['Close'].iloc[-2])) / float(hist['Close'].iloc[-2])) * 100
        elif len(hist) == 1: return float(hist['Close'].iloc[0]), 0.0
        return 0.0, 0.0
    except: return 0.0, 0.0

@st.cache_data(ttl=86400) 
def get_dividend_history(ticker):
    try:
        if not ticker or not isinstance(ticker, str): return pd.Series(dtype=float)
        hist = yf.Ticker(ticker).history(period="2y")
        if 'Dividends' in hist.columns:
            return hist[hist['Dividends'] > 0]['Dividends']
    except: pass
    return pd.Series(dtype=float)

# =========================================================
# 🌟 [전광판 UI 렌더링] 포트폴리오 계산 전에 상단에 띄웁니다!
# =========================================================
macro_data = get_macro_indicators()

st.markdown("**🌐 글로벌 매크로 전광판**")
m1, m2, m3, m4 = st.columns(4)
m5, m6, m7, m8 = st.columns(4) # 비율을 맞추기 위해 4칸으로 분할 후 1칸은 비움

def render_metric(col, label, key, prefix="", suffix="", inverse=False):
    if key in macro_data and macro_data[key] is not None:
        val = macro_data[key]["current"]
        d_val = macro_data[key]["change_val"]
        d_pct = macro_data[key]["change_pct"]
        # VIX 지수처럼 오르는게 '나쁜' 지표는 inverse=True를 주어 색상을 반전시킵니다.
        d_color = "inverse" if inverse else "normal"
        col.metric(label=label, value=f"{prefix}{val:,.2f}{suffix}", delta=f"{d_val:+,.2f} ({d_pct:+.2f}%)", delta_color=d_color)
    else:
        col.metric(label=label, value="데이터 지연", delta="-")

render_metric(m1, "🇰🇷 코스피", "코스피")
render_metric(m2, "🇺🇸 나스닥 선물", "나스닥 선물")
render_metric(m3, "💾 반도체 (SOX)", "반도체 (SOX)")
render_metric(m4, "💱 원/달러", "원/달러", suffix="원")

render_metric(m5, "💎 이더리움", "이더리움", prefix="$")
render_metric(m6, "🥶 미국 공포 (VIX)", "미국 공포 (VIX)", inverse=True) # 색상 반전 (상승=위험)
render_metric(m7, "🥶 한국 공포 (VKOSPI)", "한국 공포 (VKOSPI)", inverse=True) # 색상 반전 (상승=위험)
# m8은 모바일 배열의 아름다움을 위해 빈 공간으로 둡니다.

st.markdown("---")

# =========================================================
# 🌟 내 포트폴리오 계산 로직
# =========================================================
if df.empty:
    st.info("아직 거래 내역이 없습니다. 텔레그램 봇으로 거래를 기록해 주세요.")
else:
    required_cols = ['수량', '거래단가', '거래종류', '자산군', '종목명', '티커', '통화']
    for col in required_cols:
        if col not in df.columns: df[col] = 0 if col in ['수량', '거래단가'] else ""

    df['수량'] = pd.to_numeric(df['수량'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['거래단가'] = pd.to_numeric(df['거래단가'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    df['계산용수량'] = df.apply(lambda x: x['수량'] if str(x['거래종류']).strip() == '매수' else -x['수량'], axis=1)
    holdings = df.groupby(['자산군', '종목명', '티커', '통화'])['계산용수량'].sum().reset_index()
    holdings = holdings[holdings['계산용수량'] > 0].copy()
    
    holdings['자산군'] = holdings['자산군'].replace('', '기타').fillna('기타')
    holdings['종목명'] = holdings['종목명'].replace('', '알수없음').fillna('알수없음')

    buy_df = df[df['거래종류'] == '매수'].copy()
    buy_df['결제금액'] = buy_df['수량'] * buy_df['거래단가']
    avg_cost_df = buy_df.groupby(['종목명', '티커'])[['결제금액', '수량']].sum().reset_index()
    
    avg_cost_df['평균매입단가'] = (avg_cost_df['결제금액'] / avg_cost_df['수량']).replace([np.inf, -np.inf], 0).fillna(0)
    
    holdings = pd.merge(holdings, avg_cost_df[['종목명', '티커', '평균매입단가']], on=['종목명', '티커'], how='left')
    holdings['평균매입단가'] = holdings['평균매입단가'].fillna(0)

    # 🚨 1450원 환율 기본값 (전광판과 동일하게)
    usd_krw_price = macro_data.get("원/달러", {}).get("current", 0.0) if macro_data.get("원/달러") else 0.0
    if usd_krw_price <= 0.0: usd_krw_price = 1450.0

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

    holdings['평가액(원)'] = total_values_krw
    holdings['손익(원)'] = profit_amounts
    holdings['수익률(%)'] = profit_pcts
    holdings['평가액(만원)'] = (pd.Series(total_values_krw) / 10000).fillna(0).astype(int)

    total_asset = sum(total_values_krw)
    total_cost = sum(total_costs_krw)
    total_profit = total_asset - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0

    st.metric(label="💰 총 자산 (원)", value=f"{total_asset:,.0f} 원", delta=f"총 평가손익: {total_profit:,.0f} 원 ({total_profit_pct:,.2f}%)")

    t_sell_krw, t_sell_usd_val, t_sell_usd_krw = 0, 0.0, 0
    t_div_krw, t_div_usd_val, t_div_usd_krw = 0, 0.0, 0
    total_realized_krw = 0

    if not df_pnl.empty and '실현손익(원)' in df_pnl.columns:
        if '분류' not in df_pnl.columns: df_pnl['분류'] = ''
        if '통화' not in df_pnl.columns: df_pnl['통화'] = ''
        if '실현손익(달러)' not in df_pnl.columns: df_pnl['실현손익(달러)'] = 0.0
        
        df_pnl['실현손익(원)'] = pd.to_numeric(df_pnl['실현손익(원)'], errors='coerce').fillna(0)
        df_pnl['실현손익(달러)'] = pd.to_numeric(df_pnl['실현손익(달러)'], errors='coerce').fillna(0)
        df_pnl['분류'] = df_pnl.apply(lambda x: x['분류'] if str(x['분류']).strip() != '' else ('배당' if x.get('매도수량', 1) == 0 else '매도'), axis=1)
        
        currency_map = df.drop_duplicates('티커').set_index('티커')['통화'].to_dict()
        df_pnl['통화'] = df_pnl.apply(lambda x: x['통화'] if str(x['통화']).strip() != '' else currency_map.get(x['티커'], 'KRW'), axis=1)
        
        def calculate_today_krw(row):
            krw, usd, curr = row['실현손익(원)'], row['실현손익(달러)'], row['통화']
            if curr == 'USD':
                if usd == 0 and krw != 0: usd = krw / 1450.0  
                return usd, usd * usd_krw_price
            return 0.0, krw

        df_pnl[['실현손익(외화)', '현재환율적용_실현손익(원)']] = df_pnl.apply(lambda row: pd.Series(calculate_today_krw(row)), axis=1)
        df_pnl['차트분류'] = df_pnl.apply(lambda x: f"{x['분류']} ({'국내' if x['통화']=='KRW' else '해외'})", axis=1)
        df_pnl['실현손익_차트용(만원)'] = (df_pnl['현재환율적용_실현손익(원)'] / 10000).fillna(0).astype(int)
        
        df_pnl['날짜'] = pd.to_datetime(df_pnl['날짜'], errors='coerce')
        df_pnl = df_pnl.dropna(subset=['날짜']).copy() 
        df_pnl['일자'] = df_pnl['날짜'].dt.strftime('%m-%d')
        df_pnl['월'] = df_pnl['날짜'].dt.strftime('%Y-%m')
        df_pnl['연'] = df_pnl['날짜'].dt.strftime('%Y')

        t_sell_krw = df_pnl[(df_pnl['분류'] == '매도') & (df_pnl['통화'] == 'KRW')]['현재환율적용_실현손익(원)'].sum()
        t_sell_usd_val = df_pnl[(df_pnl['분류'] == '매도') & (df_pnl['통화'] == 'USD')]['실현손익(외화)'].sum()
        t_sell_usd_krw = df_pnl[(df_pnl['분류'] == '매도') & (df_pnl['통화'] == 'USD')]['현재환율적용_실현손익(원)'].sum()
        
        t_div_krw = df_pnl[(df_pnl['분류'] == '배당') & (df_pnl['통화'] == 'KRW')]['현재환율적용_실현손익(원)'].sum()
        t_div_usd_val = df_pnl[(df_pnl['분류'] == '배당') & (df_pnl['통화'] == 'USD')]['실현손익(외화)'].sum()
        t_div_usd_krw = df_pnl[(df_pnl['분류'] == '배당') & (df_pnl['통화'] == 'USD')]['현재환율적용_실현손익(원)'].sum()
        
        total_realized_krw = t_sell_krw + t_sell_usd_krw + t_div_krw + t_div_usd_krw

    st.markdown("**💸 실현 손익 및 배당금 요약** <span style='font-size:12px; color:gray;'>(오늘 환율 적용)</span>", unsafe_allow_html=True)
    
    summary_data = {
        "손익": ["💡 총계", "📉 매도", "🎁 배당"],
        "합계 (환산)": [f"{int(total_realized_krw):,.0f}", f"{int(t_sell_krw + t_sell_usd_krw):,.0f}", f"{int(t_div_krw + t_div_usd_krw):,.0f}"],
        "국내 (원)": [f"{int(t_sell_krw + t_div_krw):,.0f}", f"{int(t_sell_krw):,.0f}", f"{int(t_div_krw):,.0f}"],
        "해외 (달러)": [f"${t_sell_usd_val + t_div_usd_val:,.2f}", f"${t_sell_usd_val:,.2f}", f"${t_div_usd_val:,.2f}"]
    }
    df_summary = pd.DataFrame(summary_data)
    
    def style_summary(x):
        styles = pd.DataFrame('', index=x.index, columns=x.columns)
        styles['손익'] = 'font-weight: bold;'     
        styles.loc[0, '합계 (환산)'] = f'color: {gold_highlight};'
        return styles

    st.dataframe(
        df_summary.style
        .set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '15px', 'text-align': 'center'})
        .apply(style_summary, axis=None),
        use_container_width=True, hide_index=True
    )

    st.markdown("---")

    # =========================================================
    # 🌟 차트 분석 탭
    # =========================================================
    st.markdown("**📊 포트폴리오 시각화**")
    
    tab_chart1, tab_chart2, tab_chart3 = st.tabs(["🥧 자산 비중", "📈 자산 추이", "📊 실현 손익"])

    with tab_chart1:
        pc1, pc2 = st.columns(2)
        text_font_setting = dict(color='black', size=20, family="sans-serif")
        
        with pc1:
            st.markdown("<div style='text-align: center; font-size: 13px; color: gray;'>[ 자산군별 비중 ]</div>", unsafe_allow_html=True)
            fig1 = px.pie(holdings.groupby('자산군')['평가액(만원)'].sum().reset_index(), values='평가액(만원)', names='자산군', hole=0.4, color_discrete_sequence=pastel_colors)
            fig1.update_traces(textposition='inside', texttemplate='<b>%{label}</b><br><b>%{percent:.1%}</b>', textfont=text_font_setting)
            fig1.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig1, use_container_width=True)
            
        with pc2:
            st.markdown("<div style='text-align: center; font-size: 13px; color: gray;'>[ 🌟 심층 썬버스트 차트 ]</div>", unsafe_allow_html=True)
            holdings_positive = holdings[holdings['평가액(만원)'] > 0].copy()
            if not holdings_positive.empty:
                fig_sun = px.sunburst(holdings_positive, path=['자산군', '종목명'], values='평가액(만원)', color_discrete_sequence=pastel_colors)
                fig_sun.update_traces(textinfo='label+percent entry', textfont=dict(color='black', size=15))
                fig_sun.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig_sun, use_container_width=True)
            else:
                st.caption("표시할 양수(+) 자산이 없습니다.")

    with tab_chart2:
        if not df_history.empty and df_history.shape[1] >= 2:
            df_history['총자산(만원)'] = pd.to_numeric(df_history[df_history.columns[1]], errors='coerce').fillna(0) / 10000
            fig_line = px.line(df_history, x='날짜', y='총자산(만원)', markers=True)
            fig_line.update_traces(line_color=line_color, marker_color=line_color)
            fig_line.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.caption("아직 데이터가 부족하여 차트를 그릴 수 없습니다.")

    with tab_chart3:
        if not df_pnl.empty and '실현손익(원)' in df_pnl.columns:
            period = st.radio("보기 옵션", ["월별", "연별", "일별"], horizontal=True, label_visibility="collapsed")
            
            def plot_pnl_bar(data, x_col):
                color_map = {'매도 (국내)': '#FF6B6B', '매도 (해외)': '#FFA07A', '배당 (국내)': '#4DABF7', '배당 (해외)': '#51CF66'}
                fig = px.bar(data, x=x_col, y='실현손익_차트용(만원)', color='차트분류', text='실현손익_차트용(만원)', color_discrete_map=color_map)
                fig.update_traces(texttemplate='%{text:,.0f}', textfont_size=12, textangle=0, textposition="outside", cliponaxis=False)
                fig.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10), barmode='relative', legend_title_text='')
                st.plotly_chart(fig, use_container_width=True)

            if period == "월별": plot_pnl_bar(df_pnl.groupby(['월', '차트분류'])['실현손익_차트용(만원)'].sum().reset_index(), '월')
            elif period == "연별": plot_pnl_bar(df_pnl.groupby(['연', '차트분류'])['실현손익_차트용(만원)'].sum().reset_index(), '연')
            else: plot_pnl_bar(df_pnl.groupby(['일자', '차트분류'])['실현손익_차트용(만원)'].sum().reset_index(), '일자')
        else:
            st.caption("아직 매도/배당 기록이 없습니다.")

    st.markdown("---")

    # =========================================================
    # 🌟 상세 데이터 탭 
    # =========================================================
    st.markdown("**📋 상세 데이터**")
    tab_data1, tab_data2, tab_data3 = st.tabs(["📊 자산 상세", "🧾 실현 손익", "🔮 향후 6개월 배당 예측"])

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

    with tab_data2:
        if not df_pnl.empty and '실현손익(원)' in df_pnl.columns:
            display_pnl = df_pnl[['날짜', '차트분류', '종목명', '통화', '실현손익(외화)', '현재환율적용_실현손익(원)']].copy()
            display_pnl['날짜'] = display_pnl['날짜'].dt.strftime('%m-%d')
            display_pnl.sort_values('날짜', ascending=False, inplace=True)
            
            display_pnl['달러수익'] = display_pnl.apply(lambda x: f"${x['실현손익(외화)']:,.2f}" if x['통화'] == 'USD' else "-", axis=1)
            display_pnl.rename(columns={'현재환율적용_실현손익(원)': '환산수익(원)'}, inplace=True)
            display_pnl = display_pnl[['날짜', '차트분류', '종목명', '달러수익', '환산수익(원)']]
            
            def style_pnl(val):
                if isinstance(val, (int, float)):
                    color = profit_up_color if val > 0 else profit_down_color if val < 0 else text_color
                    return f'color: {color}; font-weight: bold;'
                return ''
                
            st.dataframe(
                display_pnl.style
                .set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '14px'})
                .format({'환산수익(원)': '{:,.0f}'})
                .map(style_pnl, subset=['환산수익(원)']),
                use_container_width=True, hide_index=True
            )
        else:
            st.caption("표시할 데이터가 없습니다.")
            
    with tab_data3:
        kst = pytz.timezone('Asia/Seoul')
        now = datetime.datetime.now(kst)
        next_6_months = []
        for i in range(1, 7):
            m = now.month + i
            y = now.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            next_6_months.append((y, m))
            
        expected_records = []
        total_6_months_krw = 0.0
        
        with st.spinner("과거 2년치 배당 이력을 스캔하여 향후 6개월의 현금흐름을 예측 중입니다..."):
            for _, row in holdings.iterrows():
                ticker = row['티커']
                name = row['종목명']
                qty = row['계산용수량']
                curr = row['통화']
                
                divs = get_dividend_history(ticker)
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
                        
                        expected_records.append({
                            '연월': f"{y}년 {m:02d}월",
                            '월': m,
                            '종목명': name,
                            '수량': qty, 
                            '통화': curr,
                            '예상 주당배당금': dps,
                            '예상 배당금': expected_div,
                            '환산 예상금액(원)': expected_krw
                        })
        
        if expected_records:
            next_div_df = pd.DataFrame(expected_records)
            st.markdown(f"**📈 향후 6개월 누적 예상 배당금:** 약 {int(total_6_months_krw):,.0f} 원 <span style='font-size:12px; color:gray;'>(오늘 환율 적용)</span>", unsafe_allow_html=True)
            
            fig_next = px.bar(next_div_df, x='연월', y='환산 예상금액(원)', color='종목명', 
                              hover_data={'예상 배당금': ':.2f', '통화': True},
                              color_discrete_sequence=pastel_colors)
            fig_next.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=20, b=10, l=10, r=10), barmode='stack')
            st.plotly_chart(fig_next, use_container_width=True)
            
            st.markdown("**🧾 향후 6개월 종목별 세부 배당 캘린더**")
            display_next = next_div_df.copy()
            display_next['예상 배당금'] = display_next.apply(lambda x: f"${x['예상 배당금']:,.2f}" if x['통화']=='USD' else f"{x['예상 배당금']:,.0f}원", axis=1)
            display_next['주당 배당금'] = display_next.apply(lambda x: f"${x['예상 주당배당금']:,.2f}" if x['통화']=='USD' else f"{x['예상 주당배당금']:,.0f}원", axis=1)
            
            display_next.sort_values(by=['연월', '환산 예상금액(원)'], ascending=[True, False], inplace=True)
            
            st.dataframe(
                display_next[['연월', '종목명', '수량', '주당 배당금', '예상 배당금', '환산 예상금액(원)']].style
                .set_properties(**{'background-color': df_bg, 'color': df_text, 'font-size': '13px'})
                .format({'수량': '{:,.1f}', '환산 예상금액(원)': '{:,.0f}원'}),
                use_container_width=True, hide_index=True
            )
            st.caption("※ 과거 2년 치 배당 패턴을 분석한 결과이며, 데이터 제공 지연으로 누락될 수 있습니다.")
        else:
            st.caption("보유 종목 중 향후 6개월 내에 배당이 확실하게 예정된 종목이 없습니다.")
