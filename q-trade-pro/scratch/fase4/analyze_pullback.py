import asyncio
import pandas as pd
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase4.engine.runner import Phase4Runner

async def main():
    runner = Phase4Runner([])
    await runner.load_data()
    
    total_bars = 0
    passed_htf = 0
    passed_ema50 = 0
    passed_rsi = 0
    passed_reversal = 0
    passed_strong_close = 0
    
    for sym, d in runner.aligned_data.items():
        df_15m = d["aligned"]
        
        for i in range(50, len(df_15m) - 1):
            row = df_15m.iloc[i]
            total_bars += 1
            
            # Filtros HTF (Trend)
            adx_htf = row.get("ADX_14_htf", 0)
            ema20_htf = row.get("EMA_20_htf", 0)
            ema50_htf = row.get("EMA_50_htf", 0)
            ema200_htf = row.get("EMA_200_htf", 0)
            
            if pd.isna(adx_htf) or pd.isna(ema20_htf):
                continue
                
            trend_bull = (ema20_htf > ema50_htf > ema200_htf) and (adx_htf > 25)
            trend_bear = (ema20_htf < ema50_htf < ema200_htf) and (adx_htf > 25)
            
            if not trend_bull and not trend_bear:
                continue
                
            passed_htf += 1
            
            close_px = row['close']
            open_px = row['open']
            high_px = row['high']
            low_px = row['low']
            
            ema20_ltf = row.get("EMA_20", 0)
            ema50_ltf = row.get("EMA_50", 0)
            rsi = row.get("RSI_14", 50)
            
            # Chequeamos LONG como ejemplo general (o SHORT)
            if trend_bull:
                touched_ema50 = low_px <= ema50_ltf
                if not touched_ema50: continue
                passed_ema50 += 1
                
                cooled_rsi = rsi < 45
                if not cooled_rsi: continue
                passed_rsi += 1
                
                bullish_reversal = (close_px > open_px) and (close_px > ema20_ltf)
                if not bullish_reversal: continue
                passed_reversal += 1
                
                strong_close = (close_px - low_px) > 0.7 * (high_px - low_px)
                if not strong_close: continue
                passed_strong_close += 1
                
            elif trend_bear:
                touched_ema50 = high_px >= ema50_ltf
                if not touched_ema50: continue
                passed_ema50 += 1
                
                cooled_rsi = rsi > 55
                if not cooled_rsi: continue
                passed_rsi += 1
                
                bearish_reversal = (close_px < open_px) and (close_px < ema20_ltf)
                if not bearish_reversal: continue
                passed_reversal += 1
                
                strong_close = (high_px - close_px) > 0.7 * (high_px - low_px)
                if not strong_close: continue
                passed_strong_close += 1
                
    print(f"--- ANÁLISIS DE EMBUDO (FUNNEL) TREND PULLBACK ---")
    print(f"Total Barras Analizadas: {total_bars}")
    print(f"Filtro 1 (Tendencia HTF + ADX > 25): {passed_htf} ({passed_htf/total_bars*100:.2f}%)")
    print(f"Filtro 2 (Toque de EMA50 LTF): {passed_ema50} ({passed_ema50/passed_htf*100:.2f}% del anterior)")
    print(f"Filtro 3 (RSI Enfriado): {passed_rsi} ({passed_rsi/max(1,passed_ema50)*100:.2f}% del anterior)")
    print(f"Filtro 4 (Vela de Reversión cerrando sobre EMA20): {passed_reversal} ({passed_reversal/max(1,passed_rsi)*100:.2f}% del anterior)")
    print(f"Filtro 5 (Cierre Fuerte en el 30% del rango): {passed_strong_close} ({passed_strong_close/max(1,passed_reversal)*100:.2f}% del anterior)")

if __name__ == "__main__":
    asyncio.run(main())
