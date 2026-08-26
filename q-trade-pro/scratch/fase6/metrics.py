import numpy as np
import pandas as pd
from typing import Dict, Any
import scipy.stats as stats

class Fase6Metrics:
    """
    Motor matemático aislado para calcular métricas estrictas de Fase 6.
    """
    
    @staticmethod
    def calculate_forward_returns(df: pd.DataFrame, signal_series: pd.Series, horizon: int) -> pd.Series:
        """
        Calcula el retorno de ejecución next_open a N velas.
        Signal en T -> Ejecuta en Open de T+1 -> Cierra en Close de T+horizon.
        """
        if horizon <= 0: return pd.Series(index=df.index, dtype=float)
        
        # Filtramos solo donde hay señal activa
        mask = signal_series != 0
        if not mask.any():
            return pd.Series(index=df.index, dtype=float)
            
        next_open = df['open'].shift(-1)
        future_close = df['close'].shift(-horizon)
        
        # Rendimiento natural (LONG)
        fwd_ret = (future_close / next_open) - 1.0
        
        # Aplicar dirección de la señal (1 = LONG, -1 = SHORT)
        fwd_ret = fwd_ret * signal_series
        
        # Devolver solo para las filas con señal
        return fwd_ret[mask]
        
    @staticmethod
    def calculate_mae_mfe(df: pd.DataFrame, signal_series: pd.Series, horizon: int) -> Dict[str, pd.Series]:
        """
        Calcula MAE y MFE en un horizonte dado sin stops.
        MFE = Maximum Favorable Excursion (Mayor pico a favor)
        MAE = Maximum Adverse Excursion (Peor valle en contra)
        """
        mask = signal_series != 0
        if not mask.any():
            return {"mfe": pd.Series(dtype=float), "mae": pd.Series(dtype=float)}
            
        mfe_list = []
        mae_list = []
        indices = df.index[mask]
        
        for idx in indices:
            row_num = df.index.get_loc(idx)
            # Ejecuta en T+1, cierra en T+horizon
            start_row = row_num + 1
            end_row = row_num + horizon
            
            if end_row >= len(df):
                mfe_list.append(np.nan)
                mae_list.append(np.nan)
                continue
                
            entry_price = df.iloc[start_row]['open']
            direction = signal_series.loc[idx]
            
            # Sub-dataframe de toda la vida de la operación
            window = df.iloc[start_row:end_row + 1]
            highest = window['high'].max()
            lowest = window['low'].min()
            
            if direction == 1:
                mfe = (highest / entry_price) - 1.0
                mae = (lowest / entry_price) - 1.0
            else:
                mfe = (entry_price - lowest) / entry_price
                mae = (entry_price - highest) / entry_price
                
            mfe_list.append(mfe)
            mae_list.append(mae)
            
        return {
            "mfe": pd.Series(mfe_list, index=indices),
            "mae": pd.Series(mae_list, index=indices)
        }

    @staticmethod
    def get_distribution_stats(returns: pd.Series, costs: float = 0.0) -> Dict[str, Any]:
        """
        Obtiene las métricas solicitadas en Fase 6 para un conjunto de retornos, incluyendo CI.
        """
        if returns.empty or returns.isna().all():
            return {"count": 0}
            
        net_returns = returns - costs
        n = len(net_returns.dropna())
        
        if n == 0:
            return {"count": 0}
            
        mean = net_returns.mean()
        std = net_returns.std()
        
        if n < 30 or pd.isna(std) or std == 0:
            ci_lower, ci_upper = mean, mean
        else:
            se = std / np.sqrt(n)
            ci_lower, ci_upper = stats.t.interval(0.95, n-1, loc=mean, scale=se)
        
        return {
            "count": n,
            "mean": mean,
            "median": net_returns.median(),
            "win_prob": (net_returns > 0).mean(),
            "p25": net_returns.quantile(0.25),
            "p75": net_returns.quantile(0.75),
            "std": std,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper
        }

    @staticmethod
    def filter_overlapping_signals(signal_series: pd.Series, cooldown_candles: int) -> pd.Series:
        """
        Dada una serie temporal de señales para un ÚNICO símbolo, 
        elimina cualquier señal que ocurra dentro de las 'cooldown_candles' velas
        posteriores a una señal aceptada (evento independiente).
        """
        if cooldown_candles <= 0:
            return signal_series.copy()
            
        filtered = pd.Series(0, index=signal_series.index)
        last_signal_idx = -999999
        
        # Encontramos los índices numéricos de las señales activas
        active_indices = np.where(signal_series != 0)[0]
        
        for idx in active_indices:
            if idx >= last_signal_idx + cooldown_candles:
                filtered.iloc[idx] = signal_series.iloc[idx]
                last_signal_idx = idx
                
        return filtered
