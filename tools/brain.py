"""العقل: حلقة تعلم مستمرة تجمع (1) اكتشاف العلاقات بين الأصول، (2) توليد واختبار الاستراتيجيات، (3) التعلم من نتائج صفقاتك الحية.
كل شيء يُحفظ في data/knowledge.json. لا شيء يُقبل إلا بعد اختبار صارم، ولا ينفّذ أي صفقة حقيقية."""
import json, threading
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from tools import assets as A, lab, market_tools as m

KN = Path(__file__).resolve().parent.parent / "data" / "knowledge.json"
RELATION_UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XAU/USD", "XAG/USD", "DXY", "EUR/USD", "USD/JPY", "GBP/USD", "SPY", "QQQ",
                     "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "JPM", "XOM"]
_lock, _run = threading.Lock(), threading.Lock()
EMPTY = {"relations": [], "log": [], "calibration": None, "cycles": 0, "last_cycle": None, "rel_tests": 0}


def load():
    with _lock:
        try:
            return {**EMPTY, **json.loads(KN.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            return json.loads(json.dumps(EMPTY))


def save(kn):
    with _lock:
        KN.parent.mkdir(exist_ok=True)
        KN.write_text(json.dumps(kn, ensure_ascii=False, indent=1), encoding="utf-8")


def running():
    return _run.locked() or lab.summary()["running"]


def short(s):
    return s.split("/")[0] if s.endswith("/USDT") else s


# ---------------------------------------------------------------- العلاقات بين الأصول
def daily_returns(sym):
    """عوائد يومية بأيام العمل فقط (لتتوافق العملات الرقمية مع الأسهم): عائد الاثنين = من إغلاق الجمعة."""
    _, df = m.candles(sym, "1d")
    idx = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    s = pd.Series(df["close"].values, index=idx)
    s = s[~s.index.duplicated(keep="last")]
    s = s[s.index.dayofweek < 5]
    return s.pct_change().dropna()


def _corr(x, y):
    if len(x) < 10:
        return 0.0
    r = np.corrcoef(x, y)[0, 1]
    return float(r) if np.isfinite(r) else 0.0


def check_relation(x, y, k=4.0):
    """علاقة مقبولة فقط إن: |r| ≥ k/√n (حد صارم لكثرة الاختبارات)، وبنفس الإشارة في أول 70% وآخر 30% (خارج العينة)، وفي كل ثلث."""
    n = len(x)
    r = _corr(x, y)
    if abs(r) < k / np.sqrt(n):
        return None
    cut, sg = int(n * 0.7), np.sign(r)
    r_is, r_oos = _corr(x[:cut], y[:cut]), _corr(x[cut:], y[cut:])
    thirds = [_corr(x[i * n // 3:(i + 1) * n // 3], y[i * n // 3:(i + 1) * n // 3]) for i in range(3)]
    if not (np.sign(r_is) == sg and np.sign(r_oos) == sg and abs(r_oos) >= 2 / np.sqrt(n - cut) and all(np.sign(t) == sg for t in thirds)):
        return None
    return {"r": round(r, 3), "r_oos": round(r_oos, 3), "n": int(n)}


def discover_relations(on_progress=lambda msg, pct: None):
    rets = {}
    for i, s in enumerate(RELATION_UNIVERSE):
        try:
            r = daily_returns(s)
            if len(r) >= 250:
                rets[s] = r
        except Exception:  # noqa: BLE001
            pass
        on_progress(f"جلب بيانات {s}…", 100 * (i + 1) / len(RELATION_UNIVERSE) * 0.4)
    syms, tests, lead, corr = list(rets), 0, [], []
    for a in syms:
        for b in syms:
            if a == b:
                continue
            df = pd.concat([rets[a].rename("a"), rets[b].rename("b")], axis=1, join="inner").dropna()
            if len(df) < 250:
                continue
            for lag in (1, 2, 3):                            # a يسبق b بـ lag يوم عمل
                d2 = pd.concat([df["a"].shift(lag), df["b"]], axis=1).dropna()
                tests += 1
                ev = check_relation(d2.iloc[:, 0].values, d2.iloc[:, 1].values)
                if ev:
                    lead.append({"id": f"lead:{a}:{b}:{lag}", "kind": "leadlag", "a": a, "b": b, "lag": lag, **ev})
            if a < b and A.kind(a) != A.kind(b):               # ارتباط يومي بين فئتين مختلفتين (سياق فقط)
                tests += 1
                ev = check_relation(df["a"].values, df["b"].values)
                if ev:
                    corr.append({"id": f"corr:{a}:{b}", "kind": "corr", "a": a, "b": b, "lag": 0, **ev})
        on_progress(f"اختبار العلاقات… {short(a)}", 40 + 55 * (syms.index(a) + 1) / len(syms))
    lead = sorted(lead, key=lambda r: -abs(r["r"]))[:40]
    corr = sorted(corr, key=lambda r: -abs(r["r"]))[:15]
    kn = load()
    old = {r["id"] for r in kn["relations"]}
    new = lead + corr
    now = datetime.now().isoformat(timespec="seconds")
    prev = {r["id"]: r for r in kn["relations"]}
    for r in new:
        r["found"] = prev.get(r["id"], {}).get("found", now)
    kn["relations"], kn["rel_tests"] = new, kn.get("rel_tests", 0) + tests
    save(kn)
    ids = {r["id"] for r in new}
    return {"tests": tests, "assets": len(syms), "added": [r for r in new if r["id"] not in old], "dropped": len(old - ids), "total": len(new)}


def relation_text(r):
    if r["kind"] == "leadlag":
        return (f"{short(r['a'])} يسبق {short(r['b'])} بـ{r['lag']} يوم عمل — {'نفس الاتجاه' if r['r'] > 0 else 'عكس الاتجاه'} "
                f"(ارتباط {r['r']}، خارج العينة {r['r_oos']}، {r['n']} يوم)")
    return f"{short(r['a'])} ↔ {short(r['b'])}: ارتباط يومي {r['r']} ({'طردي' if r['r'] > 0 else 'عكسي'}، خارج العينة {r['r_oos']})"


def relation_signal(symbol):
    """مساهمة علاقات التقدم/التأخر في درجات الشراء/البيع (للسوينغ فقط): حتى ±12 نقطة، من أقوى 3 علاقات."""
    rels = [r for r in load()["relations"] if r["kind"] == "leadlag" and r["b"] == symbol]
    out = {"buy": 0.0, "sell": 0.0, "notes": []}
    for r in sorted(rels, key=lambda r: -abs(r["r"]))[:3]:
        try:
            ra = daily_returns(r["a"])
        except Exception:  # noqa: BLE001
            continue
        if len(ra) < 60:
            continue
        x, sd = float(ra.iloc[-r["lag"]]), float(ra.tail(250).std()) or 1e-9
        z = x / sd
        if abs(z) < 0.5:
            continue
        up = (z > 0) == (r["r"] > 0)
        out["buy" if up else "sell"] += min(6.0, 3 + 2 * abs(z))
        out["notes"].append(f"علاقة: {short(r['a'])} تحرك {x * 100:+.2f}% قبل {r['lag']} يوم وتاريخياً يسبق {short(symbol)} "
                            f"({'نفس' if r['r'] > 0 else 'عكس'} الاتجاه) → {'دعم للشراء' if up else 'دعم للبيع'}")
    out["buy"], out["sell"] = min(out["buy"], 12.0), min(out["sell"], 12.0)
    return out


# ---------------------------------------------------------------- التعلم من الصفقات الحية
def live_feedback():
    """يوقف الاستراتيجية التي خسرت فعلياً (≥12 صفقة محسومة ومتوسط < -0.15R) ويعاير نسب النجاح المعروضة بعد ≥20 صفقة."""
    import tracker
    res = [e for e in tracker.load() if e.get("plan") and e.get("status") in ("tp", "sl") and e.get("r") is not None]
    by = {}
    for e in res:
        for nm in e["plan"].get("strategy", []):
            by.setdefault(nm, []).append(e["r"])
    lib, retired = lab.load(), []
    for it in lib["items"]:
        rs = by.get(it["name"], [])
        if it["status"] == "active" and len(rs) >= 12 and float(np.mean(rs)) < -0.15:
            it["status"], it["note"] = "retired", f"أوقفها التعلم من الصفقات الحية: {len(rs)} صفقة بمتوسط {np.mean(rs):.2f}R"
            retired.append(it["name"])
    if retired:
        lab.save(lib)
    kn, pairs = load(), [(e["plan"]["win_rate_est"], e["status"] == "tp") for e in res if e["plan"].get("win_rate_est") is not None]
    if len(pairs) >= 20:
        est, act = float(np.mean([p[0] for p in pairs])), 100 * float(np.mean([p[1] for p in pairs]))
        kn["calibration"] = {"n": len(pairs), "est": round(est, 1), "actual": round(act, 1), "factor": round(max(0.6, min(1.2, act / est)), 2) if est else 1.0}
        save(kn)
    return {"resolved": len(res), "retired": retired, "calibration": kn["calibration"]}


def calibration_factor():
    c = load()["calibration"]
    return c["factor"] if c else 1.0


# ---------------------------------------------------------------- دورة التعلم الكاملة
def cycle(on_progress=lambda msg, pct: None, use_llm=False, n=40):
    if not _run.acquire(blocking=False):
        raise RuntimeError("دورة تعلم تعمل الآن.")
    try:
        on_progress("التعلم من نتائج صفقاتك الحية…", 1)
        fb = live_feedback()
        rel = discover_relations(lambda msg, p: on_progress(msg, 3 + p * 0.32))
        on_progress("توليد واختبار استراتيجيات جديدة…", 36)
        lr = lab.discover(n, use_llm, lambda msg, p: on_progress(msg, 36 + p * 0.64))
        kn = load()
        entry = {"time": datetime.now().isoformat(timespec="seconds"), "relations_added": [relation_text(r) for r in rel["added"][:6]],
                 "relations_total": rel["total"], "relations_dropped": rel["dropped"], "rel_tests": rel["tests"],
                 "strategies_added": lr["added"], "strategies_retired": lr["retired"], "strategies_tested": lr["tested"],
                 "live_retired": fb["retired"], "live_resolved": fb["resolved"]}
        kn["log"] = ([entry] + kn["log"])[:30]
        kn["cycles"] += 1
        kn["last_cycle"] = entry["time"]
        save(kn)
        on_progress("اكتملت دورة التعلم", 100)
        return entry
    finally:
        _run.release()


def report_text(e):
    L = [f"🧠 تقرير التعلم — دورة جديدة",
         f"🔬 اختبر {e['strategies_tested']} فكرة استراتيجية و{e['rel_tests']} علاقة بين الأصول"]
    if e["strategies_added"]:
        L.append("✅ استراتيجيات أُضيفت: " + "، ".join(e["strategies_added"][:4]))
    if e["strategies_retired"] or e["live_retired"]:
        L.append("⏸ أُوقفت: " + "، ".join((e["strategies_retired"] + e["live_retired"])[:4]))
    if e["relations_added"]:
        L.append("🔗 علاقات جديدة:\n" + "\n".join("• " + t for t in e["relations_added"][:3]))
    L.append(f"إجمالي العلاقات المقبولة الآن: {e['relations_total']}")
    return "\n".join(L)


def summary():
    kn = load()
    return {"relations": len(kn["relations"]), "cycles": kn["cycles"], "last_cycle": kn["last_cycle"], "calibration": kn["calibration"],
            "running": running(), "lab": lab.summary()}
