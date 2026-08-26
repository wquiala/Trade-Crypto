import pandas as pd
from typing import List, Dict, Any
from .base import BaseStrategy

class PriceActionBreakout(BaseStrategy):
    def __init__(self):
        super().__init__("Breakout Price Action")

    def generate_signals(self, df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> List[Dict[str, Any]]:
        signals = []
        
        if 'donchian_high_50' not in df_15m.columns:
            df_15m['donchian_high_50'] = df_15m['high'].rolling(50).max().shift(1)
            df_15m['donchian_low_50'] = df_15m['low'].rolling(50).min().shift(1)
        if 'vol_sma_20' not in df_15m.columns:
            df_15m['vol_sma_20'] = df_15m['volume'].rolling(20).mean().shift(1)
            
        for i in range(50, len(df_15m) - 1):
            row = df_15m.iloc[i]
            
            # Filtros HTF (Sesgo)
            ema50_htf = row.get("EMA_50_htf", 0)
            if pd.isna(ema50_htf):
                continue
                
            close_px = row['close']
            high_px = row['high']
            low_px = row['low']
            vol = row['volume']
            vol_sma = row.get('vol_sma_20', 0)
            atr = row.get("ATR_14", close_px * 0.01)
            
            # Condiciones LTF
            range_expansion = (high_px - low_px) > (1.5 * atr)
            vol_surge = vol > (2.0 * vol_sma) if vol_sma > 0 else False
            
            donchian_h = row['donchian_high_50']
            donchian_l = row['donchian_low_50']
            
            signal = None
            
            if close_px > ema50_htf: # Bullish bias
                breakout = close_px > donchian_h
                strong_close = (close_px - low_px) > 0.7 * (high_px - low_px)
                if breakout and range_expansion and vol_surge and strong_close:
                    signal = "LONG"
                    
            elif close_px < ema50_htf: # Bearish bias
                breakout = close_px < donchian_l
                strong_close = (high_px - close_px) > 0.7 * (high_px - low_px)
                if breakout and range_expansion and vol_surge and strong_close:
                    signal = "SHORT"
                    
            if signal:
                signals.append({
                    "time": row.name,
                    "signal": signal,
                    "entry_price": df_15m.iloc[i+1]['open'],
                    "atr": atr,
                    "features": row.to_dict()
                })
                
        return signals
