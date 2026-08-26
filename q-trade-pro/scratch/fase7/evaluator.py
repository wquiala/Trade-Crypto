import asyncio
import pandas as pd
import numpy as np
import scipy.stats as stats
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase5.dataset import Fase5Dataset
from scratch.fase7.features import Fase7Features
from scratch.fase7.experiments import Fase7Experiments
from scratch.fase6.metrics import Fase6Metrics

COSTS = 0.0020
HORIZONS = {
    "1h": 4,
    "4h": 16,
    "8h": 32,
    "12h": 48,
    "24h": 96
}

def analyze_bucket(bucket_name: str, signals_dict: dict, dataset_dict: dict, horizon_name: str, horizon_candles: int, report: list, pval_threshold: float = 0.00083):
    """
    Evalúa estadísticamente un bucket específico.
    """
    all_raw_returns = []
    all_indep_returns = []
    all_benchmark_returns = []
    
    total_raw = 0
    total_indep = 0
    
    returns_by_symbol = {}
    returns_train_a = []
    returns_train_b = []
    
    for sym, signals in signals_dict.items():
        df = dataset_dict[sym]
        
        # Filtramos overlap con cooldown = horizon
        indep_signals = Fase6Metrics.filter_overlapping_signals(signals, cooldown_candles=horizon_candles)
        
        raw_count = (signals == 1).sum()
        indep_count = (indep_signals == 1).sum()
        
        total_raw += raw_count
        total_indep += indep_count
        
        if indep_count == 0:
            continue
            
        # Calcular retornos forward
        # (Close_{T+N} / Open_{T+1}) - 1
        open_t1 = df['open'].shift(-1)
        close_tN = df['close'].shift(-horizon_candles)
        fwd_returns = (close_tN / open_t1) - 1.0
        
        # Extraer retornos de los eventos independientes
        indep_indices = indep_signals[indep_signals == 1].index
        valid_indep_indices = indep_indices[~fwd_returns.loc[indep_indices].isna()]
        indep_rets = fwd_returns.loc[valid_indep_indices]
        
        all_indep_returns.append(indep_rets)
        returns_by_symbol[sym] = indep_rets
        
        # Train A y Train B (Aprox mitad del tiempo)
        mid_point = df.index[len(df) // 2]
        returns_train_a.append(indep_rets[indep_rets.index < mid_point])
        returns_train_b.append(indep_rets[indep_rets.index >= mid_point])
        
        # Generar benchmark (todas las velas válidas filtradas por el mismo cooldown)
        # Para ser justos, tomamos una muestra aleatoria de tamaño indep_count
        # usando muestreo independiente
        all_possible_signals = pd.Series(1, index=df.index)
        all_indep_possible = Fase6Metrics.filter_overlapping_signals(all_possible_signals, cooldown_candles=horizon_candles)
        all_possible_indices = all_indep_possible[all_indep_possible == 1].index
        valid_possible_indices = all_possible_indices[~fwd_returns.loc[all_possible_indices].isna()]
        
        if len(valid_possible_indices) > 0:
            sampled_benchmark = fwd_returns.loc[np.random.choice(valid_possible_indices, min(len(valid_possible_indices), len(valid_indep_indices)), replace=False)]
            all_benchmark_returns.append(sampled_benchmark)

    if total_indep < 30:
        # report.append(f"| {bucket_name} | {horizon_name} | {total_raw} | {total_indep} | - | INSUFFICIENT DATA |")
        return

    # Consolidar
    indep_rets = pd.concat(all_indep_returns)
    bench_rets = pd.concat(all_benchmark_returns) if all_benchmark_returns else pd.Series(dtype=float)
    
    net_rets = indep_rets - COSTS
    mean_gross = indep_rets.mean()
    mean_net = net_rets.mean()
    median = net_rets.median()
    std = net_rets.std()
    
    win_rate = (net_rets > 0).mean()
    gains = net_rets[net_rets > 0].sum()
    losses = abs(net_rets[net_rets < 0].sum())
    pf = (gains / losses) if losses != 0 else float('inf')
    
    n = len(net_rets)
    se = std / np.sqrt(n) if n > 0 else 0
    ci_lower, ci_upper = stats.t.interval(0.95, n-1, loc=mean_net, scale=se) if n > 1 and std > 0 else (mean_net, mean_net)
    
    # P-Value vs Benchmark
    if len(bench_rets) > 1 and len(indep_rets) > 1:
        # Welch's t-test
        t_stat, p_val = stats.ttest_ind(indep_rets, bench_rets, equal_var=False)
    else:
        p_val = 1.0
        
    # Check robustez temporal
    rets_a = pd.concat(returns_train_a) - COSTS if returns_train_a else pd.Series(dtype=float)
    rets_b = pd.concat(returns_train_b) - COSTS if returns_train_b else pd.Series(dtype=float)
    mean_a = rets_a.mean() if not rets_a.empty else 0
    mean_b = rets_b.mean() if not rets_b.empty else 0
    
    time_robust = (mean_a > 0 and mean_b > 0) or (mean_a < 0 and mean_b < 0)
    
    # Check robustez por simbolo (cuantos contribuyen en la misma direccion)
    sym_positive = sum(1 for rets in returns_by_symbol.values() if (rets - COSTS).mean() > 0)
    sym_total = len(returns_by_symbol)
    sym_robust = sym_positive >= 5 if mean_net > 0 else (sym_total - sym_positive) >= 5
    
    # Veredicto
    verdict = "NEGATIVE"
    if mean_net > 0:
        if ci_lower > 0 and p_val <= pval_threshold:
            if time_robust and sym_robust:
                verdict = "ROBUST CANDIDATE"
            else:
                verdict = "STATISTICALLY POSITIVE"
        else:
            verdict = "POSITIVE BUT WEAK"
            
    # Solo reportamos si es interesante o para dejar constancia
    ci_str = f"[{ci_lower*100:.2f}%, {ci_upper*100:.2f}%]"
    pval_str = f"{p_val:.5f}{'**' if p_val <= pval_threshold else ''}"
    
    report.append(f"| {bucket_name} | {horizon_name} | {total_raw} | {n} | {mean_gross*100:.2f}% | {mean_net*100:.2f}% | {median*100:.2f}% | {win_rate*100:.1f}% | {pf:.2f} | {ci_str} | {pval_str} | {verdict} |")

async def main():
    print("🚀 Iniciando FASE 7 (Market Regime / Microstructure Edge Discovery)...")
    dataset = Fase5Dataset()
    await dataset.load_and_prepare()
    
    # Feature extraction
    print("Calculando features...")
    dataset_dict = {}
    for sym, df in dataset.data.items():
        dataset_dict[sym] = Fase7Features.calculate_all_features(df)
        
    dataset_dict = Fase7Features.add_cross_sectional_features(dataset_dict)
    
    report = ["# FASE 7: REPORTE DE DESCUBRIMIENTO (EDGE DISCOVERY)"]
    report.append("El siguiente informe detalla el rendimiento estadístico puro (Long) de los activos cuando se encuentran en los regímenes especificados. Los umbrales estadísticos exigen p-value <= 0.00083 (Bonferroni) para ser significativos.")
    
    report.append("\n## Resultados Generales")
    report.append("| Bucket | Horizonte | RAW | INDEP | Mean Gross | Mean Net | Mediana | Win Rate | PF | CI 95% | P-Value vs Rand | Veredicto |")
    report.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    
    print("Generando buckets y evaluando...")
    # Por horizonte y bucket
    for horizon_name, horizon_candles in HORIZONS.items():
        # Extraer señales por bucket
        buckets_signals = {}
        for sym, df in dataset_dict.items():
            b = Fase7Experiments.get_all_buckets(df)
            for b_name, sig in b.items():
                if b_name not in buckets_signals:
                    buckets_signals[b_name] = {}
                buckets_signals[b_name][sym] = sig
                
        # Evaluar cada bucket
        for b_name, sig_dict in buckets_signals.items():
            analyze_bucket(b_name, sig_dict, dataset_dict, horizon_name, horizon_candles, report)
            
    with open("/Users/iwilfredo/.gemini/antigravity-ide/brain/80384aa0-52a8-4f4c-b69f-49af4107809d/FASE7_REPORT.md", "w") as f:
        f.write("\n".join(report))
        
    print("✅ Fase 7 completada.")

if __name__ == "__main__":
    np.random.seed(42)
    asyncio.run(main())
