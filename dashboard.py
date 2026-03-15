import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
import plotly.express as px
from oauth2client.service_account import ServiceAccountCredentials
import json

# --- 1. 기본 설정 (아이콘 및 제목) ---
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
    pastel_colors = ['#FFB3BA', '#FFDFBA', '#FFFFBA', '#BAFFC9', '#BAE1FF', '#E8BAFF']
    line_color = '#FF99CC'
    profit_up_color, profit_down_color = '#FF9999', '#99CCFF' 
    gold_highlight = '#FFD700' 
else:
    bg_color, text_color = "#F8F9FA", "#212529"
    df_bg, df_text = "#FFFFFF", "#212529"
    chart_template = "plotly_white"
    pastel_colors = ['#FF8A98', '#FFB677', '#E5E570', '#85E39C', '#8AC4FF', '#C785FF']
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
    </style>
""", unsafe_allow_html=True)

# --- 2. 데이터 로드 및 전처리 (무결점 방어 로직) ---
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
        try:
            sheet_pnl = client.open(SHEET_NAME).worksheet("실현손익")
            df_pnl = pd.DataFrame(sheet_pnl.get_all_records())
        except:
            df_pnl = pd.DataFrame()
            
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
        if len(hist) >= 2: return float(hist['Close'].iloc[-1]), ((float(hist['Close'].iloc[-1]) - float(hist['Close'].iloc[-2])) / float(hist['Close'].iloc[-2])) * 100
        elif len(hist) == 1: return float(hist['Close'].iloc[0]), 0.0
        return 0.0, 0.0
    except: return 0.0, 0.0

if df.empty:
    st.info("아직 거래 내역이 없습니다.")
else:
    # 🚨 콤마 섞인 문자열 등 데이터 오류 철통 방어
    for col in ['수량', '거래단가']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    df['계산용수량'] = df.apply(lambda x: x['수량'] if x['거래종류'] == '매수' else -x['수량'], axis=1)
    holdings = df.groupby(['자산군', '종목명', '티커', '통화'])['계산용수량'].sum().reset_index()
    holdings = holdings[holdings['계산용수량'] > 0].copy()
    
    # 🚨 썬버스트 차트 파괴 방지를 위한 빈칸(NaN) 채우기
    holdings['자산군'] = holdings['자산군'].replace('', '기타').fillna('기타')
    holdings['종목명'] = holdings['종목명'].replace('', '알수없음').fillna('알수없음')

    buy_df = df[df['거래종류'] == '매수'].copy()
    buy_df['결제금액'] = buy_df['수량'] * buy_df['거래단가']
    avg_cost_df = buy_df.groupby(['종목명', '티커'])[['결제금액', '수량']].sum().reset_index()
    avg_cost_df['평균매입단가'] = avg_cost_df['결제금액'] / avg_cost_df['수량']
    
    holdings = pd.merge(holdings, avg_cost_df[['종목명', '티커', '평균매입단가']], on=['종목명', '티커'], how='left')
    holdings['평균매입단가'] = holdings['평균매입단가'].fillna(0)

    # 🚨 환율 0원 파괴 방어
    usd_krw_price, _ = get_market_data("KRW=X")
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
    holdings['평가액(만원)'] = (pd.Series(total_values_krw) / 10000).astype(int)

    total_asset = sum(total_values_krw)
    total_cost = sum(total_costs_krw)
    total_profit = total_asset - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0

    st.metric(label="💰 총 자산 (원)", value=f"{total_asset:,.0f} 원", delta=f"총 평가손익: {total_profit:,.0f} 원 ({total_profit_pct:,.2f}%)")

    # --- 실현 손익 데이터 처리 ---
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
                if usd == 0 and krw != 0: usd = krw / 1350.0  
                return usd, usd * usd_krw_price
            return 0.0, krw

        df_pnl[['실현손익(외화)', '현재환율적용_실현손익(원)']] = df_pnl.apply(lambda row: pd.Series(calculate_today_krw(row)), axis=1)
        df_pnl['차트분류'] = df_pnl.apply(lambda x: f"{x['분류']} ({'국내' if x['통화']=='KRW' else '해외'})", axis=1)
        df_pnl['실현손익_차트용(만원)'] = (df_pnl['현재환율적용_실현손익(원)'] / 10000).astype(int)
        
        df_pnl['날짜'] = pd.to_datetime(df_pnl['날짜'], errors='coerce')
        df_pnl = df_pnl.dropna(subset=['날짜']) # 날짜 오류 파괴 방어
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

    # 🌟 실현손익 요약 표
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
            # 🌟 [기능 5] 자산군 -> 종목명으로 이어지는 썬버스트 차트 도입!
            holdings_positive = holdings[holdings['평가액(만원)'] > 0].copy()
            if not holdings_positive.empty:
                fig_sun = px.sunburst(holdings_positive, path=['자산군', '종목명'], values='평가액(만원)', color_discrete_sequence=pastel_colors)
                fig_sun.update_traces(textinfo='label+percent entry', textfont=dict(color='black', size=15))
                fig_sun.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig_sun, use_container_width=True)
            else:
                st.caption("표시할 양수(+) 자산이 없습니다.")

    with tab_chart2:
        if not df_history.empty:
            df_history['총자산(만원)'] = pd.to_numeric(df_history[df_history.columns[1]], errors='coerce').fillna(0) / 10000
            fig_line = px.line(df_history, x='날짜', y='총자산(만원)', markers=True)
            fig_line.update_traces(line_color=line_color, marker_color=line_color)
            fig_line.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.caption("아직 '일별기록' 시트에 데이터가 없습니다.")

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
    # 🌟 상세 데이터 탭 (기능 3: 배당 분석 탭 추가)
    # =========================================================
    st.markdown("**📋 상세 데이터**")
    tab_data1, tab_data2, tab_data3 = st.tabs(["📊 자산 상세", "🧾 실현 손익", "🎁 배당 분석"])

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
        # 🌟 [기능 3] 배당금 캘린더 및 예측 시스템
        if not df_pnl.empty:
            div_df = df_pnl[df_pnl['분류'] == '배당'].copy()
            if not div_df.empty:
                div_monthly = div_df.groupby('월')['현재환율적용_실현손익(원)'].sum().reset_index()
                div_monthly.rename(columns={'현재환율적용_실현손익(원)': '배당금(원)'}, inplace=True)
                
                # 예측 로직: 최근 12개월 평균값 (없으면 전체 평균)
                avg_div = div_monthly['배당금(원)'].mean()
                
                st.markdown(f"**📈 다음 달 예상 배당금:** 약 {int(avg_div):,.0f} 원 (환율 적용)")
                
                fig_div = px.bar(div_monthly, x='월', y='배당금(원)', text='배당금(원)')
                fig_div.update_traces(marker_color='#4DABF7', texttemplate='%{text:,.0f}', textposition="outside", cliponaxis=False)
                fig_div.update_layout(template=chart_template, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=20, b=10, l=10, r=10))
                st.plotly_chart(fig_div, use_container_width=True)
            else:
                st.caption("아직 기록된 배당금 내역이 없습니다.")
        else:
            st.caption("아직 기록된 배당금 내역이 없습니다.")
