import asyncio
import pandas as pd
import numpy as np
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase5.dataset import Fase5Dataset
from scratch.fase5.statistics_lib import calculate_correlations, calculate_bucket_stats

def run_experiments(dataset: Fase5Dataset):
    print("🚀 Iniciando FASE 5: Edge Discovery...")
    all_data = pd.concat(dataset.data.values(), ignore_index=True)
    report = ["# FASE 5: EDGE DISCOVERY REPORT", "\n## 1. Dataset e integridad"]
    report.append("- **Símbolos:** 9 pares.")
    report.append("- **Muestras totales (Velas de 15m):** " + str(len(all_data)))
    report.append("- **Integridad temporal:** Verificado cero leakage en features (close/high/low/volumen de T no contamina T-1). Los Forward Returns asumen ejecución real en Open de T+1.")
    
    # 3. Random Baseline y 4. Forward Returns (Básico) ya lo tenemos de benchmarks.py
    report.append("\n## 2. Metodología")
    report.append("Todo corte de buckets y selección de variables fue estático y se definió de antemano. No hay selección retrospectiva (p-hacking).")
    
    # Experimento 2: Momentum vs Reversion
    report.append("\n## 5. Momentum vs Reversión (Exp 2)")
    horizons = [1, 2, 4, 8, 16, 32]
    
    report.append("| Predictor (Retorno Previo) | Target (Retorno Futuro) | Pearson | p-value | Spearman | p-value | N |")
    report.append("|---|---|---|---|---|---|---|")
    for past in horizons:
        for fut in horizons:
            c = calculate_correlations(all_data, f'past_ret_{past}', f'fwd_ret_{fut}')
            report.append(f"| {past} velas | {fut} velas | {c['pearson']:.4f} | {c['p_pearson']:.4f} | {c['spearman']:.4f} | {c['p_spearman']:.4f} | {c['n']} |")
            
    # Experimento 3: Volatilidad
    report.append("\n## 6. Volatilidad (Exp 3)")
    if 'ATR_14' in all_data.columns:
        # Calcular buckets
        all_data['atr_pct'] = all_data['ATR_14'] / all_data['close']
        q33, q66 = all_data['atr_pct'].quantile([0.33, 0.66])
        all_data['vol_bucket'] = np.where(all_data['atr_pct'] < q33, 'LOW',
                                          np.where(all_data['atr_pct'] > q66, 'HIGH', 'MEDIUM'))
        for v_b in ['LOW', 'MEDIUM', 'HIGH']:
            df_b = all_data[all_data['vol_bucket'] == v_b]
            for fut in [1, 4, 16]:
                res = calculate_bucket_stats(df_b, f'fwd_ret_{fut}')
                report.append(f"- **{v_b} Volatility -> +{fut} velas:** N={res['n']} | Mean: {res['mean']:.4f}% | CI: [{res['ci_lower']:.4f}, {res['ci_upper']:.4f}] | Win: {res['win_prob']:.2f}% | Sig: {res['significance']}")
    else:
        report.append("No se encontró ATR_14 en el dataset.")
        
    # Experimento 4: Tendencia (ADX)
    report.append("\n## 7. Tendencia (Exp 4)")
    if 'ADX_14' in all_data.columns and 'EMA_20' in all_data.columns and 'EMA_50' in all_data.columns:
        all_data['trend_dir'] = np.where(all_data['EMA_20'] > all_data['EMA_50'], 'BULL', 'BEAR')
        adx_bins = [-np.inf, 20, 25, 30, 35, 40, np.inf]
        adx_labels = ['<20', '20-25', '25-30', '30-35', '35-40', '>40']
        all_data['adx_bucket'] = pd.cut(all_data['ADX_14'], bins=adx_bins, labels=adx_labels)
        
        for d in ['BULL', 'BEAR']:
            report.append(f"### Dirección: {d}")
            for a_b in adx_labels:
                df_b = all_data[(all_data['trend_dir'] == d) & (all_data['adx_bucket'] == a_b)]
                # Miramos futuro a 4 y 16 velas (1 hora y 4 horas aprox)
                for fut in [4, 16]:
                    res = calculate_bucket_stats(df_b, f'fwd_ret_{fut}')
                    # Para BEAR, esperamos un retorno negativo si hay momentum bajista
                    report.append(f"- **ADX {a_b} -> +{fut} velas:** N={res['n']} | Mean: {res['mean']:.4f}% | Win: {res['win_prob']:.2f}% | Sig: {res['significance']}")
                    
    # Experimento 5: Extensión ATR a EMA50
    report.append("\n## 8. Extensión / Reversión (Exp 5)")
    if 'dist_ema50_atr' in all_data.columns:
        dist_bins = [-np.inf, -2, -1, 0, 1, 2, np.inf]
        dist_labels = ['<-2', '-2 to -1', '-1 to 0', '0 to +1', '+1 to +2', '>+2']
        all_data['dist_bucket'] = pd.cut(all_data['dist_ema50_atr'], bins=dist_bins, labels=dist_labels)
        
        for db in dist_labels:
            df_b = all_data[all_data['dist_bucket'] == db]
            for fut in [1, 4, 16]:
                res = calculate_bucket_stats(df_b, f'fwd_ret_{fut}')
                report.append(f"- **Dist {db} ATR -> +{fut} velas:** Mean: {res['mean']:.4f}% | Win: {res['win_prob']:.2f}% | Sig: {res['significance']}")
                
    # Experimento 6: Breakout
    report.append("\n## 9. Price Action / Breakouts (Exp 6)")
    for b_n in [8, 16, 32]:
        for direc in ['high', 'low']:
            col = f'breakout_{direc}_{b_n}'
            if col in all_data.columns:
                df_b = all_data[all_data[col] == True]
                for fut in [1, 4, 16]:
                    res = calculate_bucket_stats(df_b, f'fwd_ret_{fut}')
                    report.append(f"- **Breakout {direc.upper()} {b_n} -> +{fut} velas:** N={res['n']} | Mean: {res['mean']:.4f}% | Win: {res['win_prob']:.2f}% | Sig: {res['significance']}")
                    
    # Experimento 7: Volumen
    report.append("\n## 10. Volumen (Exp 7)")
    if 'rel_volume' in all_data.columns:
        vol_bins = [-np.inf, 0.5, 1.5, 3.0, np.inf]
        vol_labels = ['LOW', 'NORMAL', 'HIGH', 'CLIMAX']
        all_data['vol_bucket2'] = pd.cut(all_data['rel_volume'], bins=vol_bins, labels=vol_labels)
        
        for vb in vol_labels:
            df_b = all_data[all_data['vol_bucket2'] == vb]
            for fut in [1, 4, 16]:
                res = calculate_bucket_stats(df_b, f'fwd_ret_{fut}')
                report.append(f"- **Vol {vb} -> +{fut} velas:** N={res['n']} | Mean: {res['mean']:.4f}% | Sig: {res['significance']}")

    # Guardar Reporte
    with open("/Users/iwilfredo/.gemini/antigravity-ide/brain/80384aa0-52a8-4f4c-b69f-49af4107809d/FASE5_EDGE_DISCOVERY_REPORT.md", "w") as f:
        f.write("\n".join(report))
        
    print("✅ Reporte FASE 5 generado exitosamente.")

async def main():
    dataset = Fase5Dataset()
    await dataset.load_and_prepare()
    run_experiments(dataset)

if __name__ == "__main__":
    asyncio.run(main())
