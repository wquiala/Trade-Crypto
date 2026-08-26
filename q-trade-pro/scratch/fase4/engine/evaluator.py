import numpy as pd
import numpy as np

class Evaluator:
    @staticmethod
    def calculate_metrics(trades):
        if not trades:
            return {"trades": 0, "win_rate": 0, "gross_pnl": 0, "net_pnl": 0, "pf": 0, "expectancy": 0}
        
        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        
        gross_pnl = sum(t.gross_pnl for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)
        
        gross_profit = sum(t.gross_pnl for t in wins)
        gross_loss = abs(sum(t.gross_pnl for t in losses))
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        r_multiples = [t.pnl_r for t in trades]
        expectancy = np.mean(r_multiples) if r_multiples else 0
        
        return {
            "trades": len(trades),
            "win_rate": len(wins) / len(trades) * 100 if trades else 0,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "pf": pf,
            "expectancy": expectancy,
            "mfe": np.mean([t.mfe for t in trades]),
            "mae": np.mean([t.mae for t in trades])
        }
