import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands

class FeatureEngine:
    """
    Calcula variables derivadas e indicadores técnicos utilizando la librería 'ta'
    para máximo rendimiento vectorizado.
    """
    
    @staticmethod
    def compute(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula las métricas base necesarias para el RegimeDetector y el ScoringEngine.
        Operamos sobre el DataFrame in-place o retornamos uno nuevo.
        """
        # Asegurar que los datos están ordenados
        df.sort_index(inplace=True)
        
        # 1. Indicadores de Tendencia (EMAs)
        df['EMA_20'] = EMAIndicator(close=df['close'], window=20).ema_indicator()
        df['EMA_50'] = EMAIndicator(close=df['close'], window=50).ema_indicator()
        df['EMA_200'] = EMAIndicator(close=df['close'], window=200).ema_indicator()
        
        # 2. Indicadores de Momentum (RSI, MACD)
        df['RSI_14'] = RSIIndicator(close=df['close'], window=14).rsi()
        macd = MACD(close=df['close'], window_slow=26, window_fast=12, window_sign=9)
        df['MACDh_12_26_9'] = macd.macd_diff()
        
        # 3. Volatilidad (ATR, Bollinger Bands)
        df['ATRr_14'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        bb = BollingerBands(close=df['close'], window=20, window_dev=2)
        df['BBU_20_2.0'] = bb.bollinger_hband()
        df['BBL_20_2.0'] = bb.bollinger_lband()
        
        # 4. Fuerza de la Tendencia (ADX)
        df['ADX_14'] = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14).adx()
        
        # Eliminar filas con NaN (las primeras debido al lookback de los indicadores)
        df.dropna(inplace=True)
        
        return df

    @staticmethod
    def compute_multi_timeframe(df_lower: pd.DataFrame, df_higher: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula indicadores de ambas temporalidades y los fusiona.
        """
        # Calcular features de la temporalidad superior
        df_higher_features = FeatureEngine.compute(df_higher.copy())
        
        # Calcular features de la temporalidad inferior
        df_lower_features = FeatureEngine.compute(df_lower.copy())
        
        # Fusionar (requiere que data_processor ya haya importado la lógica)
        # Esto usualmente lo orquesta el Main Loop o el Data Processor
        return df_lower_features, df_higher_features
