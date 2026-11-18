"""تشغيل سطر الأوامر (اختياري):  python main.py ETH/USDT 2500 [ai|local]"""
import sys
from dotenv import load_dotenv
from engine import run_analysis, STEPS

load_dotenv()
NAMES = {k: n for k, n, _ in STEPS}


def show(key, state, text):
    if state == "done":
        print(f"\n--- {NAMES[key]} ---\n{text}")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTC/USDT"
    cap = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0
    mode = sys.argv[3] if len(sys.argv) > 3 else "local"
    res = run_analysis(sym, cap, mode, show)
    print("\n==== القرار النهائي:", res["decision"], "====")
