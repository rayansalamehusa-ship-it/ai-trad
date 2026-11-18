"""محرك التحليل: analyze() للوضع المحلي (متعدد الفريمات، شراء/بيع، صفقات أو سكالبينج)، run_ai() لوضع CrewAI، scan() لمسح عدة أصول."""
import os, time
from tools import assets as A, brain, grok, lab, market_tools as m, strategies as S, market_models as MM

os.environ.setdefault("OTEL_SDK_DISABLED", "true")

STEPS = [
    ("price", "مراقب الأسعار", "Price Watcher"),
    ("news", "محلل الأخبار", "News Scout"),
    ("strategist", "باحث الاستراتيجيات", "Strategy Researcher"),
    ("hunter", "صياد الفرص", "Opportunity Hunter"),
    ("simulator", "مهندس المحاكاة", "Backtester"),
    ("risk", "مدير المخاطر", "Risk Manager"),
    ("ceo", "المدير التنفيذي", "CEO"),
]
KEYS = [s[0] for s in STEPS]
MODES = {
    "swing": {"label": "صفقات (سوينغ)", "tfs": ["1h", "4h", "1d"], "entry": "4h", "w": {"1h": .25, "4h": .40, "1d": .35},
              "sl_lim": (1.2, 3.0), "tp": (1.5, 3.0), "track": "1h", "expire_h": 14 * 24},
    "scalp": {"label": "سكالبينج", "tfs": ["5m", "15m", "1h"], "entry": "15m", "w": {"5m": .25, "15m": .40, "1h": .35},
              "sl_lim": (0.8, 2.0), "tp": (1.2, 2.4), "track": "5m", "expire_h": 12},
}
GRADES = [(70, "A", "فرصة قوية"), (55, "B", "فرصة متوسطة"), (40, "C", "فرصة ضعيفة (مضاربة)")]
SIDE_AR = {"BUY": "شراء", "SELL": "بيع", "WAIT": "انتظار"}
TREND_AR = {"up": "صاعد ▲", "down": "هابط ▼", "flat": "جانبي ◆"}
_noop = lambda *a: None  # noqa: E731


def parse_decision(text):
    t = text.upper()
    a, r = t.find("APPROVED"), t.find("REJECTED")
    if a < 0 and r < 0:
        return "UNKNOWN"
    if a < 0:
        return "REJECTED"
    if r < 0:
        return "APPROVED"
    return "APPROVED" if a < r else "REJECTED"


# ---------------------------------------------------------------- جمع البيانات لفريم واحد
def _tf_view(symbol, tf, items):
    ex, df = m.candles(symbol, tf)
    if len(df) < 150:
        raise RuntimeError(f"بيانات {symbol} على فريم {tf} غير كافية ({len(df)} شمعة)")
    ind, c, cost = S.Ind(df), df.close, A.cost(symbol)
    e20, e50, atr_ = ind.ema(20), ind.ema(50), ind.atr()
    mc, sg = ind.macd()
    hist = mc - sg
    _, pdi, mdi = ind.adx_di()
    v = {"tf": tf, "ex": ex, "df": df, "ind": ind, "price": float(c.iloc[-1]), "atr": float(atr_.iloc[-1]),
         "ema20": float(e20.iloc[-1]), "ema50": float(e50.iloc[-1]), "rsi": round(float(ind.rsi().iloc[-1]), 1),
         "adx": round(float(ind.adx().iloc[-1]), 1), "hist": float(hist.iloc[-1]), "hist_prev": float(hist.iloc[-2]),
         "reg": S.regime(df, ind), "hh20": float(df.high.tail(20).max()), "sw_low": float(df.low.tail(12).min()),
         "sw_high": float(df.high.tail(12).max()), "e20s": e20, "e50s": e50}
    up = v["ema20"] > v["ema50"] and v["price"] > v["ema50"]
    dn = v["ema20"] < v["ema50"] and v["price"] < v["ema50"]
    v["trend"] = "up" if up else "down" if dn else "flat"
    strats, trades = [], {}
    for it in items:
        ev = S.evaluate(it, df, ind, cost)
        st = S.trade_stats([t[2] for t in ev["trades"]])
        fl, fs = bool(ev["long"].tail(2).any()), bool(ev["short"].tail(2).any())
        sig = "BUY" if fl and not fs else "SELL" if fs and not fl else None
        trades[it["id"]] = ev["trades"]
        strats.append({"id": it["id"], "name": it["name"], "origin": it["origin"], "exits": it["exits"], "signal": sig,
                       "stats": st, "passed": S.asset_pass(st), "bars": len(df)})
    v["strats"], v["trades"] = strats, trades
    # درجات الشراء/البيع لهذا الفريم (0-100)
    b = s = 0.0
    if v["trend"] == "up":
        b += 30
    elif v["price"] > v["ema50"]:
        b += 12
    if v["trend"] == "down":
        s += 30
    elif v["price"] < v["ema50"]:
        s += 12
    if v["hist"] > 0:
        b += 10 + (5 if v["hist"] > v["hist_prev"] else 0)
    elif v["hist"] < 0:
        s += 10 + (5 if v["hist"] < v["hist_prev"] else 0)
    r = v["rsi"]
    b += 10 if 45 <= r <= 68 else 8 if r < 30 else 0
    s += 10 if 32 <= r <= 55 else 8 if r > 70 else 0
    if v["adx"] >= 22:
        if float(pdi.iloc[-1]) > float(mdi.iloc[-1]):
            b += 10
        else:
            s += 10
    nb = sum(1 for x in strats if x["signal"] == "BUY" and x["passed"])
    ns = sum(1 for x in strats if x["signal"] == "SELL" and x["passed"])
    v["buy"], v["sell"] = min(100.0, b + min(35, 15 * nb)), min(100.0, s + min(35, 15 * ns))
    return v


