"""جلب البيانات: عملات رقمية (ccxt) + ذهب/فوركس (yfinance) بعدة فريمات، أخبار، الخوف والطمع، التمويل، حاسبة الحجم."""
import time
import numpy as np
import pandas as pd
import requests
import deps
from tools import assets as A

EXCHANGES = ["binance", "bybit", "okx", "kraken"]   # تبديل تلقائي إذا حُجبت منصة
_cache, _fng, _dcache = {}, {"t": 0, "v": None}, {}
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
LIMITS = {"5m": 2000, "15m": 2000, "1h": 1500, "4h": 1000, "1d": 700}
TTL = {"5m": 60, "15m": 120, "1h": 300, "4h": 600, "1d": 1800}   # ثوانٍ: ذاكرة مؤقتة لتخفيف الطلبات


def _exchange(name):
    ccxt = deps.lazy("ccxt")
    if ccxt is None:
        raise RuntimeError(f'مكتبة ccxt غير مثبتة. نفّذ: "{deps.sys.executable}" -m pip install ccxt')
    if name not in _cache:
        _cache[name] = getattr(ccxt, name)({"enableRateLimit": True})
    return _cache[name]


def _call(method, *args, **kwargs):
    last = None
    for name in EXCHANGES:
        try:
            return name, getattr(_exchange(name), method)(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"تعذر الاتصال بأي منصة ({last})")


def _frame(rows):
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def _ccxt_candles(symbol, tf, limit):
    ms, since, rows, name = TF_MS[tf], int(time.time() * 1000) - limit * TF_MS[tf], [], None
    for _ in range(6):                                  # ترقيم صفحات للحصول على أكثر من 1000 شمعة
        name, raw = _call("fetch_ohlcv", symbol, timeframe=tf, since=since, limit=1000)
        if not raw:
            break
        rows += raw
        nxt = raw[-1][0] + ms
        if nxt <= since or len(raw) < 2 or nxt >= time.time() * 1000 - ms:
            break
        since = nxt
    return name, _frame(rows)


_YH = {"User-Agent": "Mozilla/5.0 (compatible; TradingFirm/6.3)"}
_YF_INTERVAL = {"5m": "5m", "15m": "15m", "1h": "60m", "4h": "60m", "1d": "1d"}


def _yahoo_http(ys, interval, days=None, start_ms=None):
    """احتياط بلا yfinance: واجهة Yahoo Chart المباشرة عبر requests. يعيد DataFrame بفهرس UTC وأعمدة open/high/low/close/volume."""
    now = int(time.time())
    p1 = int(start_ms / 1000) if start_ms else now - int(days or 60) * 86400
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ys}", headers=_YH, timeout=15,
                     params={"interval": interval, "period1": p1, "period2": now, "includePrePost": "false"})
    r.raise_for_status()
    res = (r.json().get("chart", {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        return pd.DataFrame()
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"open": q.get("open"), "high": q.get("high"), "low": q.get("low"), "close": q.get("close"),
                       "volume": q.get("volume") or [0] * len(res["timestamp"])},
                      index=pd.to_datetime(res["timestamp"], unit="s", utc=True))
    df["volume"] = df["volume"].fillna(0)
    return df.dropna(subset=["open", "high", "low", "close"])


def _yahoo_df(ys, tf, days=None, start_ms=None):
    """بيانات Yahoo لرمز واحد: يجرّب yfinance (ويثبّته تلقائياً إن نقص) ثم يسقط إلى HTTP المباشر."""
    interval = _YF_INTERVAL.get(tf, "60m")
    yf = deps.lazy("yfinance")
    if yf is not None:
        try:
            kw = {"start": pd.Timestamp(start_ms, unit="ms", tz="UTC") - pd.Timedelta(hours=1)} if start_ms else {"period": f"{int(days or 60)}d"}
            raw = yf.download(ys, interval=interval, progress=False, auto_adjust=False, threads=False, **kw)
            if raw is not None and not raw.empty:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                raw = raw.rename(columns=str.lower)
                if "volume" not in raw.columns:
                    raw["volume"] = 0.0
                raw = raw[["open", "high", "low", "close", "volume"]]
                raw.index = raw.index.tz_localize("UTC") if raw.index.tz is None else raw.index.tz_convert("UTC")
                return raw
        except Exception:  # noqa: BLE001
            pass
    return _yahoo_http(ys, interval, days, start_ms)


def _yf_candles(symbol, tf, limit):
    days = {"5m": 60, "15m": 60, "1h": 730, "4h": 730, "1d": 1825}[tf]
    last = None
    for ys in A.yf_symbols(symbol):
        try:
            raw = _yahoo_df(ys, tf, days=days)
            if raw is None or raw.empty:
                continue
            if tf == "4h":
                raw = raw.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
            ts_ms = ((raw.index - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)).astype("int64")
            out = raw.reset_index(drop=True)
            out.insert(0, "ts", np.asarray(ts_ms))
            return f"Yahoo Finance ({ys})", _frame(out.tail(limit).values.tolist())
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"تعذر جلب بيانات {symbol} من Yahoo Finance ({last or 'لا بيانات'}). تأكد من الإنترنت — "
                       f"وإن كان السبب نقص مكتبة فنفّذ: \"{deps.sys.executable}\" -m pip install yfinance")


