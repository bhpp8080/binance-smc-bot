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

def has_open_position():
    """अकाऊंटवर आधीपासूनच कोणती पोझिशन ओपन आहे का हे तपासते"""
    res = send_signed_request("GET", "/fapi/v2/positionRisk")
    if isinstance(res, list):
        for pos in res:
            if pos.get("symbol") == SYMBOL:
                amt = float(pos.get("positionAmt", 0))
                if amt != 0:
                    return True
    return False

def get_klines():
    url = f"{BASE_URL}/fapi/v1/klines?symbol={SYMBOL}&interval={TIMEFRAME}&limit=50"
    res = requests.get(url).json()
    df = pd.DataFrame(res, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    df['close'] = df['close'].astype(float)
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    return df

def calculate_bollinger_bands(df, window=20, num_std=2.0):
    df['sma'] = df['close'].rolling(window=window).mean()
    df['std'] = df['close'].rolling(window=window).std()
    df['upper_band'] = df['sma'] + (df['std'] * num_std)
    df['lower_band'] = df['sma'] - (df['std'] * num_std)
    return df

def check_recent_signals(df):
    """
    चालू (unclosed) कँडल सोडून, मागील पूर्ण झालेल्या (closed) 5 कँडल्स तपासल्या जातात.
    """
    closed_df = df.iloc[:-1].copy()
    
    # मागील ५ कँडल्समध्ये सर्वात नवीन ट्रिगर झालेला सिग्नल शोधणे
    for i in range(len(closed_df) - 1, len(closed_df) - 6, -1):
        prev_close = closed_df.iloc[i-1]['close']
        prev_lower = closed_df.iloc[i-1]['lower_band']
        prev_upper = closed_df.iloc[i-1]['upper_band']
        
        curr_close = closed_df.iloc[i]['close']
        curr_lower = closed_df.iloc[i]['lower_band']
        curr_upper = closed_df.iloc[i]['upper_band']
        signal_time = closed_df.iloc[i]['time']
        
        # BUY Signal (Crossover)
        if prev_close <= prev_lower and curr_close > curr_lower:
            return "BUY", curr_close, curr_lower, signal_time
            
        # SELL Signal (Crossunder)
        if prev_close >= prev_upper and curr_close < curr_upper:
            return "SELL", curr_close, curr_upper, signal_time
            
    return None, closed_df.iloc[-1]['close'], None, None

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
        
    else:  # SELL
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
    print(f"  Quantity: {qty} BTC ($10 Risk Target)")
    print(f"  Stop Loss: {sl_price}")
    print(f"  Take Profit (1:2 RR): {tp_price}")

    # Market Order
    market_order = send_signed_request("POST", "/fapi/v1/order", {
        "symbol": SYMBOL, "side": side, "type": "MARKET", "quantity": qty
    })
    print("📌 Market Order Result:", market_order)

    # Stop Loss
    sl_order = send_signed_request("POST", "/fapi/v1/order", {
        "symbol": SYMBOL, "side": exit_side, "type": "STOP_MARKET", "stopPrice": sl_price, "closePosition": "true"
    })
    print("🛡️ Stop Loss Order Result:", sl_order)

    # Take Profit
    tp_order = send_signed_request("POST", "/fapi/v1/order", {
        "symbol": SYMBOL, "side": exit_side, "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "closePosition": "true"
    })
    print("🎯 Take Profit Order Result:", tp_order)

print(f"🤖 Bollinger Bands Bot ({SYMBOL} {TIMEFRAME}) Running...")

try:
    if has_open_position():
        print("⚠️ Active trade already open on Binance. Skipping new entry to protect risk.")
    else:
        df = get_klines()
        df = calculate_bollinger_bands(df)
        signal, entry_price, band_price, sig_time = check_recent_signals(df)

        if signal:
            print(f"🟢 Signal Found! Side: {signal} | Signal Time: {sig_time}")
            execute_trade(signal, entry_price, band_price)
        else:
            print(f"⏳ Market Checked (Current Price: {entry_price}). No valid Crossover/Crossunder in recent candles.")

except Exception as e:
    print("❌ Strategy Execution Error:", str(e))
