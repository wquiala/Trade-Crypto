import pandas as pd
import numpy as np
from typing import List, Dict, Any
from .base import BaseStrategy

class TrendMomentum(BaseStrategy):
    def __init__(self):
        super().__init__("Trend Momentum")

    def generate_signals(self, df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> List[Dict[str, Any]]:
        # Aseguramos que tenemos los indicadores calculados en df_15m (que viene alineado con HTF)
        # Asumimos que los DataFrames ya traen 'EMA_20_htf', 'EMA_50_htf', 'EMA_200_htf', 'ADX_14_htf', 'RSI_14', etc.
        signals = []
        
        # Calcular Donchian 20 y Volumen Relativo si no existen
        if 'donchian_high_20' not in df_15m.columns:
            df_15m['donchian_high_20'] = df_15m['high'].rolling(20).max().shift(1)
            df_15m['donchian_low_20'] = df_15m['low'].rolling(20).min().shift(1)
        if 'vol_sma_20' not in df_15m.columns:
            df_15m['vol_sma_20'] = df_15m['volume'].rolling(20).mean().shift(1)
            
        for i in range(50, len(df_15m) - 1): # -1 porque la entrada es next_open
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
            high_px = row['high']
            low_px = row['low']
            vol = row['volume']
            vol_sma = row.get('vol_sma_20', 0)
            rsi = row.get("RSI_14", 50)
            
            donchian_h = row['donchian_high_20']
            donchian_l = row['donchian_low_20']
            
            # Condición Momentum Fuerte y Volumen Relativo > 1.5
            vol_surge = vol > (1.5 * vol_sma) if vol_sma > 0 else False
            
            signal = None
            if trend_bull and close_px > donchian_h and rsi > 60 and vol_surge:
                signal = "LONG"
            elif trend_bear and close_px < donchian_l and rsi < 40 and vol_surge:
                signal = "SHORT"
                
            if signal:
                signals.append({
                    "time": row.name, # index is datetime
                    "signal": signal,
                    "entry_price": df_15m.iloc[i+1]['open'], # Next open
                    "atr": row.get("ATR_14", close_px * 0.01),
                    "features": row.to_dict() # Guardamos para análisis posterior
                })
                
        return signals
