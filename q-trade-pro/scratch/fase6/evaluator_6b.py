import asyncio
import pandas as pd
import numpy as np
import sys
from datetime import timedelta

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase5.dataset import Fase5Dataset
from scratch.fase6.hypotheses import Fase6Hypotheses
from scratch.fase6.metrics import Fase6Metrics

COSTS = 0.0020  # 0.20%

def analyze_hypothesis(name: str, signals_dict: dict, dataset_dict: dict, report: list, top_events: list):
    """
    signals_dict: {symbol: pd.Series de señales puras}
    dataset_dict: {symbol: pd.DataFrame de OHLCV}
    """
    report.append(f"\n## Hipótesis: {name}")
    
    # 1. Sensibilidad del Overlap (Cooldowns) - Usamos horizonte fijo de 24h (96 velas) para medir rendimiento
    horizon = 96 
    cooldown_hours = [0, 4, 8, 12, 24]
    
    report.append("### Análisis de Sensibilidad del Overlap (Horizonte 24h)")
    report.append("| Cooldown | Señales | Eventos Indep. | Excluidos | Media (Net) | Mediana | Net Exp | Profit Factor | Win Rate | CI 95% |")
    report.append("|---|---|---|---|---|---|---|---|---|---|")
    
    independent_signals_by_sym = {}
    
    for cd in cooldown_hours:
        cd_candles = cd * 4
        all_fwd_returns = []
        total_signals = 0
        total_events = 0
        
        for sym, signals in signals_dict.items():
            df = dataset_dict[sym]
            active_signals = (signals != 0).sum()
            total_signals += active_signals
            
            if active_signals == 0:
                continue
                
            filtered_signals = Fase6Metrics.filter_overlapping_signals(signals, cd_candles)
            events = (filtered_signals != 0).sum()
            total_events += events
            
            # Guardamos las señales independientes (cooldown 24h) para luego
            if cd == 24:
                independent_signals_by_sym[sym] = filtered_signals
                
            fwd = Fase6Metrics.calculate_forward_returns(df, filtered_signals, horizon=horizon)
            all_fwd_returns.append(fwd)
            
        if total_events == 0:
            report.append(f"| {cd}h | {total_signals} | 0 | {total_signals} | - | - | - | - | - | - |")
            continue
            
        all_fwd = pd.concat(all_fwd_returns)
        stats = Fase6Metrics.get_distribution_stats(all_fwd, costs=COSTS)
        
        excluded = total_signals - total_events
        mean_net = stats['mean'] * 100
        median = stats['median'] * 100
        win_rate = stats['win_prob'] * 100
        
        net_rets = all_fwd - COSTS
        gains = net_rets[net_rets > 0].sum()
        losses = abs(net_rets[net_rets < 0].sum())
        pf = (gains / losses) if losses != 0 else float('inf')
        
        ci_str = f"[{stats['ci_lower']*100:.2f}%, {stats['ci_upper']*100:.2f}%]"
        
        report.append(f"| {cd}h | {total_signals} | {total_events} | {excluded} | {mean_net:.4f}% | {median:.2f}% | {mean_net:.4f}% | {pf:.2f} | {win_rate:.1f}% | {ci_str} |")
        
    # 2. Test de Robustez por Símbolo (Usando cooldown 24h)
    report.append("\n### Test de Robustez por Símbolo (Cooldown 24h)")
    report.append("| Símbolo | Eventos Indep. | Net Expectancy | Profit Factor | Win Rate |")
    report.append("|---|---|---|---|---|")
    
    for sym, indep_sig in independent_signals_by_sym.items():
        events = (indep_sig != 0).sum()
        if events == 0:
            continue
        
        df = dataset_dict[sym]
        fwd = Fase6Metrics.calculate_forward_returns(df, indep_sig, horizon=horizon)
        stats = Fase6Metrics.get_distribution_stats(fwd, costs=COSTS)
        
        net_rets = fwd - COSTS
        gains = net_rets[net_rets > 0].sum()
        losses = abs(net_rets[net_rets < 0].sum())
        pf = (gains / losses) if losses != 0 else float('inf')
        
        report.append(f"| {sym} | {events} | {stats['mean']*100:.4f}% | {pf:.2f} | {stats['win_prob']*100:.1f}% |")
        
        # Para Top 10
        active_indices = indep_sig[indep_sig != 0].index
        for idx in active_indices:
            row_num = df.index.get_loc(idx)
            if row_num + horizon >= len(df): continue
            
            entry_idx = df.index[row_num + 1]
            entry_price = df.iloc[row_num + 1]['open']
            horizon_idx = df.index[row_num + horizon]
            horizon_price = df.iloc[row_num + horizon]['close']
            
            dir_sig = indep_sig.loc[idx]
            raw_ret = fwd.loc[idx] # Fase6Metrics ya le aplicó la dirección
            net_ret = raw_ret - COSTS
            
            window = df.iloc[row_num + 1 : row_num + horizon + 1]
            highest = window['high'].max()
            lowest = window['low'].min()
            
            if dir_sig == 1:
                mfe = (highest / entry_price) - 1.0
                mae = (lowest / entry_price) - 1.0
            else:
                mfe = (entry_price - lowest) / entry_price
                mae = (entry_price - highest) / entry_price
                
            top_events.append({
                "symbol": sym,
                "hypothesis": name,
                "signal_timestamp": idx,
                "entry_timestamp": entry_idx,
                "entry_price": entry_price,
                "horizon_timestamp": horizon_idx,
                "horizon_price": horizon_price,
                "raw_return": raw_ret,
                "net_return": net_ret,
                "mfe": mfe,
                "mae": mae
            })
            
