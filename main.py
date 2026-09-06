import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import numpy as np

# =====================================================================
# BINANCE CONFIGURATION
# =====================================================================
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE_URL = "https://testnet.binancefuture.com"
SYMBOL = "BTCUSDT"
RISK_PER_TRADE_USDT = 10.0
RR_RATIO = 2.0

# =====================================================================
# BINANCE API HELPERS
# =====================================================================
def send_signed_request(method, endpoint, params=None):
    if params is None:
        params = {}
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
    """अकाऊंटवर आधीपासून पोझिशन चालू आहे का हे तपासते"""
    try:
        res = send_signed_request("GET", "/fapi/v2/positionRisk")
        if isinstance(res, list):
            for pos in res:
                if pos.get("symbol") == SYMBOL:
                    amt = float(pos.get("positionAmt", 0))
                    if amt != 0:
                        return True
    except Exception as e:
        print("⚠️ Position Check Error:", str(e))
    return False

def get_klines(interval, limit=50):
    url = f"{BASE_URL}/fapi/v1/klines?symbol={SYMBOL}&interval={interval}&limit={limit}"
    res = requests.get(url).json()
    df = pd.DataFrame(res, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    
    # Capitalizing column names to match user's SMC script
    df['Open'] = df['open'].astype(float)
    df['High'] = df['high'].astype(float)
    df['Low'] = df['low'].astype(float)
    df['Close'] = df['close'].astype(float)
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    return df[['time', 'Open', 'High', 'Low', 'Close']]

# =====================================================================
# AUTOMATED ORDER FLOW / ORDER BLOCK DETECTOR
# =====================================================================
def auto_detect_ltf_obs(tf_list=['15m', '5m', '3m']):
    """
    15m, 5m, आणि 3m टाइमफ्रेमवरून आपोआप चालीव Bullish/Bearish Order Blocks शोधणे
    """
    bullish_obs = []
    bearish_obs = []

    for tf in tf_list:
        df = get_klines(interval=tf, limit=30)
        if df.empty or len(df) < 5:
            continue
        
        # Bullish OB: ब्रेकआऊटच्या आधीची शेवटची Red Candle
        for i in range(len(df) - 3, 2, -1):
            if df.iloc[i]['Close'] < df.iloc[i]['Open']: # Red Candle
                if df.iloc[i+1]['Close'] > df.iloc[i]['High']: # Breakout
                    bullish_obs.append({
                        'tf': tf,
                        'top': float(df.iloc[i]['High']),
                        'bot': float(df.iloc[i]['Low'])
                    })
                    break

        # Bearish OB: ब्रेकडाऊनच्या आधीची शेवटची Green Candle
        for i in range(len(df) - 3, 2, -1):
            if df.iloc[i]['Close'] > df.iloc[i]['Open']: # Green Candle
                if df.iloc[i+1]['Close'] < df.iloc[i]['Low']: # Breakdown
                    bearish_obs.append({
                        'tf': tf,
                        'top': float(df.iloc[i]['High']),
                        'bot': float(df.iloc[i]['Low'])
                    })
                    break

    return bullish_obs, bearish_obs

# =====================================================================
# SMC STRATEGY ENGINE (YOUR ALGORITHM)
# =====================================================================
class SMCStrategyEngine:
    def __init__(self, rr_ratio=2.0):
        self.rr_ratio = rr_ratio

    def calculate_mean_threshold(self, top, bottom):
        return bottom + (top - bottom) / 2.0

    def resolve_ltf_overlap(self, ltf_obs):
        if not ltf_obs:
            return None, None
        tf_weights = {'3m': 1, '5m': 2, '15m': 3}
        sorted_obs = sorted(ltf_obs, key=lambda x: tf_weights.get(x['tf'], 99))
        entry_ob = sorted_obs[0]
        outer_ob = sorted_obs[-1]
        return entry_ob, outer_ob

    def evaluate_buy_setup(self, candles_df, ltf_obs):
        entry_ob, outer_ob = self.resolve_ltf_overlap(ltf_obs)
        if not entry_ob or not outer_ob:
            return {"signal": "NO_SETUP", "reason": "No valid LTF Order Flow"}

        mt_level = self.calculate_mean_threshold(entry_ob['top'], entry_ob['bot'])
        sl_price = outer_ob['bot']
        
        setup_tapped = False
        last_red_high = None
        
        for idx, row in candles_df.iterrows():
            candle_open = row['Open']
            candle_high = row['High']
            candle_low = row['Low']
            candle_close = row['Close']

            if candle_low <= entry_ob['top'] and candle_close >= entry_ob['bot']:
                setup_tapped = True

            if setup_tapped:
                if candle_close < mt_level:
                    return {"signal": "INVALIDATED", "reason": "Candle closed below 50% Mean Threshold"}

                if candle_close < candle_open:
                    last_red_high = candle_high

                if last_red_high is not None and candle_close > last_red_high:
                    entry_price = candle_close
                    risk = entry_price - sl_price
                    
                    if risk <= 0:
                        return {"signal": "INVALIDATED", "reason": "Invalid Risk Distance"}

                    tp_price = entry_price + (risk * self.rr_ratio)
                    
                    return {
                        "signal": "BUY_ENTRY",
                        "entry_time": row['time'],
                        "entry_price": entry_price,
                        "sl_price": sl_price,
                        "tp_price": tp_price,
                        "risk_points": risk,
                        "entry_tf": entry_ob['tf'],
                        "sl_tf": outer_ob['tf']
                    }

        return {"signal": "WAITING_FOR_TRIGGER", "reason": "Conditions met, waiting for trigger"}

    def evaluate_sell_setup(self, candles_df, ltf_obs):
        entry_ob, outer_ob = self.resolve_ltf_overlap(ltf_obs)
        if not entry_ob or not outer_ob:
            return {"signal": "NO_SETUP", "reason": "No valid LTF Order Flow"}

        mt_level = self.calculate_mean_threshold(entry_ob['top'], entry_ob['bot'])
        sl_price = outer_ob['top']
        
        setup_tapped = False
        last_green_low = None
        
        for idx, row in candles_df.iterrows():
            candle_open = row['Open']
            candle_high = row['High']
            candle_low = row['Low']
            candle_close = row['Close']

            if candle_high >= entry_ob['bot'] and candle_close <= entry_ob['top']:
                setup_tapped = True

            if setup_tapped:
                if candle_close > mt_level:
                    return {"signal": "INVALIDATED", "reason": "Candle closed above 50% Mean Threshold"}

                if candle_close > candle_open:
                    last_green_low = candle_low

                if last_green_low is not None and candle_close < last_green_low:
                    entry_price = candle_close
                    risk = sl_price - entry_price
                    
                    if risk <= 0:
                        return {"signal": "INVALIDATED", "reason": "Invalid Risk Distance"}

                    tp_price = entry_price - (risk * self.rr_ratio)
                    
                    return {
                        "signal": "SELL_ENTRY",
                        "entry_time": row['time'],
                        "entry_price": entry_price,
                        "sl_price": sl_price,
                        "tp_price": tp_price,
                        "risk_points": risk,
                        "entry_tf": entry_ob['tf'],
                        "sl_tf": outer_ob['tf']
                    }

        return {"signal": "WAITING_FOR_TRIGGER", "reason": "Conditions met, waiting for trigger"}

# =====================================================================
# ORDER EXECUTION ENGINE
# =====================================================================
def execute_trade(side, entry_price, sl_price, tp_price):
    sl_distance = abs(entry_price - sl_price)
    qty = round(RISK_PER_TRADE_USDT / sl_distance, 3)

    if qty < 0.001:
        qty = 0.001

    exit_side = "SELL" if side == "BUY" else "BUY"

    print(f"🎯 Executing {side} Order via SMC Volumetric Order Flow Engine:")
    print(f"  Entry Price: {entry_price}")
    print(f"  Quantity: {qty} BTC ($10 Risk Target)")
    print(f"  Stop Loss: {sl_price}")
    print(f"  Take Profit (1:2 RR): {tp_price}")

    # Market Order
    market_order = send_signed_request("POST", "/fapi/v1/order", {
        "symbol": SYMBOL, "side": side, "type": "MARKET", "quantity": qty
    })
    print("📌 Market Order Result:", market_order)

    # Stop Loss Order
    sl_order = send_signed_request("POST", "/fapi/v1/order", {
        "symbol": SYMBOL, "side": exit_side, "type": "STOP_MARKET", "stopPrice": round(sl_price, 2), "closePosition": "true"
    })
    print("🛡️ Stop Loss Order Result:", sl_order)

    # Take Profit Order
    tp_order = send_signed_request("POST", "/fapi/v1/order", {
        "symbol": SYMBOL, "side": exit_side, "type": "TAKE_PROFIT_MARKET", "stopPrice": round(tp_price, 2), "closePosition": "true"
    })
    print("🎯 Take Profit Order Result:", tp_order)

# =====================================================================
# MAIN RUNNER
# =====================================================================
print(f"🤖 SMC Order Flow Trading Bot Running for {SYMBOL}...")

try:
    if has_open_position():
        print("⚠️ Active trade already open on Binance. Skipping new entry to protect risk.")
    else:
        # 1. Fetch Auto LTF Order Blocks
        bullish_obs, bearish_obs = auto_detect_ltf_obs(['15m', '5m', '3m'])
        
        # 2. Fetch 3m Trigger Candles
        df_3m = get_klines('3m', limit=20)
        
        engine = SMCStrategyEngine(rr_ratio=RR_RATIO)
        
        # 3. Evaluate Buy and Sell Setups
        buy_res = engine.evaluate_buy_setup(df_3m, bullish_obs)
        sell_res = engine.evaluate_sell_setup(df_3m, bearish_obs)

        if buy_res["signal"] == "BUY_ENTRY":
            print(f"🟢 BUY ENTRY TRIGGERED! Time: {buy_res['entry_time']}")
            execute_trade("BUY", buy_res['entry_price'], buy_res['sl_price'], buy_res['tp_price'])

        elif sell_res["signal"] == "SELL_ENTRY":
            print(f"🔴 SELL ENTRY TRIGGERED! Time: {sell_res['entry_time']}")
            execute_trade("SELL", sell_res['entry_price'], sell_res['sl_price'], sell_res['tp_price'])

        else:
            current_close = df_3m.iloc[-1]['Close']
            print(f"⏳ Market Checked (Price: {current_close}). Buy: {buy_res['signal']} | Sell: {sell_res['signal']}")

except Exception as e:
    print("❌ Strategy Execution Error:", str(e))
