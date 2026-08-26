import pandas as pd
import numpy as np
import sys
from datetime import timedelta

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from backtest.backtester import Backtester
from config.config import BacktestConfig

class Fase5Dataset:
    def __init__(self):
        # Limitado estrictamente a 4 meses de TRAIN por consistencia con Fase 4
        self.bt_cfg = BacktestConfig(backtest_months=4)
        self.base_bt = Backtester(backtest_cfg=self.bt_cfg)
        self.data = {}
        
    async def load_and_prepare(self):
        print("📥 Descargando datos TRAIN (4 meses)...")
        raw_data = await self.base_bt.download()
        
        for sym, raw in raw_data.items():
            df_15m, df_1h = self.base_bt._prepare_symbol_data(raw)
            if df_15m is not None and df_1h is not None:
                # Alineamos HTF (que usa ffill y asegura no-lookahead)
                df_aligned = self.base_bt._align_htf(df_15m, df_1h)
                
                # Cortamos estrictamente el dataset a la fecha de TRAIN para evitar contaminación
                start_date = df_aligned.index.min()
                cutoff_date = start_date + timedelta(days=120)
                df_train = df_aligned[df_aligned.index < cutoff_date].copy()
                
                # Calculamos Forward Returns de forma segura
                self._calculate_forward_returns(df_train)
                # Calculamos Past Returns
                self._calculate_past_returns(df_train)
                # Calculamos otros indicadores (Volumen relativo, Donchian, etc)
                self._calculate_features(df_train)
                
                self.data[sym] = df_train
        print(f"✅ Datos preparados y saneados para {len(self.data)} símbolos.")

    def _calculate_forward_returns(self, df: pd.DataFrame):
        """
        Calcula retornos futuros asumiendo ejecución en OPEN[T+1] (next_open).
        Para un horizonte N, el retorno es Close[T+N] / Open[T+1] - 1.
        Esto elimina el 100% del look-ahead bias intra-vela.
        """
        horizons = [1, 2, 4, 8, 16, 32, 48]
        
        for n in horizons:
            # Shift negativo mueve los valores futuros al presente.
            # Close futuro (en T+N)
            future_close = df['close'].shift(-n)
            # Open ejecución (en T+1)
            next_open = df['open'].shift(-1)
            
            # El forward return para LONG
            df[f'fwd_ret_{n}'] = (future_close / next_open) - 1.0
            
    def _calculate_past_returns(self, df: pd.DataFrame):
        """
        Calcula retornos pasados estrictamente hasta T.
        Retorno de N velas hacia atrás = Close[T] / Close[T-N] - 1
        """
        horizons = [1, 2, 4, 8, 16, 32]
        for n in horizons:
            past_close = df['close'].shift(n)
            df[f'past_ret_{n}'] = (df['close'] / past_close) - 1.0
            
    def _calculate_features(self, df: pd.DataFrame):
        """
        Calcula las variables independientes de los Buckets.
        """
        # Volumen Relativo (SMA 20 del volumen pasado, para usar en T hay que hacer shift(1) 
        # del promedio o usar la ventana excluyendo T? 
        # Si cerramos en T, ya conocemos el volumen de T. Entonces SMA(20) que incluye T es válido.
        df['vol_sma_20'] = df['volume'].rolling(20).mean()
        df['rel_volume'] = np.where(df['vol_sma_20'] > 0, df['volume'] / df['vol_sma_20'], 1.0)
        
        # Distancia a EMA50 en múltiplos de ATR
        if 'EMA_50' in df.columns and 'ATR_14' in df.columns:
            df['dist_ema50_atr'] = (df['close'] - df['EMA_50']) / df['ATR_14']
            
        # Breakouts de N periodos (Shift(1) para comparar Close[T] con High[T-1..T-N])
        for n in [8, 16, 32]:
            highest_past = df['high'].rolling(n).max().shift(1)
            lowest_past = df['low'].rolling(n).min().shift(1)
            df[f'breakout_high_{n}'] = df['close'] > highest_past
            df[f'breakout_low_{n}'] = df['close'] < lowest_past

