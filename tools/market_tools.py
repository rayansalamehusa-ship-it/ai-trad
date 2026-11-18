"""جلب البيانات: عملات رقمية (ccxt) + ذهب/فوركس (yfinance) بعدة فريمات، أخبار، الخوف والطمع، التمويل، حاسبة الحجم."""
import time
import numpy as np
import pandas as pd
import requests
from tools import assets as A

EXCHANGES = ["binance", "bybit", "okx", "kraken"]   # تبديل تلقائي إذا حُجبت منصة
_cache, _fng, _dcache = {}, {"t": 0, "v": None}, {}
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
LIMITS = {"5m": 2000, "15m": 2000, "1h": 1500, "4h": 1000, "1d": 700}
TTL = {"5m": 60, "15m": 120, "1h": 300, "4h": 600, "1d": 1800}   # ثوانٍ: ذاكرة مؤقتة لتخفيف الطلبات


def _exchange(name):
    import ccxt
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


def _yf_candles(symbol, tf, limit):
    import yfinance as yf
    interval, period = {"5m": ("5m", "60d"), "15m": ("15m", "60d"), "1h": ("60m", "730d"),
                        "4h": ("60m", "730d"), "1d": ("1d", "5y")}[tf]
    last = None
    for ys in A.yf_symbols(symbol):
        try:
            raw = yf.download(ys, period=period, interval=interval, progress=False, auto_adjust=False, threads=False)
            if raw is None or raw.empty:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns=str.lower)
            if "volume" not in raw.columns:
                raw["volume"] = 0.0
            raw = raw[["open", "high", "low", "close", "volume"]]
            if tf == "4h":
                raw = raw.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
            idx = raw.index.tz_localize("UTC") if raw.index.tz is None else raw.index.tz_convert("UTC")
            ts_ms = ((idx - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)).astype("int64")
            out = raw.reset_index(drop=True)
            out.insert(0, "ts", np.asarray(ts_ms))
            return f"Yahoo Finance ({ys})", _frame(out.tail(limit).values.tolist())
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"تعذر جلب بيانات {symbol} من Yahoo Finance ({last}). تأكد من تثبيت yfinance ومن الإنترنت.")


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
        import yfinance as yf
        for ys in A.yf_symbols(symbol):
            h = yf.Ticker(ys).history(period="1d", interval="1m")
            if len(h):
                return float(h["Close"].iloc[-1]), None
    except Exception:  # noqa: BLE001
        pass
    return None, None


def history_since(symbol, ts_ms, tf="1h"):
    """شموع بعد وقت معيّن لمتابعة نتيجة الصفقات: [[ts,o,h,l,c,v],…] (تشمل الشمعة الجارية)."""
    if A.kind(symbol) == "crypto":
        _, raw = _call("fetch_ohlcv", symbol, timeframe=tf, since=int(ts_ms), limit=1000)
        return raw
    import yfinance as yf
    from datetime import datetime, timezone
    start = datetime.fromtimestamp(ts_ms / 1000 - 3600, tz=timezone.utc)
    for ys in A.yf_symbols(symbol):
        h = yf.download(ys, start=start, interval={"5m": "5m", "15m": "15m", "1h": "60m"}.get(tf, "60m"), progress=False, auto_adjust=False, threads=False)
        if h is None or h.empty:
            continue
        if isinstance(h.columns, pd.MultiIndex):
            h.columns = h.columns.get_level_values(0)
        idx = h.index.tz_convert("UTC") if h.index.tz is not None else h.index.tz_localize("UTC")
        return [[int(t.timestamp() * 1000), r.Open, r.High, r.Low, r.Close, 0] for t, r in zip(idx, h.itertuples())]
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
