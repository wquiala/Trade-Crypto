import asyncio
import pandas as pd
import numpy as np
import sys
import random

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase5.dataset import Fase5Dataset
from scratch.fase6.hypotheses import Fase6Hypotheses
from scratch.fase6.metrics import Fase6Metrics

async def run_audit():
    dataset = Fase5Dataset()
    await dataset.load_and_prepare()
    
    records = []
    
    # Recolectar todas las señales
    for sym, df in dataset.data.items():
        df_feats = Fase6Hypotheses.calculate_features(df.copy())
        
        # A
        sig_a = Fase6Hypotheses.generate_signals_A_fading_breakout(df_feats)
        mask_a = sig_a != 0
        for idx in df_feats.index[mask_a]:
            records.append({"symbol": sym, "hyp": "A", "signal_timestamp": idx, "dir": sig_a.loc[idx], "df": df_feats})
            
        # B2
        sig_b2 = Fase6Hypotheses.generate_signals_B_climax_bajista(df_feats)
        mask_b2 = sig_b2 != 0
        for idx in df_feats.index[mask_b2]:
            records.append({"symbol": sym, "hyp": "B2", "signal_timestamp": idx, "dir": sig_b2.loc[idx], "df": df_feats})
            
        # C2
        sig_c2 = Fase6Hypotheses.generate_signals_C2(df_feats)
        mask_c2 = sig_c2 != 0
        for idx in df_feats.index[mask_c2]:
            records.append({"symbol": sym, "hyp": "C2", "signal_timestamp": idx, "dir": sig_c2.loc[idx], "df": df_feats})
            
        # C3
        sig_c3 = Fase6Hypotheses.generate_signals_C3(df_feats)
        mask_c3 = sig_c3 != 0
        for idx in df_feats.index[mask_c3]:
            records.append({"symbol": sym, "hyp": "C3", "signal_timestamp": idx, "dir": sig_c3.loc[idx], "df": df_feats})

    horizon = 96 # 24h
    results = []
    
    for r in records:
        df = r["df"]
        idx = r["signal_timestamp"]
        row_num = df.index.get_loc(idx)
        
        if row_num + horizon >= len(df):
            continue
            
        entry_idx = df.index[row_num + 1]
        entry_price = df.iloc[row_num + 1]['open']
        horizon_idx = df.index[row_num + horizon]
        horizon_price = df.iloc[row_num + horizon]['close']
        
        direction = r["dir"]
        
        window = df.iloc[row_num + 1 : row_num + horizon + 1]
        highest = window['high'].max()
        lowest = window['low'].min()
        
        # MFE/MAE de producción incorrecta (para replicar por qué falló)
        if direction == 1:
            raw_return = (horizon_price / entry_price) - 1.0
            mfe_bad = (highest / entry_price) - 1.0
            mae_bad = (lowest / entry_price) - 1.0
            
            mfe_good = (highest / entry_price) - 1.0
            mae_good = (lowest / entry_price) - 1.0
        else:
            raw_return = ((horizon_price / entry_price) - 1.0) * -1
            mfe_bad = (entry_price / lowest) - 1.0  # Formula errónea
            mae_bad = (entry_price / highest) - 1.0 # Formula errónea
            
            mfe_good = (entry_price - lowest) / entry_price
            mae_good = (entry_price - highest) / entry_price
            
        net_return = raw_return - 0.0020
        
        results.append({
            "symbol": r["symbol"],
            "hyp": r["hyp"],
            "signal_timestamp": idx,
            "entry_timestamp": entry_idx,
            "entry_price": entry_price,
            "horizon_timestamp": horizon_idx,
            "horizon_price": horizon_price,
            "raw_return": raw_return,
            "net_return": net_return,
            "mfe_bad": mfe_bad,
            "mae_bad": mae_bad,
            "mfe_good": mfe_good,
            "mae_good": mae_good,
            "highest": highest,
            "lowest": lowest,
            "dir": direction
        })
        
    df_res = pd.DataFrame(results)
    
    with open("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro/scratch/fase6/audit_output.txt", "w") as f:
        f.write("--- 20 CASOS ALEATORIOS ---\n")
        sample = df_res.sample(n=min(20, len(df_res)), random_state=42)
        for _, row in sample.iterrows():
            f.write(f"Sym: {row['symbol']} | Hyp: {row['hyp']} | Dir: {row['dir']} | Sig: {row['signal_timestamp']} | Ent: {row['entry_timestamp']} ({row['entry_price']:.4f}) -> Hor: {row['horizon_timestamp']} ({row['horizon_price']:.4f}) | Raw: {row['raw_return']*100:.2f}% | Net: {row['net_return']*100:.2f}% | Bad MFE: {row['mfe_bad']*100:.2f}% | Good MFE: {row['mfe_good']*100:.2f}%\n")
            
        f.write("\n--- TOP 10 RETORNOS (LONG y SHORT) ---\n")
        top_ret = df_res.sort_values(by="raw_return", ascending=False).head(10)
        for _, row in top_ret.iterrows():
             f.write(f"Sym: {row['symbol']} | Hyp: {row['hyp']} | Dir: {row['dir']} | Ent: {row['entry_timestamp']} ({row['entry_price']:.4f}) -> Hor: {row['horizon_timestamp']} ({row['horizon_price']:.4f}) | Raw: {row['raw_return']*100:.2f}% | Good MFE: {row['mfe_good']*100:.2f}%\n")
             
        f.write("\n--- TOP 10 MFE BAD ---\n")
        top_mfe = df_res.sort_values(by="mfe_bad", ascending=False).head(10)
        for _, row in top_mfe.iterrows():
             f.write(f"Sym: {row['symbol']} | Hyp: {row['hyp']} | Dir: {row['dir']} | Ent: {row['entry_timestamp']} ({row['entry_price']:.4f}) | Low: {row['lowest']:.4f} | Bad MFE: {row['mfe_bad']*100:.2f}% | Good MFE: {row['mfe_good']*100:.2f}%\n")

if __name__ == "__main__":
    asyncio.run(run_audit())
