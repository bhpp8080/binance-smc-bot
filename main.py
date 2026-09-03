import os
import time
import hmac
import hashlib
import requests
import pandas as pd

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE_URL = "https://testnet.binancefuture.com"
SYMBOL = "BTCUSDT"
TIMEFRAME = "3m"
RISK_PER_TRADE_USDT = 10.0
RR_RATIO = 2.0

def send_signed_request(method, endpoint, params={}):
    params['timestamp'] = int(time.time() * 1000)
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    url = f"{BASE_URL}{endpoint}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": API_KEY}
    
    if method == "GET":
        return requests.get(url, headers=headers).json()
    elif method == "POST":
        return requests.post(url, headers=headers).json()

def get_klines():
    url = f"{BASE_URL}/fapi/v1/klines?symbol={SYMBOL}&interval={TIMEFRAME}&limit=50"
    res = requests.get(url).json()
    df = pd.DataFrame(res, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    df['close'] = df['close'].astype(float)
    return df

def calculate_bollinger_bands(df, window=20, num_std=2.0):
    df['sma'] = df['close'].rolling(window=window).mean()
    df['std'] = df['close'].rolling(window=window).std()
    df['upper_band'] = df['sma'] + (df['std'] * num_std)
    df['lower_band'] = df['sma'] - (df['std'] * num_std)
    return df

def check_signal(df):
    prev_close = df.iloc[-2]['close']
    prev_lower = df.iloc[-2]['lower_band']
    prev_upper = df.iloc[-2]['upper_band']
    
    curr_close = df.iloc[-1]['close']
    curr_lower = df.iloc[-1]['lower_band']
    curr_upper = df.iloc[-1]['upper_band']
    
    if prev_close <= prev_lower and curr_close > curr_lower:
        return "BUY", curr_close, curr_lower
    
    if prev_close >= prev_upper and curr_close < curr_upper:
        return "SELL", curr_close, curr_upper
        
    return None, curr_close, None

def execute_trade(side, entry_price, band_price):
    if side == "BUY":
        sl_price = round(band_price, 2)
        sl_distance = entry_price - sl_price
        if sl_distance <= 0:
            sl_distance = entry_price * 0.005
            sl_price = round(entry_price - sl_distance, 2)
            
        tp_price = round(entry_price + (sl_distance * RR_RATIO), 2)
        qty = round(RISK_PER_TRADE_USDT / sl_distance, 3)
        exit_side = "SELL"
        
    else:
        sl_price = round(band_price, 2)
        sl_distance = sl_price - entry_price
        if sl_distance <= 0:
            sl_distance = entry_price * 0.005
            sl_price = round(entry_price + sl_distance, 2)
            
        tp_price = round(entry_price - (sl_distance * RR_RATIO), 2)
        qty = round(RISK_PER_TRADE_USDT / sl_distance, 3)
        exit_side = "BUY"

    if qty < 0.001:
        qty = 0.001

    print(f"🎯 Executing {side} Order:")
    print(f"  Entry Price: {entry_price}")
    print(f"  Quantity: {qty} BTC")
    print(f"  Stop Loss: {sl_price}")
    print(f"  Take Profit (1:2 RR): {tp_price}")

    market_order = send_signed_request("POST", "/fapi/v1/order", {
        "symbol": SYMBOL, "side": side, "type": "MARKET", "quantity": qty
    })
    print("📌 Market Order Result:", market_order)

    sl_order = send_signed_request("POST", "/fapi/v1/order", {
        "symbol": SYMBOL, "side": exit_side, "type": "STOP_MARKET", "stopPrice": sl_price, "closePosition": "true"
    })
    print("🛡️ Stop Loss Order Result:", sl_order)

    tp_order = send_signed_request("POST", "/fapi/v1/order", {
        "symbol": SYMBOL, "side": exit_side, "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "closePosition": "true"
    })
    print("🎯 Take Profit Order Result:", tp_order)

print(f"🤖 Bollinger Bands Directed Strategy ({SYMBOL} {TIMEFRAME}) Running...")

try:
    df = get_klines()
    df = calculate_bollinger_bands(df)
    signal, entry_price, band_price = check_signal(df)

    if signal:
        execute_trade(signal, entry_price, band_price)
    else:
        print(f"⏳ Market Checked (Current Price: {entry_price}). No Crossover/Crossunder Signal right now.")

except Exception as e:
    print("❌ Strategy Execution Error:", str(e))
