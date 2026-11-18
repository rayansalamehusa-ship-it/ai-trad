import os
from crewai import Agent, LLM
from tools.crew_tools import (fetch_price_and_technicals, fetch_crypto_news, run_backtest_simulation,
                              calculate_position_size, list_strategy_library, create_new_strategy, grok_x_pulse)


def create_trading_team():
    def make_llm(var, default):
        model = os.getenv(var, default).strip() or default
        if "/" not in model:
            model = "gemini/" + model
        # Gemini 3 يوصي Google باستعمال temperature=1.0
        temp = 1.0 if "gemini-3" in model else 0.2
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        return LLM(model=model, api_key=key, temperature=temp)

    worker = make_llm("WORKER_MODEL", "gemini/gemini-3.5-flash")
    boss = make_llm("CEO_MODEL", "gemini/gemini-3.5-flash")

    def agent(role, goal, story, llm, tools=None):
        return Agent(role=role, goal=goal, backstory=story, tools=tools or [], llm=llm,
                     allow_delegation=False, verbose=True)

    return {
        "price": agent("مراقب الأسعار والسيولة (Price Watcher)",
                       "جلب الأسعار الحية ونسبة التغير ومؤشر RSI بدقة.",
                       "متخصص في قراءة بيانات المنصات اللحظية وحركة الشموع.", worker, [fetch_price_and_technicals]),
        "news": agent("محلل الأخبار ومشاعر السوق (News Scout)",
                      "جمع أحدث الأخبار وتحديد ما إذا كانت تدعم الصعود أم الهبوط.",
                      "محلل مالي متخصص في رصد الأخبار العاجلة وتأثيرها على المتداولين.", worker, [fetch_crypto_news, grok_x_pulse]),
        "strategist": agent("باحث الاستراتيجيات (Strategy Researcher)",
                            "إدارة مخزون الاستراتيجيات: تطبيقها على الأصل الحالي، واقتراح وإنشاء استراتيجيات جديدة تُختبر بصرامة قبل قبولها.",
                            "باحث كمّي يشكّ في كل فكرة ولا يقبلها إلا بعد اختبار على عدة أصول وفريمات، ويعترف بصدق عندما ترفضها البوابة.",
                            worker, [list_strategy_library, run_backtest_simulation, create_new_strategy]),
        "hunter": agent("صياد الصفقات (Opportunity Hunter)",
                        "اقتراح صفقة محددة (BUY أو SELL أو WAIT) مع الدخول والهدف ووقف الخسارة بأرقام دقيقة، بتوافق الفريمات.",
                        "متداول محترف يبحث عن فرص ذات عائد مرتفع ونسبة مخاطرة/عائد لا تقل عن 1.5، ولا يعاكس الفريم الأكبر بلا سبب.", worker),
        "simulator": agent("مهندس المحاكاة (Backtester)",
                           "اختبار الاستراتيجية على البيانات التاريخية للتأكد من جدواها.",
                           "عالم بيانات يختبر كل فكرة بالأرقام قبل المخاطرة بأي دولار.", worker, [run_backtest_simulation]),
        "risk": agent("مدير المخاطر الصارم (Risk Manager)",
                      "التأكد من أن الخسارة المحتملة لا تتجاوز 2% من رأس المال.",
                      "حارس رأس المال؛ يرفض أي صفقة متهورة. يستخدم دائماً حاسبة الحجم ولا يحسب بنفسه.", worker,
                      [calculate_position_size]),
        "ceo": agent("المدير التنفيذي (CEO Decision Maker)",
                     "قراءة تقارير الفريق وإصدار القرار النهائي: APPROVED أو REJECTED مع اتجاه الصفقة.",
                     "قائد استثماري مخضرم لا يقرر إلا بعد توافق الأخبار والتحليل الفني وإدارة المخاطر.", boss),
    }
