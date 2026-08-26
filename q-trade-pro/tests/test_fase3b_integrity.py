import pytest
from datetime import datetime, timedelta
import sys
import os

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from models.trade import TradeRecord

# Mock helper para Fase 3B
def split_train_val(trades, cutoff_date):
    train = [t for t in trades if t.entry_time < cutoff_date]
    val = [t for t in trades if t.entry_time >= cutoff_date]
    return train, val

def test_fase3b_data_leakage():
    """
    Verifica que la división Train/Validation no tiene solapamientos
    y que los conjuntos son independientes.
    """
    base_time = datetime(2026, 1, 1)
    
    trades = [
        TradeRecord(trade_id="1", entry_time=base_time + timedelta(days=10), net_pnl=10),
        TradeRecord(trade_id="2", entry_time=base_time + timedelta(days=50), net_pnl=-5),
        TradeRecord(trade_id="3", entry_time=base_time + timedelta(days=130), net_pnl=20),
        TradeRecord(trade_id="4", entry_time=base_time + timedelta(days=150), net_pnl=-10),
    ]
    
    cutoff = base_time + timedelta(days=120)
    train, val = split_train_val(trades, cutoff)
    
    assert len(train) == 2
    assert len(val) == 2
    
    # Comprobar que no hay leakage de fechas
    assert all(t.entry_time < cutoff for t in train)
    assert all(t.entry_time >= cutoff for t in val)
    
    # Comprobar independencia de objetos
    train_ids = {t.trade_id for t in train}
    val_ids = {t.trade_id for t in val}
    assert train_ids.isdisjoint(val_ids)

def test_fase3b_mfe_unlimited_math():
    """
    Verificar que el cálculo matemático del MFE sin límites es coherente.
    """
    # Si entramos en 100, y el max_high es 115. El ATR es 10. Riesgo = 1.5 ATR = 15.
    # El MFE debería ser 15 / 15 = 1.0 R
    entry_p = 100.0
    max_high = 115.0
    atr = 10.0
    risk_dist = atr * 1.5
    
    mfe_r = (max_high - entry_p) / risk_dist
    assert mfe_r == 1.0
    
    # Short
    min_low = 85.0
    mfe_r_short = (entry_p - min_low) / risk_dist
    assert mfe_r_short == 1.0

