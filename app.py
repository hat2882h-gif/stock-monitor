import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="مراقب استراتيجية", page_icon="📈", layout="centered")

# ============================================================
# تنسيق عام (RTL + ألوان ثابتة تشتغل بأي وضع - فاتح أو غامق)
# ============================================================
st.markdown("""
<style>
html, body, [class*="css"]  { direction: rtl; text-align: right; }
.block-container { padding-top: 2rem; }

.metric-card {
    background:#f7f8f8 !important; color:#1a2323 !important;
    border-radius:12px; padding:14px 16px; margin-bottom:10px;
    border:1px solid #e4e6e6;
}
.metric-card b { color:#0d2b2b !important; }

.header-box {
    background: linear-gradient(180deg,#0d2b2b,#0a2222);
    color:#ffffff !important; padding:20px; border-radius:16px; margin-bottom:20px;
}
.header-box * { color:#ffffff !important; }

.badge-orange { background:#fdeecb !important; color:#b8860b !important; font-weight:700; padding:6px 14px; border-radius:20px; display:inline-block; }
.badge-green  { background:#e6f4ef !important; color:#0f8a6b !important; font-weight:700; padding:6px 14px; border-radius:20px; display:inline-block; }
.badge-grey   { background:#eceeee !important; color:#5a6666 !important; font-weight:700; padding:6px 14px; border-radius:20px; display:inline-block; }
.badge-red    { background:#fde8e8 !important; color:#c0392b !important; font-weight:700; padding:6px 14px; border-radius:20px; display:inline-block; }
.badge-blue   { background:#e6eefc !important; color:#1d5ed1 !important; font-weight:700; padding:6px 14px; border-radius:20px; display:inline-block; }

.readiness-box {
    border-radius:16px; padding:18px 20px; margin-bottom:16px; border-width:2px; border-style:solid;
    color:#1a2323 !important;
}
.readiness-box * { color:#1a2323 !important; }
.readiness-score { font-size:14px; font-weight:700; background:#fff; border-radius:8px; padding:3px 10px; display:inline-block; }
.readiness-title { font-size:19px; font-weight:800; margin:6px 0 10px; }
.reason-pill { background:rgba(255,255,255,.6); border-radius:20px; padding:6px 12px; font-size:13px; display:inline-block; margin:2px 4px 2px 0; }

.stage-wrap { display:flex; justify-content:space-between; margin:14px 0 6px; }
.stage-item { flex:1; text-align:center; }
.stage-circle {
    width:34px; height:34px; border-radius:50%; margin:0 auto 6px;
    display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px;
    border:2px solid #d7dbdb; color:#8a9494 !important; background:#fff;
}
.stage-circle.done { background:#0f8a6b; border-color:#0f8a6b; color:#fff !important; }
.stage-label { font-size:11px; color:#5a6666 !important; }
</style>
""", unsafe_allow_html=True)

st.title("📈 مراقب استراتيجية ")
st.caption("أدخل رمز أي سهم — تحليل الدعم، دورة تكوين القاع، المؤشرات الفنية، وبيانات الاستعارة (Short)")
st.caption("⚠️ هذا تقدير مبني على منطق عام مستوحى من الواجهة، وليس نسخة طبق الأصل من خوارزمية مملوكة لأي طرف ثالث.")

col1, col2 = st.columns([2, 1])
with col1:
    ticker_input = st.text_input("رمز السهم", value="AAPL").strip().upper()
with col2:
    lookback_days = st.number_input("عدد أيام البحث", min_value=60, max_value=1500, value=400, step=10)

run = st.button("🔍 جلب البيانات وتحليلها", use_container_width=True)


# ============================================================
# دوال مساعدة
# ============================================================
def safe_last_close(df: pd.DataFrame):
    closes = df['Close'].dropna()
    return None if closes.empty else closes.iloc[-1]


