import asyncio
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase4.strategies.trend_momentum import TrendMomentum
from scratch.fase4.strategies.trend_pullback import TrendPullback
from scratch.fase4.strategies.price_action import PriceActionBreakout
from scratch.fase4.strategies.random_entry import RandomEntry
from scratch.fase4.engine.runner import Phase4Runner
from scratch.fase4.engine.evaluator import Evaluator

async def main():
    strategies = [
        TrendMomentum(),
        TrendPullback(),
        PriceActionBreakout(),
        RandomEntry(probability=0.01) # Approx 1% of bars
    ]
    
    runner = Phase4Runner(strategies)
    await runner.load_data()
    results = runner.run()
    
    with open("/Users/iwilfredo/.gemini/antigravity-ide/brain/80384aa0-52a8-4f4c-b69f-49af4107809d/fase4_train_informe.md", "w") as f:
        f.write("# Q-Trade Pro — FASE 4: Resultados TRAIN\n\n")
        
        for name, data in results.items():
            train_trades = data["train"]
            metrics = Evaluator.calculate_metrics(train_trades)
            
            f.write(f"## {name}\n")
            f.write(f"- Trades: {metrics['trades']}\n")
            f.write(f"- Win Rate: {metrics['win_rate']:.1f}%\n")
            f.write(f"- Expectancy: {metrics['expectancy']:.2f}R\n")
            f.write(f"- Profit Factor: {metrics['pf']:.2f}\n")
            f.write(f"- Gross PnL: ${metrics['gross_pnl']:.2f}\n")
            f.write(f"- Net PnL: ${metrics['net_pnl']:.2f}\n")
            f.write(f"- MFE: {metrics.get('mfe', 0):.2f}R\n")
            f.write(f"- MAE: {metrics.get('mae', 0):.2f}R\n\n")

if __name__ == "__main__":
    asyncio.run(main())
