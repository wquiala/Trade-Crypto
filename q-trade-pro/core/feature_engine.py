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
        n = len(df)
        if n == 0:
            return df
        
        # Para tokens recién listados con muy pocas velas (< 15)
        if n < 15:
            df['EMA_20'] = df['close']
            df['EMA_50'] = df['close']
            df['EMA_200'] = df['close']
            df['RSI_14'] = 50.0
            df['MACDh_12_26_9'] = 0.0
            hl = df['high'] - df['low']
            df['ATRr_14'] = hl.mask(hl == 0, df['close'] * 0.02)
            df['BBU_20_2.0'] = df['close'] * 1.02
            df['BBL_20_2.0'] = df['close'] * 0.98
            df['ADX_14'] = 0.0
            df['VOL_SMA_20'] = df['volume'].rolling(window=min(20, n), min_periods=1).mean()
            df['VOL_RATIO'] = df['volume'] / df['VOL_SMA_20'].replace(0, 1e-9)
            df.bfill(inplace=True)
            df.ffill(inplace=True)
            return df

        # 1. Indicadores de Tendencia (EMAs)
        df['EMA_20'] = EMAIndicator(close=df['close'], window=min(20, n - 1)).ema_indicator()
        df['EMA_50'] = EMAIndicator(close=df['close'], window=min(50, n - 1)).ema_indicator()
        if n >= 200:
            df['EMA_200'] = EMAIndicator(close=df['close'], window=200).ema_indicator()
        else:
            df['EMA_200'] = df['EMA_50']
        
        # 2. Indicadores de Momentum (RSI, MACD)
        df['RSI_14'] = RSIIndicator(close=df['close'], window=14).rsi()
        macd = MACD(close=df['close'], window_slow=min(26, n-1), window_fast=min(12, max(2, n//2)), window_sign=min(9, max(2, n//3)))
        df['MACDh_12_26_9'] = macd.macd_diff()
        
        # 3. Volatilidad (ATR, Bollinger Bands)
        df['ATRr_14'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        bb = BollingerBands(close=df['close'], window=min(20, n-1), window_dev=2)
        df['BBU_20_2.0'] = bb.bollinger_hband()
        df['BBL_20_2.0'] = bb.bollinger_lband()
        
        # 4. Fuerza de la Tendencia (ADX)
        df['ADX_14'] = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14).adx()
        
        # 5. Volumen Institucional (Media y Ratio de Participación)
        df['VOL_SMA_20'] = df['volume'].rolling(window=min(20, n), min_periods=1).mean()
        df['VOL_RATIO'] = df['volume'] / df['VOL_SMA_20'].replace(0, 1e-9)
        
        # Rellenar nulos iniciales y limpiar sin vaciar
        df.bfill(inplace=True)
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
