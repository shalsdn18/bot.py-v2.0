import json, importlib.util, pandas as pd
from pathlib import Path
p = Path('tmp_positions.json')
p.write_text(json.dumps({'POL':{'name':'Policy','entry_price':100.0,'highest_price':105.0,'opened_at':'2026-01-01 09:00','market':'US'}}), encoding='utf-8')
spec = importlib.util.spec_from_file_location('bot_under_test', 'bot.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.TELEGRAM_TOKEN = 'x'
mod.CHAT_ID = 'y'
mod.TARGETS = [{'ticker':'POL','name':'Policy','market':'US'}]
mod.TICKER_MARKET_MAP = {'POL':'US'}
mod.POSITIONS_FILE = str(p)
mod.get_market_risk = lambda: {'level':'Normal','score':50,'summary':'risk'}
mod.get_latest_news = lambda _name: 'news'
mod.get_ai_comment = lambda **kw: 'ai'
mod.send_telegram = lambda msg: True
mod.yf.download = lambda *_a, **_kw: pd.DataFrame({'Close':[100.0]*68+[100.0,110.0]}, index=pd.date_range('2024-01-01', periods=70, freq='D'))
mod.analyze_market()
print(p.read_text(encoding='utf-8'))
