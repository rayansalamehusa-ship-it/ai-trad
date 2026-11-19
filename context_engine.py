"""محرك السياق — الخطوة الأولى في تشغيل الفريق: يفهم السوق قبل البحث عن أي صفقة.

المخرج `permission` يحدد ما يُسمح للبحث عنه لاحقاً:
  long      السياق صاعد  → يُبحث عن الشراء فقط
  short     السياق هابط  → يُبحث عن البيع فقط
  selective السياق محايد/متعارض → أي اتجاه لكن بدرجة A فقط وبمخاطرة مخفضة
  wait      لا تدخل (سوق مغلق، تذبذب شديد، بيانات غير كافية) → يتخطى الفريق البحث عن صفقة كلياً

الأرقام أوزان داخلية لترجيح الأدلة وليست احتمالات ربح معايرة.
"""
import intelligence

FRAMES_W = {"swing": {"1d": .40, "4h": .35, "1h": .25}, "scalp": {"1h": .45, "15m": .35, "5m": .20}}
BIAS_AT = 25            # أدنى |D| لاعتبار السياق صاعداً/هابطاً
STRONG_AT = 45          # قوة تعتبر «قوية» → مخاطرة عادية
MAX_ADJ = 12.0          # أقصى تعديل يضيفه السياق على درجتي الشراء/البيع
PERM_AR = {"long": "مسموح: شراء فقط", "short": "مسموح: بيع فقط", "selective": "انتقائي: صفقة بدرجة A فقط وبمخاطرة مخفضة", "wait": "لا تدخل — انتظر"}
BIAS_AR = {"bullish": "صاعد", "bearish": "هابط", "neutral": "محايد"}
STATE_AR = {"trending": "اتجاهي", "ranging": "عرضي", "transition": "انتقالي", "volatile": "تذبذب شديد", "closed": "السوق مغلق"}
_sgn = {"up": 1, "down": -1, "flat": 0}


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def build(symbol, style, views, entry_tf, market_model=None, closed=False, sent=0, fng=None, flow=None, relation=None, kind="crypto"):
    """views: {tf: عرض الفريم من engine} — يكفي أن يحتوي df/trend/rsi/adx/reg/price. يعيد قاموساً قابلاً للتحويل إلى JSON."""
    w = FRAMES_W[style]
    frames, notes, miss = {}, [], []
    for tf in w:
        v = views.get(tf)
        if not v:
            continue
        try:
            frames[tf] = intelligence.analyze_frame(v["df"], tf)
        except Exception as e:  # noqa: BLE001
            miss.append(f"{tf}: {str(e)[:60]}")
    syn = intelligence.combine(frames, {k: w[k] for k in frames}) if frames else {"bias": "unknown", "bull_score": 50.0, "timeframes_aligned": False}

    # ---- الاتجاه المركّب D في [-100, 100]
    d_frames = (float(syn.get("bull_score", 50.0)) - 50.0) * 2
    wt = sum(w[tf] for tf in views if tf in w) or 1.0
    d_trend = 100.0 * sum(w[tf] * _sgn[views[tf]["trend"]] for tf in views if tf in w) / wt
    D = 0.5 * d_frames + 0.5 * d_trend
    mood = _clamp(5.0 * sent, -10, 10)
    D += mood
    flow_adj = 0.0
    if flow and flow.get("available") and flow.get("cvd_ratio") is not None:
        flow_adj = _clamp(12.0 * float(flow["cvd_ratio"]), -8, 8)
        D += flow_adj
    rel = 0.0
    if relation:
        rel = _clamp(float(relation.get("buy", 0)) - float(relation.get("sell", 0)), -12, 12)
        D += rel
    D = _clamp(D, -100, 100)
    bias = "bullish" if D >= BIAS_AT else "bearish" if D <= -BIAS_AT else "neutral"
    strength = round(abs(D))

    # ---- حالة السوق
    ev = views[entry_tf]
    mm = market_model or {}
    if closed:
        state = "closed"
    elif ev["reg"]["state"] == "high_vol":
        state = "volatile"
    else:
        state = mm.get("regime") if mm.get("available") and mm.get("regime") in ("trending", "ranging", "transition") else ev["reg"]["state"]
        state = state if state in STATE_AR else "transition"

    trends = [v["trend"] for tf, v in views.items() if tf in w]
    nz = {t for t in trends if t != "flat"}
    top_tf = list(w)[0]
    top = views.get(top_tf, ev)["trend"]
    aligned = len(nz) <= 1 and (bias == "neutral" or top in ("flat", "up" if bias == "bullish" else "down"))

    # ---- الإذن
    why = []
    if closed:
        permission = "wait"; why.append("السوق مغلق أو البيانات متأخرة — قد يتغير السعر عند الافتتاح")
    elif state == "volatile":
        permission = "wait"; why.append("التذبذب في أعلى 5% من آخر 250 شمعة على فريم الدخول — خطر مرتفع")
    elif not frames and not views:
        permission = "wait"; why.append("لا توجد بيانات كافية لفهم السياق")
    elif bias == "bullish":
        permission = "long"
    elif bias == "bearish":
        permission = "short"
    else:
        permission = "selective"
    if permission in ("long", "short") and (strength < STRONG_AT or not aligned):
        risk_mode = "reduced"
    elif permission == "selective":
        risk_mode = "reduced"
    else:
        risk_mode = "normal"
    adjust = round(_clamp(D / 100.0 * MAX_ADJ, -MAX_ADJ, MAX_ADJ), 1) if permission != "wait" else 0.0

    # ---- التفسير بالعربية
    notes.append(f"الاتجاه المركّب: {BIAS_AR[bias]} (قوة {strength}/100) — فريمات {'متوافقة' if aligned else 'غير متوافقة'}")
    notes.append("اتجاه الفريمات (EMA): " + " · ".join(f"{tf} {({'up': 'صاعد', 'down': 'هابط', 'flat': 'جانبي'})[views[tf]['trend']]}" for tf in w if tf in views))
    notes.append(f"حالة السوق: {STATE_AR[state]} — ADX {ev['adx']} · تقلب أعلى من {ev['reg']['vol_pct']}% من آخر 250 شمعة")
    if mm.get("available"):
        notes.append(f"بنية السوق: {({'bullish': 'صاعدة', 'bearish': 'هابطة', 'mixed': 'مختلطة'}).get(mm['structure'], mm['structure'])} · CHOP {mm['choppiness']} · انحراف VWAP {mm['vwap_gap_pct']}%")
    ef = frames.get(entry_tf) or {}
    for k, t in (("sweep_low", "سحب سيولة سفلي (قاع مكسور ثم استعيد) — داعم للصعود"), ("sweep_high", "سحب سيولة علوي (قمة مكسورة ثم استعيدت) — داعم للهبوط")):
        if (ef.get("liquidity") or {}).get(k):
            notes.append(t)
    if (ef.get("structure") or {}).get("bos_up"):
        notes.append("إغلاق فوق أعلى نطاق البنية القصير (BOS صاعد)")
    if (ef.get("structure") or {}).get("bos_down"):
        notes.append("إغلاق تحت أدنى نطاق البنية القصير (BOS هابط)")
    if mood:
        notes.append(f"مزاج الأخبار: {'إيجابي' if sent > 0 else 'سلبي'} ({sent:+d}) → {mood:+.0f} على الاتجاه")
    if fng and kind == "crypto":
        notes.append(f"الخوف والطمع: {fng['value']} ({fng['label']})")
    if flow_adj:
        notes.append(f"تدفق الأوامر الحقيقي: انحياز CVD {float(flow['cvd_ratio']) * 100:+.1f}% → {flow_adj:+.1f} على الاتجاه")
    if rel:
        notes.append(f"علاقات الأصول المكتشفة: {rel:+.0f} على الاتجاه")
    notes += why
    if risk_mode == "reduced" and permission != "wait":
        notes.append("المخاطرة ستُخفَّض 50% لأن السياق ليس قوياً/متوافقاً بما يكفي")

    # ---- ملخص
    if permission == "wait":
        headline = "لا تدخل الآن: " + (why[0] if why else "السياق غير صالح للتداول")
    elif permission == "selective":
        headline = f"سياق {STATE_AR[state]} بلا اتجاه واضح — لن يُقبل إلا صفقة بدرجة A وبمخاطرة مخفضة"
    else:
        headline = f"سياق {STATE_AR[state]} {BIAS_AR[bias]} (قوة {strength}/100) — {PERM_AR[permission]}"

    lv = {"resistance": (ef.get("structure") or {}).get("reference_high") or (ef.get("liquidity") or {}).get("prior_high"),
          "support": (ef.get("structure") or {}).get("reference_low") or (ef.get("liquidity") or {}).get("prior_low")}
    return {"bias": bias, "bias_label": BIAS_AR[bias], "strength": strength, "direction_score": round(D, 1), "aligned": bool(aligned),
            "state": state, "state_label": STATE_AR[state], "permission": permission, "permission_label": PERM_AR[permission],
            "risk_mode": risk_mode, "risk_factor": 0.5 if risk_mode == "reduced" else 1.0, "adjust": adjust, "headline": headline, "notes": notes,
            "frames": [{"tf": tf, "trend": views[tf]["trend"], "bias": (frames.get(tf) or {}).get("bias"), "regime": (frames.get(tf) or {}).get("regime_label"),
                        "adx": views[tf]["adx"], "rsi": views[tf]["rsi"]} for tf in w if tf in views],
            "levels": {k: (round(float(v), 8) if v else None) for k, v in lv.items()}, "missing": miss,
            "flow": ({"cvd_ratio": flow.get("cvd_ratio"), "book_imbalance": flow.get("book_imbalance"), "venue": flow.get("venue")} if flow and flow.get("available") else None)}


def block_reason(ctx, side, grade):
    """هل يمنع السياق هذا الاتجاه/الدرجة؟ يعيد نص السبب أو None."""
    p = ctx["permission"]
    if p == "wait":
        return ctx["headline"]
    if p == "long" and side == "SELL":
        return f"السياق صاعد (قوة {ctx['strength']}/100): صفقات البيع ممنوعة حتى ينقلب السياق"
    if p == "short" and side == "BUY":
        return f"السياق هابط (قوة {ctx['strength']}/100): صفقات الشراء ممنوعة حتى ينقلب السياق"
    if p == "selective" and grade != "A":
        return "السياق محايد: لا تُقبل إلا صفقة بدرجة A"
    return None
