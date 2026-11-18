"""كتالوج الأصول (عملات رقمية + ذهب/فضة + فوركس + مؤشر الدولار) وتحويل الأسماء وتنسيق الأسعار."""
from math import floor, log10

FX = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD"}
METALS = {"XAU", "XAG"}
STOCKS = {"AAPL": "آبل", "MSFT": "مايكروسوفت", "NVDA": "إنفيديا", "GOOGL": "ألفابت (جوجل)", "AMZN": "أمازون", "META": "ميتا",
          "TSLA": "تسلا", "AVGO": "برودكوم", "JPM": "جي بي مورغان", "XOM": "إكسون موبيل",
          "SPY": "مؤشر S&P 500 (SPY)", "QQQ": "ناسداك 100 (QQQ)"}
CRYPTO = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]

CATALOG = [
    ("crypto", "عملات رقمية", [(f"{c}/USDT", c) for c in CRYPTO]),
    ("metal", "الذهب والفضة", [("XAU/USD", "الذهب"), ("XAG/USD", "الفضة")]),
    ("forex", "العملات الأجنبية", [
        ("EUR/USD", "اليورو / دولار"), ("GBP/USD", "الجنيه / دولار"), ("USD/JPY", "دولار / ين"),
        ("USD/CHF", "دولار / فرنك"), ("AUD/USD", "أسترالي / دولار"), ("USD/CAD", "دولار / كندي"),
        ("NZD/USD", "نيوزيلندي / دولار"), ("EUR/JPY", "يورو / ين"), ("GBP/JPY", "جنيه / ين"),
        ("EUR/GBP", "يورو / جنيه")]),
    ("index", "مؤشر الدولار", [("DXY", "مؤشر الدولار DXY")]),
    ("stock", "أقوى الأسهم تأثيراً (أمريكا)", [(k, v) for k, v in STOCKS.items() if k not in ("SPY", "QQQ")]),
    ("etf", "مؤشرات الأسهم", [("SPY", STOCKS["SPY"]), ("QQQ", STOCKS["QQQ"])]),
]

ALIASES = {
    "GOLD": "XAU/USD", "XAUUSD": "XAU/USD", "الذهب": "XAU/USD", "ذهب": "XAU/USD",
    "SILVER": "XAG/USD", "XAGUSD": "XAG/USD", "الفضة": "XAG/USD", "فضة": "XAG/USD",
    "DXY": "DXY", "USDX": "DXY", "DOLLAR": "DXY", "الدولار": "DXY", "دولار": "DXY",
    "اليورو": "EUR/USD", "يورو": "EUR/USD", "الين": "USD/JPY", "ين": "USD/JPY",
    "الجنيه": "GBP/USD", "الاسترليني": "GBP/USD",
    "ابل": "AAPL", "آبل": "AAPL", "مايكروسوفت": "MSFT", "انفيديا": "NVDA", "إنفيديا": "NVDA", "جوجل": "GOOGL", "قوقل": "GOOGL",
    "امازون": "AMZN", "أمازون": "AMZN", "ميتا": "META", "تسلا": "TSLA", "ناسداك": "QQQ",
}

# تكلفة التنفيذ التقديرية لكل جهة (عمولة + سبريد + انزلاق) كنسبة من السعر
COSTS = {"stock": 0.0005, "crypto": 0.0015, "forex": 0.0001, "metal": 0.0003, "index": 0.0002}


def normalize(s):
    s = (s or "").strip().upper().replace("-", "/").replace(" ", "")
    if s in ALIASES:
        return ALIASES[s]
    if s in STOCKS:
        return s
    if "/" in s:
        return s
    if len(s) == 6 and s[:3] in (FX | METALS) and s[3:] in FX:
        return f"{s[:3]}/{s[3:]}"
    if s.endswith("USDT") and len(s) > 4:
        return f"{s[:-4]}/USDT"
    return s + "/USDT"


def kind(sym):
    if sym in STOCKS:
        return "stock"
    if sym == "DXY":
        return "index"
    base, _, quote = sym.partition("/")
    if base in METALS:
        return "metal"
    if base in FX and quote in FX:
        return "forex"
    return "crypto"


def yf_symbols(sym):
    """رموز Yahoo Finance المحتملة (تُجرَّب بالترتيب)."""
    if sym == "DXY":
        return ["DX-Y.NYB", "DX=F"]
    if sym in STOCKS:
        return [sym]
    b, _, q = sym.partition("/")
    if b == "XAU":
        return ["XAUUSD=X", "GC=F"]
    if b == "XAG":
        return ["XAGUSD=X", "SI=F"]
    return [f"{b}{q}=X"] + ([f"{q}=X"] if b == "USD" else [])


def cost(sym):
    return COSTS[kind(sym)]


def rp(p):
    """تقريب السعر إلى خانات مناسبة لحجمه (فوركس 5 خانات، ذهب 2، عملات صغيرة أكثر)."""
    p = float(p)
    if p == 0:
        return 0.0
    return round(p, max(2, 5 - int(floor(log10(abs(p))))))


def groups():
    return [{"key": k, "label": l, "items": [{"symbol": s, "name": n} for s, n in it]} for k, l, it in CATALOG]
