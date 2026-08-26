import pandas as pd
from typing import List, Dict, Any

class BaseStrategy:
    """
    Interfaz base para todas las estrategias independientes de la Fase 4.
    """
    def __init__(self, name: str):
        self.name = name

    def generate_signals(self, df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Recibe DataFrames crudos (pre-alineados) y devuelve una lista de señales.
        Cada señal debe tener al menos:
        - "time": datetime
        - "signal": "LONG" o "SHORT"
        - "entry_price": float
        - "atr": float (para dimensionamiento posterior)
        """
        raise NotImplementedError("Debe ser implementado por la estrategia hija.")
