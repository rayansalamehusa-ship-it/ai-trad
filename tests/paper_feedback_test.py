"""اختبار تعلّم العقل من نتائج المحفظة الورقية دون اتصال أو تعديل بيانات المستخدم."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import brain, lab  # noqa: E402
import tracker  # noqa: E402
import paper_trading  # noqa: E402


def main():
    temp = Path(tempfile.mkdtemp(prefix="paper-feedback-"))
    brain.KN = temp / "knowledge.json"
    lab.LIB = temp / "strategies.json"
    tracker.HIST = temp / "history.json"
    paper_trading.STORE = temp / "paper_account.json"
    tracker.save([])
    paper_trading.reset()

    winner = paper_trading.open_position("BTC/USDT", "LONG", 100, 99, 102, 0.5)
    paper_trading.close_position(winner["id"], 101, "TEST_WIN")
    loser = paper_trading.open_position("ETH/USDT", "SHORT", 100, 101, 98, 0.5)
    paper_trading.close_position(loser["id"], 101, "TEST_LOSS")

    result = brain.live_feedback()
    stats = result["paper"]
    assert stats["resolved"] == 2, stats
    assert stats["wins"] == 1 and stats["losses"] == 1, stats
    assert stats["win_rate"] == 50.0 and stats["avg_r"] == 0.0, stats
    assert brain.load()["paper_feedback"] == stats
    assert result["retired"] == [], "Paper trades must not be attributed to an unknown strategy"
    print("PAPER FEEDBACK TEST: ALL OK", stats)


if __name__ == "__main__":
    main()
