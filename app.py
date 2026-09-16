import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="مراقب استراتيجية فيصل", page_icon="📈", layout="centered")

# ---------- تنسيق عام (RTL + ألوان ثابتة تشتغل بأي وضع - فاتح أو غامق) ----------
st.markdown("""
<style>
html, body, [class*="css"]  { direction: rtl; text-align: right; }
.block-container { padding-top: 2rem; }

.metric-card {
    background:#f7f8f8 !important;
    color:#1a2323 !important;
    border-radius:12px;
    padding:14px 16px;
    margin-bottom:10px;
    border:1px solid #e4e6e6;
}
.metric-card b { color:#0d2b2b !important; }

.header-box {
    background: linear-gradient(180deg,#0d2b2b,#0a2222);
    color:#ffffff !important;
    padding:20px; border-radius:16px; margin-bottom:20px;
}
.header-box * { color:#ffffff !important; }

.badge-orange {
    background:#fdeecb !important; color:#b8860b !important; font-weight:700;
    padding:6px 14px; border-radius:20px; display:inline-block;
}
.badge-green {
    background:#e6f4ef !important; color:#0f8a6b !important; font-weight:700;
    padding:6px 14px; border-radius:20px; display:inline-block;
}
.badge-grey {
    background:#eceeee !important; color:#5a6666 !important; font-weight:700;
    padding:6px 14px; border-radius:20px; display:inline-block;
}
</style>
""", unsafe_allow_html=True)

st.title("📈 مراقب استراتيجية فيصل")
st.caption("أدخل رمز أي سهم (تقسّم أو ما تقسّم) وشوف مؤشراته تلقائيًا")

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

            info = {}
            try:
                info = ticker_obj.info
            except Exception:
                info = {}
            company_name = info.get("longName") or info.get("shortName") or ticker_input

            current_price = daily['Close'].iloc[-1]
            prev_close = daily['Close'].iloc[-2] if len(daily) > 1 else current_price
            change_pct = (current_price - prev_close) / prev_close * 100 if prev_close else 0

            # ---------- الهيدر ----------
            change_color = "#4ade80" if change_pct >= 0 else "#f87171"
            change_sign = "+" if change_pct >= 0 else ""
            st.markdown(f"""
            <div class="header-box">
                <div style="font-size:13px;opacity:.8;">{ticker_input}</div>
                <div style="font-size:26px;font-weight:700;">{company_name}</div>
                <div style="font-size:22px;margin-top:8px;">
                    ${current_price:.3f}
                    <span style="font-size:14px;color:{change_color};">({change_sign}{change_pct:.2f}%)</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ---------- هل فيه تقسيم؟ (اختياري - ما يوقف التحليل لو ما فيه) ----------
            splits = ticker_obj.splits
            has_split = False
            if len(splits):
                tz = splits.index.tz
                recent_splits = splits[splits.index >= pd.Timestamp(start, tz=tz)]
                if len(recent_splits) > 0:
                    has_split = True
                    split_date = recent_splits.index[-1]
                    split_ratio = recent_splits.iloc[-1]

            # ---------- تحديد فترة "منذ الحدث" ----------
            if has_split:
                ref_date = split_date
                ref_data = daily[daily.index >= ref_date]
                ref_label = "منذ التقسيم"
                open_on_ref_day = ref_data['Open'].iloc[0]
            else:
                ref_data = daily
                ref_date = daily.index[0]
                ref_label = "منذ بداية الفترة المحللة"
                open_on_ref_day = ref_data['Open'].iloc[0]

            days_since_ref = (pd.Timestamp.now(tz=ref_data.index.tz) - ref_date).days

            high_in_range = ref_data['High'].max()
            high_in_range_date = ref_data['High'].idxmax()
            low_in_range = ref_data['Low'].min()
            low_in_range_date = ref_data['Low'].idxmin()

            distance_from_low_pct = (current_price - low_in_range) / low_in_range * 100
            distance_from_high_pct = (high_in_range - current_price) / high_in_range * 100

            high_first_4h = np.nan
            if has_split and not intraday.empty:
                window_start = ref_date
                window_end = ref_date + pd.Timedelta(hours=4)
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

            # ---------- ثبات فوق الدعم (أدنى قاع بالفترة) ----------
            support_level = low_in_range
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
            st.subheader("بيانات الدعم ومنطقة الهدف")
            c1, c2, c3 = st.columns(3)
            c1.metric("الدعم المعتمد", f"${support_level:.3f}")
            c2.metric("المسافة عن الدعم", f"{distance_from_low_pct:.1f}%")
            if has_split:
                c3.metric("نسبة التقسيم", f"1:{int(split_ratio)}")
            else:
                c3.metric("المسافة عن القمة", f"{distance_from_high_pct:.1f}%")

            colA, colB = st.columns(2)
            with colA:
                extra_line = f"<div class='metric-card'><b>تاريخ التقسيم:</b> {split_date.date()}</div>" if has_split else ""
                st.markdown(f"""
                {extra_line}
                <div class="metric-card"><b>{ref_label}:</b> {days_since_ref} يوم</div>
                <div class="metric-card"><b>سعر بداية الفترة:</b> ${open_on_ref_day:.3f}</div>
                <div class="metric-card"><b>أعلى قمة بالفترة:</b> ${high_in_range:.3f} ({high_in_range_date.date()})</div>
                """, unsafe_allow_html=True)
            with colB:
                high4h_line = ""
                if has_split:
                    high4h_txt = f"${high_first_4h:.3f}" if not np.isnan(high_first_4h) else "غير متوفر"
                    high4h_line = f"<div class='metric-card'><b>أعلى أول 4 ساعات:</b> {high4h_txt}</div>"
                st.markdown(f"""
                {high4h_line}
                <div class="metric-card"><b>أدنى قاع بالفترة:</b> ${low_in_range:.3f} ({low_in_range_date.date()})</div>
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

            if not has_split:
                st.markdown('<span class="badge-grey">ملاحظة: لا يوجد تقسيم مسجل لهذا السهم بالفترة المختارة — التحليل مبني على أعلى/أدنى سعر بالفترة</span>', unsafe_allow_html=True)

            st.markdown("### درجة الجاهزية")
            st.progress(min(int(score), 100) / 100)
            st.write(f"**{score:.0f}/100**")

            with st.expander("تفاصيل EMA"):
                for p in ema_periods:
                    if p in ema_status:
                        val = latest[f'EMA{p}']
                        st.write(f"EMA{p}: {val:.3f} — {'السعر تحته ✓' if ema_status[p] else 'السعر فوقه ✗'}")

            with st.expander("عرض البيانات اليومية الخام"):
                st.dataframe(daily.tail(30))

        except Exception as e:
            st.error(f"صار خطأ: {e}")

