import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import market_tools
import orderflow
class Fake:
    has={"fetchTrades":True,"fetchOrderBook":True,"fetchFundingRate":False,"fetchOpenInterest":False,"fetchLiquidations":False}
    def fetch_trades(self,symbol,limit):
        return [{"side":"buy","amount":1,"price":100},{"side":"sell","amount":.2,"price":100.01}]*8
    def fetch_order_book(self,symbol,limit):
        return {"bids":[[99.9,10]],"asks":[[100.1,5]]}
orderflow._exchange_for=lambda s:(Fake(),"fake")
r=orderflow.analyze("BTC/USDT")
assert r["available"] and r["trade_count"]==16
assert r["cvd_notional"]>0 and r["book_imbalance"]>0
assert r["liquidations"] is None
print("orderflow smoke test OK")
