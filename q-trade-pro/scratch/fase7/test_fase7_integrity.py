import pytest
import pandas as pd
import numpy as np
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase7.features import Fase7Features
from scratch.fase7.experiments import Fase7Experiments

def test_no_lookahead_in_volatility():
    """
    Verifica que la medición del ATR no incluya volatilidad de T+1
    y que los percentiles de 30 días no miren al futuro.
    """
    dates = pd.date_range("2026-01-01", periods=100, freq="15min")
    # Precio sube paulatinamente
    closes = np.linspace(100, 150, 100)
    highs = closes + 1
    lows = closes - 1
    
    # En T=99 hay un spike masivo pero SOLO en T=99
    highs[99] = 300
    
    df = pd.DataFrame({
        "open": closes,
        "close": closes,
        "high": highs,
        "low": lows,
        "volume": [100] * 100
    }, index=dates)
    
    df_feat = Fase7Features.calculate_all_features(df)
    
    # El ATR relativo de T=98 no debe verse afectado por el spike en T=99
    assert df_feat['atr_relative'].iloc[98] < df_feat['atr_relative'].iloc[99]
    # En T=98, el high fue 149+1=150.
    
def test_cross_sectional_alignment():
    """
    Verifica que el ranking cross-sectional se calcule estrictamente
    usando información hasta T para todos los símbolos.
    """
    dates = pd.date_range("2026-01-01", periods=20, freq="15min")
    
    df1 = pd.DataFrame({"close": np.linspace(100, 120, 20)}, index=dates) # Sube 20%
    df2 = pd.DataFrame({"close": np.linspace(100, 150, 20)}, index=dates) # Sube 50%
    df3 = pd.DataFrame({"close": np.linspace(100, 90, 20)}, index=dates)  # Baja 10%
    
    dfs = {'SYM1': df1, 'SYM2': df2, 'SYM3': df3}
    dfs_feat = Fase7Features.add_cross_sectional_features(dfs)
    
    # En T=19 (última vela), el ret_4h de SYM2 debe ser el mejor (rank=3), SYM3 el peor (rank=1)
    assert dfs_feat['SYM2']['rank_4h'].iloc[-1] == 3.0
    assert dfs_feat['SYM3']['rank_4h'].iloc[-1] == 1.0
    
def test_liquidity_zscore_no_leakage():
    """
    Verifica que el Z-Score de volumen no contenga data futura.
    """
    dates = pd.date_range("2026-01-01", periods=100, freq="15min")
    vol = np.ones(100) * 10
    vol[99] = 1000 # Spike en T=99
    
    df = pd.DataFrame({
        "open": [10]*100, "close": [10]*100, "high": [10]*100, "low": [10]*100,
        "volume": vol
    }, index=dates)
    
    df_feat = Fase7Features.calculate_all_features(df)
    
    # Media movil en T=98 no debe verse afectada por el spike en T=99
    assert df_feat['vol_24h_mean'].iloc[98] == 10.0
    
def test_buckets_generation():
    """
    Verifica que los buckets devuelvan un 0 o 1 estricto y no haya superposición
    entre clases mutuamente excluyentes (ej. VOL_LOW y VOL_HIGH).
    """
    dates = pd.date_range("2026-01-01", periods=50, freq="15min")
    df = pd.DataFrame({
        "atr_relative": np.random.rand(50),
        "atr_rel_p33": [0.33] * 50,
        "atr_rel_p66": [0.66] * 50
    }, index=dates)
    
    buckets = Fase7Experiments.get_volatility_regime_buckets(df)
    
    # No puede ser LOW y HIGH al mismo tiempo
    overlap = (buckets['VOL_LOW'] == 1) & (buckets['VOL_HIGH'] == 1)
    assert not overlap.any()
