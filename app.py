import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="مراقب استراتيجية فيصل", page_icon="📈", layout="centered")

# ---------- تنسيق عام (RTL + ألوان قريبة من اللوحة الأصلية) ----------
st.markdown("""
<style>
html, body, [class*="css"]  { direction: rtl; text-align: right; }
.block-container { padding-top: 2rem; }
.metric-card {
    background:#f7f8f8; border-radius:12px; padding:14px 16px; margin-bottom:10px;
}
.header-box {
    background: linear-gradient(180deg,#0d2b2b,#0a2222);
    color:white; padding:20px; border-radius:16px; margin-bottom:20px;
}
.badge-orange {
    background:#fdeecb; color:#b8860b; font-weight:700;
    padding:6px 14px; border-radius:20px; display:inline-block;
}
.badge-green {
    background:#e6f4ef; color:#0f8a6b; font-weight:700;
    padding:6px 14px; border-radius:20px; display:inline-block;
}
</style>
""", unsafe_allow_html=True)

st.title("📈 مراقب استراتيجية فيصل")
st.caption("أدخل رمز أي سهم وشوف مؤشرات ما بعد التقسيم تلقائيًا")

# ---------- إدخال المستخدم ----------
col1, col2 = st.columns([2, 1])
with col1:
    ticker_input = st.text_input("رمز السهم", value="AAPL").strip().upper()
with col2:
    lookback_days = st.number_input("عدد أيام البحث", min_value=60, max_value=1500, value=400, step=10)

run = st.button("🔍 جلب البيانات وتحليلها", use_container_width=True)

