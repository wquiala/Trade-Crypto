import asyncio
import pandas as pd
import numpy as np
import scipy.stats as stats
import sys
from datetime import datetime, timedelta

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase4.strategies.trend_momentum import TrendMomentum
from scratch.fase4.strategies.trend_pullback import TrendPullback
from scratch.fase4.strategies.price_action import PriceActionBreakout
from scratch.fase4.strategies.random_entry import RandomEntry
from scratch.fase4.engine.runner import Phase4Runner
from scratch.fase4.engine.evaluator import Evaluator

def calculate_significance(trades_strategy, trades_random):
    """Calcula p-value de T-Test para Expectancy"""
    if not trades_strategy or not trades_random:
        return "N/A"
        
    r_strat = [t.pnl_r for t in trades_strategy]
    r_rand = [t.pnl_r for t in trades_random]
    
    # Welch's t-test (desigual varianza)
    t_stat, p_val = stats.ttest_ind(r_strat, r_rand, equal_var=False)
    
    # Confidence interval for Expectancy (95%)
    mean_strat = np.mean(r_strat)
    se_strat = stats.sem(r_strat)
    ci_strat = stats.t.interval(0.95, len(r_strat)-1, loc=mean_strat, scale=se_strat)
    
    return {
        "p_value": p_val,
        "ci_lower": ci_strat[0],
        "ci_upper": ci_strat[1]
    }

async def main():
    print("Ejecutando simulación para reporte avanzado...")
    strategies = [
        TrendMomentum(),
        PriceActionBreakout(),
        RandomEntry(probability=0.01)
    ]
    
    runner = Phase4Runner(strategies)
    await runner.load_data()
    results = runner.run()
    
    report = []
    report.append("# Q-Trade Pro — FASE 4A: INFORME FINAL (TRAIN)")
    report.append("## 1. Confirmación de Integridad")
    report.append("- **Look-ahead / Leakage:** Verificado negativo mediante `test_fase4_integrity.py`.")
    report.append("- **Ejecución Simétrica:** Todas las estrategias usaron el mismo iterador, SL 1.5R, TP 3.0R, Slippage 0.05% y Maker/Taker 0.05%.")
    report.append("- **Dataset:** 4 meses TRAIN (sólo In-Sample). VALIDATION no se ha ejecutado.\n")
    
    random_trades = results["Random Entry"]["train"]
    
    report.append("## 2. Comparación de Estrategias vs Random")
    report.append("| Estrategia | Trades | Win Rate | Expectancy | Profit Factor | PnL |")
    report.append("|---|---|---|---|---|---|")
    
    for name, data in results.items():
        train_trades = data["train"]
        metrics = Evaluator.calculate_metrics(train_trades)
        report.append(f"| {name} | {metrics['trades']} | {metrics['win_rate']:.1f}% | {metrics['expectancy']:.2f}R | {metrics['pf']:.2f} | ${metrics['net_pnl']:.2f} |")
        
    report.append("\n## 3. Significancia Estadística de la Expectancy (95% CI)")
    for name, data in results.items():
        if name == "Random Entry": continue
        train_trades = data["train"]
        sig = calculate_significance(train_trades, random_trades)
        if sig != "N/A":
            p_val = sig["p_value"]
            significativo = "SÍ" if p_val < 0.05 else "NO"
            report.append(f"- **{name}:** 95% CI [{sig['ci_lower']:.3f}R, {sig['ci_upper']:.3f}R]. p-value contra Random: {p_val:.4f}. ¿Edge estadístico demostrado? **{significativo}**")
            
    report.append("\n## 4. Desglose Direccional (LONG vs SHORT)")
    for name, data in results.items():
        train_trades = data["train"]
        longs = [t for t in train_trades if t.signal == "LONG"]
        shorts = [t for t in train_trades if t.signal == "SHORT"]
        m_long = Evaluator.calculate_metrics(longs)
        m_short = Evaluator.calculate_metrics(shorts)
        report.append(f"### {name}")
        report.append(f"- LONG: {m_long['trades']} trades, {m_long['win_rate']:.1f}% WR, {m_long['expectancy']:.2f}R Exp.")
        report.append(f"- SHORT: {m_short['trades']} trades, {m_short['win_rate']:.1f}% WR, {m_short['expectancy']:.2f}R Exp.\n")
        
    report.append("\n## 5. Distribución por Símbolo")
    for name, data in results.items():
        train_trades = data["train"]
        syms = set(t.symbol for t in train_trades)
        report.append(f"### {name}")
        for s in syms:
            s_trades = [t for t in train_trades if t.symbol == s]
            m_s = Evaluator.calculate_metrics(s_trades)
            report.append(f"- {s}: {m_s['trades']} trades, {m_s['win_rate']:.1f}% WR, {m_s['expectancy']:.2f}R Exp.")
        report.append("")
            
    with open("/Users/iwilfredo/.gemini/antigravity-ide/brain/80384aa0-52a8-4f4c-b69f-49af4107809d/fase4a_informe_final.md", "w") as f:
        f.write("\n".join(report))
        
    print("Reporte guardado con éxito.")

if __name__ == "__main__":
    asyncio.run(main())
