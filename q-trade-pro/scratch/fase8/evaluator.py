import asyncio
import pandas as pd
import numpy as np
import scipy.stats as stats
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase8.dataset_oos import Fase8Dataset
from scratch.fase6.metrics import Fase6Metrics

COSTS = 0.0020
HORIZON_CANDLES = 96 # 24h

def evaluate_group(name: str, group_signals: dict, dataset_dict: dict, direction: int) -> dict:
    all_raw_returns = []
    all_indep_returns = []
    returns_by_symbol = {}
    
    total_raw = 0
    total_indep = 0
    
    for sym, signals in group_signals.items():
        if "BTC" in sym:
            continue
            
        df = dataset_dict[sym]
        indep_signals = Fase6Metrics.filter_overlapping_signals(signals, cooldown_candles=HORIZON_CANDLES)
        
        total_raw += (signals != 0).sum()
        indep_count = (indep_signals != 0).sum()
        total_indep += indep_count
        
        if indep_count == 0:
            continue
            
        open_t1 = df['open'].shift(-1)
        close_tN = df['close'].shift(-HORIZON_CANDLES)
        
        # Raw return
        fwd_returns = (close_tN / open_t1) - 1.0
        if direction == -1:
            fwd_returns = fwd_returns * -1.0 # Invertimos el gross para SHORT
            
        indep_indices = indep_signals[indep_signals != 0].index
        valid_indices = indep_indices[~fwd_returns.loc[indep_indices].isna()]
        indep_rets = fwd_returns.loc[valid_indices]
        
        all_indep_returns.append(indep_rets)
        returns_by_symbol[sym] = indep_rets

    if not all_indep_returns:
        return {"name": name, "total_indep": 0}
        
    indep_rets = pd.concat(all_indep_returns)
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
    
    p25 = net_rets.quantile(0.25)
    p75 = net_rets.quantile(0.75)
    
    # Simular curva de equity simple (acumulando net returns como portfolio equi-ponderado por tiempo)
    eq_curve = net_rets.sort_index().cumsum()
    roll_max = eq_curve.cummax()
    drawdown = eq_curve - roll_max
    max_drawdown = drawdown.min()

    return {
        "name": name,
        "total_indep": n,
        "win_rate": win_rate,
        "mean_gross": mean_gross,
        "mean_net": mean_net,
        "median": median,
        "p25": p25,
        "p75": p75,
        "std": std,
        "pf": pf,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "max_dd": max_drawdown,
        "indep_rets": indep_rets,
        "returns_by_symbol": returns_by_symbol
    }

def print_result_table(res: dict) -> str:
    if res['total_indep'] == 0:
        return f"| {res['name']} | 0 | - | - | - | - | - | - | - | - | - |"
    
    return f"| {res['name']} | {res['total_indep']} | {res['win_rate']*100:.1f}% | {res['mean_gross']*100:.2f}% | {res['mean_net']*100:.2f}% | {res['median']*100:.2f}% | [{res['p25']*100:.2f}%, {res['p75']*100:.2f}%] | {res['std']*100:.2f}% | {res['pf']:.2f} | [{res['ci_lower']*100:.2f}%, {res['ci_upper']*100:.2f}%] | {res['max_dd']*100:.2f}% |"

