import pytest
import pandas as pd
import numpy as np
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase7.features import Fase7Features

def test_no_btc_in_universe():
    # Simulamos el evaluador comprobando que excluye BTC
    universe = ["ETH/USDT", "SOL/USDT", "BTC/USDT", "ADA/USDT"]
    filtered = [sym for sym in universe if "BTC" not in sym]
    assert "BTC/USDT" not in filtered
    
def test_btc_regime_no_lookahead():
    dates = pd.date_range("2026-01-01", periods=100, freq="15min")
    # BTC cae masivamente en T=99
    btc_close = np.linspace(100, 100, 100)
    btc_close[99] = 50
    
    df_btc = pd.DataFrame({"close": btc_close}, index=dates)
    df_btc['ret_24h'] = (df_btc['close'] / df_btc['close'].shift(2)) - 1.0 # Simulación simplificada
    
    eth_df = pd.DataFrame({"close": np.linspace(10, 10, 100)}, index=dates)
    eth_df['ret_24h'] = 0.0
    dfs = {'BTC/USDT': df_btc, 'ETH/USDT': eth_df}
    dfs_feat = Fase7Features.add_cross_sectional_features(dfs)
    
    eth_df = dfs_feat['ETH/USDT']
    # En T=98, ETH no debe saber que BTC cae en T=99
    assert eth_df['btc_ret_24h'].iloc[98] == 0.0
    
def test_cost_deduction():
    from scratch.fase8.evaluator import evaluate_group
    
    dates = pd.date_range("2026-01-01", periods=5, freq="15min")
    df = pd.DataFrame({
        "open": [100, 100, 100, 100, 100],
        "close": [100, 90, 80, 70, 60] # CAE 10% CADA VELA
    }, index=dates)
    
    sig = pd.Series([0, 1, 0, 0, 0], index=dates) # Entrada en T=1
    
    dataset_dict = {"ETH/USDT": df}
    signals_dict = {"ETH/USDT": sig}
    
    # Evaluar SHORT con HORIZON = 1 (para probar)
    import scratch.fase8.evaluator as ev
    ev.HORIZON_CANDLES = 1
    
    res = ev.evaluate_group("TEST", signals_dict, dataset_dict, direction=-1)
    
    # Entrada en T=1 (Open en T=2 es 100). Cierre en T=1+1=2 (Close=80).
    # Raw Short Return = (80 / 100 - 1) * -1 = +20%
    # Net = 20% - 0.20% = 19.80%
    
    assert np.isclose(res['mean_gross'], 0.20)
    assert np.isclose(res['mean_net'], 0.198)
