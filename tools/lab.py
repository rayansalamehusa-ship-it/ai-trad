"""مختبر الاستراتيجيات: مخزون استراتيجيات + وكيل يولّد ويختبر استراتيجيات جديدة (بحث عشوائي/طفرات/اقتراح Gemini).

القاعدة: لا تدخل استراتيجية المخزون إلا بعد اجتياز بوابة صارمة على بيانات عدة أصول وفريمات مقسّمة زمنياً:
  تدريب (0–60%) ← تحقق (60–80%) ← اختبار أخير (80–100%) لم يُستعمل في الاختيار.
"""
import hashlib, json, os, random, re, threading, time
from datetime import datetime
from pathlib import Path
import numpy as np
from tools import assets as A, market_tools as m, strategies as S

LIB = Path(__file__).resolve().parent.parent / "data" / "strategies.json"
UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XAU/USD", "EUR/USD", "USD/JPY", "GBP/USD", "NVDA", "SPY"]
TFS = ["15m", "1h", "4h"]
_lock, _run = threading.Lock(), threading.Lock()

BUILTIN = [
    ("ema_cross", {"fast": 20, "slow": 50, "adx_min": 20}, {"sl_atr": 1.5, "rr": 2.0, "hold": 30}),
    ("ema_cross", {"fast": 9, "slow": 21, "adx_min": 0}, {"sl_atr": 1.2, "rr": 1.5, "hold": 20}),
    ("pullback", {"trend": 200, "rsi_len": 3, "rsi_lo": 30}, {"sl_atr": 1.5, "rr": 1.5, "hold": 16}),
    ("donchian", {"n": 20, "adx_min": 20}, {"sl_atr": 2.0, "rr": 2.5, "hold": 40}),
    ("rsi_rev", {"len": 14, "lo": 30}, {"sl_atr": 1.5, "rr": 1.5, "hold": 16}),
    ("boll_rev", {"n": 20, "k": 2.0}, {"sl_atr": 1.5, "rr": 1.5, "hold": 16}),
    ("macd_cross", {"fast": 12, "slow": 26, "sig": 9, "trend": 200}, {"sl_atr": 1.5, "rr": 2.0, "hold": 30}),
    ("stoch", {"n": 14, "lo": 20}, {"sl_atr": 1.2, "rr": 1.5, "hold": 14}),
]


def spec_id(spec):
    return hashlib.md5(json.dumps([spec["type"], spec["params"], spec["exits"]], sort_keys=True).encode()).hexdigest()[:8]


def _item(spec, origin, status="active", note=""):
    spec = S.clean_spec(spec)
    return {"id": spec_id(spec), "name": S.name_of(spec), **spec, "origin": origin, "status": status, "note": note,
            "created": datetime.now().isoformat(timespec="seconds"), "stats": None, "fails": 0}


