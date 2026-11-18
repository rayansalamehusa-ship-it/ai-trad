"""خوارزميات سياق السوق والتعلّم الإحصائي المتدرّج.

لا تستخدم هذه الوحدة بيانات مستقبلية في الميزات. تقدير تدفق الحجم مبني على OHLCV
ويظل Proxy؛ ليس دفتر أوامر أو CVD حقيقياً. نموذج الاتجاه تجريبي وغير معاير.
"""
import math
import numpy as np
import pandas as pd
from tools import strategies as S


def _safe(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _features(df, horizon=6):
    d = df.copy().reset_index(drop=True)
    c, h, l = d.close.astype(float), d.high.astype(float), d.low.astype(float)
    vol = d.volume.astype(float).fillna(0) if "volume" in d else pd.Series(0.0, index=d.index)
    ret = c.pct_change()
    atr = S.atr(d, 14)
    adx = S.adx(d, 14)
    delta = c.diff().abs()
    er = (c - c.shift(10)).abs() / delta.rolling(10).sum().replace(0, np.nan)
    rsi = S.rsi(c, 14)
    rng = (h - l).replace(0, np.nan)
    signed_vol = vol * ((2 * c - h - l) / rng).clip(-1, 1)
    flow = signed_vol.rolling(20).sum() / vol.rolling(20).sum().replace(0, np.nan)
    typical = (h + l + c) / 3
    vwap = (typical * vol).rolling(24).sum() / vol.rolling(24).sum().replace(0, np.nan)
    vm, vs = vol.rolling(30).mean(), vol.rolling(30).std()
    vz = ((vol - vm) / vs.replace(0, np.nan)).fillna(0.0)
    x = pd.DataFrame({
        "ret1": ret,
        "ret3": c.pct_change(3),
        "ret6": c.pct_change(6),
        "rsi": (rsi - 50) / 50,
        "adx": adx / 50,
        "efficiency": er,
        "atr_pct": atr / c.replace(0, np.nan),
        "volume_z": vz.clip(-4, 4) / 4,
        "flow_proxy": flow,
        "vwap_gap": (c / vwap - 1).clip(-.1, .1) * 10,
    }).replace([np.inf, -np.inf], np.nan)
    future = c.shift(-horizon) / c - 1
    y = (future > 0).astype(float)
    return x, y, future


def _fit_logistic(x, y, steps=450, lr=0.08, reg=0.025):
    """لوجستك ريدج صغير بـNumPy فقط؛ التطبيع من عينة التدريب حصراً."""
    mu = x.mean(axis=0)
    sd = x.std(axis=0)
    sd[sd < 1e-8] = 1.0
    z = np.clip((x - mu) / sd, -6, 6)
    z = np.column_stack([np.ones(len(z)), z])
    w = np.zeros(z.shape[1], dtype=float)
    for _ in range(steps):
        p = 1 / (1 + np.exp(-np.clip(z @ w, -30, 30)))
        grad = (z.T @ (p - y)) / len(y)
        grad[1:] += reg * w[1:]
        w -= lr * grad
    return w, mu, sd


def _predict(x, model):
    w, mu, sd = model
    z = np.clip((x - mu) / sd, -6, 6)
    z = np.column_stack([np.ones(len(z)), z])
    return 1 / (1 + np.exp(-np.clip(z @ w, -30, 30)))


def walk_forward_model(df, horizon=6):
    """اختبار توسعي: كل طية تُدرّب على الماضي فقط ثم تتنبأ بالجزء اللاحق."""
    x, y, _ = _features(df, horizon)
    valid = x.notna().all(axis=1).values
    labeled = valid & y.notna().values
    ids = np.flatnonzero(labeled)
    if len(ids) < 260 or not valid[-1]:
        return {"available": False, "reason": "يلزم نحو 260 عينة صالحة على الأقل"}
    X, Y = x.values, y.values
    preds, actual, baselines = [], [], []
    n = len(ids)
    # تقييم خارج العينة على آخر 40% بثلاث طيات متزايدة.
    starts = [int(n * .60), int(n * .73), int(n * .86)]
    ends = [int(n * .73), int(n * .86), n]
    for a, b in zip(starts, ends):
        train_ids, test_ids = ids[:max(0, a - horizon)], ids[a:b]  # purge: منع تداخل أفق الوسم مع الاختبار
        if len(train_ids) < 150 or len(test_ids) < 10:
            continue
        model = _fit_logistic(X[train_ids], Y[train_ids])
        pp = _predict(X[test_ids], model)
        preds.extend(pp.tolist()); actual.extend(Y[test_ids].tolist())
        baselines.extend([float(Y[train_ids].mean())] * len(test_ids))
    # تدريب نهائي على كل التسميات المتاحة للتنبؤ بالشمعة الحالية (من دون وسمها).
    model = _fit_logistic(X[ids], Y[ids])
    p_now = float(_predict(X[[-1]], model)[0])
    if len(actual) >= 20:
        aa, pp, bb = np.asarray(actual), np.asarray(preds), np.asarray(baselines)
        brier = float(np.mean((pp - aa) ** 2))
        base_brier = float(np.mean((bb - aa) ** 2))
        acc = float(np.mean((pp >= .5) == (aa >= .5)))
    else:
        brier = base_brier = acc = None
    return {"available": True, "horizon_bars": horizon, "samples": int(len(ids)),
            "oos_samples": len(actual), "prob_up_experimental": round(p_now, 3),
            "oos_accuracy": None if acc is None else round(acc * 100, 1),
            "oos_brier": None if brier is None else round(brier, 4),
            "baseline_brier": None if base_brier is None else round(base_brier, 4),
            "beats_baseline": bool(brier is not None and brier < base_brier),
            "warning": "نموذج اتجاه تجريبي، وليس احتمال ربح صفقة معايراً"}


def analyze_market(df):
    """نظام السوق + هيكل سوينغ + تدفق حجم تقريبي + VWAP + نموذج توسعي."""
    if df is None or len(df) < 220:
        return {"available": False, "reason": "يلزم 220 شمعة على الأقل"}
    d = df.copy().reset_index(drop=True)
    c, h, l = d.close.astype(float), d.high.astype(float), d.low.astype(float)
    atr = S.atr(d, 14)
    adx = S.adx(d, 14)
    n = 20
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    chop = 100 * np.log10(tr.rolling(n).sum() / (h.rolling(n).max() - l.rolling(n).min()).replace(0, np.nan)) / np.log10(n)
    er = (c - c.shift(n)).abs() / c.diff().abs().rolling(n).sum().replace(0, np.nan)
    atr_pct = (atr / c.replace(0, np.nan)).dropna()
    cur_atr_pct = _safe(atr_pct.iloc[-1])
    vol_rank = float((atr_pct.tail(250) <= cur_atr_pct).mean()) if len(atr_pct) else .5
    adx_now, chop_now, er_now = _safe(adx.iloc[-1]), _safe(chop.iloc[-1], 50), _safe(er.iloc[-1])
    if adx_now >= 22 and er_now >= .28 and chop_now < 61.8:
        regime = "trending"
    elif (adx_now < 18 and er_now < .25) or chop_now >= 61.8:
        regime = "ranging"
    else:
        regime = "transition"
    volatility = "high" if vol_rank >= .85 else "low" if vol_rank <= .15 else "normal"

    # Swing points لا تُعرف إلا بعد تأكيد ثلاث شمعات إلى اليمين.
    left = right = 3
    ph = h.shift(right).where(h.shift(right) >= h.rolling(left + right + 1).max())
    pl = l.shift(right).where(l.shift(right) <= l.rolling(left + right + 1).min())
    highs, lows = ph.dropna(), pl.dropna()
    last_high = _safe(highs.iloc[-1], _safe(h.iloc[-2])) if len(highs) else _safe(h.iloc[-2])
    last_low = _safe(lows.iloc[-1], _safe(l.iloc[-2])) if len(lows) else _safe(l.iloc[-2])
    prior_high = _safe(highs.iloc[-2], last_high) if len(highs) > 1 else last_high
    prior_low = _safe(lows.iloc[-2], last_low) if len(lows) > 1 else last_low
    structure = "bullish" if last_high > prior_high and last_low > prior_low else "bearish" if last_high < prior_high and last_low < prior_low else "mixed"
    bos_up, bos_down = _safe(c.iloc[-1]) > last_high, _safe(c.iloc[-1]) < last_low

    vol = d.volume.astype(float).fillna(0) if "volume" in d else pd.Series(0.0, index=d.index)
    rng = (h-l).replace(0, np.nan)
    signed = vol * ((2*c-h-l)/rng).clip(-1,1)
    denom = _safe(vol.tail(20).sum())
    flow = _safe(signed.tail(20).sum() / denom) if denom > 0 else 0.0
    typical = (h+l+c)/3
    vwap_denom = _safe(vol.tail(24).sum())
    vwap = _safe((typical.tail(24)*vol.tail(24)).sum()/vwap_denom, _safe(c.iloc[-1])) if vwap_denom > 0 else _safe(c.iloc[-1])
    vwap_gap = (_safe(c.iloc[-1])/vwap-1)*100 if vwap else 0.0

    bull = (2 if structure == "bullish" else 0) + (2 if bos_up else 0) + (1 if flow > .12 else 0) + (1 if vwap_gap > .15 else 0)
    bear = (2 if structure == "bearish" else 0) + (2 if bos_down else 0) + (1 if flow < -.12 else 0) + (1 if vwap_gap < -.15 else 0)
    if regime == "ranging": bull *= .65; bear *= .65
    quality = min(100, round(abs(bull-bear)*15 + (15 if regime == "trending" else 5 if regime == "transition" else 0) + (10 if volatility == "normal" else 0)))
    model = walk_forward_model(d)
    return {"available": True, "regime": regime, "volatility": volatility,
            "adx": round(adx_now, 2), "choppiness": round(chop_now, 2), "efficiency_ratio": round(er_now, 3),
            "atr_percentile": round(vol_rank*100, 1), "structure": structure,
            "bos_up": bool(bos_up), "bos_down": bool(bos_down),
            "flow_imbalance_proxy": round(flow, 3), "vwap": round(vwap, 8), "vwap_gap_pct": round(vwap_gap, 3),
            "bull_score": round(bull, 2), "bear_score": round(bear, 2), "quality_score": quality,
            "ml": model,
            "notes": ["مؤشر تدفق الحجم تقديري من OHLCV وليس CVD حقيقياً",
                      "نموذج ML اتجاهي تجريبي؛ لا يُستخدم وحده لاتخاذ صفقة"]}