def _gather(symbol, style):
    cfg, kind_ = MODES[style], A.kind(symbol)
    items = lab.active_items()
    views = {tf: _tf_view(symbol, tf, items) for tf in cfg["tfs"]}
    ev = views[cfg["entry"]]
    market_model = MM.analyze_market(ev["df"])
    price, chg = m.quote(symbol)
    low = views[cfg["tfs"][0]]
    price = float(price) if price else low["price"]
    if chg is None:
        bpd = int(86_400_000 / m.TF_MS[cfg["entry"]])
        cl = ev["df"].close
        chg = (ev["price"] / float(cl.iloc[-1 - bpd]) - 1) * 100 if len(cl) > bpd else 0.0
    # تجميع الاتجاه عبر الفريمات
    buy = sum(cfg["w"][tf] * views[tf]["buy"] for tf in cfg["tfs"])
    sell = sum(cfg["w"][tf] * views[tf]["sell"] for tf in cfg["tfs"])
    # طبقة مستقلة لهيكل السوق وتدفق الحجم وVWAP. أثر ML محدود ولا يُستخدم إلا إذا تفوق خارج العينة على baseline.
    if market_model.get("available"):
        buy += min(8.0, market_model["bull_score"] * 1.5)
        sell += min(8.0, market_model["bear_score"] * 1.5)
        ml = market_model.get("ml", {})
        if ml.get("available") and ml.get("beats_baseline"):
            delta = max(-4.0, min(4.0, (ml["prob_up_experimental"] - 0.5) * 16))
            buy += delta
            sell -= delta
    trends = [views[tf]["trend"] for tf in cfg["tfs"]]
    why = []
    if all(t == "up" for t in trends):
        buy += 8; why.append("كل الفريمات صاعدة — توافق كامل (+8 للشراء)")
    if all(t == "down" for t in trends):
        sell += 8; why.append("كل الفريمات هابطة — توافق كامل (+8 للبيع)")
    top = views[cfg["tfs"][-1]]
    if top["trend"] == "down":
        buy -= 15; why.append(f"الفريم الأكبر ({top['tf']}) هابط — عكس الشراء (-15)")
    if top["trend"] == "up":
        sell -= 15; why.append(f"الفريم الأكبر ({top['tf']}) صاعد — عكس البيع (-15)")
    if ev["reg"]["state"] == "high_vol":
        buy -= 20; sell -= 20; why.append("تذبذب شديد على فريم الدخول (-20 للطرفين)")
    if style == "swing":                                   # علاقات الأصول المكتشفة (تقدم/تأخر يومي)
        try:
            rel = brain.relation_signal(symbol)
            buy, sell, why = buy + rel["buy"], sell + rel["sell"], why + rel["notes"]
        except Exception:  # noqa: BLE001
            pass
    lts = float(low["df"]["ts"].iloc[-1])
    closed = kind_ != "crypto" and (time.time() * 1000 - lts) > 8 * m.TF_MS[cfg["tfs"][0]]
    buy, sell = max(0.0, min(100.0, buy)), max(0.0, min(100.0, sell))
    return {"closed": closed, "cfg": cfg, "views": views, "ev": ev, "market_model": market_model, "price": price, "chg": round(float(chg), 2), "buy": buy, "sell": sell,
            "why": why, "kind": A.kind(symbol), "n_lib": len(items)}


