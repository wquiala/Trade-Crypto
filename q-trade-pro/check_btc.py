import asyncio
import pandas as pd
from core.data_processor import MarketDataFetcher
from core.feature_engine import FeatureEngine
from core.regime_detector import RegimeDetector
import ccxt.async_support as ccxt

async def main():
    exchange = ccxt.bingx({'enableRateLimit': True})
    try:
        raw_data = await exchange.fetch_ohlcv('BTC/USDT:USDT', timeframes=['15m', '1h'])
        df_15m = MarketDataFetcher.normalize_klines(raw_data['15m'])
        df_1h = MarketDataFetcher.normalize_klines(raw_data['1h'])
        
        df_15m_feat = FeatureEngine.compute(df_15m)
        df_1h_feat = FeatureEngine.compute(df_1h)
        
        regime = RegimeDetector.detect(df_1h_feat)
        
        last_15m = df_15m_feat.iloc[-1]
        
        print(f"Régimen (1h): {regime}")
        print(f"ADX (15m): {last_15m.get('ADX_14')}")
        print(f"RSI (15m): {last_15m.get('RSI_14')}")
        print(f"MACD Hist: {last_15m.get('MACDh_12_26_9')}")
        print(f"Close: {last_15m.get('close')}")
        print(f"EMA 20: {last_15m.get('EMA_20')}")
        print(f"EMA 50: {last_15m.get('EMA_50')}")
        
    finally:
        await exchange.close()

asyncio.run(main())