def candles(symbol, tf="4h", limit=None):
    """شموع مغلقة فقط (تُحذف الشمعة الجارية كي لا يحدث تحيز)."""
    limit = limit or LIMITS.get(tf, 1000)
    key = (symbol, tf)
    hit = _dcache.get(key)
    if hit and time.time() - hit[0] < TTL.get(tf, 300):
        return hit[1], hit[2].copy()
    name, df = (_ccxt_candles if A.kind(symbol) == "crypto" else _yf_candles)(symbol, tf, limit)
    df = df.iloc[:-1].reset_index(drop=True)
    _dcache[key] = (time.time(), name, df)
    return name, df.copy()


def quote(symbol):
    """(آخر سعر، تغير 24س%) أو (None, None) — يعتمد المحرك على آخر إغلاق عند الفشل."""
    try:
        if A.kind(symbol) == "crypto":
            _, t = _call("fetch_ticker", symbol)
            return float(t["last"]), (None if t.get("percentage") is None else float(t["percentage"]))
        for ys in A.yf_symbols(symbol):
            h = _yahoo_df(ys, "5m", days=2)
            if h is not None and len(h):
                return float(h["close"].iloc[-1]), None
    except Exception:  # noqa: BLE001
        pass
    return None, None


def history_since(symbol, ts_ms, tf="1h"):
    """شموع بعد وقت معيّن لمتابعة نتيجة الصفقات: [[ts,o,h,l,c,v],…] (تشمل الشمعة الجارية)."""
    if A.kind(symbol) == "crypto":
        _, raw = _call("fetch_ohlcv", symbol, timeframe=tf, since=int(ts_ms), limit=1000)
        return raw
    for ys in A.yf_symbols(symbol):
        h = _yahoo_df(ys, tf if tf in ("5m", "15m", "1h") else "1h", start_ms=ts_ms)
        if h is None or h.empty:
            continue
        return [[int(t.timestamp() * 1000), float(r.open), float(r.high), float(r.low), float(r.close), 0] for t, r in zip(h.index, h.itertuples())]
    return []


def funding_rate(symbol):
    """معدل التمويل للعقود الدائمة (للعملات الرقمية فقط) — مؤشر ازدحام الصفقات."""
    if A.kind(symbol) != "crypto":
        return None
    try:
        base, quote_ = symbol.split("/")
        r = _exchange("binanceusdm").fetch_funding_rate(f"{base}/{quote_}:{quote_}")
        return float(r["fundingRate"])
    except Exception:  # noqa: BLE001
        return None


def fear_greed():
    if time.time() - _fng["t"] < 600:
        return _fng["v"]
    try:
        d = requests.get("https://api.alternative.me/fng/", timeout=8).json()["data"][0]
        _fng.update(t=time.time(), v={"value": int(d["value"]), "label": d["value_classification"]})
    except Exception:  # noqa: BLE001
        _fng.update(t=time.time(), v=None)
    return _fng["v"]


def get_news(coin="BTC"):
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/news/",
                         params={"lang": "EN", "categories": coin}, timeout=10).json()
        return [{"title": a.get("title", ""), "source": a.get("source", "")} for a in (r.get("Data") or [])[:6]]
    except Exception:  # noqa: BLE001
        return []


_POS = ("surge", "rally", "gain", "bull", "approve", "adoption", "record", "rise", "jump", "etf", "inflow")
_NEG = ("crash", "hack", "ban", "bear", "drop", "plunge", "lawsuit", "fraud", "fall", "sell-off", "liquidat", "outflow")


def news_sentiment(items):
    s = 0
    for a in items:
        t = a["title"].lower()
        s += any(w in t for w in _POS) - any(w in t for w in _NEG)
    return s


def position_size(capital, entry, stop_loss, risk_pct=2.0, cap=True):
    """حجم الصفقة بحيث لا تتجاوز الخسارة عند الوقف risk_pct% من رأس المال.
    cap=True: سبوت بلا رافعة (الحجم ≤ رأس المال). cap=False: فوركس/ذهب/بيع على المكشوف (قد يتطلب رافعة)."""
    dist = abs(entry - stop_loss) / entry if entry else 0
    if dist <= 0:
        return {"size_usd": 0.0, "risk_usd": 0.0, "stop_distance_pct": 0.0, "leverage": 0.0}
    size = capital * risk_pct / 100 / dist
    if cap:
        size = min(capital, size)
    return {"size_usd": round(size, 2), "risk_usd": round(size * dist, 2), "stop_distance_pct": round(dist * 100, 3),
            "leverage": round(size / capital, 2) if capital else 0.0}
