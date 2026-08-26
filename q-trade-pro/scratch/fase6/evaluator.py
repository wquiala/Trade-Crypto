import asyncio
import pandas as pd
import numpy as np
import sys
from datetime import timedelta

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase5.dataset import Fase5Dataset
from scratch.fase6.hypotheses import Fase6Hypotheses
from scratch.fase6.metrics import Fase6Metrics

COSTS = 0.0020  # 0.20% de fricción total por trade

def evaluate_hypothesis(name: str, signals: pd.Series, df: pd.DataFrame, report: list):
    report.append(f"\n## Hipótesis: {name}")
    horizons = [16, 32, 48, 96] # 4h, 8h, 12h, 24h (velas de 15m)
    
    # ¿Cuántas señales generadas en total?
    total_signals = (signals != 0).sum()
    report.append(f"- **Total Señales:** {total_signals}")
    if total_signals == 0:
        report.append("- No hay señales para evaluar.")
        return

    for h in horizons:
        fwd_returns = Fase6Metrics.calculate_forward_returns(df, signals, horizon=h)
        stats = Fase6Metrics.get_distribution_stats(fwd_returns, costs=COSTS)
        
        if stats['count'] == 0: continue
            
        mean = stats['mean'] * 100
        win = stats['win_prob'] * 100
        median = stats['median'] * 100
        
        mae_mfe = Fase6Metrics.calculate_mae_mfe(df, signals, horizon=h)
        mfe_mean = mae_mfe['mfe'].mean() * 100 if not mae_mfe['mfe'].empty else 0
        mae_mean = mae_mfe['mae'].mean() * 100 if not mae_mfe['mae'].empty else 0
        
        # Calcular PnL asumiendo 1 unidad de capital en cada trade
        gross_return = (fwd_returns.mean() * 100) if not fwd_returns.empty else 0
        net_return = mean
        
        # Expectancy es net_return. Profit Factor simulado (sum gains / sum losses)
        net_rets = fwd_returns - COSTS
        gains = net_rets[net_rets > 0].sum()
        losses = abs(net_rets[net_rets < 0].sum())
        pf = (gains / losses) if losses != 0 else float('inf')
        
        status = "✅ PASS" if mean > 0 and pf > 1.0 else "❌ FAIL"
        
        report.append(f"### Horizonte: {h*15/60:.1f} horas ({h} velas)")
        report.append(f"- **Net Expectancy:** {mean:.4f}% {status}")
        report.append(f"- **Profit Factor:** {pf:.2f}")
        report.append(f"- **Win Rate:** {win:.1f}%")
        report.append(f"- **Distribución:** Mediana {median:.2f}% | P25 {(stats['p25']*100):.2f}% | P75 {(stats['p75']*100):.2f}%")
        report.append(f"- **MAE/MFE Promedio:** MFE {mfe_mean:.2f}% | MAE {mae_mean:.2f}%")
        report.append(f"- **Gross Return (sin costes):** {gross_return:.4f}%")

async def main():
    print("🚀 Iniciando FASE 6 (TRAIN)...")
    dataset = Fase5Dataset()
    await dataset.load_and_prepare()
    
    report = ["# FASE 6: REPORTE DE EVALUACIÓN TRAIN"]
    report.append("Evaluación estricta de las hipótesis de reversión. Coste restado = 0.20% por operación.")
    
    # Juntamos todas las señales en una sola evaluación para toda la red
    # Aunque lo correcto es concatenar y evaluar
    all_dfs = []
    
    for sym, df in dataset.data.items():
        df_feats = Fase6Hypotheses.calculate_features(df.copy())
        all_dfs.append(df_feats)
        
    master_df = pd.concat(all_dfs, ignore_index=True)
    
    # A
    sig_a = Fase6Hypotheses.generate_signals_A_fading_breakout(master_df)
    evaluate_hypothesis("A) Fading Breakout Bajista", sig_a, master_df, report)
    
    # B1
    sig_b1 = Fase6Hypotheses.generate_signals_B_climax_alcista(master_df)
    evaluate_hypothesis("B1) Vol Climax Alcista (LONG)", sig_b1, master_df, report)
    
    # B2
    sig_b2 = Fase6Hypotheses.generate_signals_B_climax_bajista(master_df)
    evaluate_hypothesis("B2) Vol Climax Bajista (SHORT)", sig_b2, master_df, report)
    
    # C1
    sig_c1 = Fase6Hypotheses.generate_signals_C1(master_df)
    evaluate_hypothesis("C1) Breakdown 32 + Vol Climax", sig_c1, master_df, report)
    
    # C2
    sig_c2 = Fase6Hypotheses.generate_signals_C2(master_df)
    evaluate_hypothesis("C2) Breakdown 32 + ADX>40 + BEAR", sig_c2, master_df, report)
    
    # C3
    sig_c3 = Fase6Hypotheses.generate_signals_C3(master_df)
    evaluate_hypothesis("C3) Breakdown 32 + Vol Climax + ADX>40 + BEAR", sig_c3, master_df, report)
    
    with open("/Users/iwilfredo/.gemini/antigravity-ide/brain/80384aa0-52a8-4f4c-b69f-49af4107809d/FASE6_TRAIN_REPORT.md", "w") as f:
        f.write("\n".join(report))
        
    print("✅ Backtest completado exitosamente. Reporte guardado.")

if __name__ == "__main__":
    asyncio.run(main())
