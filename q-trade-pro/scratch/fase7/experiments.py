import pandas as pd
import numpy as np

class Fase7Experiments:
    """
    Clasifica las velas en buckets según el plan de Fase 7.
    Devuelve diccionarios de pd.Series (1 donde la vela pertenece al bucket, 0 donde no).
    """
    
    @staticmethod
    def get_volatility_regime_buckets(df: pd.DataFrame) -> dict:
        b = {}
        # Ignoramos donde no hay datos suficientes (NaN)
        valid = ~df['atr_rel_p33'].isna()
        
        b['VOL_LOW'] = (valid & (df['atr_relative'] <= df['atr_rel_p33'])).astype(int)
        b['VOL_MEDIUM'] = (valid & (df['atr_relative'] > df['atr_rel_p33']) & (df['atr_relative'] <= df['atr_rel_p66'])).astype(int)
        b['VOL_HIGH'] = (valid & (df['atr_relative'] > df['atr_rel_p66'])).astype(int)
        return b

    @staticmethod
    def get_market_regime_buckets(df: pd.DataFrame) -> dict:
        b = {}
        if 'btc_ret_24h' not in df.columns:
            return b
            
        valid = ~df['btc_ret_24h'].isna()
        
        # BTC State
        b['BTC_BEAR'] = (valid & (df['btc_ret_24h'] < -0.02)).astype(int)
        b['BTC_NEUTRAL'] = (valid & (df['btc_ret_24h'] >= -0.02) & (df['btc_ret_24h'] <= 0.02)).astype(int)
        b['BTC_BULL'] = (valid & (df['btc_ret_24h'] > 0.02)).astype(int)
        
        # Divergence
        b['SYM_WEAKER_THAN_BTC'] = (valid & (df['ret_24h'] < df['btc_ret_24h'])).astype(int)
        b['SYM_STRONGER_THAN_BTC'] = (valid & (df['ret_24h'] > df['btc_ret_24h'])).astype(int)
        
        return b

    @staticmethod
    def get_cross_sectional_buckets(df: pd.DataFrame) -> dict:
        b = {}
        if 'rank_4h' not in df.columns:
            return b
            
        valid = ~df['rank_4h'].isna()
        
        b['RANK_LAGGARD'] = (valid & (df['rank_4h'] <= 2)).astype(int)
        b['RANK_AVERAGE'] = (valid & (df['rank_4h'] > 2) & (df['rank_4h'] < 8)).astype(int)
        b['RANK_LEADER'] = (valid & (df['rank_4h'] >= 8)).astype(int)
        
        return b

    @staticmethod
    def get_liquidity_anomalies_buckets(df: pd.DataFrame) -> dict:
        b = {}
        valid = ~df['vol_z_score'].isna()
        
        b['VOL_Z_NORMAL'] = (valid & (df['vol_z_score'] < 2.0)).astype(int)
        b['VOL_Z_HIGH'] = (valid & (df['vol_z_score'] >= 2.0) & (df['vol_z_score'] <= 4.0)).astype(int)
        b['VOL_Z_EXTREME'] = (valid & (df['vol_z_score'] > 4.0)).astype(int)
        
        return b
        
    @staticmethod
    def get_all_buckets(df: pd.DataFrame) -> dict:
        buckets = {}
        buckets.update(Fase7Experiments.get_volatility_regime_buckets(df))
        buckets.update(Fase7Experiments.get_market_regime_buckets(df))
        buckets.update(Fase7Experiments.get_cross_sectional_buckets(df))
        buckets.update(Fase7Experiments.get_liquidity_anomalies_buckets(df))
        return buckets
