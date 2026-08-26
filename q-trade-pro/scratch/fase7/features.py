import pandas as pd
import numpy as np

class Fase7Features:
    """
    Motor matemático para extraer features de régimen de mercado
    y anomalías de microestructura sin look-ahead.
    """
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift(1))
        low_close = np.abs(df['low'] - df['close'].shift(1))
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr

    @staticmethod
    def calculate_all_features(df: pd.DataFrame) -> pd.DataFrame:
        """Calcula features específicas de Fase 7"""
        df = df.copy()
        
        # A) Volatility Regime
        df['atr_14'] = Fase7Features.calculate_atr(df, 14)
        df['atr_relative'] = df['atr_14'] / df['close']
        df['atr_rel_p33'] = df['atr_relative'].rolling(30*96).quantile(0.33)
        df['atr_rel_p66'] = df['atr_relative'].rolling(30*96).quantile(0.66)
        
        # B) Retornos 24h
        df['ret_24h'] = (df['close'] / df['close'].shift(96)) - 1.0
        
        # D) Volume Anomalies (Z-Score)
        df['vol_24h_mean'] = df['volume'].rolling(96).mean()
        df['vol_24h_std'] = df['volume'].rolling(96).std()
        
        # Evitar división por cero
        vol_std = np.where(df['vol_24h_std'] == 0, 1e-9, df['vol_24h_std'])
        df['vol_z_score'] = (df['volume'] - df['vol_24h_mean']) / vol_std
        
        return df

    @staticmethod
    def add_cross_sectional_features(dfs: dict) -> dict:
        """
        Recibe un diccionario {symbol: df}.
        Añade las métricas relativas (BTC lead/lag y Cross-sectional ranking).
        """
        # Garantizar que todos los DFs tengan el mismo índice (intersección)
        common_idx = None
        for sym, df in dfs.items():
            if common_idx is None:
                common_idx = df.index
            else:
                common_idx = common_idx.intersection(df.index)
                
        # Extraer retornos de BTC si existe
        btc_key = next((k for k in dfs.keys() if 'BTC' in k), None)
        btc_ret_24h = None
        if btc_key:
            btc_ret_24h = dfs[btc_key].loc[common_idx, 'ret_24h']
            
        # Calcular retornos a 4h (16 velas) para cross-sectional ranking
        ret_4h_df = pd.DataFrame(index=common_idx)
        for sym, df in dfs.items():
            ret_4h_df[sym] = (df.loc[common_idx, 'close'] / df.loc[common_idx, 'close'].shift(16)) - 1.0
            
        # Rank: 1 (peor) a 9 (mejor)
        rank_4h_df = ret_4h_df.rank(axis=1, ascending=True)
        
        # Actualizar los DFs con las nuevas features
        updated_dfs = {}
        for sym, df in dfs.items():
            df_aligned = df.loc[common_idx].copy()
            if btc_ret_24h is not None:
                df_aligned['btc_ret_24h'] = btc_ret_24h
                df_aligned['divergence_vs_btc'] = df_aligned['ret_24h'] - df_aligned['btc_ret_24h']
                
            df_aligned['rank_4h'] = rank_4h_df[sym]
            updated_dfs[sym] = df_aligned
            
        return updated_dfs
