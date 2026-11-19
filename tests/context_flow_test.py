"""اختبار تسلسل «السياق أولاً»: ترتيب الخطوات، تخطي البحث عند «لا تدخل»، ومنع الاتجاه المعاكس للسياق. بيانات اصطناعية بلا إنترنت."""
import sys, tempfile, json
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import market_tools as m, lab, brain   # noqa: E402

_t = Path(tempfile.mkdtemp())           # لا نلمس مخزون المستخدم ولا معرفته
lab.LIB = _t / "strategies.json"
brain.KN = _t / "knowledge.json"
m.quote = lambda symbol: (None, None)
m.fear_greed = lambda: None
m.get_news = lambda coin="BTC": []
m.funding_rate = lambda symbol: None
import engine, context_engine as CX        # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("✓" if cond else "✗"), name, extra)
    if not cond:
        fails.append(name)


def trend_df(sym, tf, slope, n=1200, noise=0.002):
    rng = np.random.default_rng(7)
    c = 100 * np.exp(np.cumsum(slope + rng.normal(0, noise, n)))
    o = np.r_[c[0], c[:-1]]
    sp = np.abs(rng.normal(0, 0.001, n)) * c
    ts = (int(__import__("time").time() * 1000) // m.TF_MS[tf] - n + np.arange(n)) * m.TF_MS[tf]
    return pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) + sp, "low": np.minimum(o, c) - sp, "close": c, "volume": 1.0})


# 1) ترتيب الخطوات: السياق قبل الاستراتيجيات والصياد
order = [k for k, _, _ in engine.STEPS]
check("السياق بعد الأخبار وقبل الباحث والصياد", order.index("news") < order.index("context") < order.index("strategist") < order.index("hunter"), str(order))

# 2) سوق صاعد بوضوح: السياق صاعد ← البيع ممنوع
m.candles = lambda symbol, tf="4h", limit=None: ("synthetic-up", trend_df(symbol, tf, +0.0012))
seq = []
r = engine.analyze("ETH/USDT", 1000, "swing", lambda k, s, t: seq.append((k, s)))
ctx = r["context"]
check("سوق صاعد → سياق صاعد", ctx["bias"] == "bullish", f"{ctx['bias']} {ctx['strength']}")
check("الإذن شراء فقط", ctx["permission"] == "long", ctx["permission"])
check("لا خطة بيع في سياق صاعد", not (r["plan"] and r["plan"]["action"] == "SELL"))
first_done = [k for k, s in seq if s == "done"]
check("السياق يُنهى قبل الصياد", first_done.index("context") < first_done.index("hunter"), str(first_done))
json.dumps(r)

# 3) سوق هابط: عكس ذلك
m.candles = lambda symbol, tf="4h", limit=None: ("synthetic-down", trend_df(symbol, tf, -0.0012))
r = engine.analyze("ETH/USDT", 1000, "swing")
check("سوق هابط → بيع فقط", r["context"]["permission"] == "short", r["context"]["permission"])
check("لا خطة شراء في سياق هابط", not (r["plan"] and r["plan"]["action"] == "BUY"))

# 4) block_reason مباشرة
c_long = {"permission": "long", "strength": 60, "headline": "x"}
check("block: بيع في سياق صاعد", CX.block_reason(c_long, "SELL", "A") is not None)
check("block: شراء في سياق صاعد مسموح", CX.block_reason(c_long, "BUY", "B") is None)
check("block: انتقائي يرفض B", CX.block_reason({"permission": "selective", "strength": 5, "headline": "x"}, "BUY", "B") is not None)
check("block: انتقائي يقبل A", CX.block_reason({"permission": "selective", "strength": 5, "headline": "x"}, "BUY", "A") is None)

# 5) سوق مغلق (بيانات قديمة لأصل غير رقمي): لا بحث عن صفقات إطلاقاً
def stale(symbol, tf="4h", limit=None):
    d = trend_df(symbol, tf, +0.0012)
    d["ts"] = d["ts"] - 10 * 86_400_000
    return "synthetic-stale", d
m.candles = stale
called = []
orig_eval = engine.S.evaluate
engine.S.evaluate = lambda *a, **k: (called.append(1), orig_eval(*a, **k))[1]
seq = []
r = engine.analyze("XAU/USD", 1000, "swing", lambda k, s, t: seq.append((k, s)))
engine.S.evaluate = orig_eval
st = dict(seq)
check("سوق مغلق → الإذن wait", r["context"]["permission"] == "wait" and r["stand_aside"])
check("الباحث والمحاكي والمخاطر تُخطيت", st.get("strategist") == "skipped" and st.get("simulator") == "skipped" and st.get("risk") == "skipped", str(st))
check("لم تُختبر أي استراتيجية (توفير وقت)", not called, f"{len(called)} استدعاء")
check("القرار REJECTED بلا خطة", r["decision"] == "REJECTED" and r["plan"] is None)

# 6) المسح السريع يحمل ملخص السياق
rows = []
m.candles = lambda symbol, tf="4h", limit=None: ("synthetic-up", trend_df(symbol, tf, +0.0012))
engine.scan(["BTC/USDT", "ETH/USDT"], 1000, "swing", rows.append)
check("صفوف المسح فيها ctx", all("ctx" in x and x["ctx"]["permission"] for x in rows), str([x.get("ctx", {}).get("permission") for x in rows]))

# 7) خفض المخاطرة عند ضعف السياق
if r2 := engine.analyze("SOL/USDT", 1000, "swing"):
    p = r2["plan"]
    if p:
        check("risk_pct = 2 × عامل السياق", abs(p["risk_pct"] - 2.0 * r2["context"]["risk_factor"]) < 1e-9, str(p["risk_pct"]))

print("\nALL OK" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
