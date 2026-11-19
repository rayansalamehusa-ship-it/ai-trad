"""أدوات CrewAI (تغلّف دوال المحرك والمختبر كي يستدعيها الوكلاء)."""
import json
from crewai.tools import tool
from tools import assets as A, grok, lab, market_tools as m

CURRENT = {"style": "swing"}      # يضبطه engine.run_ai قبل التشغيل


@tool("Fetch Live Price & Multi-Timeframe Technicals")
def fetch_price_and_technicals(symbol: str) -> str:
    """يجلب السعر واتجاه كل فريم وRSI وADX وحالة السوق لزوج مثل BTC/USDT أو XAU/USD أو EUR/USD."""
    from engine import describe_market
    try:
        return describe_market(symbol, CURRENT["style"])
    except Exception as e:  # noqa: BLE001
        return f"خطأ أثناء جلب بيانات {symbol}: {e}"


@tool("Fetch Latest Crypto News")
def fetch_crypto_news(coin: str) -> str:
    """يجلب أحدث عناوين الأخبار لعملة رقمية مثل BTC (للذهب والفوركس لا توجد أخبار آلية)."""
    items = m.get_news(coin.split("/")[0])
    if not items:
        return "تعذر جلب الأخبار أو لا توجد أخبار؛ اعتمد على التحليل الفني."
    return "\n".join(f"{i}. {a['title']} ({a['source']})" for i, a in enumerate(items, 1))


@tool("Run Strategy Backtest Simulation")
def run_backtest_simulation(symbol: str) -> str:
    """يختبر كل استراتيجيات المخزون (شراء وبيع) على فريم الدخول مع الوقف/الهدف بالـATR والتكلفة، ويذكر الإشارات الحالية."""
    from engine import describe_strategies
    try:
        return describe_strategies(symbol, CURRENT["style"])
    except Exception as e:  # noqa: BLE001
        return f"خطأ في المحاكاة: {e}"


@tool("Position Size Calculator")
def calculate_position_size(capital: float, entry: float, stop_loss: float) -> str:
    """يحسب حجم الصفقة بالدولار بحيث لا تتجاوز الخسارة 2% من رأس المال."""
    r = m.position_size(float(capital), float(entry), float(stop_loss), cap=False)
    return f"حجم الصفقة: ${r['size_usd']} | الخسارة القصوى: ${r['risk_usd']} | بعد الوقف: {r['stop_distance_pct']}% | الرافعة المطلوبة ≈ {r['leverage']}×"


@tool("List Strategy Library")
def list_strategy_library(dummy: str = "") -> str:
    """يعرض مخزون الاستراتيجيات الحالي (الاسم، المصدر، إحصاءات الاختبار الأخير)."""
    lib = lab.load()
    out = [f"المخزون: {lab.summary()}"]
    for it in lib["items"]:
        st = (it.get("stats") or {}).get("val") or {}
        out.append(f"- [{it['status']}/{it['origin']}] {it['name']} | تحقق: {st.get('n', '?')} صفقة، PF {st.get('pf', '?')}")
    return "\n".join(out)


@tool("Create And Validate New Strategy")
def create_new_strategy(spec_json: str) -> str:
    """ينشئ استراتيجية جديدة ويختبرها على عدة أصول وفريمات. المدخل JSON مثل:
    {"type":"ema_cross","params":{"fast":12,"slow":48,"adx_min":18},"exits":{"sl_atr":1.5,"rr":2.0,"hold":30}}
    الأنواع: ema_cross, pullback, donchian, rsi_rev, boll_rev, macd_cross, stoch. تُضاف للمخزون فقط إن اجتازت البوابة الصارمة."""
    try:
        ok, ev = lab.add_spec(json.loads(spec_json), origin="llm", note="أنشأها وكيل CrewAI")
    except Exception as e:  # noqa: BLE001
        return f"مواصفة غير صالحة أو خطأ: {e}"
    return ("✅ أُضيفت للمخزون. " if ok else "❌ رُفضت (لم تجتز البوابة أو مكررة). ") + json.dumps(ev, ensure_ascii=False)


@tool("Grok X Sentiment Pulse")
def grok_x_pulse(symbol: str) -> str:
    """يسأل Grok (xAI) عن مزاج منصة X لآخر 48 ساعة حول الأصل (عملة رقمية/ذهب/فوركس) ويعيد ملخصاً وحسابات ومخاطر قادمة."""
    if not grok.available():
        return "مفتاح xAI غير مضبوط؛ اعتمد على باقي المصادر."
    try:
        sym = A.normalize(symbol)
        return grok.pulse_text(grok.x_pulse(sym, A.kind(sym)))
    except Exception as e:  # noqa: BLE001
        return f"تعذر جلب نبض X: {e}"


@tool("Market Context Analysis")
def market_context(symbol: str) -> str:
    """يحدد سياق السوق لأصل (BTC/USDT, XAU/USD, EUR/USD…): الحالة، الميل، وما المسموح (شراء فقط/بيع فقط/انتقائي/لا تدخل)."""
    from engine import describe_context
    try:
        return describe_context(symbol, CURRENT["style"])
    except Exception as e:  # noqa: BLE001
        return f"خطأ في فهم السياق: {e}"