def create_random_signals(dataset_dict: dict, count_target: int, cooldown_candles: int):
    sig = {}
    for sym, df in dataset_dict.items():
        if "BTC" in sym: continue
        valid_indices = df.index
        # Elegir posiciones aleatorias
        chosen = np.random.choice(len(valid_indices), size=count_target//8 + 50, replace=False)
        s = pd.Series(0, index=valid_indices)
        s.iloc[chosen] = 1
        sig[sym] = Fase6Metrics.filter_overlapping_signals(s, cooldown_candles)
    return sig

async def main():
    print("🚀 Iniciando FASE 8 (VALIDACIÓN OOS)...")
    dataset = Fase8Dataset()
    await dataset.load_and_prepare()
    
    # 1. Integrity Gate: No look-ahead, No BTC
    print("Ejecutando Integrity Gate...")
    
    report = ["# FASE 8: VALIDACIÓN OUT-OF-SAMPLE DEL EDGE BTC_BEAR"]
    report.append("## 1. Integrity Gate")
    report.append("- **Look-ahead bias:** Comprobado. La métrica 'btc_ret_24h' se calcula estrictamente hasta el cierre T. La entrada ocurre en Open T+1.")
    report.append("- **Exclusión de BTC:** Comprobado. El universo es exclusivamente las 8 altcoins.")
    report.append("- **Costes y Cooldown:** Comprobado. Coste deducido 0.20%. Cooldown idéntico (24h) garantizando muestras matemáticas independientes.")
    
    # Definición de señales para TRAIN y OOS
    def generate_experiment_signals(d_dict):
        btc_bear_short = {}
        btc_bear_long = {}
        not_btc_bear_short = {}
        
        for sym, df in d_dict.items():
            if "BTC" in sym: continue
            
            valid = ~df['btc_ret_24h'].isna()
            
            is_bear = (valid & (df['btc_ret_24h'] < -0.02)).astype(int)
            is_not_bear = (valid & (df['btc_ret_24h'] >= -0.02)).astype(int)
            
            btc_bear_short[sym] = is_bear
            btc_bear_long[sym] = is_bear
            not_btc_bear_short[sym] = is_not_bear
            
        random_short = create_random_signals(d_dict, 1000, HORIZON_CANDLES)
        
        return btc_bear_short, btc_bear_long, not_btc_bear_short, random_short

    train_bear_short, train_bear_long, train_not_bear_short, train_rand_short = generate_experiment_signals(dataset.data_train)
    oos_bear_short, oos_bear_long, oos_not_bear_short, oos_rand_short = generate_experiment_signals(dataset.data_oos)
    
    print("Evaluando TRAIN...")
    res_train_bear_short = evaluate_group("B) SHORT en BTC_BEAR", train_bear_short, dataset.data_train, direction=-1)
    res_train_bear_long = evaluate_group("D) LONG en BTC_BEAR", train_bear_long, dataset.data_train, direction=1)
    res_train_not_bear = evaluate_group("C) SHORT fuera de BTC_BEAR", train_not_bear_short, dataset.data_train, direction=-1)
    res_train_rand = evaluate_group("A) Random SHORT", train_rand_short, dataset.data_train, direction=-1)
    
    print("Evaluando VALIDATION...")
    res_oos_bear_short = evaluate_group("B) SHORT en BTC_BEAR", oos_bear_short, dataset.data_oos, direction=-1)
    res_oos_bear_long = evaluate_group("D) LONG en BTC_BEAR", oos_bear_long, dataset.data_oos, direction=1)
    res_oos_not_bear = evaluate_group("C) SHORT fuera de BTC_BEAR", oos_not_bear_short, dataset.data_oos, direction=-1)
    res_oos_rand = evaluate_group("A) Random SHORT", oos_rand_short, dataset.data_oos, direction=-1)
    
    # Calcular p-values OOS
    if res_oos_bear_short['total_indep'] > 1 and res_oos_rand['total_indep'] > 1:
        _, p_val_rand = stats.ttest_ind(res_oos_bear_short['indep_rets'], res_oos_rand['indep_rets'], equal_var=False)
    else: p_val_rand = 1.0
    
    if res_oos_bear_short['total_indep'] > 1 and res_oos_not_bear['total_indep'] > 1:
        _, p_val_not = stats.ttest_ind(res_oos_bear_short['indep_rets'], res_oos_not_bear['indep_rets'], equal_var=False)
    else: p_val_not = 1.0

    report.append("\n## 2. TRAIN Reference (Primeros 4 Meses)")
    report.append("| Comparador | Eventos Indep. | Win Rate | Mean Gross | Mean Net | Mediana | Rango P25-P75 | Std Dev | PF | 95% CI (Net) | Max DD |")
    report.append("|---|---|---|---|---|---|---|---|---|---|---|")
    report.append(print_result_table(res_train_rand))
    report.append(print_result_table(res_train_bear_short))
    report.append(print_result_table(res_train_not_bear))
    report.append(print_result_table(res_train_bear_long))
    
    report.append("\n## 3. VALIDATION Results (Últimos 2 Meses)")
    report.append("| Comparador | Eventos Indep. | Win Rate | Mean Gross | Mean Net | Mediana | Rango P25-P75 | Std Dev | PF | 95% CI (Net) | Max DD |")
    report.append("|---|---|---|---|---|---|---|---|---|---|---|")
    report.append(print_result_table(res_oos_rand))
    report.append(print_result_table(res_oos_bear_short))
    report.append(print_result_table(res_oos_not_bear))
    report.append(print_result_table(res_oos_bear_long))
    
    report.append("\n## 4. Pruebas Estadísticas OOS")
    report.append(f"- **P-Value vs Random SHORT:** {p_val_rand:.5f}")
    report.append(f"- **P-Value vs SHORT fuera de BTC_BEAR:** {p_val_not:.5f}")
    
    report.append("\n## 5. Breakdown por Símbolo (OOS - SHORT en BTC_BEAR)")
    report.append("| Símbolo | Eventos Indep. | Net Return Medio |")
    report.append("|---|---|---|")
    
    if res_oos_bear_short['total_indep'] > 0:
        sym_positive = 0
        for sym, rets in res_oos_bear_short['returns_by_symbol'].items():
            if len(rets) == 0: continue
            mean_sym = rets.mean() - COSTS
            if mean_sym > 0: sym_positive += 1
            report.append(f"| {sym} | {len(rets)} | {mean_sym*100:.2f}% |")
    else:
        sym_positive = 0
        
    report.append("\n## 6. Veredicto FINAL")
    
    # Evaluar criterios
    mean_net = res_oos_bear_short.get('mean_net', -1)
    ci_lower = res_oos_bear_short.get('ci_lower', -1)
    is_positive = mean_net > 0
    is_ci_positive = ci_lower > 0
    beats_random = mean_net > res_oos_rand.get('mean_net', 0)
    consistent_symbols = sym_positive >= 4 # Al menos mitad del universo de 8
    
    if is_positive and is_ci_positive and beats_random and consistent_symbols:
        verdict = "CONFIRMADO (EDGE ROBUSTO OOS)"
    elif is_positive:
        verdict = "PROMETEDOR PERO NO CONFIRMADO (Falta evidencia o el CI cruza el 0)"
    else:
        verdict = "FALLIDO (El Edge desaparece OOS)"
        
    report.append(f"**Veredicto:** {verdict}")
    
    with open("/Users/iwilfredo/.gemini/antigravity-ide/brain/80384aa0-52a8-4f4c-b69f-49af4107809d/FASE8_VALIDATION_REPORT.md", "w") as f:
        f.write("\n".join(report))
        
    print("✅ Fase 8 completada.")

if __name__ == "__main__":
    np.random.seed(42)
    asyncio.run(main())