def _side_hist(g, side):
    """إحصاء تاريخي لصفقات الاستراتيجيات الناجحة في اتجاه معيّن على فريم الدخول (آخر 50% من البيانات = السوق الحديث)."""
    ev, sd = g["ev"], 1 if side == "BUY" else -1
    cut = len(ev["df"]) // 2
    rs = [t[2] for s in ev["strats"] if s["passed"] for t in ev["trades"][s["id"]] if t[1] == sd and t[0] >= cut]
    return S.trade_stats(rs)


# ---------------------------------------------------------------- نصوص الفريق
def _price_text(symbol, g, fng, fund):
    lines = [f"المصدر: {g['ev']['ex']} | السعر: {A.rp(g['price'])} | تغير 24س: {g['chg']}%"]
    for tf, v in g["views"].items():
        lines.append(f"• {tf}: {TREND_AR[v['trend']]} | RSI {v['rsi']} | ADX {v['adx']} | {v['reg']['label']}")
    if fng and g["kind"] == "crypto":
        lines.append(f"الخوف والطمع: {fng['value']} ({fng['label']})")
    if fund is not None:
        lines.append(f"معدل التمويل: {fund * 100:.4f}%")
    return "\n".join(lines)


def _strat_text(g, style):
    ev, lines = g["ev"], []
    lines.append(f"اختبار على فريم {ev['tf']} ({len(ev['df'])} شمعة) | الدخول عند الشمعة التالية، وقف/هدف بالـATR، مع تكلفة التنفيذ")
    for s in sorted(ev["strats"], key=lambda x: -x["stats"]["avg_r"]):
        st = s["stats"]
        lines.append(f"• {s['name']} [{'📈 شراء الآن' if s['signal'] == 'BUY' else '📉 بيع الآن' if s['signal'] == 'SELL' else 'لا إشارة'}]\n"
                     f"   صفقات {st['n']} | نجاح {st['win_rate']}% | متوسط {st['avg_r']}R | PF {st['pf']} | أقصى هبوط {st['max_dd_r']}R | "
                     f"{'✓ اجتازت' if s['passed'] else '✗ لم تجتز'}")
    return "\n".join(lines)


def describe_market(symbol, style="swing"):          # تستعملها أدوات CrewAI
    symbol = A.normalize(symbol)
    g = _gather(symbol, style)
    return _price_text(symbol, g, m.fear_greed(), m.funding_rate(symbol))


def describe_strategies(symbol, style="swing"):
    symbol = A.normalize(symbol)
    return _strat_text(_gather(symbol, style), style)


def _chart(v, n=100):
    df = v["df"].tail(n)
    return {"c": [[A.rp(x) for x in r] for r in df[["open", "high", "low", "close"]].values],
            "e20": [A.rp(x) for x in v["e20s"].tail(n)], "e50": [A.rp(x) for x in v["e50s"].tail(n)]}