if run and ticker_input:
    with st.spinner("يجيب البيانات..."):
        try:
            ticker_obj = yf.Ticker(ticker_input)
            end = datetime.today()
            start = end - timedelta(days=int(lookback_days))
            daily = ticker_obj.history(start=start, end=end, interval="1d", auto_adjust=False)

            if daily.empty:
                st.error("ما قدرت أجيب بيانات لهذا الرمز. تأكد إنه صحيح.")
                st.stop()

            try:
                intraday = ticker_obj.history(period="60d", interval="1h", auto_adjust=False)
            except Exception:
                intraday = pd.DataFrame()

            info = ticker_obj.info if hasattr(ticker_obj, "info") else {}
            company_name = info.get("longName") or info.get("shortName") or ticker_input

            splits = ticker_obj.splits
            if len(splits):
                tz = splits.index.tz
                splits = splits[splits.index >= pd.Timestamp(start, tz=tz)]

            current_price = daily['Close'].iloc[-1]

            # ---------- الهيدر ----------
            st.markdown(f"""
            <div class="header-box">
                <div style="font-size:13px;opacity:.7;">{ticker_input}</div>
                <div style="font-size:26px;font-weight:700;">{company_name}</div>
                <div style="font-size:22px;margin-top:8px;">السعر الحالي: ${current_price:.3f}</div>
            </div>
            """, unsafe_allow_html=True)

            if len(splits) == 0:
                st.warning(f"لا يوجد تقسيم مسجل لسهم {ticker_input} خلال آخر {lookback_days} يوم.")
            else:
                split_date = splits.index[-1]
                split_ratio = splits.iloc[-1]

                post_split = daily[daily.index >= split_date]
                open_on_split_day = post_split['Open'].iloc[0]
                days_since_split = (pd.Timestamp.now(tz=post_split.index.tz) - split_date).days

                high_post_split = post_split['High'].max()
                high_post_split_date = post_split['High'].idxmax()
                low_post_split = post_split['Low'].min()
                low_post_split_date = post_split['Low'].idxmin()

                distance_from_low_pct = (current_price - low_post_split) / low_post_split * 100
                distance_from_high_pct = (high_post_split - current_price) / high_post_split * 100

                high_first_4h = np.nan
                if not intraday.empty:
                    window_start = split_date
                    window_end = split_date + pd.Timedelta(hours=4)
                    first_4h = intraday[(intraday.index >= window_start) & (intraday.index <= window_end)]
                    if not first_4h.empty:
                        high_first_4h = first_4h['High'].max()

                # ---------- EMA ----------
                ema_periods = [20, 50, 100, 200]
                for p in ema_periods:
                    daily[f'EMA{p}'] = daily['Close'].ewm(span=p, adjust=False).mean()
                latest = daily.iloc[-1]
                ema_status = {p: latest['Close'] < latest[f'EMA{p}'] for p in ema_periods if not np.isnan(latest[f'EMA{p}'])}
                below_all_ema = all(ema_status.values()) if ema_status else False

                # ---------- ثبات فوق الدعم ----------
                support_level = low_post_split
                recent_closes = daily['Close'].tail(10)
                closes_above_support = (recent_closes > support_level).astype(int)
                consecutive_above = 0
                for v in closes_above_support[::-1]:
                    if v == 1:
                        consecutive_above += 1
                    else:
                        break
                sessions_needed = 2
                remaining = max(0, sessions_needed - consecutive_above)

                # ---------- درجة الجاهزية ----------
                score = 0
                score += 30 if below_all_ema else 0
                support_test_ok = distance_from_low_pct < 5
                score += 30 if support_test_ok else 0
                score += min(consecutive_above, sessions_needed) / sessions_needed * 40

                # ---------- عرض النتائج ----------
                st.subheader("بيانات التقسيم ومنطقة الهدف")
                c1, c2, c3 = st.columns(3)
                c1.metric("الدعم المعتمد", f"${support_level:.3f}")
                c2.metric("المسافة عن الدعم", f"{distance_from_low_pct:.1f}%")
                c3.metric("نسبة التقسيم", f"1:{int(split_ratio)}")

                colA, colB = st.columns(2)
                with colA:
                    st.markdown(f"""
                    <div class="metric-card"><b>تاريخ التقسيم:</b> {split_date.date()}</div>
                    <div class="metric-card"><b>افتتاح يوم التقسيم:</b> ${open_on_split_day:.3f}</div>
                    <div class="metric-card"><b>منذ التقسيم:</b> {days_since_split} يوم</div>
                    <div class="metric-card"><b>أعلى قمة بعد التقسيم:</b> ${high_post_split:.3f} ({high_post_split_date.date()})</div>
                    """, unsafe_allow_html=True)
                with colB:
                    high4h_txt = f"${high_first_4h:.3f}" if not np.isnan(high_first_4h) else "غير متوفر"
                    st.markdown(f"""
                    <div class="metric-card"><b>أعلى أول 4 ساعات:</b> {high4h_txt}</div>
                    <div class="metric-card"><b>أدنى قاع بعد التقسيم:</b> ${low_post_split:.3f} ({low_post_split_date.date()})</div>
                    <div class="metric-card"><b>المسافة عن القمة:</b> {distance_from_high_pct:.1f}%</div>
                    <div class="metric-card"><b>الجلسات المتتالية فوق الدعم:</b> {consecutive_above}</div>
                    """, unsafe_allow_html=True)

                st.subheader("مراقب استراتيجية فيصل")
                b1, b2 = st.columns(2)
                with b1:
                    if below_all_ema:
                        st.markdown('<span class="badge-green">✓ أسفل جميع EMA</span>', unsafe_allow_html=True)
                    else:
                        st.markdown('<span class="badge-orange">✗ ليس أسفل جميع EMA</span>', unsafe_allow_html=True)
                with b2:
                    if remaining == 0:
                        st.markdown('<span class="badge-green">دعم مؤكد</span>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<span class="badge-orange">ينقصه {remaining} جلسة ثبات</span>', unsafe_allow_html=True)

                st.markdown("### درجة الجاهزية")
                st.progress(min(int(score), 100) / 100)
                st.write(f"**{score:.0f}/100**")

                with st.expander("تفاصيل EMA"):
                    for p in ema_periods:
                        if p in [k for k in ema_status]:
                            val = latest[f'EMA{p}']
                            st.write(f"EMA{p}: {val:.3f} — {'السعر تحته ✓' if ema_status[p] else 'السعر فوقه ✗'}")

                with st.expander("عرض البيانات اليومية الخام"):
                    st.dataframe(daily.tail(30))

        except Exception as e:
            st.error(f"صار خطأ: {e}")