def load():
    with _lock:
        try:
            lib = json.loads(LIB.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            lib = None
        if not lib or not lib.get("items"):
            lib = {"meta": {"tested": 0, "last_run": None, "runs": 0},
                   "items": [_item({"type": t, "params": p, "exits": e}, "builtin") for t, p, e in BUILTIN]}
            _save(lib)
        return lib


def _save(lib):
    LIB.parent.mkdir(exist_ok=True)
    LIB.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")


def save(lib):
    with _lock:
        _save(lib)


def active_items():
    return [it for it in load()["items"] if it["status"] == "active"]


def summary():
    lib = load()
    its = lib["items"]
    return {"total": len(its), "active": sum(i["status"] == "active" for i in its),
            "generated": sum(i["origin"] != "builtin" for i in its), **lib["meta"], "running": _run.locked()}


# ---------------------------------------------------------------- التقييم الزمني المقسّم
class DS:
    def __init__(self, sym, tf, df):
        self.sym, self.tf, self.df, self.ind, self.cost = sym, tf, df, S.Ind(df), A.cost(sym)


def load_universe(on_progress=None):
    out = []
    for k, sym in enumerate(UNIVERSE):
        for tf in TFS:
            try:
                _, df = m.candles(sym, tf)
                if len(df) >= 300:
                    out.append(DS(sym, tf, df))
            except Exception:  # noqa: BLE001
                pass
        if on_progress:
            on_progress(f"جلب البيانات… {sym}", 2 + 8 * (k + 1) / len(UNIVERSE))
    return out


def evaluate_on(spec, data):
    tr_r, va_r, te_r, per = [], [], [], []
    for d in data:
        ev = S.evaluate(spec, d.df, d.ind, d.cost)
        n = len(d.df)
        c1, c2 = int(n * 0.6), int(n * 0.8)
        for i, _s, r in ev["trades"]:
            (tr_r if i < c1 else va_r if i < c2 else te_r).append(r)
        allr = [t[2] for t in ev["trades"]]
        if len(allr) >= 3:
            per.append(float(np.mean(allr)) > 0)
    return {"train": S.trade_stats(tr_r), "val": S.trade_stats(va_r), "test": S.trade_stats(te_r),
            "consistency": round(sum(per) / len(per), 2) if per else 0.0, "datasets": len(per)}


def gate(ev):
    """بوابة القبول: تحقق قوي + اتساق بين الأصول + اختبار أخير غير سلبي."""
    t, v, x = ev["train"], ev["val"], ev["test"]
    return (v["n"] >= 12 and v["pf"] >= 1.2 and v["avg_r"] > 0.05 and t["avg_r"] > 0
            and x["n"] >= 5 and x["avg_r"] > 0 and ev["consistency"] >= 0.55)


# ---------------------------------------------------------------- توليد المرشحين
def random_spec(rng):
    t = rng.choice(list(S.TYPES))
    p = {k: (rng.randint(lo, hi) if kd is int else round(rng.uniform(lo, hi), 2)) for k, (lo, hi, kd) in S.TYPES[t].items()}
    ex = {"sl_atr": rng.choice([1.0, 1.5, 2.0, 2.5]), "rr": rng.choice([1.2, 1.5, 2.0, 2.5, 3.0]), "hold": rng.choice([12, 24, 36, 48])}
    return {"type": t, "params": p, "exits": ex}


def mutate(item, rng):
    p, ex = dict(item["params"]), dict(item["exits"])
    for k, (lo, hi, kd) in S.TYPES[item["type"]].items():
        if rng.random() < 0.5:
            p[k] = p[k] * rng.uniform(0.7, 1.3)
    if rng.random() < 0.4:
        ex["sl_atr"] *= rng.uniform(0.8, 1.25)
        ex["rr"] *= rng.uniform(0.8, 1.25)
    return {"type": item["type"], "params": p, "exits": ex}


def llm_propose(n=5, grounded=True):
    """يطلب من Gemini (مع بحث Google إن أمكن) استراتيجيات معروفة بصيغة المواصفة؛ تمر لاحقاً بنفس البوابة الصارمة."""
    import requests
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("أضف مفتاح Gemini من الإعدادات لاستعمال اقتراح الذكاء الاصطناعي.")
    model = (os.getenv("WORKER_MODEL") or "gemini/gemini-2.5-flash").split("/")[-1]
    schema = {t: {k: [lo, hi] for k, (lo, hi, _) in ps.items()} for t, ps in S.TYPES.items()}
    prompt = (f"أنت باحث استراتيجيات تداول كمّي. ابحث في الاستراتيجيات الفنية المعروفة للذهب والفوركس والعملات الرقمية (ويب وأدبيات) "
              f"واقترح {n} استراتيجيات مختلفة وغير متكررة، وعبّر عن كل واحدة فقط باستعمال هذه الأنواع والحدود (JSON):\n{json.dumps(schema)}\n"
              f"exits: sl_atr {list(S.EXIT_LIMITS['sl_atr'][:2])}، rr {list(S.EXIT_LIMITS['rr'][:2])}، hold {list(S.EXIT_LIMITS['hold'][:2])}.\n"
              'أعد فقط مصفوفة JSON بلا شرح: [{"name":"..","type":"..","params":{..},"exits":{..},"source":"مصدر/فكرة قصيرة"}]')
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    text = None
    for tools in ([{"google_search": {}}] if grounded else []) + [None]:
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        if tools:
            body["tools"] = tools
        r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=90)
        if r.ok:
            text = "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
            break
        last = r.text[:200]
    if text is None:
        raise RuntimeError(f"فشل طلب Gemini: {last}")
    mt = re.search(r"\[.*\]", text, re.S)
    out = []
    for it in json.loads(mt.group(0)) if mt else []:
        try:
            sp = S.clean_spec(it)
            sp["note"] = str(it.get("source", ""))[:140]
            out.append(sp)
        except Exception:  # noqa: BLE001
            continue
    return out