async def main():
    print("🚀 Iniciando FASE 6B (TRAIN Corregido)...")
    dataset = Fase5Dataset()
    await dataset.load_and_prepare()
    
    report = ["# FASE 6B: REPORTE DE EVALUACIÓN TRAIN (METODOLOGÍA CORREGIDA)"]
    report.append("Auditoría superada: Fórmulas MFE/MAE SHORT simétricas implementadas. Filtro de eventos independientes por cooldown añadido.")
    
    dataset_dict = {}
    sig_A = {}
    sig_B1 = {}
    sig_B2 = {}
    sig_C1 = {}
    sig_C2 = {}
    sig_C3 = {}
    
    for sym, df in dataset.data.items():
        df_feats = Fase6Hypotheses.calculate_features(df.copy())
        dataset_dict[sym] = df_feats
        
        sig_A[sym] = Fase6Hypotheses.generate_signals_A_fading_breakout(df_feats)
        sig_B1[sym] = Fase6Hypotheses.generate_signals_B_climax_alcista(df_feats)
        sig_B2[sym] = Fase6Hypotheses.generate_signals_B_climax_bajista(df_feats)
        sig_C1[sym] = Fase6Hypotheses.generate_signals_C1(df_feats)
        sig_C2[sym] = Fase6Hypotheses.generate_signals_C2(df_feats)
        sig_C3[sym] = Fase6Hypotheses.generate_signals_C3(df_feats)
        
    top_events = []
    
    analyze_hypothesis("A) Fading Breakout Bajista", sig_A, dataset_dict, report, top_events)
    analyze_hypothesis("B1) Vol Climax Alcista (LONG)", sig_B1, dataset_dict, report, top_events)
    analyze_hypothesis("B2) Vol Climax Bajista (SHORT)", sig_B2, dataset_dict, report, top_events)
    analyze_hypothesis("C1) Breakdown 32 + Vol Climax", sig_C1, dataset_dict, report, top_events)
    analyze_hypothesis("C2) Breakdown 32 + ADX>40 + BEAR", sig_C2, dataset_dict, report, top_events)
    analyze_hypothesis("C3) Breakdown 32 + Vol Climax + ADX>40 + BEAR", sig_C3, dataset_dict, report, top_events)
    
    report.append("\n## TOP 10 EVENTOS INDEPENDIENTES (TODAS LAS HIPÓTESIS)")
    df_top = pd.DataFrame(top_events)
    if not df_top.empty:
        df_top = df_top.sort_values(by="raw_return", ascending=False).head(10)
        report.append("| Símbolo | Hipótesis | Señal | Entrada | P.Entrada | Horizonte | P.Horizonte | Raw Ret | Net Ret | MFE | MAE |")
        report.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for _, row in df_top.iterrows():
            report.append(f"| {row['symbol']} | {row['hypothesis']} | {row['signal_timestamp']} | {row['entry_timestamp']} | {row['entry_price']:.4f} | {row['horizon_timestamp']} | {row['horizon_price']:.4f} | {row['raw_return']*100:.2f}% | {row['net_return']*100:.2f}% | {row['mfe']*100:.2f}% | {row['mae']*100:.2f}% |")

    report.append("\n## VEREDICTO FINAL FASE 6B")
    report.append("Revisar Net Expectancy a 24h, Profit Factor, y significancia estadística (CI > 0).")
            
    with open("/Users/iwilfredo/.gemini/antigravity-ide/brain/80384aa0-52a8-4f4c-b69f-49af4107809d/FASE6B_TRAIN_REPORT.md", "w") as f:
        f.write("\n".join(report))
        
    print("✅ Backtest 6B completado exitosamente. Reporte guardado.")

if __name__ == "__main__":
    asyncio.run(main())
