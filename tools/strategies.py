"""مؤشرات + استراتيجيات معرّفة بمواصفات (شراء وبيع) + باكتيست على مستوى الصفقة (وقف/هدف بالـATR) + فلتر حالة السوق.

كل استراتيجية = مواصفة JSON {type, params, exits} فلا يُنفَّذ أي كود خارجي؛ هذا ما يسمح للوكيل بتوليد استراتيجيات جديدة بأمان.
"""
import numpy as np
import pandas as pd


# ---------------------------------------------------------------- مؤشرات
def ema(c, n):
    return c.ewm(span=int(n), adjust=False).mean()


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n=14):
    c = df.close
    tr = pd.concat([df.high - df.low, (df.high - c.shift()).abs(), (df.low - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df, n=14, with_di=False):
    up, dn = df.high.diff(), -df.low.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr(df, n)
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    out = dx.ewm(alpha=1 / n, adjust=False).mean()
    return (out, pdi, mdi) if with_di else out


def macd(c, f=12, s=26, sg=9):
    m = ema(c, f) - ema(c, s)
    return m, ema(m, sg)


def boll(c, n=20, k=2.0):
    ma, sd = c.rolling(int(n)).mean(), c.rolling(int(n)).std()
    return ma, ma + k * sd, ma - k * sd


def stoch(df, n=14, d=3):
    ll, hh = df.low.rolling(int(n)).min(), df.high.rolling(int(n)).max()
    k = 100 * (df.close - ll) / (hh - ll).replace(0, np.nan)
    return k, k.rolling(d).mean()


class Ind:
    """مخزن مؤقت للمؤشرات على إطار بيانات واحد كي لا تُحسب مرتين."""

    def __init__(self, df):
        self.df, self.c, self._k = df, df.close, {}

    def _g(self, key, fn):
        if key not in self._k:
            self._k[key] = fn()
        return self._k[key]

    def ema(self, n): return self._g(("ema", int(n)), lambda: ema(self.c, n))
    def rsi(self, n=14): return self._g(("rsi", int(n)), lambda: rsi(self.c, int(n)))
    def atr(self, n=14): return self._g(("atr", n), lambda: atr(self.df, n))
    def adx(self, n=14): return self._g(("adx", n), lambda: adx(self.df, n))
    def adx_di(self, n=14): return self._g(("adxdi", n), lambda: adx(self.df, n, True))
    def macd(self, f=12, s=26, g=9): return self._g(("macd", f, s, g), lambda: macd(self.c, f, s, g))
    def boll(self, n, k): return self._g(("boll", n, k), lambda: boll(self.c, n, k))
    def stoch(self, n): return self._g(("stoch", n), lambda: stoch(self.df, n))


def _up(a, b):
    bp = b.shift() if hasattr(b, "shift") else b
    return (a > b) & (a.shift() <= bp)


def _dn(a, b):
    bp = b.shift() if hasattr(b, "shift") else b
    return (a < b) & (a.shift() >= bp)


# ---------------------------------------------------------------- تعريف أنواع الاستراتيجيات (حدود المعاملات)
TYPES = {
    "ema_cross": {"fast": (5, 40, int), "slow": (20, 120, int), "adx_min": (0, 30, int)},
    "pullback": {"trend": (50, 200, int), "rsi_len": (2, 14, int), "rsi_lo": (25, 48, int)},
    "donchian": {"n": (10, 60, int), "adx_min": (0, 30, int)},
    "rsi_rev": {"len": (2, 21, int), "lo": (15, 35, int)},
    "boll_rev": {"n": (10, 40, int), "k": (1.5, 3.0, float)},
    "macd_cross": {"fast": (6, 16, int), "slow": (18, 40, int), "sig": (5, 12, int), "trend": (0, 200, int)},
    "stoch": {"n": (5, 21, int), "lo": (10, 30, int)},
}
EXIT_LIMITS = {"sl_atr": (0.8, 3.0, float), "rr": (1.0, 3.5, float), "hold": (8, 60, int)}
DEFAULT_EXITS = {"sl_atr": 1.5, "rr": 2.0, "hold": 24}


def _clamp(v, lo, hi, kind):
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = (lo + hi) / 2
    v = min(max(v, lo), hi)
    return int(round(v)) if kind is int else round(v, 2)


def clean_spec(spec):
    """يتحقق من المواصفة ويقصّ المعاملات داخل الحدود؛ يرمي ValueError إن كان النوع غير معروف."""
    t = spec.get("type")
    if t not in TYPES:
        raise ValueError(f"نوع استراتيجية غير معروف: {t}")
    params = {k: _clamp((spec.get("params") or {}).get(k, (lo + hi) / 2), lo, hi, kd) for k, (lo, hi, kd) in TYPES[t].items()}
    if t in ("ema_cross", "macd_cross") and params["fast"] >= params["slow"]:
        params["slow"] = min(TYPES[t]["slow"][1], params["fast"] + 8)
        params["fast"] = min(params["fast"], params["slow"] - 1)
    ex = {k: _clamp((spec.get("exits") or {}).get(k, DEFAULT_EXITS[k]), lo, hi, kd) for k, (lo, hi, kd) in EXIT_LIMITS.items()}
    return {"type": t, "params": params, "exits": ex}


def name_of(spec):
    t, p = spec["type"], spec["params"]
    return {
        "ema_cross": lambda: f"تقاطع EMA {p['fast']}/{p['slow']}" + (f" + ADX≥{p['adx_min']}" if p["adx_min"] else ""),
        "pullback": lambda: f"ارتداد مع الاتجاه (EMA{p['trend']} + RSI{p['rsi_len']}<{p['rsi_lo']})",
        "donchian": lambda: f"اختراق قناة {p['n']}" + (f" + ADX≥{p['adx_min']}" if p["adx_min"] else ""),
        "rsi_rev": lambda: f"ارتداد RSI({p['len']}) عند {p['lo']}/{100 - p['lo']}",
        "boll_rev": lambda: f"ارتداد بولنجر ({p['n']}، {p['k']})",
        "macd_cross": lambda: f"تقاطع MACD ({p['fast']},{p['slow']},{p['sig']})" + (f" + EMA{p['trend']}" if p["trend"] else ""),
        "stoch": lambda: f"ستوكاستيك ({p['n']}) عند {p['lo']}/{100 - p['lo']}",
    }[t]()


def signals(spec, ind):
    """(شراء، بيع): سلاسل منطقية — True عند إغلاق الشمعة التي تتحقق فيها شروط الدخول."""
    t, p, c = spec["type"], spec["params"], ind.c
    if t == "ema_cross":
        f, s = ind.ema(p["fast"]), ind.ema(p["slow"])
        ok = ind.adx() >= p["adx_min"]
        lg, sh = _up(f, s) & ok, _dn(f, s) & ok
    elif t == "pullback":
        tr, r = ind.ema(p["trend"]), ind.rsi(p["rsi_len"])
        lg, sh = (c > tr) & _up(r, p["rsi_lo"]), (c < tr) & _dn(r, 100 - p["rsi_lo"])
    elif t == "donchian":
        hh, ll = ind.df.high.rolling(p["n"]).max().shift(1), ind.df.low.rolling(p["n"]).min().shift(1)
        ok = ind.adx() >= p["adx_min"]
        lg, sh = (c > hh) & (c.shift() <= hh.shift()) & ok, (c < ll) & (c.shift() >= ll.shift()) & ok
    elif t == "rsi_rev":
        r = ind.rsi(p["len"])
        lg, sh = _up(r, p["lo"]), _dn(r, 100 - p["lo"])
    elif t == "boll_rev":
        _, up_, lo_ = ind.boll(p["n"], p["k"])
        lg, sh = (c.shift() < lo_.shift()) & (c > lo_), (c.shift() > up_.shift()) & (c < up_)
    elif t == "macd_cross":
        m, sg = ind.macd(p["fast"], p["slow"], p["sig"])
        lg, sh = _up(m, sg), _dn(m, sg)
        if p["trend"]:
            tr = ind.ema(p["trend"])
            lg, sh = lg & (c > tr), sh & (c < tr)
    else:  # stoch
        k, d = ind.stoch(p["n"])
        lg, sh = _up(k, d) & (k < p["lo"] + 10), _dn(k, d) & (k > 90 - p["lo"])
    return lg.fillna(False).astype(bool), sh.fillna(False).astype(bool)


# ---------------------------------------------------------------- الباكتيست على مستوى الصفقة
def sim(df, long, short, sl_atr=1.5, rr=2.0, hold=24, cost=0.0015, atr_s=None):
    """يحاكي كل إشارة: الدخول عند افتتاح الشمعة التالية، الوقف sl_atr×ATR، الهدف rr×الوقف، خروج زمني بعد hold شمعة.
    إن لمس السعر الوقف والهدف في نفس الشمعة يُحتسب الوقف أولاً (تحفظاً). التكلفة تُخصم بوحدات R.
    تُرجع قائمة (رقم شمعة الإشارة، الاتجاه +1/-1، النتيجة بـ R)."""
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    a = (atr_s if atr_s is not None else atr(df)).values
    L, S, n, out, i = long.values, short.values, len(df), [], 30
    while i < n - 1:
        side = 1 if (L[i] and not S[i]) else -1 if (S[i] and not L[i]) else 0
        if side == 0 or not np.isfinite(a[i]) or a[i] <= 0:
            i += 1
            continue
        entry, dist = o[i + 1], sl_atr * a[i]
        sl, tp, end, res, ex = entry - side * dist, entry + side * rr * dist, min(n - 1, i + hold), None, None
        for j in range(i + 1, end + 1):
            if side == 1:
                if l[j] <= sl:
                    res, ex = -1.0, j
                    break
                if h[j] >= tp:
                    res, ex = rr, j
                    break
            else:
                if h[j] >= sl:
                    res, ex = -1.0, j
                    break
                if l[j] <= tp:
                    res, ex = rr, j
                    break
        if res is None:
            res, ex = side * (c[end] - entry) / dist, end
        out.append((i, side, res - 2 * cost * entry / dist))
        i = max(ex, i + 1)
    return out


def trade_stats(rs):
    rs = np.asarray(list(rs), dtype=float)
    n = len(rs)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "pf": 0.0, "total_r": 0.0, "max_dd_r": 0.0}
    w, ls = rs[rs > 0].sum(), -rs[rs < 0].sum()
    pf = w / ls if ls > 0 else (99.0 if w > 0 else 0.0)
    cum = np.cumsum(rs)
    dd = (cum - np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]).min()
    return {"n": int(n), "win_rate": round(100 * float((rs > 0).mean()), 1), "avg_r": round(float(rs.mean()), 3),
            "pf": round(min(float(pf), 99.0), 2), "total_r": round(float(cum[-1]), 1), "max_dd_r": round(float(dd), 1)}


def evaluate(spec, df, ind=None, cost=0.0015):
    ind = ind or Ind(df)
    lg, sh = signals(spec, ind)
    ex = spec["exits"]
    tr = sim(df, lg, sh, ex["sl_atr"], ex["rr"], ex["hold"], cost, ind.atr())
    return {"trades": tr, "long": lg, "short": sh}


def asset_pass(st):
    """اجتياز الاختبار على هذا الأصل/الفريم: عينة كافية + توقع موجب + معامل ربح مقبول."""
    return st["n"] >= 8 and st["avg_r"] >= 0.05 and st["pf"] >= 1.15


def regime(df, ind=None):
    ind = ind or Ind(df)
    a = float(ind.adx().iloc[-1])
    ap = ind.atr() / df.close
    pct = float((ap.tail(250) < ap.iloc[-1]).mean() * 100)
    state = "high_vol" if pct >= 95 else "trending" if a >= 22 else "ranging"
    label = {"high_vol": "تذبذب شديد", "trending": "اتجاهي", "ranging": "عرضي (متذبذب)"}[state]
    return {"state": state, "label": label, "adx": round(a, 1), "vol_pct": round(pct)}
