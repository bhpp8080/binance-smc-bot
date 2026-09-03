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
TIMEFRAME = "15m"

def get_klines(symbol=SYMBOL, interval=TIMEFRAME, limit=50):
    url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    res = requests.get(url).json()
    df = pd.DataFrame(res, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    return df

def analyze_smc_signal(df):
    c0 = df.iloc[-1]
    c1 = df.iloc[-2]
    c2 = df.iloc[-3]

    signal = None

    # Bullish FVG Setup
    if c0['low'] > c2['high'] and c1['close'] > c1['open']:
        signal = "BUY"

    # Bearish FVG Setup
    elif c0['high'] < c2['low'] and c1['close'] < c1['open']:
        signal = "SELL"

    return signal

def place_order(symbol, side, quantity=0.002):
    endpoint = "/fapi/v1/order"
    timestamp = int(time.time() * 1000)
    query_string = f"symbol={symbol}&side={side}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    url = f"{BASE_URL}{endpoint}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": API_KEY}
    
    response = requests.post(url, headers=headers)
    return response.json()

print(f"🤖 SMC Bot Scanning Market for {SYMBOL} ({TIMEFRAME})...")

try:
    data = get_klines()
    signal = analyze_smc_signal(data)
    
    if signal:
        print(f"⚡ SMC Signal Detected: {signal}! Executing Order...")
        res = place_order(SYMBOL, signal)
        print("📌 Execution Result:", res)
    else:
        print("⏳ Market Analysis Completed: No SMC setup at the moment.")

except Exception as e:
    print("❌ Strategy Execution Error:", str(e))