def fetch_iborrowdesk(ticker: str):
    """يحاول جلب بيانات الاستعارة من IBorrowDesk. يرجع (data, error_message).
    data يكون None لو فشل، مع رسالة تشرح السبب بدال ما نسكت عن الخطأ."""
    url = f"https://iborrowdesk.com/api/ticker/{ticker}"
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
    except Exception as e:
        return None, f"تعذر الاتصال بـ IBorrowDesk: {e}"

    if resp.status_code == 404:
        return None, "الرمز غير موجود على IBorrowDesk (غالبًا يدعم أسهم أمريكية فقط)."
    if resp.status_code != 200:
        return None, f"IBorrowDesk رجع خطأ HTTP {resp.status_code}."

    try:
        data = resp.json()
    except Exception:
        return None, "استجابة IBorrowDesk ما كانت بصيغة JSON صالحة (ممكن يكون الموقع غيّر شكل الـ API)."

    # نجرب أكثر من مسار محتمل لهيكلة البيانات لأن الـ API غير موثّق رسميًا
    daily = None
    if isinstance(data, dict):
        daily = data.get("daily") or data.get("data") or data.get("results")
    elif isinstance(data, list):
        daily = data

    if not daily:
        return None, "ما فيه بيانات استعارة مسجلة لهذا الرمز بـ IBorrowDesk."

    latest = daily[-1]
    fee = latest.get("fee") if isinstance(latest, dict) else None
    available = latest.get("available") if isinstance(latest, dict) else None
    date = (latest.get("time") or latest.get("date")) if isinstance(latest, dict) else None

    if fee is None and available is None:
        return None, "الحقول المتوقعة (fee / available) غير موجودة برد IBorrowDesk."

    return {"fee": fee, "available": available, "date": date}, None


def fetch_yahoo_short_data(ticker_obj):
    """مصدر بديل موثوق من Yahoo Finance (نفس مكتبة yfinance المستخدمة أصلًا).
    يعطي بيانات الفائدة القصيرة (Short Interest) وهي مو مطابقة 100% لرسوم
    الاستعارة اليومية من IBorrowDesk، لكنها مؤشر بديل مفيد ومتوفر بثبات أكبر."""
    try:
        info = ticker_obj.info
    except Exception:
        return None
    fields = {
        "sharesShort": info.get("sharesShort"),
        "shortRatio": info.get("shortRatio"),
        "shortPercentOfFloat": info.get("shortPercentOfFloat"),
        "sharesShortPriorMonth": info.get("sharesShortPriorMonth"),
        "dateShortInterest": info.get("dateShortInterest"),
    }
    if all(v is None for v in fields.values()):
        return None
    return fields


