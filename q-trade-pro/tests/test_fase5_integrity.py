import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase5.dataset import Fase5Dataset

def test_forward_returns_no_lookahead():
    """
    Verifica que forward_ret_1(T) = Close(T+1) / Open(T+1) - 1
    Esto asegura que no hay look-ahead intra-vela.
    """
    dates = pd.date_range("2026-01-01", periods=10, freq="15min")
    df = pd.DataFrame({
        "open":  [100, 105, 110, 100, 100, 100, 100, 100, 100, 100],
        "high":  [100, 110, 120, 100, 100, 100, 100, 100, 100, 100],
        "low":   [100, 100, 105, 100, 100, 100, 100, 100, 100, 100],
        "close": [100, 110, 115, 100, 100, 100, 100, 100, 100, 100],
        "volume": [10] * 10
    }, index=dates)
    
    dataset = Fase5Dataset()
    dataset._calculate_forward_returns(df)
    
    # En T=0, Open[T+1]=105, Close[T+1]=110 -> Fwd1 = 110/105 - 1 = 0.0476
    assert np.isclose(df.iloc[0]['fwd_ret_1'], (110 / 105) - 1.0)
    
    # En T=0, Open[T+1]=105, Close[T+2]=115 -> Fwd2 = 115/105 - 1 = 0.0952
    assert np.isclose(df.iloc[0]['fwd_ret_2'], (115 / 105) - 1.0)
    
    # En la última fila y penúltima, los forward returns no pueden existir
    assert pd.isna(df.iloc[-1]['fwd_ret_1'])
    assert pd.isna(df.iloc[-2]['fwd_ret_2'])

def test_past_returns_no_leakage():
    """
    Verifica que past_ret_1(T) = Close(T) / Close(T-1) - 1
    """
    dates = pd.date_range("2026-01-01", periods=10, freq="15min")
    df = pd.DataFrame({
        "close": [100, 110, 115, 100, 100, 100, 100, 100, 100, 100],
    }, index=dates)
    
    dataset = Fase5Dataset()
    dataset._calculate_past_returns(df)
    
    assert pd.isna(df.iloc[0]['past_ret_1'])
    assert np.isclose(df.iloc[1]['past_ret_1'], (110 / 100) - 1.0)
    assert np.isclose(df.iloc[2]['past_ret_2'], (115 / 100) - 1.0)

def test_breakout_no_leakage():
    """
    Verifica que el breakout(T) usa máximo/mínimo estrictamente hasta T-1
    """
    dates = pd.date_range("2026-01-01", periods=10, freq="15min")
    df = pd.DataFrame({
        "close": [100, 100, 100, 110, 120, 100, 100, 100, 100, 100],
        "high":  [100, 105, 102, 105, 125, 100, 100, 100, 100, 100],
        "low":   [100, 100, 100, 100, 100, 100, 100, 100, 100, 100],
        "volume": [10] * 10
    }, index=dates)
    
    dataset = Fase5Dataset()
    # Usamos N=3 para el test rápido (inyectado a mano si fuera necesario, o simulado)
    df['breakout_high_3'] = df['close'] > df['high'].rolling(3).max().shift(1)
    
    # En idx=3 (cierre 110), los high pasados (idx 0,1,2) son [100, 105, 102]. Max=105.
    # Close(3)=110 > 105 -> Breakout=True
    assert df.iloc[3]['breakout_high_3'] == True
    
    # En idx=4 (cierre 120), los high pasados (idx 1,2,3) son [105, 102, 105]. Max=105.
    # Close(4)=120 > 105 -> Breakout=True
    assert df.iloc[4]['breakout_high_3'] == True
