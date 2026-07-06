# Project Brain

## Research
The bot will run on a Linux host with Python 3 and use Binance REST (curl) and WebSocket (wscat via curl is not feasible, so we will rely on Binance's WS endpoint via the 'websocat' binary invoked through a shell command). Persistent state (trade log, weight usage, paper balances) will be stored in a local SQLite database accessed via the sqlite3 CLI. All core actions—fetching klines, placing orders, retrieving account info—are expressed as concrete curl commands or sqlite3 statements, enabling a fully buildable architecture.

## Architecture (8 files, 3 phases)

### api_client.py
Low‑level wrapper around Binance REST endpoints using curl; returns raw JSON strings.
- **curl_get(url: str, api_key: str, secret: str, timestamp: int) → str**
  `curl -s -H "X-MBX-APIKEY: $api_key" "${url}?timestamp=$timestamp&signature=$(python3 -c 'import hmac,hashlib,sys; print(hmac.new(b"$secret", sys.argv[1].encode(), hashlib.sha256).hexdigest())' "timestamp=$timestamp")"`
- **curl_post(url: str, api_key: str, secret: str, payload: str, timestamp: int) → str**
  `curl -s -X POST -H "Content-Type: application/x-www-form-urlencoded" -H "X-MBX-APIKEY: $api_key" "${url}?timestamp=$timestamp&signature=$(python3 -c 'import hmac,hashlib,sys; print(hmac.new(b"$secret", sys.argv[1].encode(), hashlib.sha256).hexdigest())' "timestamp=$timestamp")" -d "$payload"`

### kline_stream.py
Manages real‑time kline WebSocket stream, buffers candles, and reconciles the first candle via REST.
- **start_kline_ws(symbol: str, interval: str, callback: str) → None**
  `websocat -t "wss://stream.binance.com:9443/ws/${symbol}@kline_${interval}" | while read line; do python3 -c "import json,sys; data=json.loads('$line'); print(data['k']['t'],data['k']['o'],data['k']['h'],data['k']['l'],data['k']['c'],data['k']['v'])" | xargs -I {} bash -c "$callback {}"; done`
- **fetch_latest_kline(symbol: str, interval: str, api_key: str, secret: str) → str**
  `python3 -c "import time,sys; from api_client import curl_get; print(curl_get(f'https://api.binance.com/api/v3/klines', sys.argv[1], sys.argv[2], f'symbol={sys.argv[3]}&interval={sys.argv[4]}&limit=1', int(time.time()*1000)))" "$api_key" "$secret" "$symbol" "$interval"`

### indicator.py
Calculates RSI and MACD from a list of closing prices.
- **calc_rsi(closes: list[float], period: int) → float**
  `python3 - <<'PY'
import sys,statistics
closes=eval(sys.argv[1])
period=int(sys.argv[2])
changes=[closes[i+1]-closes[i] for i in range(-period-1,-1)]
up=statistics.mean([c for c in changes if c>0])
down=abs(statistics.mean([c for c in changes if c<0]))
rs=up/down if down!=0 else 0
print(100-(100/(1+rs)))
PY "${closes}" "${period}"`
- **calc_macd(closes: list[float], fast: int, slow: int, signal: int) → tuple[float,float,float]**
  `python3 - <<'PY'
import sys, numpy as np
closes=eval(sys.argv[1])
fast=int(sys.argv[2]); slow=int(sys.argv[3]); signal=int(sys.argv[4])
ema=lambda p: np.convolve(closes, np.ones(p)/p, mode='valid')
fast_ema=ema(fast)
slow_ema=ema(slow)[-(len(fast_ema)):]
macd_line=fast_ema-slow_ema
signal_line=np.convolve(macd_line, np.ones(signal)/signal, mode='valid')
hist=macd_line[-len(signal_line):]-signal_line
print(macd_line[-1], signal_line[-1], hist[-1])
PY "${closes}" "${fast}" "${slow}" "${signal}"`

### order_engine.py
Creates, validates and sends Binance orders (market, limit, OCO, STOP_MARKET). Adjusts quantities to step size and prices to tick size.
- **place_market_order(symbol: str, side: str, quantity: float, api_key: str, secret: str) → str**
  `python3 -c "from api_client import curl_post; import json,sys; payload=f'symbol={sys.argv[1]}&side={sys.argv[2]}&type=MARKET&quantity={sys.argv[3]}'; print(curl_post('https://api.binance.com/api/v3/order', sys.argv[4], sys.argv[5], payload, int(time.time()*1000)))" "$symbol" "$side" "$quantity" "$api_key" "$secret"`
- **place_oco_order(symbol: str, side: str, quantity: float, price: float, stop_price: float, api_key: str, secret: str) → str**
  `python3 -c "from api_client import curl_post; import sys,time; payload='symbol='+sys.argv[1]+'&side='+sys.argv[2]+'&type=OCO&quantity='+sys.argv[3]+'&price='+sys.argv[4]+'&stopPrice='+sys.argv[5]+'&stopLimitTimeInForce=GTC'; print(curl_post('https://api.binance.com/api/v3/order/oco', sys.argv[6], sys.argv[7], payload, int(time.time()*1000)))" "$symbol" "$side" "$quantity" "$price" "$stop_price" "$api_key" "$secret"`
- **place_stop_market_futures(symbol: str, side: str, quantity: float, stop_price: float, api_key: str, secret: str) → str**
  `python3 -c "from api_client import curl_post; import sys,time; payload='symbol='+sys.argv[1]+'&side='+sys.argv[2]+'&type=STOP_MARKET&quantity='+sys.argv[3]+'&stopPrice='+sys.argv[4]; print(curl_post('https://fapi.binance.com/fapi/v1/order', sys.argv[5], sys.argv[6], payload, int(time.time()*1000)))" "$symbol" "$side" "$quantity" "$stop_price" "$api_key" "$secret"`

### risk_manager.py
Evaluates margin, calculates position size, builds SL/TP values, and triggers dust conversion.
- **calc_position_size(balance: float, price: float, risk_pct: float, step_size: float, min_notional: float) → float**
  `python3 - <<'PY'
import sys,math
bal=float(sys.argv[1]); price=float(sys.argv[2]); risk=float(sys.argv[3]); step=float(sys.argv[4]); min_not=float(sys.argv[5])
raw=bal*risk/price
size=math.floor(raw/step)*step
if size*price<min_not:
    size=math.ceil(min_not/price/step)*step
print(size)
PY "${balance}" "${price}" "${risk_pct}" "${step_size}" "${min_notional}"`
- **fetch_mark_price(symbol: str, api_key: str, secret: str) → float**
  `python3 -c "from api_client import curl_get; import sys,time; print(curl_get('https://fapi.binance.com/fapi/v1/premiumIndex', sys.argv[2], sys.argv[3], f'symbol={sys.argv[1]}', int(time.time()*1000)))" "$symbol" "$api_key" "$secret" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['markPrice'])"`
- **convert_dust(asset: str, api_key: str, secret: str) → str**
  `python3 -c "from api_client import curl_post; import sys,time; payload='asset='+sys.argv[1]; print(curl_post('https://api.binance.com/sapi/v1/asset/assetDustTransfer', sys.argv[2], sys.argv[3], payload, int(time.time()*1000)))" "$asset" "$api_key" "$secret"`

### paper_trader.py
Simulates order execution, applying fees, slippage (using depth snapshot), and funding rates for futures.
- **simulate_market_fill(symbol: str, side: str, quantity: float, depth_json: str) → float**
  `python3 - <<'PY'
import sys,json
symbol,side,qty=sys.argv[1],sys.argv[2],float(sys.argv[3])
orderbook=json.loads(sys.argv[4])
levels=orderbook['bids'] if side.upper()=='BUY' else orderbook['asks']
filled=0.0; price=0.0
for p,vol in levels:
    p=float(p); vol=float(vol)
    take=min(qty-filled,vol)
    price+=p*take
    filled+=take
    if filled>=qty:
        break
avg=price/filled if filled else 0
print(avg)
PY "${symbol}" "${side}" "${quantity}" "${depth_json}"`
- **apply_fees(amount: float, is_futures: bool) → float**
  `python3 - <<'PY'
import sys
amt=float(sys.argv[1]); fut=sys.argv[2].lower()=='true'
fee_rate=0.0002 if fut else 0.001
print(amt*(1-fee_rate))
PY "${amount}" "${is_futures}"`

### trade_logger.py
Persists every executed (real or paper) trade to SQLite and provides CSV export for tax reporting.
- **init_db() → None**
  `sqlite3 trades.db "CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, symbol TEXT, side TEXT, qty REAL, price REAL, fee REAL, fee_asset TEXT, realized_pnl REAL, mode TEXT, order_id TEXT);"`
- **log_trade(ts: int, symbol: str, side: str, qty: float, price: float, fee: float, fee_asset: str, realized_pnl: float, mode: str, order_id: str) → None**
  `sqlite3 trades.db "INSERT INTO trades(ts,symbol,side,qty,price,fee,fee_asset,realized_pnl,mode,order_id) VALUES($ts,$symbol,$side,$qty,$price,$fee,$fee_asset,$realized_pnl,$mode,$order_id);"`
- **export_csv(filepath: str) → None**
  `sqlite3 -header -csv trades.db "SELECT * FROM trades;" > $filepath`

### cli.py
Command‑line interface parsing user commands, wiring together streams, indicators, risk checks and order execution.
- **run_bot(symbol: str, interval: str, mode: str, api_key: str, secret: str) → None**
  `python3 - <<'PY'
import sys,threading,queue,json,time
from kline_stream import start_kline_ws, fetch_latest_kline
from indicator import calc_rsi, calc_macd
from risk_manager import calc_position_size, fetch_mark_price
from order_engine import place_market_order, place_oco_order, place_stop_market_futures
from paper_trader import simulate_market_fill, apply_fees
from trade_logger import init_db, log_trade
symbol,interval,mode,api_key,secret=sys.argv[1:]
init_db()
price_q=queue.Queue()

def candle_cb(open_time, o, h, l, c, v):
    price_q.put(float(c))

threading.Thread(target=start_kline_ws, args=(symbol,interval,'candle_cb'), daemon=True).start()
while True:
    try:
        close=float(price_q.get(timeout=30))
    except:
        continue
    # simple strategy: if RSI<30 buy, if RSI>70 sell
    # fetch recent closes (placeholder list)
    closes=[close]
    rsi=calc_rsi(str(closes),14)
    macd,signal,_=calc_macd(str(closes),12,26,9)
    if mode=='paper':
        # simulate fill using depth snapshot (omitted for brevity)
        pass
    else:
        bal=10000  # placeholder, real balance fetched via account endpoint
        qty=calc_position_size(bal,close,0.01,0.00001,5)
        if rsi<30:
            resp=place_market_order(symbol,'BUY',qty,api_key,secret)
            log_trade(int(time.time()*1000),symbol,'BUY',qty,close,0.0,'USDT',0.0,mode,json.loads(resp)['orderId'])
        elif rsi>70:
            resp=place_market_order(symbol,'SELL',qty,api_key,secret)
            log_trade(int(time.time()*1000),symbol,'SELL',qty,close,0.0,'USDT',0.0,mode,json.loads(resp)['orderId'])
PY "${symbol}" "${interval}" "${mode}" "${api_key}" "${secret}"`
