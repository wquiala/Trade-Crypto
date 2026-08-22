import asyncio
import os
import ccxt.async_support as ccxt
from dotenv import load_dotenv

load_dotenv()

async def test_markets():
    api_key = os.environ.get('BINGX_API_KEY')
    secret = os.environ.get('BINGX_SECRET')
    exchange = ccxt.bingx({
        'no': api_key,
        'secret': secret,
        'enableRateLimit': True,
    })
    exchange.set_sandbox_mode(True)
    
    try:
        markets = await exchange.load_markets()
        symbols = list(markets.keys())
        print(f"Total symbols: {len(symbols)}")
        print("First 10 symbols:", symbols[:10])
    except Exception as e:
        print("Error:", e)
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(test_markets())
