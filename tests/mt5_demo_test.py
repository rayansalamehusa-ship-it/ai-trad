"""Offline safety tests for the MT5 Demo bridge; no terminal or order is contacted."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mt5_demo

class Account:
    def __init__(self, mode):
        self.trade_mode = mode
        self.trade_allowed = True

class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    def __init__(self, mode): self.mode = mode
    def account_info(self): return Account(self.mode)

assert mt5_demo._account(FakeMT5(0)).trade_mode == 0
try:
    mt5_demo._account(FakeMT5(2))
except PermissionError:
    pass
else:
    raise AssertionError('Real account must be rejected')

old = mt5_demo.SETTINGS
try:
    mt5_demo.SETTINGS = Path(tempfile.mkdtemp()) / 'mt5_settings.json'
    assert mt5_demo.set_auto(False, 0.5)['auto_trade'] is False
    try:
        mt5_demo.set_auto(True, 1.1)
    except ValueError:
        pass
    else:
        raise AssertionError('Risk above 1% must be rejected')
finally:
    mt5_demo.SETTINGS = old
print('MT5 Demo safety tests: OK')