def compute_rsi(close: pd.Series, period: int = 14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line


def stage_circle_html(number_or_check, done, label):
    content = "✓" if done else str(number_or_check)
    cls = "stage-circle done" if done else "stage-circle"
    return f"""<div class="stage-item">
        <div class="{cls}">{content}</div>
        <div class="stage-label">{label}</div>
    </div>"""


# ============================================================
# التشغيل الرئيسي
# ============================================================
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

            daily = daily.dropna(subset=['Close'])
            if daily.empty:
                st.error("البيانات المرجعة فارغة أو غير مكتملة لهذا الرمز.")
                st.stop()

            try:
                intraday = ticker_obj.history(period="60d", interval="1h", auto_adjust=False)
            except Exception:
                intraday = pd.DataFrame()

            try:
                info = ticker_obj.info
            except Exception:
                info = {}
            company_name = info.get("longName") or info.get("shortName") or ticker_input

            current_price = safe_last_close(daily)
            if current_price is None:
                st.error("ما قدرت أحدد آخر سعر إغلاق صالح لهذا الرمز.")
                st.stop()

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

            # ---------- هل فيه تقسيم؟ ----------
            splits = ticker_obj.splits
            has_split = False
            if len(splits):
                tz = splits.index.tz
                recent_splits = splits[splits.index >= pd.Timestamp(start, tz=tz)]
                if len(recent_splits) > 0:
                    has_split = True
                    split_date = recent_splits.index[-1]
                    split_ratio = recent_splits.iloc[-1]

            if has_split:
                ref_date = split_date
                ref_data = daily[daily.index >= ref_date]
                ref_label = "منذ التقسيم"
            else:
                ref_data = daily
                ref_date = daily.index[0]
                ref_label = "منذ بداية الفترة المحللة"

            if ref_data.empty:
                ref_data = daily
                ref_date = daily.index[0]

            open_on_ref_day = ref_data['Open'].iloc[0]
            days_since_ref = (pd.Timestamp.now(tz=ref_data.index.tz) - ref_date).days

            high_in_range = ref_data['High'].max()
            high_in_range_date = ref_data['High'].idxmax()
            low_in_range = ref_data['Low'].min()
            low_in_range_date = ref_data['Low'].idxmin()

            distance_from_low_pct = (current_price - low_in_range) / low_in_range * 100 if low_in_range else np.nan
            distance_from_high_pct = (high_in_range - current_price) / high_in_range * 100 if high_in_range else np.nan
            pullback_from_peak_pct = (current_price - high_in_range) / high_in_range * 100 if high_in_range else np.nan

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

            # ---------- RSI / MACD ----------
            rsi_series = compute_rsi(daily['Close'])
            rsi_latest = rsi_series.iloc[-1]
            macd_line, signal_line = compute_macd(daily['Close'])
            macd_positive = macd_line.iloc[-1] > signal_line.iloc[-1]

            # ---------- أعلى فجوة (gap) وصعود آخر 20 جلسة ----------
            gaps = (daily['Open'] - daily['Close'].shift(1)) / daily['Close'].shift(1) * 100
            biggest_gap = gaps.abs().max()
            last20 = daily['Close'].tail(21)
            up_days = (last20.diff().dropna() > 0).sum()
            up_days_pct = up_days / max(len(last20) - 1, 1) * 100

            # ---------- ثبات فوق الدعم ----------
            support_level = low_in_range
            recent_closes = daily['Close'].tail(10)
            closes_above_support = (recent_closes > support_level).astype(int)
            consecutive_above = 0
            for v in closes_above_support[::-1]:
                if v == 1:
                    consecutive_above += 1
                else:
                    break

            # ---------- دورة تكوين القاع (5 مراحل) ----------
            stage1_ok = True  # قاع: محدد دائمًا بمجرد ما نحدد أدنى نقطة
            stage2_ok = consecutive_above >= 3  # ثبات 3 جلسات فوق الدعم
            stage3_ok = (not np.isnan(distance_from_low_pct)) and distance_from_low_pct >= 10  # ارتداد 10%
            # اختبار: رجوع قريب من الدعم بعد الارتداد بدون كسره (نطاق 15% فوق الدعم كحد أقصى للاعتبار "اختبار")
            stage4_ok = stage3_ok and (not np.isnan(distance_from_low_pct)) and distance_from_low_pct <= 20 and consecutive_above >= 1
            # تأكيد: جلستين إغلاق متتاليتين فوق الدعم بعد الاختبار
            stage5_ok = stage4_ok and consecutive_above >= 2

            rebound_progress = min(distance_from_low_pct, 10) if not np.isnan(distance_from_low_pct) else 0
            rebound_progress_pct = max(rebound_progress, 0) / 10 * 100

            # ---------- الشروط الآلية الثمانية ودرجة الجاهزية ----------
            conditions = {
                "أسفل جميع EMA": below_all_ema,
                "المسافة عن الدعم أقل من 5%": (not np.isnan(distance_from_low_pct)) and distance_from_low_pct < 5,
                "ثبات جلستين على الأقل فوق الدعم": consecutive_above >= 2,
                "ارتداد 10% أو أكثر من القاع": stage3_ok,
                "اختبار ناجح للدعم": stage4_ok,
                "تأكيد الاختبار (جلستين متتاليتين)": stage5_ok,
                "RSI ليس بمنطقة تشبع شرائي (<70)": (not np.isnan(rsi_latest)) and rsi_latest < 70,
                "MACD إيجابي": bool(macd_positive),
            }
            completed_count = sum(1 for v in conditions.values() if v)
            score = completed_count / len(conditions) * 100
            missing = [k for k, v in conditions.items() if not v]

            if score >= 90:
                readiness_title = "جاهز"
                box_color = "#0f8a6b"; box_bg = "#e6f4ef"
            elif score >= 62:
                readiness_title = "قريب من الجاهزية"
                box_color = "#b8860b"; box_bg = "#fdf6e3"
            else:
                readiness_title = "مراقبة مبكرة"
                box_color = "#1d5ed1"; box_bg = "#e6eefc"

            # ============================================================
            # عرض النتائج
            # ============================================================
            missing_pills = "".join(f'<span class="reason-pill">{m}</span>' for m in missing[:4]) if missing else '<span class="reason-pill">كل الشروط الآلية مكتملة ✓</span>'
            st.markdown(f"""
            <div class="readiness-box" style="border-color:{box_color};background:{box_bg};">
                <span class="readiness-score">{completed_count}/{len(conditions)}</span>
                <div class="readiness-title" style="color:{box_color} !important;">{readiness_title} — {score:.0f}/100</div>
                {missing_pills}
            </div>
            """, unsafe_allow_html=True)

            st.markdown("#### دورة الدعم: تكوين قاع")
            stages_html = f"""
            <div class="stage-wrap">
                {stage_circle_html(5, stage5_ok, "تأكيد")}
                {stage_circle_html(4, stage4_ok, "اختبار")}
                {stage_circle_html(3, stage3_ok, "ارتداد 10%")}
                {stage_circle_html(2, stage2_ok, "ثبات 3")}
                {stage_circle_html(1, stage1_ok, "قاع")}
            </div>
            """
            st.markdown(stages_html, unsafe_allow_html=True)
            st.progress(min(rebound_progress_pct, 100) / 100)
            reb_txt = f"{distance_from_low_pct:.1f}%" if not np.isnan(distance_from_low_pct) else "—"
            st.caption(f"تقدم الارتداد المطلوب: {reb_txt} / 10%")

            st.subheader("بيانات الدعم ومنطقة الهدف")
            c1, c2, c3 = st.columns(3)
            c1.metric("الدعم المعتمد", f"${support_level:.3f}")
            dist_low_txt = f"{distance_from_low_pct:.1f}%" if not np.isnan(distance_from_low_pct) else "—"
            c2.metric("المسافة عن الدعم", dist_low_txt)
            if has_split:
                c3.metric("نسبة التقسيم", f"1:{int(split_ratio)}")
            else:
                dist_high_txt = f"{distance_from_high_pct:.1f}%" if not np.isnan(distance_from_high_pct) else "—"
                c3.metric("المسافة عن القمة", dist_high_txt)

            colA, colB = st.columns(2)
            with colA:
                extra_line = f"<div class='metric-card'><b>تاريخ التقسيم:</b> {split_date.date()}</div>" if has_split else ""
                st.markdown(f"""
                {extra_line}
                <div class="metric-card"><b>{ref_label}:</b> {days_since_ref} يوم</div>
                <div class="metric-card"><b>سعر بداية الفترة:</b> ${open_on_ref_day:.3f}</div>
                <div class="metric-card"><b>أعلى قمة بالفترة:</b> ${high_in_range:.3f} ({high_in_range_date.date()})</div>
                <div class="metric-card"><b>الجلسات المتتالية فوق الدعم:</b> {consecutive_above}</div>
                """, unsafe_allow_html=True)
            with colB:
                high4h_line = ""
                if has_split:
                    high4h_txt = f"${high_first_4h:.3f}" if not np.isnan(high_first_4h) else "غير متوفر"
                    high4h_line = f"<div class='metric-card'><b>أعلى أول 4 ساعات:</b> {high4h_txt}</div>"
                pullback_txt = f"{pullback_from_peak_pct:.1f}%" if not np.isnan(pullback_from_peak_pct) else "—"
                st.markdown(f"""
                {high4h_line}
                <div class="metric-card"><b>أدنى قاع بالفترة:</b> ${low_in_range:.3f} ({low_in_range_date.date()})</div>
                <div class="metric-card"><b>التراجع من القمة:</b> {pullback_txt}</div>
                <div class="metric-card"><b>أكبر فجوة سعرية:</b> {biggest_gap:.1f}%</div>
                <div class="metric-card"><b>صعود آخر 20 جلسة:</b> {up_days_pct:.1f}%</div>
                """, unsafe_allow_html=True)

            st.subheader("المؤشرات الفنية")
            i1, i2, i3 = st.columns(3)
            rsi_txt = f"{rsi_latest:.2f}" if not np.isnan(rsi_latest) else "—"
            i1.metric("RSI (14)", rsi_txt)
            i2.metric("MACD", "إيجابي ✓" if macd_positive else "سلبي ✗")
            i3.metric("EMA", "أسفل الكل ✓" if below_all_ema else "ليس أسفل الكل")

            with st.expander("تفاصيل EMA"):
                for p in ema_periods:
                    if p in ema_status:
                        val = latest[f'EMA{p}']
                        st.write(f"EMA{p}: {val:.3f} — {'السعر تحته ✓' if ema_status[p] else 'السعر فوقه ✗'}")

            # ---------- بيانات الاستعارة (Short) ----------
            st.subheader("بيانات الاستعارة (Short)")
            ib_data, ib_error = fetch_iborrowdesk(ticker_input)

            if ib_data is not None:
                fee = ib_data.get("fee")
                available = ib_data.get("available")
                date_txt = ib_data.get("date") or "—"
                st.caption("المصدر: IBorrowDesk")
                ic1, ic2 = st.columns(2)
                with ic1:
                    st.metric("نسبة رسوم الاستعارة (Fee)", f"{fee}%" if fee is not None else "—")
                with ic2:
                    avail_txt = f"{available:,}" if isinstance(available, (int, float)) else (available or "—")
                    st.metric("الأسهم المتاحة للاستعارة", avail_txt)
                st.caption(f"آخر تحديث بحسب IBorrowDesk: {date_txt}")
                if isinstance(fee, (int, float)):
                    if fee >= 50:
                        st.markdown('<span class="badge-red">رسوم استعارة مرتفعة جدًا</span>', unsafe_allow_html=True)
                    elif fee >= 10:
                        st.markdown('<span class="badge-orange">رسوم استعارة مرتفعة نسبيًا</span>', unsafe_allow_html=True)
                    else:
                        st.markdown('<span class="badge-green">رسوم استعارة منخفضة</span>', unsafe_allow_html=True)
            else:
                # نعرض سبب فشل IBorrowDesk بدل ما نسكت عنه، وننتقل لمصدر بديل
                st.markdown(f'<span class="badge-grey">IBorrowDesk: {ib_error}</span>', unsafe_allow_html=True)

                yahoo_short = fetch_yahoo_short_data(ticker_obj)
                if yahoo_short is None:
                    st.markdown('<span class="badge-grey">ولا المصدر البديل (Yahoo Finance) عنده بيانات استعارة لهذا الرمز.</span>', unsafe_allow_html=True)
                else:
                    st.caption("المصدر البديل: Yahoo Finance (بيانات الفائدة القصيرة — Short Interest، مو نفس رسوم الاستعارة اليومية بالضبط)")
                    yc1, yc2 = st.columns(2)
                    with yc1:
                        ss = yahoo_short.get("sharesShort")
                        st.metric("الأسهم المباعة على المكشوف", f"{ss:,}" if isinstance(ss, (int, float)) else "—")
                    with yc2:
                        spf = yahoo_short.get("shortPercentOfFloat")
                        spf_txt = f"{spf*100:.2f}%" if isinstance(spf, (int, float)) else "—"
                        st.metric("النسبة من الأسهم المتاحة للتداول (Float)", spf_txt)
                    yc3, yc4 = st.columns(2)
                    with yc3:
                        sr = yahoo_short.get("shortRatio")
                        st.metric("نسبة أيام التغطية (Short Ratio)", f"{sr:.2f}" if isinstance(sr, (int, float)) else "—")
                    with yc4:
                        dsi = yahoo_short.get("dateShortInterest")
                        if isinstance(dsi, (int, float)):
                            dsi_txt = datetime.fromtimestamp(dsi).strftime("%Y-%m-%d")
                        else:
                            dsi_txt = "—"
                        st.metric("تاريخ آخر تحديث", dsi_txt)

            with st.expander("عرض البيانات اليومية الخام"):
                st.dataframe(daily.tail(30))

        except Exception as e:
            st.error(f"صار خطأ: {e}")

