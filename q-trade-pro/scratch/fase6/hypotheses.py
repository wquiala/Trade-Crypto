import pandas as pd
import numpy as np

class Fase6Hypotheses:
    """
    Motor matemático aislado para calcular señales de las hipótesis de Fase 6.
    A) FADING BREAKOUT
    B) CLIMAX / ABSORPTION
    C) COMBINED PANIC REVERSAL
    """

    @staticmethod
    def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula las variables base. 
        OJO: df ya viene ordenado por fecha. 
        NO usamos shift aquí para los predictores per se, 
        sino que durante la evaluación nos aseguramos de usar df.iloc[T]
        para tomar la decisión y medir el forward return en T+N.
        """
        # Breakout 32
        df['lowest_32'] = df['low'].rolling(32).min()
        
        # Vol climax 
        df['vol_sma_20'] = df['volume'].rolling(20).mean()
        df['vol_climax'] = np.where(df['vol_sma_20'] > 0, df['volume'] / df['vol_sma_20'], 1.0)
        
        # ADX (Asumimos que viene pre-calculado por el base backtester en df_1h y alineado por ffill, 
        # o lo volvemos a calcular aquí con ta si es necesario. Pero la Fase 5 demostró que 
        # ya venía en el dataset). Asumimos que viene en 'ADX_14' o 'ADX_14_htf'.
        
        # Bear Trend (EMA20 < EMA50). Asumimos que ya vienen en el df o las calculamos.
        # Las calculamos para estar seguros y no depender del exterior:
        df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['bear_regime'] = df['ema_20'] < df['ema_50']
        
        return df

    @staticmethod
    def generate_signals_A_fading_breakout(df: pd.DataFrame) -> pd.Series:
        """
        HIPÓTESIS A: FADING BREAKOUT BAJISTA
        - Precio rompe mínimo de 32 velas.
        Nota: Un breakdown en T significa que Close[T] < Lowest32 de [T-32 a T-1].
        """
        lowest_32_past = df['lowest_32'].shift(1)
        # Señal = 1 (LONG)
        return (df['close'] < lowest_32_past).astype(int)

    @staticmethod
    def generate_signals_B_climax_alcista(df: pd.DataFrame) -> pd.Series:
        """
        HIPÓTESIS B (BULLISH CLIMAX): 
        - vol_climax > 3.0
        - Cierre bajista en T (para buscar el rebote)
        """
        return ((df['vol_climax'] > 3.0) & (df['close'] < df['open'])).astype(int)

    @staticmethod
    def generate_signals_B_climax_bajista(df: pd.DataFrame) -> pd.Series:
        """
        HIPÓTESIS B (BEARISH CLIMAX): 
        - vol_climax > 3.0
        - Cierre alcista en T (para buscar el rechazo hacia abajo)
        """
        # Señal = -1 (SHORT)
        return ((df['vol_climax'] > 3.0) & (df['close'] > df['open'])).astype(int) * -1

    @staticmethod
    def generate_signals_C1(df: pd.DataFrame) -> pd.Series:
        """
        HIPÓTESIS C1: Breakdown 32 + Vol Climax
        """
        lowest_32_past = df['lowest_32'].shift(1)
        is_breakdown = df['close'] < lowest_32_past
        is_climax = df['vol_climax'] > 3.0
        return (is_breakdown & is_climax).astype(int)

    @staticmethod
    def generate_signals_C2(df: pd.DataFrame) -> pd.Series:
        """
        HIPÓTESIS C2: Breakdown 32 + ADX > 40 + BEAR
        Asume que df['ADX_14'] existe por la Fase 5.
        """
        lowest_32_past = df['lowest_32'].shift(1)
        is_breakdown = df['close'] < lowest_32_past
        # Si no hay ADX, devolvemos 0
        if 'ADX_14' not in df.columns:
            return pd.Series(0, index=df.index)
            
        is_adx_extreme = df['ADX_14'] > 40
        is_bear = df['bear_regime']
        return (is_breakdown & is_adx_extreme & is_bear).astype(int)

    @staticmethod
    def generate_signals_C3(df: pd.DataFrame) -> pd.Series:
        """
        HIPÓTESIS C3: Breakdown 32 + Vol Climax + ADX > 40 + BEAR
        """
        c1 = Fase6Hypotheses.generate_signals_C1(df) == 1
        c2 = Fase6Hypotheses.generate_signals_C2(df) == 1
        return (c1 & c2).astype(int)
