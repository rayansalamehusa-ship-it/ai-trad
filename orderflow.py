"""Order-flow intelligence عبر CCXT: صفقات منفذة ودفتر أوامر ومشتقات.
لا يخلط هذا الملف بيانات OHLCV التقديرية مع تدفق الصفقات الحقيقي.
"""
import time
from tools import market_tools as M
from tools import assets as A

_cache = {}
TTL = 12

def _exchange_for(symbol):
    base, quote = symbol.split("/")
    candidates = ["binance", "bybit", "okx", "kraken"]
    last = None
    for name in candidates:
        try:
            ex = M._exchange(name)
            if ex.has.get("fetchTrades") and ex.has.get("fetchOrderBook"):
                return ex, name
        except Exception as exc:
            last = exc
    raise RuntimeError(f"لا توجد منصة متاحة لتدفق الأوامر: {last}")

def analyze(symbol, trade_limit=500, depth=20):
    symbol = A.normalize(symbol)
    if A.kind(symbol) != "crypto":
        return {"available": False, "reason": "Order Flow المباشر متاح هنا للعملات الرقمية فقط"}
    key = (symbol, trade_limit, depth)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return dict(hit[1], cached=True)
    ex, venue = _exchange_for(symbol)
    trades = ex.fetch_trades(symbol, limit=trade_limit)
    book = ex.fetch_order_book(symbol, limit=depth)
    buys = sells = 0.0
    buy_count = sell_count = 0
    for t in trades:
        amount = float(t.get("amount") or 0)
        cost = float(t.get("cost") or amount * float(t.get("price") or 0))
        side = t.get("side")
        if side == "buy":
            buys += cost; buy_count += 1
        elif side == "sell":
            sells += cost; sell_count += 1
    total = buys + sells
    cvd = buys - sells
    cvd_ratio = cvd / total if total else 0.0
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    bid_depth = sum(float(x[0])*float(x[1]) for x in bids[:depth])
    ask_depth = sum(float(x[0])*float(x[1]) for x in asks[:depth])
    depth_total = bid_depth + ask_depth
    imbalance = (bid_depth-ask_depth)/depth_total if depth_total else 0.0
    best_bid = float(bids[0][0]) if bids else None
    best_ask = float(asks[0][0]) if asks else None
    mid = (best_bid+best_ask)/2 if best_bid and best_ask else None
    spread = ((best_ask-best_bid)/mid*10000) if mid else None
    # امتصاص محتمل: حجم عدواني كبير مع تغير سعري محدود ضمن عينة الصفقات.
    prices = [float(t["price"]) for t in trades if t.get("price") is not None]
    price_change = ((prices[-1]/prices[0])-1)*100 if len(prices)>1 and prices[0] else 0.0
    absorption = None
    if total > 0 and len(prices) >= 10:
        dominant = "buy" if buys > sells else "sell"
        dominant_share = max(buys,sells)/total
        absorption = bool(dominant_share >= .65 and abs(price_change) <= .04)
    # مشتقات: تختلف التغطية حسب المنصة والسوق، فلا نفترض توفرها.
    funding = oi = liquidations = None
    errors = []
    try:
        if ex.has.get("fetchFundingRate"):
            fr = ex.fetch_funding_rate(symbol)
            funding = float(fr["fundingRate"]) if fr.get("fundingRate") is not None else None
    except Exception as exc: errors.append("funding: "+str(exc)[:100])
    try:
        if ex.has.get("fetchOpenInterest"):
            item = ex.fetch_open_interest(symbol)
            oi = item.get("openInterestAmount") or item.get("openInterestValue")
            oi = float(oi) if oi is not None else None
    except Exception as exc: errors.append("open_interest: "+str(exc)[:100])
    try:
        if ex.has.get("fetchLiquidations"):
            rows = ex.fetch_liquidations(symbol, limit=100)
            liquidations = {"count":len(rows), "contracts":sum(float(x.get("contracts") or 0) for x in rows),
                            "notional":sum(float(x.get("price") or 0)*float(x.get("contracts") or 0) for x in rows)}
    except Exception as exc: errors.append("liquidations: "+str(exc)[:100])
    result = {
        "available": True, "venue": venue, "symbol": symbol, "trade_count": len(trades),
        "buy_notional": round(buys,2), "sell_notional": round(sells,2),
        "cvd_notional": round(cvd,2), "cvd_ratio": round(cvd_ratio,4),
        "buy_trade_count":buy_count, "sell_trade_count":sell_count,
        "bid_depth_notional":round(bid_depth,2), "ask_depth_notional":round(ask_depth,2),
        "book_imbalance":round(imbalance,4), "spread_bps":round(spread,2) if spread is not None else None,
        "best_bid":best_bid, "best_ask":best_ask, "absorption_possible":absorption,
        "sample_price_change_pct":round(price_change,4), "funding_rate":funding,
        "open_interest":oi, "liquidations":liquidations, "errors":errors,
        "warnings":["CVD محسوب من عينة الصفقات المنفذة المسترجعة، وليس تاريخاً كاملاً أو تدفقاً مؤسسياً موحداً.",
                    "دفتر الأوامر لقطة لحظية وقد تُلغى الأوامر؛ لا يثبت نية المشاركين.",
                    "الامتصاص إشارة احتمالية مبسطة وليس كشفاً مؤكداً.",
                    "التصفية والتمويل والفائدة المفتوحة تعتمد على دعم المنصة ونوع السوق."]
    }
    _cache[key] = (time.time(), result)
    return result
