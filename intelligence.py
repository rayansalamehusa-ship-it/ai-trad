"""محرك سياق السوق من شموع OHLCV المغلقة. الحجم هنا proxy وليس تدفق أوامر حقيقياً."""
import math
import numpy as np
import pandas as pd
from tools import strategies as S


def _f(x, digits=4):
    try:
        v = float(x)
        return round(v, digits) if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def analyze_frame(df: pd.DataFrame, timeframe="5m"):
    required = {"open", "high", "low", "close", "volume"}
    if df is None or len(df) < 220 or not required.issubset(df.columns):
        raise ValueError("يلزم 220 شمعة مغلقة على الأقل لتسخين EMA200 مع OHLCV")
    d = df.copy().reset_index(drop=True)
    for col in required:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(d) < 220:
        raise ValueError("البيانات الصالحة أقل من 220 شمعة")
    c, h, l, v = d.close, d.high, d.low, d.volume.fillna(0)
    atr = S.atr(d, 14)
    adx = S.adx(d, 14)
    e20, e50, e200 = S.ema(c, 20), S.ema(c, 50), S.ema(c, 200)
    px, av = float(c.iloc[-1]), float(atr.iloc[-1])
    if not math.isfinite(av) or av <= 0: av = max(px * .001, 1e-9)
    prior_high, prior_low = float(h.iloc[-21:-1].max()), float(l.iloc[-21:-1].min())
    sweep_high = float(h.iloc[-1]) > prior_high and px < prior_high
    sweep_low = float(l.iloc[-1]) < prior_low and px > prior_low
    bull_fvg = float(l.iloc[-1]) > float(h.iloc[-3])
    bear_fvg = float(h.iloc[-1]) < float(l.iloc[-3])
    bull_gap = float(l.iloc[-1] - h.iloc[-3]) if bull_fvg else 0.0
    bear_gap = float(l.iloc[-3] - h.iloc[-1]) if bear_fvg else 0.0
    struct_hi, struct_lo = float(h.iloc[-11:-1].max()), float(l.iloc[-11:-1].min())
    bos_up, bos_down = px > struct_hi, px < struct_lo
    adx_now = float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else 0.0
    atr_pct = av / px * 100 if px else 0.0
    atr_s = (atr / c.replace(0, np.nan) * 100).dropna().tail(200)
    vol_rank = float((atr_s <= atr_pct).mean()) if len(atr_s) else .5
    regime = "trending" if adx_now >= 25 else "ranging" if adx_now <= 18 else "transition"
    volatility = "high" if vol_rank >= .8 else "low" if vol_rank <= .2 else "normal"
    vm, vs = float(v.rolling(30).mean().iloc[-1]), float(v.rolling(30).std().iloc[-1])
    vz = (float(v.iloc[-1]) - vm) / vs if vs > 0 else 0.0
    rng = max(float(h.iloc[-1] - l.iloc[-1]), 1e-12)
    close_loc = (px - float(l.iloc[-1])) / rng
    vol_proxy = vz * (2 * close_loc - 1)
    bull = float(px > float(e50.iloc[-1])) + float(float(e20.iloc[-1]) > float(e50.iloc[-1])) + .5 * float(px > float(e200.iloc[-1]))
    bear = float(px <= float(e50.iloc[-1])) + float(float(e20.iloc[-1]) <= float(e50.iloc[-1])) + .5 * float(px <= float(e200.iloc[-1]))
    bull += 2 * sweep_low + 1.5 * bos_up + (min(1.0, bull_gap / av) if bull_fvg else 0) + .5 * (vol_proxy > .5)
    bear += 2 * sweep_high + 1.5 * bos_down + (min(1.0, bear_gap / av) if bear_fvg else 0) + .5 * (vol_proxy < -.5)
    total = bull + bear
    bp = 50.0 if not total else 100 * bull / total
    bias = "neutral" if max(bull, bear) < 2.5 or abs(bull - bear) < 1 else "bullish" if bull > bear else "bearish"
    labels = {"trending":"اتجاه", "ranging":"عرضي", "transition":"انتقالي"}
    notes = [{"bullish":"الميل الحالي صاعد وفق الأدلة المتاحة", "bearish":"الميل الحالي هابط وفق الأدلة المتاحة", "neutral":"الأدلة متعارضة أو غير كافية؛ الانتظار أفضل"}[bias], labels[regime]]
    if sweep_low: notes.append("اختراق القاع السابق ثم الإغلاق فوقه: احتمال سحب سيولة سفلية")
    if sweep_high: notes.append("اختراق القمة السابقة ثم الإغلاق تحتها: احتمال سحب سيولة علوية")
    if bos_up: notes.append("إغلاق فوق أعلى نطاق البنية القصير")
    if bos_down: notes.append("إغلاق تحت أدنى نطاق البنية القصير")
    if bull_fvg: notes.append("ظهرت فجوة قيمة عادلة صاعدة")
    if bear_fvg: notes.append("ظهرت فجوة قيمة عادلة هابطة")
    if volatility == "high": notes.append("التقلب مرتفع نسبياً؛ خفّض المخاطرة أو انتظر")
    return {"timeframe":timeframe,"bars":len(d),"price":_f(px,8),"regime":regime,"regime_label":labels[regime],"volatility":volatility,"atr_pct":_f(atr_pct,3),"atr_percentile":_f(vol_rank*100,1),"adx":_f(adx_now,2),"bias":bias,"bull_score":_f(bull,2),"bear_score":_f(bear,2),"bull_bias_score":_f(bp,1),"bear_bias_score":_f(100-bp,1),"structure":{"bos_up":bool(bos_up),"bos_down":bool(bos_down),"reference_high":_f(struct_hi,8),"reference_low":_f(struct_lo,8)},"liquidity":{"sweep_high":bool(sweep_high),"sweep_low":bool(sweep_low),"prior_high":_f(prior_high,8),"prior_low":_f(prior_low,8)},"fvg":{"bullish":bool(bull_fvg),"bearish":bool(bear_fvg),"bullish_gap":_f(bull_gap,8),"bearish_gap":_f(bear_gap,8)},"volume_proxy":{"z_score":_f(vz,2),"signed_pressure_estimate":_f(vol_proxy,2),"warning":"تقدير من OHLCV وليس Order Flow حقيقياً"},"interpretation":notes}


def combine(frames):
    weights={"1h":.5,"15m":.3,"5m":.2}
    used=[(tf,x) for tf,x in frames.items() if tf in weights]
    if not used: return {"bias":"unknown","confidence":0,"scenario":"لا توجد بيانات كافية"}
    bull=sum(weights[t]*(x["bull_bias_score"] or 50) for t,x in used)/sum(weights[t] for t,_ in used)
    bear=100-bull
    bias="bullish" if bull>=60 else "bearish" if bull<=40 else "neutral"
    aligned=len({x["bias"] for _,x in used if x["bias"]!="neutral"})<=1
    conf=abs(bull-50)*2*(1 if aligned else .65)
    scenario="ميل صاعد؛ انتظر محفز دخول" if bias=="bullish" else "ميل هابط؛ انتظر محفز دخول" if bias=="bearish" else "لا توجد أفضلية واضحة؛ الانتظار أكثر منطقية"
    return {"bias":bias,"bull_score":round(bull,1),"bear_score":round(bear,1),"bias_strength":round(conf,1),"timeframes_aligned":aligned,"scenario":scenario,"decision_hint":"watch" if bias=="neutral" or not aligned else "wait_for_trigger"}