# ---------------------------------------------------------------- خطة الصفقة
def _levels(side, v, cfg, best):
    p, a, sd = v["price"], v["atr"], 1 if side == "BUY" else -1
    if best:
        dist, r1, r2 = best["exits"]["sl_atr"] * a, best["exits"]["rr"], best["exits"]["rr"] * 1.5
    else:
        lo, hi = cfg["sl_lim"]
        sw = v["sw_low"] if sd > 0 else v["sw_high"]
        dist, (r1, r2) = min(max(abs(p - sw) + 0.25 * a, lo * a), hi * a), cfg["tp"]
    ext = (p - v["ema20"]) * sd
    # Market-entry mode: use the live analysis price; never wait for a pullback limit.
    # Execution layer rechecks the latest broker Bid/Ask and rejects stale setups.
    limit = None
    return {"entry": A.rp(p), "stop_loss": A.rp(p - sd * dist), "take_profit": A.rp(p + sd * r1 * dist),
            "take_profit2": A.rp(p + sd * r2 * dist), "entry_limit": limit, "entry_type": "MARKET", "rr": round(r1, 2), "dist": dist}


def analyze(symbol, capital, style="swing", emit=_noop, light=False):
    """light=True: مسح سريع بدون أخبار ولا معدل التمويل."""
    symbol = A.normalize(symbol)
    style = style if style in MODES else "swing"
    emit("price", "running", "")
    g = _gather(symbol, style)
    cfg, ev, kind = g["cfg"], g["ev"], g["kind"]
    fng = m.fear_greed() if kind == "crypto" else None
    fund = None if light else m.funding_rate(symbol)
    emit("price", "done", _price_text(symbol, g, fng, fund))

    emit("news", "running", "")
    sent, gk, news_lines = 0, None, []
    if kind == "crypto":
        items = [] if light else m.get_news(symbol.split("/")[0])
        sent = m.news_sentiment(items)
        mood = "إيجابي" if sent > 0 else "سلبي" if sent < 0 else "محايد"
        news_lines = ([f"• {a['title']}" for a in items] + [f"\nالمزاج العام للعناوين: {mood}"]) if items else ["لا عناوين متاحة — المزاج محايد."]
    else:
        news_lines = ["أصل غير رقمي: لا تغذية عناوين آلية. " + ("راقب إعلانات الأرباح وأخبار الشركة والقطاع." if kind == "stock" else "راقب التقويم الاقتصادي (الفيدرالي، التضخم، الوظائف) وتجنّب الدخول قبل الأخبار القوية بـ30 دقيقة.")]
    if light:
        news_lines.append("(تم تخطي الأخبار وGrok في المسح السريع)")
    elif grok.available():
        try:
            gk = grok.x_pulse(symbol, kind)
            sent += gk["sentiment"]
            news_lines += ["", grok.pulse_text(gk)]
        except Exception as e:  # noqa: BLE001
            gk = {"error": str(e)[:160]}
            news_lines += ["", f"تعذر جلب نبض X من Grok: {gk['error']}"]
    else:
        news_lines += ["", "💡 أضف مفتاح xAI (Grok) في الإعدادات لقراءة منصة X مباشرة."]
    emit("news", "done", "\n".join(news_lines))

    emit("strategist", "running", "")
    lib = lab.summary()
    act = [f"• {tf}: " + ("، ".join(f"{'📈' if s['signal'] == 'BUY' else '📉'} {s['name']}" for s in v["strats"] if s["signal"] and s["passed"]) or "لا إشارات مؤكدة")
           for tf, v in g["views"].items()]
    emit("strategist", "done", f"مخزون الاستراتيجيات: {lib['total']} ({lib['active']} نشطة، {lib['generated']} مولّدة بالبحث، {lib.get('tested', 0)} فكرة اختُبرت)\n"
         f"آخر بحث: {(lib.get('last_run') or 'لم يُجرَ بعد').replace('T', ' ')}\nالإشارات الحالية المؤكدة (اجتازت اختباراً على هذا الأصل):\n" + "\n".join(act))

    emit("hunter", "running", "")
    buy, sell = g["buy"], g["sell"]
    tot = (buy + sell) or 1.0
    buy_pct, sell_pct = round(100 * buy / tot), 100 - round(100 * buy / tot)
    gap = abs(buy - sell)
    side = "BUY" if buy > sell else "SELL"
    top = max(buy, sell)
    grade, glabel = next(((gr, l) for t, gr, l in GRADES if top >= t), ("-", "لا تدخل الآن"))
    clear = gap >= 12
    confirm = [s for s in ev["strats"] if s["signal"] == side and s["passed"]]
    best = max(confirm, key=lambda s: s["stats"]["avg_r"]) if confirm else None
    hist = {"BUY": _side_hist(g, "BUY"), "SELL": _side_hist(g, "SELL")}
    plan, action = None, "WAIT"
    if grade != "-" and clear:
        action = side
        lv = _levels(side, ev, cfg, best)
        ps = m.position_size(capital, ev["price"], lv["stop_loss"], cap=(kind in ("crypto", "stock") and side == "BUY"))
        h = hist[side]
        wr = round(100 * (h["n"] * h["win_rate"] / 100 + 0.4 * 10) / (h["n"] + 10), 1) if h["n"] else None
        if wr is not None:
            wr = round(min(95.0, wr * brain.calibration_factor()), 1)
        cost_r = round(2 * A.cost(symbol) * ev["price"] / lv["dist"], 2) if lv["dist"] else 0
        confirmed_tfs = [tf for tf, v in g["views"].items() if v["trend"] == ("up" if side == "BUY" else "down")]
        plan = {"action": side, "symbol": symbol, "mode": style, "entry_tf": cfg["entry"], "confirmed_tfs": confirmed_tfs,
                **{k: lv[k] for k in ("entry", "stop_loss", "take_profit", "take_profit2", "entry_limit", "entry_type", "rr")},
                "size_usd": ps["size_usd"], "risk_usd": ps["risk_usd"], "leverage": ps["leverage"], "grade": grade, "grade_label": glabel,
                "score": round(top), "strategy": [s["name"] for s in confirm], "win_rate_est": wr, "win_n": h["n"], "cost_r": cost_r,
                "track": cfg["track"], "expire_ms": cfg["expire_h"] * 3_600_000}
    why = list(g["why"])
    mm = g.get("market_model", {})
    if mm.get("available"):
        why.append(f"خوارزمية بنية السوق: {mm['structure']} | النظام: {mm['regime']} | CHOP {mm['choppiness']} | ER {mm['efficiency_ratio']}")
        why.append(f"VWAP deviation {mm['vwap_gap_pct']}% | تدفق حجم تقريبي {mm['flow_imbalance_proxy']}")
        ml = mm.get("ml", {})
        if ml.get("available"):
            why.append(f"نموذج ML تجريبي: اتجاه صاعد {round(ml['prob_up_experimental']*100,1)}% خلال {ml['horizon_bars']} شموع؛ خارج العينة {ml['oos_accuracy']}%، تفوق على baseline: {'نعم' if ml['beats_baseline'] else 'لا'}")
    for tf, v in g["views"].items():
        why.append(f"{tf}: {TREND_AR[v['trend']]} — شراء {round(v['buy'])} / بيع {round(v['sell'])}")
    hunter = [f"الوضع: {cfg['label']} | فريم الدخول {cfg['entry']} | الفريمات المختبرة: {'، '.join(cfg['tfs'])}",
              f"قوة الاتجاه: شراء {buy_pct}% ({round(buy)}/100) مقابل بيع {sell_pct}% ({round(sell)}/100)",
              "الأعلى: " + (SIDE_AR[side] + f" — {glabel}" if grade != "-" else "لا أحد يتجاوز 40/100")]
    if not clear and grade != "-":
        hunter.append("⚠️ الفارق بين الشراء والبيع أقل من 12 نقطة — إشارات متعارضة → انتظار")
    for k, lab_ in (("BUY", "شراء"), ("SELL", "بيع")):
        h = hist[k]
        hunter.append(f"نجاح تاريخي حديث لاستراتيجيات {lab_} الناجحة: " + (f"{h['win_rate']}% من {h['n']} صفقة (متوسط {h['avg_r']}R)" if h["n"] else "لا بيانات كافية"))
    if plan:
        hunter.append(f"\nخطة {SIDE_AR[side]}:\nدخول: {plan['entry']}" + (f" (الأفضل عند {plan['entry_limit']})" if plan["entry_limit"] else "")
                      + f"\nوقف الخسارة: {plan['stop_loss']}\nالهدف 1: {plan['take_profit']} (1:{plan['rr']})\nالهدف 2: {plan['take_profit2']}")
    emit("hunter", "done", "\n".join(hunter))

    emit("simulator", "running", "")
    emit("simulator", "done", _strat_text(g, style))

    emit("risk", "running", "")
    if plan:
        emit("risk", "done", f"رأس المال: ${capital:,.2f}\nحجم الصفقة: ${plan['size_usd']:,.2f}" +
             (f" (رافعة ≈ {plan['leverage']}×)" if plan["leverage"] > 1 else " (بلا رافعة)") +
             f"\nالخسارة القصوى عند الوقف: ${plan['risk_usd']:,.2f} (≈ 2%)\nتكلفة التنفيذ التقديرية: {plan['cost_r']}R")
    else:
        emit("risk", "done", f"رأس المال: ${capital:,.2f}\nلا صفقة مقترحة — لا مخاطرة.")

    emit("ceo", "running", "")
    veto, warn = [], []
    if ev["reg"]["state"] == "high_vol":
        veto.append("التذبذب في أعلى 5% من آخر 250 شمعة على فريم الدخول — خطر مرتفع")
    if plan and g["closed"]:
        veto.append("السوق مغلق حالياً أو البيانات متأخرة — قد يتغير السعر عند الافتتاح")
    if plan and not confirm:
        veto.append("لا توجد استراتيجية ناجحة تؤكد الاتجاه الآن — الإعداد قراءة فنية فقط")
    if plan and grade == "C":
        veto.append("درجة ضعيفة (C) — لا تكفي للموافقة الصارمة")
    if plan and side == "BUY" and sent <= -2:
        veto.append("الأخبار سلبية بوضوح")
    if plan and side == "SELL" and sent >= 2:
        veto.append("الأخبار إيجابية بوضوح — خطر على صفقة البيع")
    if plan and plan["cost_r"] > 0.25:
        veto.append(f"تكلفة التنفيذ مرتفعة ({plan['cost_r']}R) — الوقف قريب جداً من السعر")
    if fng and fng["value"] >= 85 and side == "BUY":
        warn.append(f"طمع مفرط ({fng['value']}) — احتمال تصحيح")
    if fng and fng["value"] <= 15 and side == "SELL":
        warn.append(f"خوف شديد ({fng['value']}) — احتمال ارتداد")
    if fund is not None and fund > 0.0005 and side == "BUY":
        warn.append("معدل التمويل مرتفع: صفقات الشراء مزدحمة")
    if plan and side == "SELL" and kind == "crypto":
        warn.append("البيع في العملات الرقمية يتطلب عقوداً آجلة/هامش (Futures/Margin)؛ في السبوت يعني الخروج من مركز شراء فقط.")
    if kind == "stock":
        warn.append("الأسهم تتحرك فقط في ساعات السوق الأمريكي (9:30 صباحاً–4:00 عصراً بتوقيت نيويورك)، وقد تقفز عند الافتتاح؛ تجنّب الدخول قبل إعلان الأرباح.")
    elif kind != "crypto":
        warn.append("تجنّب الدخول قبل الأخبار الاقتصادية القوية، والسبريد يتسع عند الافتتاح وبعد الأخبار.")
    if style == "scalp":
        warn.append("السكالبينج حساس للسبريد والتنفيذ: تحقق أن سبريد وسيطك أقل بكثير من مسافة الوقف.")
    n = best["stats"]["n"] if best else 0
    conf = "جيدة" if n >= 30 else "متوسطة" if n >= 15 else "منخفضة"
    warn.append(f"العينة الإحصائية لأفضل استراتيجية مؤكدة {n} صفقة — الاختبار على نفس بيانات الأصل (ليس خارج العينة)، فالنتائج تقديرية." if n
                else "لا توجد استراتيجية مؤكدة — خفّض الحجم أو انتظر.")
    decision = "REJECTED" if (veto or not plan) else "APPROVED"
    if decision == "APPROVED":
        report = f"اجتازت الفلتر الصارم: {SIDE_AR[side]} بتوافق الفريمات واستراتيجية مؤكدة ({'، '.join(plan['strategy'][:2])})."
    elif plan:
        report = "لم تجتز الفلتر الصارم، وهذه خطة مضاربية:\n" + "\n".join(f"• {v}" for v in veto)
    else:
        report = "لا تدخل الآن:\n• " + ("إشارات الشراء والبيع متقاربة" if grade != "-" else "قوة الاتجاه ضعيفة") + (
            "\n• " + veto[0] if veto else "")
    report += "\n\nلماذا؟\n" + "\n".join(f"• {w}" for w in why) + "\n\nتنبيهات:\n" + "\n".join(f"⚠️ {w}" for w in warn)
    review = None
    if not light and grok.available() and os.getenv("GROK_REVIEW", "1") != "0":
        try:
            review = grok.second_opinion(symbol, "\n".join(hunter) + "\n" + "\n".join(warn) + "\nالقرار الآلي: " + decision)
            vl = {"agree": "يوافق ✅", "caution": "يوصي بالحذر ⚠️", "disagree": "يعارض ❌"}[review["verdict"]]
            report += f"\n\nرأي Grok المستقل (استشاري): {vl}\n" + "\n".join(f"• {x}" for x in review["points"])
        except Exception as e:  # noqa: BLE001
            review = {"error": str(e)[:160]}
    emit("ceo", "done", f"{decision}\n{report}")
    strategies = [{k: v for k, v in s.items()} for s in sorted(ev["strats"], key=lambda x: -x["stats"]["avg_r"])]
    return {"decision": decision, "action": action, "plan": plan, "report": report, "mode": style, "mode_label": cfg["label"],
            "entry_tf": cfg["entry"], "asset_kind": kind, "market_closed": g["closed"], "regime": ev["reg"]["state"], "regime_label": ev["reg"]["label"],
            "confidence": conf, "warnings": warn, "grok": {"pulse": gk, "review": review}, "strategies": strategies, "bars": len(ev["df"]),
            "market_model": g.get("market_model"), "buy_score": round(buy), "sell_score": round(sell), "buy_pct": buy_pct, "sell_pct": sell_pct, "side_hist": hist,
            "tfs": [{"tf": tf, "trend": v["trend"], "trend_label": TREND_AR[v["trend"]], "rsi": v["rsi"], "adx": v["adx"],
                     "buy": round(v["buy"]), "sell": round(v["sell"]), "regime": v["reg"]["label"],
                     "active": [{"name": s["name"], "signal": s["signal"]} for s in v["strats"] if s["signal"] and s["passed"]]}
                    for tf, v in g["views"].items()],
            "charts": {tf: _chart(v) for tf, v in g["views"].items()}, "score": round(top) + (100 if decision == "APPROVED" else 0),
            "setup_score": round(top), "grade": grade, "grade_label": glabel, "price": A.rp(g["price"]), "rsi": ev["rsi"],
            "adx": ev["adx"], "change": g["chg"], "symbol": symbol}


