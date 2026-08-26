import pandas as pd
import numpy as np
import sys
from datetime import timedelta

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from backtest.backtester import Backtester
from config.config import BacktestConfig
from scratch.fase7.features import Fase7Features

class Fase8Dataset:
    def __init__(self):
        # 6 meses en total: 4 meses de TRAIN + 2 meses OOS
        self.bt_cfg = BacktestConfig(backtest_months=6)
        self.base_bt = Backtester(backtest_cfg=self.bt_cfg)
        self.data_train = {}
        self.data_oos = {}
        
    async def load_and_prepare(self):
        print("📥 Descargando datos TRAIN y OOS (6 meses totales)...")
        raw_data = await self.base_bt.download()
        
        for sym, raw in raw_data.items():
            df_15m, df_1h = self.base_bt._prepare_symbol_data(raw)
            if df_15m is not None and df_1h is not None:
                # Alineamos HTF (sin lookahead)
                df_aligned = self.base_bt._align_htf(df_15m, df_1h)
                
                start_date = df_aligned.index.min()
                # TRAIN: del mes 0 al mes 4 (120 días)
                cutoff_train = start_date + timedelta(days=120)
                
                # OOS: del mes 4 al final
                df_train = df_aligned[df_aligned.index < cutoff_train].copy()
                df_oos = df_aligned[df_aligned.index >= cutoff_train].copy()
                
                # OOS debe ser de al menos 30 dias para ser valido
                if len(df_oos) > (30 * 96):
                    self.data_train[sym] = df_train
                    self.data_oos[sym] = df_oos
                    
        # Calcular variables relativas
        print(f"✅ Datos separados: TRAIN ({len(self.data_train)} símbolos), OOS ({len(self.data_oos)} símbolos).")
        
        # Calcular features (incluye BTC)
        for d in [self.data_train, self.data_oos]:
            for sym, df in d.items():
                d[sym] = Fase7Features.calculate_all_features(df)
            
            # Esto alineará los diccionarios y agregará btc_ret_24h
            aligned = Fase7Features.add_cross_sectional_features(d)
            d.clear()
            d.update(aligned)
