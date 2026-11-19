"""اختبار دخاني بدون إنترنت: بيانات اصطناعية تُحقن مكان الشبكة لاختبار المنطق (ليس لاختبار الربحية)."""
import os, sys, zlib, tempfile, json
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import assets as A, market_tools as m, lab, strategies as S, brain   # noqa: E402

_t = Path(tempfile.mkdtemp())
lab.LIB = _t / "strategies.json"      # لا نلمس مخزون المستخدم
brain.KN = _t / "knowledge.json"


def synth(symbol, tf, n=1200):
    rng = np.random.default_rng(zlib.crc32(f"{symbol}{tf}".encode()))
    base = {"BTC": 60000, "ETH": 3000, "SOL": 150, "XAU": 2350, "EUR": 1.08, "USD": 150.0, "GBP": 1.27, "NVD": 120.0, "SPY": 520.0, "AAP": 190.0}.get(symbol[:3], 100.0)
    drift = np.cumsum(rng.choice([-1, 1], size=n // 80 + 1) * 0.0004).repeat(80)[:n]
    r = drift + rng.normal(0, 0.004, n)
    c = base * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    sp = np.abs(rng.normal(0, 0.003, n)) * c
    df = pd.DataFrame({"ts": (int(__import__("time").time() * 1000) // m.TF_MS[tf] - n + np.arange(n)) * m.TF_MS[tf], "open": o, "high": np.maximum(o, c) + sp, "low": np.minimum(o, c) - sp, "close": c, "volume": 1.0})
    return df


m.candles = lambda symbol, tf="4h", limit=None: ("synthetic", synth(symbol, tf))
m.quote = lambda symbol: (None, None)
m.fear_greed = lambda: None
m.get_news = lambda coin="BTC": []
m.funding_rate = lambda symbol: None
import engine, notify, tracker      # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("✓" if cond else "✗"), name, extra)
    if not cond:
        fails.append(name)


# 1) أسماء الأصول
for raw, want in [("btc", "BTC/USDT"), ("BTCUSDT", "BTC/USDT"), ("xauusd", "XAU/USD"), ("EURUSD", "EUR/USD"), ("الذهب", "XAU/USD"),
                  ("usd-jpy", "USD/JPY"), ("DXY", "DXY"), ("اليورو", "EUR/USD")]:
    check(f"normalize {raw}", A.normalize(raw) == want, A.normalize(raw))
check("kind", [A.kind(x) for x in ("BTC/USDT", "XAU/USD", "EUR/USD", "DXY")] == ["crypto", "metal", "forex", "index"])

# 2) الاستراتيجيات: كل الأنواع تعمل وتُنتج صفقات بالاتجاهين
df = synth("ETH/USDT", "1h")
ind = S.Ind(df)
for t in S.TYPES:
    spec = S.clean_spec({"type": t, "params": {}, "exits": {}})
    ev = S.evaluate(spec, df, ind)
    sides = {x[1] for x in ev["trades"]}
    check(f"strategy {t}: {len(ev['trades'])} trades", len(ev["trades"]) > 0 and sides <= {1, -1}, str(sides))
check("clean_spec fast<slow", S.clean_spec({"type": "ema_cross", "params": {"fast": 50, "slow": 10}})["params"]["fast"] < S.clean_spec({"type": "ema_cross", "params": {"fast": 50, "slow": 10}})["params"]["slow"])
try:
    S.clean_spec({"type": "os.system"}); check("reject unknown type", False)
except ValueError:
    check("reject unknown type", True)

# 3) محاكي الصفقات: بيع رابح عند هبوط حاد
dd = pd.DataFrame({"open": [100.0] * 60, "high": [100.5] * 60, "low": [99.5] * 60, "close": [100.0] * 60})
dd.loc[42:, ["open", "high", "low", "close"]] = 90.0
sig = pd.Series(False, index=dd.index); sig[40] = True
tr = S.sim(dd, pd.Series(False, index=dd.index), sig, 1.0, 2.0, 10, 0.0, pd.Series(1.0, index=dd.index))
check("short TP hit = +2R", len(tr) == 1 and tr[0][1] == -1 and abs(tr[0][2] - 2.0) < 1e-9, str(tr))
tr = S.sim(dd, sig, pd.Series(False, index=dd.index), 1.0, 2.0, 10, 0.0, pd.Series(1.0, index=dd.index))
check("long SL hit = -1R", len(tr) == 1 and abs(tr[0][2] + 1.0) < 1e-9, str(tr))

# 4) التحليل على الأنماط والأصول
for style in ("swing", "scalp"):
    for sym in ("BTC/USDT", "XAU/USD", "EUR/USD", "USD/JPY", "NVDA"):
        steps = {}
        r = engine.analyze(sym, 1000, style, lambda k, s, t: steps.__setitem__(k, s))
        ok = set(steps) == set(engine.KEYS) and all(v in ("done", "skipped") for v in steps.values())
        check(f"analyze {style} {sym}: {r['action']} {r['grade']} buy{r['buy_pct']}/sell{r['sell_pct']}", ok and r["action"] in ("BUY", "SELL", "WAIT") and r["buy_pct"] + r["sell_pct"] == 100)
        json.dumps(r)    # يجب أن تكون النتيجة قابلة للتحويل إلى JSON
        if r["plan"]:
            p = r["plan"]
            sd = 1 if p["action"] == "BUY" else -1
            ordered = sd * (p["take_profit"] - p["entry"]) > 0 and sd * (p["entry"] - p["stop_loss"]) > 0 and sd * (p["take_profit2"] - p["take_profit"]) > 0
            check(f"  plan levels ordered ({p['action']})", ordered, f"E{p['entry']} SL{p['stop_loss']} TP{p['take_profit']} TP2{p['take_profit2']}")
            check("  immediate market-entry plan", p.get("entry_type") == "MARKET" and p.get("entry_limit") is None)
            msg = notify.format_signal(r)
            check("  telegram text", ("شراء" in msg or "بيع" in msg) and str(p["stop_loss"]) in msg and str(p["take_profit"]) in msg)
        check("  charts for each tf", set(r["charts"]) == set(engine.MODES[style]["tfs"]))

# 5) الوكيل الباحث (بحث + بوابة + إضافة للمخزون)
before = lab.summary()["total"]
res = lab.discover(n=40, seed=7)
after = lab.summary()
check(f"lab.discover tested={res['tested']} added={len(res['added'])} retired={len(res['retired'])}", res["tested"] > 0 and after["total"] == before + len(res["added"]))
check("gate is strict (not everything passes)", len(res["added"]) < res["tested"])
check("builtin protected from delete", lab.delete(lab.load()["items"][0]["id"]) is False)
if res["added"]:
    gid = [i for i in lab.load()["items"] if i["origin"] != "builtin"][0]["id"]
    check("toggle & delete generated", lab.set_status(gid, "retired") and lab.delete(gid))

# 6) المتتبع: بيع يُحسم بالهدف
plan = {"action": "SELL", "entry": 100, "stop_loss": 102, "take_profit": 97, "track": "1h", "expire_ms": 10**9}
e = {"symbol": "BTC/USDT", "ts": 0, "plan": plan, "status": "open", "r": None}
m.history_since = lambda s, ts, tf="1h": [[0, 100, 101, 99, 100, 0], [1, 100, 100, 96.5, 97, 0]]
tracker._resolve(e)
check("tracker SELL tp → +1.5R", e["status"] == "tp" and e["r"] == 1.5, str(e))
m.history_since = lambda s, ts, tf="1h": [[0, 100, 102.5, 99, 100, 0]]
e = {"symbol": "BTC/USDT", "ts": 0, "plan": plan, "status": "open", "r": None}
tracker._resolve(e)
check("tracker SELL sl → -1R", e["status"] == "sl" and e["r"] == -1.0)

# 7) Grok (بردّ مُحاكى): نبض X + رأي ثانٍ + تحمّل الفشل
from tools import grok   # noqa: E402
os.environ["XAI_API_KEY"] = "test"
calls = []
def fake(prompt, tools=None, **k):
    calls.append(bool(tools))
    return 'نص {"sentiment": 5, "summary":"مزاج حذر", "posts":[{"handle":"@a","gist":"x"}], "risks":["اجتماع الفيدرالي"], "confidence":"high", "verdict":"caution", "points":["الفارق ضيق"]} '
grok._ask = fake
grok._cache.clear()
r = engine.analyze("XAU/USD", 1000, "swing")
check("grok pulse clamped to +2", r["grok"]["pulse"]["sentiment"] == 2 and r["grok"]["review"]["verdict"] == "caution", str(calls))
check("grok review in report", "رأي Grok" in r["report"])
r2 = engine.analyze("XAU/USD", 1000, "swing", light=True)
check("light scan skips grok", r2["grok"]["pulse"] is None)
def boom(*a, **k): raise RuntimeError("429")
grok._ask = boom; grok._cache.clear()
r3 = engine.analyze("EUR/USD", 1000, "swing")
check("grok failure doesn't break analysis", r3["action"] in ("BUY", "SELL", "WAIT") and "error" in r3["grok"]["pulse"])
json.dumps(r3)
# 8) الأسهم + السوق المغلق
check("stock normalize", A.normalize("إنفيديا") == "NVDA" and A.kind("NVDA") == "stock")
rs = engine.analyze("NVDA", 1000, "swing")
check("stock analysis ok", rs["asset_kind"] == "stock" and rs["market_closed"] is False)
_c = m.candles
m.candles = lambda symbol, tf="4h", limit=None: ("old", _c(symbol, tf).__getitem__(1).assign(ts=lambda d: d.ts - 10**10)) if False else ("old", synth(symbol, tf).assign(ts=lambda d: d.ts - 10**9))
rc = engine.analyze("NVDA", 1000, "swing")
check("stale stock data → market_closed, never APPROVED", rc["market_closed"] and rc["decision"] != "APPROVED")
rcr = engine.analyze("BTC/USDT", 1000, "swing")
check("crypto never 'closed'", rcr["market_closed"] is False)
m.candles = _c

# 9) العقل: علاقة مزروعة تُكتشف، ولا علاقات كاذبة في الضوضاء
rng = np.random.default_rng(3)
N = 800
idx = pd.bdate_range(end="2026-11-13", periods=N)
base = {k: pd.Series(rng.normal(0, 0.01, N), index=idx) for k in "ABCDEF"}
base["B"] = 0.35 * base["A"].shift(1).fillna(0) + pd.Series(rng.normal(0, 0.01, N), index=idx)    # A يسبق B بيوم (علاقة حقيقية)
brain.daily_returns = lambda sym: base[sym]
brain.RELATION_UNIVERSE = list("ABCDEF")
rel = brain.discover_relations()
ids = {r["id"] for r in brain.load()["relations"]}
check(f"planted lead-lag found (tests={rel['tests']}, total={rel['total']})", "lead:A:B:1" in ids)
check("no false relations in noise", all(set(i.split(":")[1:3]) & {"A", "B"} for i in ids if i.startswith("lead")) and rel["total"] <= 2, str(ids))
base["A"] = base["A"].copy(); base["A"].iloc[-1] = 0.03      # A قفز اليوم → تتوقع علاقة صعود B غداً
sig = brain.relation_signal("B")
check("relation_signal supports BUY after A jump", sig["buy"] > 0 and sig["sell"] == 0, str(sig))

# 10) التعلم من الصفقات الحية: إيقاف استراتيجية خاسرة + معايرة
import tracker as T      # noqa: E402
T.HIST = _t / "h.json"
nm = lab.load()["items"][0]["name"]
fake = [{"plan": {"strategy": [nm], "win_rate_est": 60.0}, "status": "sl", "r": -1.0} for _ in range(14)] + \
       [{"plan": {"strategy": ["x"], "win_rate_est": 60.0}, "status": "tp", "r": 1.5} for _ in range(6)]
T.save(fake)
fb = brain.live_feedback()
check("live loser retired", nm in fb["retired"] and not [i for i in lab.active_items() if i["name"] == nm], str(fb["retired"]))
check("calibration computed (est 60 vs actual 30)", fb["calibration"] and fb["calibration"]["actual"] == 30.0 and fb["calibration"]["factor"] == 0.6, str(fb["calibration"]))

# 11) دورة كاملة
brain.RELATION_UNIVERSE = list("ABCDEF")
ent = brain.cycle(n=30)
check(f"full cycle ok: tested {ent['strategies_tested']} strategies, log saved", ent["strategies_tested"] > 0 and brain.load()["cycles"] == 1)
check("report text", "تقرير التعلم" in brain.report_text(ent))

# 12) محرك فهم السوق + محفظة ورقية (لا اتصال تداول حقيقي)
import intelligence as MI, paper_trading as PT
idf = MI.analyze_frame(synth("BTC/USDT", "5m"), "5m")
check("market intelligence returns regime/structure/liquidity/FVG", all(k in idf for k in ("regime", "structure", "liquidity", "fvg", "volume_proxy")) and idf["bias"] in ("bullish", "bearish", "neutral"))
combined = MI.combine({"5m": idf, "15m": MI.analyze_frame(synth("BTC/USDT", "15m"), "15m"), "1h": MI.analyze_frame(synth("BTC/USDT", "1h"), "1h")})
check("multi-timeframe synthesis", combined["bias"] in ("bullish", "bearish", "neutral") and 0 <= combined["bias_strength"] <= 100)
PT.STORE = _t / "paper_account.json"
PT.reset()
paper_pos = PT.open_position("BTC/USDT", "LONG", 100, 99, 102, 0.5)
check("paper position risk-sized without leverage", paper_pos["qty"] > 0 and paper_pos["notional"] <= 10000 and paper_pos["risk_cash"] <= 50.000001)
paper_closed = PT.close_position(paper_pos["id"], 102, "TEST")
check("paper trade realized PnL recorded", paper_closed["realized_pnl"] > 0 and PT.snapshot()["realized_pnl"] > 0)
try:
    PT.open_position("BTC/USDT", "LONG", 100, 101, 102, 0.5)
    check("paper invalid stop rejected", False)
except ValueError:
    check("paper invalid stop rejected", True)


# 13) خوارزميات فهم السوق + نموذج ML خارج العينة
from tools import market_models as MM
mm = MM.analyze_market(synth("BTC/USDT", "1h"))
check("market model regime/structure/flow/vwap", mm["available"] and mm["regime"] in ("trending", "ranging", "transition") and mm["structure"] in ("bullish", "bearish", "mixed") and -1 <= mm["flow_imbalance_proxy"] <= 1)
ml = mm["ml"]
check("walk-forward ML model", ml["available"] and 0 <= ml["prob_up_experimental"] <= 1 and ml["oos_samples"] > 0 and ml["oos_accuracy"] is not None, str(ml))

print("\nFAILED:" if fails else "\nALL OK", fails or "")
sys.exit(1 if fails else 0)
