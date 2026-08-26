import pandas as pd
import numpy as np
from typing import List, Dict, Any
from .base import BaseStrategy

class RandomEntry(BaseStrategy):
    def __init__(self, probability: float = 0.01):
        super().__init__("Random Entry")
        self.probability = probability

    def generate_signals(self, df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> List[Dict[str, Any]]:
        signals = []
        # Semilla fija para reproducibilidad en la validación del test
        np.random.seed(42)
        
        for i in range(50, len(df_15m) - 1):
            if np.random.random() < self.probability:
                row = df_15m.iloc[i]
                signal = "LONG" if np.random.random() < 0.5 else "SHORT"
                
                signals.append({
                    "time": row.name,
                    "signal": signal,
                    "entry_price": df_15m.iloc[i+1]['open'],
                    "atr": row.get("ATR_14", row['close'] * 0.01),
                    "features": row.to_dict()
                })
                
        return signals
