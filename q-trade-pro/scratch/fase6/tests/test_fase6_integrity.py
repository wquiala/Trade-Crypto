import pytest
import pandas as pd
import numpy as np
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase6.hypotheses import Fase6Hypotheses
from scratch.fase6.metrics import Fase6Metrics

def test_no_lookahead_in_breakout():
    """
    Verifica que la condición de Fading Breakout (Hipótesis A) usa
    información estrictamente hasta T para generar señal en T.
    """
    dates = pd.date_range("2026-01-01", periods=35, freq="15min")
    
    # 32 velas con mínimos decreciendo hasta 100
    lows = np.linspace(150, 100, 32).tolist()
    closes = np.linspace(160, 110, 32).tolist()
    
    # Vela 33: Rompe el mínimo histórico de 32 (low_32 anterior era 100)
    # Su cierre es 95 (breakdown)
    lows.append(90)
    closes.append(95)
    
    # Velas extra
    lows.extend([90, 90])
    closes.extend([90, 90])
    
    df = pd.DataFrame({
        "low": lows,
        "close": closes,
        "volume": [100] * 35,
        "open": [110] * 35,
        "high": [120] * 35
    }, index=dates)
    
    # Calcular variables
    df = Fase6Hypotheses.calculate_features(df)
    
    # El mínimo en T-1 para la vela 33 (índice 32) debería ser 100
    assert df.iloc[31]['lowest_32'] == 100
    
    # Generar señal Hipótesis A
    signals = Fase6Hypotheses.generate_signals_A_fading_breakout(df)
    
    # En índice 32, Cierre=95 < Lowest32 anterior (100). Signal=1.
    assert signals.iloc[32] == 1
    
    # Los anteriores no rompen su propio rolling min desplazado.
    assert signals.iloc[31] == 0

def test_no_leakage_in_metrics():
    """
    Verifica que el cálculo de fwd_ret usa open[T+1] y close[T+N],
    eliminando el leakage intra-vela.
    """
    dates = pd.date_range("2026-01-01", periods=10, freq="15min")
    df = pd.DataFrame({
        "open":  [100, 105, 110, 100, 100, 100, 100, 100, 100, 100],
        "close": [100, 110, 115, 100, 100, 100, 100, 100, 100, 100],
        "high":  [100, 110, 120, 100, 100, 100, 100, 100, 100, 100],
        "low":   [100, 100, 105, 100, 100, 100, 100, 100, 100, 100],
    }, index=dates)
    
    # Generar una señal en T=0
    signals = pd.Series(0, index=dates)
    signals.iloc[0] = 1 # LONG
    
    # Calcular retornos a horizonte 1
    rets = Fase6Metrics.calculate_forward_returns(df, signals, horizon=1)
    
    # Para T=0, la entrada es en Open[1]=105. Salida en Close[1]=110.
    # Retorno = 110/105 - 1
    assert np.isclose(rets.iloc[0], (110 / 105) - 1.0)
    
    # Probar MAE/MFE
    mae_mfe = Fase6Metrics.calculate_mae_mfe(df, signals, horizon=1)
    # Entrada en 105. High[1]=110, Low[1]=100
    # MFE = 110/105 - 1
    # MAE = 100/105 - 1
    assert np.isclose(mae_mfe['mfe'].iloc[0], (110 / 105) - 1.0)
    assert np.isclose(mae_mfe['mae'].iloc[0], (100 / 105) - 1.0)

def test_short_mfe_mae():
    dates = pd.date_range("2026-01-01", periods=5, freq="15min")
    df = pd.DataFrame({
        "open":  [100, 100, 100, 100, 100],
        "close": [100, 100, 100, 100, 100],
        "high":  [100, 110, 100, 120, 100],
        "low":   [100, 50,  100, 90,  100],
    }, index=dates)
    
    signals = pd.Series([0]*5, index=dates)
    signals.iloc[0] = -1 # SHORT in index 0. Entry at open[1]=100.
    signals.iloc[2] = -1 # SHORT in index 2. Entry at open[3]=100.
    
    mae_mfe = Fase6Metrics.calculate_mae_mfe(df, signals, horizon=1)
    
    # 1er caso: entry=100, low=50, high=110 -> MFE = 0.50, MAE = -0.10
    assert np.isclose(mae_mfe['mfe'].iloc[0], 0.50)
    assert np.isclose(mae_mfe['mae'].iloc[0], -0.10)
    
    # 2do caso: entry=100, low=90, high=120 -> MFE = 0.10, MAE = -0.20
    assert np.isclose(mae_mfe['mfe'].iloc[1], 0.10)
    assert np.isclose(mae_mfe['mae'].iloc[1], -0.20)