def run_local(symbol, capital, style, on_step):
    return analyze(symbol, capital, style, on_step)


def scan(symbols, capital, style, on_row):
    for sym in symbols:
        try:
            r = analyze(sym, capital, style, light=True)
            row = {"symbol": sym, "price": r["price"], "decision": r["decision"], "action": r["action"], "regime_label": r["regime_label"],
                   "change": r["change"], "rsi": r["rsi"], "score": r["score"], "setup_score": r["setup_score"],
                   "buy_pct": r["buy_pct"], "sell_pct": r["sell_pct"], "grade": r["grade"], "grade_label": r["grade_label"], "plan": r["plan"]}
        except Exception as e:  # noqa: BLE001
            row = {"symbol": sym, "error": str(e)[:120], "score": -1}
        on_row(row)


# ---------------------------------------------------------------- وضع الذكاء الاصطناعي (CrewAI + Gemini)
def run_ai(symbol, capital, style, on_step):
    from crewai import Task, Crew, Process
    from agents.crew_agents import create_trading_team
    from tools import crew_tools

    symbol = A.normalize(symbol)
    crew_tools.CURRENT["style"] = style
    base = analyze(symbol, capital, style)             # حساب هيكلي صامت: الخطة والشارت والأرقام تُحسب بالكود لا بالنموذج
    coin, t, cfg = symbol, create_trading_team(), MODES[style]
    price = Task(description=f"استعمل أداة الأسعار لـ{symbol} واذكر السعر واتجاه كل فريم وRSI وحالة السوق (وضع: {cfg['label']}).",
                 expected_output="تقرير رقمي موجز متعدد الفريمات.", agent=t["price"])
    news = Task(description=f"استعمل أداة الأخبار لـ{coin} وحدد المزاج: إيجابي / سلبي / محايد (للأصول غير الرقمية اعتمد على التحليل الفني وحذّر من الأخبار الاقتصادية).",
                expected_output="ملخص الأخبار وتقييم التأثير.", agent=t["news"])
    strat = Task(description=f"استعمل أدوات المخزون: اعرض المخزون، وطبّقه على {symbol} لمعرفة الإشارات الحالية (شراء/بيع) وجودتها. "
                             "ثم اقترح استراتيجية جديدة واحدة مختلفة عن الموجودة وأنشئها بأداة الإنشاء (تُختبر تلقائياً ولا تدخل إلا إن نجحت). "
                             "قل بصدق إن رُفضت.", expected_output="الإشارات الحالية وجودتها ونتيجة الاستراتيجية الجديدة.",
                 agent=t["strategist"], context=[price])
    hunter = Task(description=f"بناءً على التقارير اقترح لـ{symbol} إما BUY أو SELL أو WAIT مع سعر الدخول وTake Profit وStop Loss بأرقام دقيقة "
                              "(الوقف بين 1 و2.5×ATR). لا تعاكس الفريم الأكبر إلا بسبب قوي. القرار الحسابي المرجعي من المحرك:\n" + base["report"][:900],
                  expected_output="خطة الصفقة بالأرقام.", agent=t["hunter"], context=[price, news, strat])
    sim = Task(description=f"شغّل أداة الاختبار التاريخي على {symbol} وفسّر أي الاستراتيجيات اجتازت وهل تتفوق، واذكر أن العينة صغيرة إن كانت الصفقات قليلة.",
               expected_output="نتائج المحاكاة وتقييم صادق لموثوقيتها.", agent=t["simulator"], context=[hunter])
    risk = Task(description=f"رأس المال {capital}$. استعمل حاسبة الحجم (لا تحسب يدوياً) بسعر الدخول ووقف الخسارة المقترحين، ثم قيّم المخاطر.",
                expected_output="حجم الدخول بالدولار وتقييم المخاطر.", agent=t["risk"], context=[hunter, sim])
    ceo = Task(description=f"راجع كل التقارير لـ{symbol} واتخذ القرار النهائي. ارفض إذا كان التذبذب شديداً أو لم تؤكد استراتيجية ناجحة الاتجاه. "
                           "ابدأ ردك بكلمة واحدة فقط: APPROVED أو REJECTED، ثم اشرح بالعربية مع نقاط الدخول والخروج واتجاه الصفقة (شراء/بيع)، واذكر مستوى الثقة بصدق.",
               expected_output="APPROVED أو REJECTED في السطر الأول ثم التفاصيل.", agent=t["ceo"],
               context=[price, news, strat, hunter, sim, risk])
    done = []

    def cb(out):
        i = len(done)
        done.append(1)
        on_step(KEYS[i], "done", getattr(out, "raw", str(out)))
        if i + 1 < len(KEYS):
            on_step(KEYS[i + 1], "running", "")

    on_step("price", "running", "")
    crew = Crew(agents=list(t.values()), tasks=[price, news, strat, hunter, sim, risk, ceo],
                process=Process.sequential, task_callback=cb, verbose=True)
    result = str(crew.kickoff())
    return {**base, "decision": parse_decision(result), "report": result + "\n\n— الحساب الآلي المرجعي —\n" + base["report"]}


def run_analysis(symbol, capital, mode, style, on_step):
    if mode == "ai":
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            raise RuntimeError("أضف مفتاح Google Gemini من تبويب الإعدادات أولاً (أو اختر الوضع المحلي المجاني).")
        try:
            import crewai  # noqa: F401
        except ImportError:
            raise RuntimeError("مكتبة crewai غير مثبتة. نفّذ: pip install -r requirements-ai.txt")
        return run_ai(symbol, capital, style, on_step)
    return run_local(symbol, capital, style, on_step)
