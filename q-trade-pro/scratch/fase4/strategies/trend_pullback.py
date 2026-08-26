import pandas as pd
from typing import List, Dict, Any
from .base import BaseStrategy

class TrendPullback(BaseStrategy):
    def __init__(self):
        super().__init__("Trend Pullback")

    def generate_signals(self, df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> List[Dict[str, Any]]:
        signals = []
            
        for i in range(50, len(df_15m) - 1):
            row = df_15m.iloc[i]
            
            # Filtros HTF (Trend)
            adx_htf = row.get("ADX_14_htf", 0)
            ema20_htf = row.get("EMA_20_htf", 0)
            ema50_htf = row.get("EMA_50_htf", 0)
            ema200_htf = row.get("EMA_200_htf", 0)
            
            if pd.isna(adx_htf) or pd.isna(ema20_htf):
                continue
                
            trend_bull = (ema20_htf > ema50_htf > ema200_htf) and (adx_htf > 25)
            trend_bear = (ema20_htf < ema50_htf < ema200_htf) and (adx_htf > 25)
            
            # LTF Triggers
            close_px = row['close']
            open_px = row['open']
            high_px = row['high']
            low_px = row['low']
            
            ema20_ltf = row.get("EMA_20", 0)
            ema50_ltf = row.get("EMA_50", 0)
            rsi = row.get("RSI_14", 50)
            
            signal = None
            
            # Para LONG: el precio bajó hasta EMA50, el RSI se enfrió (<45), 
            # y ahora la vela cierra fuerte por encima de la EMA20_LTF.
            if trend_bull:
                touched_ema50 = low_px <= ema50_ltf
                cooled_rsi = rsi < 45
                bullish_reversal = (close_px > open_px) and (close_px > ema20_ltf)
                strong_close = (close_px - low_px) > 0.7 * (high_px - low_px) # Cierra en el 30% superior
                
                if touched_ema50 and cooled_rsi and bullish_reversal and strong_close:
                    signal = "LONG"
                    
            elif trend_bear:
                touched_ema50 = high_px >= ema50_ltf
                cooled_rsi = rsi > 55
                bearish_reversal = (close_px < open_px) and (close_px < ema20_ltf)
                strong_close = (high_px - close_px) > 0.7 * (high_px - low_px) # Cierra en el 30% inferior
                
                if touched_ema50 and cooled_rsi and bearish_reversal and strong_close:
                    signal = "SHORT"
                
            if signal:
                signals.append({
                    "time": row.name,
                    "signal": signal,
                    "entry_price": df_15m.iloc[i+1]['open'],
                    "atr": row.get("ATR_14", close_px * 0.01),
                    "features": row.to_dict()
                })
                
        return signals
