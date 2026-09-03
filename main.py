import os
import time
import hmac
import hashlib
import requests

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE_URL = "https://testnet.binancefuture.com"

def get_binance_balance():
    endpoint = "/fapi/v2/balance"
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    url = f"{BASE_URL}{endpoint}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": API_KEY}
    
    response = requests.get(url, headers=headers)
    return response.json()

print("🤖 Binance Futures Testnet SMC Bot Running...")
try:
    balance = get_binance_balance()
    print("📌 Wallet Balance Response:", balance)
except Exception as e:
    print("❌ Error connecting to Binance:", str(e))