def discover(n=60, use_llm=False, on_progress=lambda msg, pct: None, seed=None):
    """دورة بحث واحدة: مرشحون (اقتراح LLM + طفرات من الناجحين + عشوائي) ← بوابة صارمة ← إضافة للمخزون، ثم إعادة فحص القديم."""
    if not _run.acquire(blocking=False):
        raise RuntimeError("دورة بحث أخرى تعمل الآن.")
    t0 = time.time()
    try:
        rng = random.Random(seed)
        data = load_universe(on_progress)
        if len(data) < 6:
            raise RuntimeError("تعذر جلب بيانات كافية للاختبار (تحقق من الإنترنت).")
        lib = load()
        known = {i["id"] for i in lib["items"]}
        rejected = set(lib["meta"].get("rejected", []))      # ذاكرة الأفكار المرفوضة: لا تُعاد
        cands, notes = [], {}
        if use_llm:
            on_progress("الذكاء الاصطناعي يبحث عن استراتيجيات…", 11)
            for sp in llm_propose(max(3, n // 6)):
                notes[spec_id(sp)] = sp.pop("note", "")
                cands.append((sp, "llm"))
        pool = [i for i in lib["items"] if i["status"] == "active"]
        while len(cands) < n:
            cands.append((mutate(rng.choice(pool), rng) if pool and rng.random() < 0.5 else random_spec(rng), "generated"))
        added, tested, seen = [], 0, set()
        for k, (sp, origin) in enumerate(cands):
            sp = S.clean_spec(sp)
            sid = spec_id(sp)
            if sid in known or sid in seen or sid in rejected:
                continue
            seen.add(sid)
            tested += 1
            ev = evaluate_on(sp, data)
            if gate(ev):
                it = _item(sp, origin, note=notes.get(sid, ""))
                it["stats"] = {**ev, "checked": datetime.now().isoformat(timespec="seconds")}
                lib["items"].append(it)
                added.append(it["name"])
            else:
                rejected.add(sid)
            on_progress(f"اختبار {k + 1}/{len(cands)} — أضيف {len(added)}", 12 + 80 * (k + 1) / len(cands))
        retired = []
        on_progress("إعادة فحص المخزون على أحدث البيانات…", 94)
        for it in lib["items"]:
            if it["id"] in seen and it["stats"]:
                continue
            ev = evaluate_on(it, data)
            it["stats"] = {**ev, "checked": datetime.now().isoformat(timespec="seconds")}
            if it["origin"] != "builtin" and it["status"] == "active":
                it["fails"] = 0 if gate(ev) else it.get("fails", 0) + 1
                if it["fails"] >= 2:
                    it["status"] = "retired"
                    retired.append(it["name"])
        lib["meta"]["rejected"] = list(rejected)[-3000:]
        lib["meta"].update(tested=lib["meta"].get("tested", 0) + tested, last_run=datetime.now().isoformat(timespec="seconds"),
                           runs=lib["meta"].get("runs", 0) + 1)
        save(lib)
        on_progress("اكتمل", 100)
        return {"tested": tested, "added": added, "retired": retired, "seconds": round(time.time() - t0)}
    finally:
        _run.release()


def set_status(sid, status):
    lib = load()
    for it in lib["items"]:
        if it["id"] == sid:
            it["status"] = status
            save(lib)
            return True
    return False


def delete(sid):
    lib = load()
    keep = [i for i in lib["items"] if not (i["id"] == sid and i["origin"] != "builtin")]
    ok = len(keep) != len(lib["items"])
    lib["items"] = keep
    save(lib)
    return ok


def add_spec(spec, origin="llm", note=""):
    """إضافة استراتيجية يقترحها وكيل CrewAI بعد اختبارها على المجموعة؛ تُرجع (نجحت؟، نتائج الاختبار)."""
    sp = S.clean_spec(spec)
    data = load_universe()
    ev = evaluate_on(sp, data)
    lib = load()
    if spec_id(sp) in {i["id"] for i in lib["items"]}:
        return False, ev
    ok = gate(ev)
    it = _item(sp, origin, status="active" if ok else "retired", note=note)
    it["stats"] = {**ev, "checked": datetime.now().isoformat(timespec="seconds")}
    if ok:
        lib["items"].append(it)
        save(lib)
    return ok, ev
