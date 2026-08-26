"""
core/feature_engine.py
======================
Cálculo de indicadores técnicos para el motor de señales de Q-Trade Pro.

Warmup mínimo
─────────────
EMA_200 necesita al menos 200 velas para estabilizarse.
Se recomienda descargar MIN_CANDLES_REQUIRED = 210 velas antes de operar.
Cualquier resultado con menos velas es estadísticamente no fiable.

Bollinger Bands
───────────────
Las Bollinger Bands NO se calculan en compute() porque la estrategia
no opera en régimen RANGING. Están disponibles en compute_ranging_features()
para uso futuro cuando se habilite la estrategia de mean-reversion.
"""

import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands

# Mínimo de velas requeridas para que los indicadores sean estadísticamente válidos.
# EMA_200 necesita 200 velas + margen de estabilización.
MIN_CANDLES_REQUIRED = 210


class FeatureEngine:
    """
    Calcula variables derivadas e indicadores técnicos utilizando la librería 'ta'
    para máximo rendimiento vectorizado.

    Métodos:
    ─────────
    - compute(): features base para BULL_TREND / BEAR_TREND (sin BB).
    - compute_ranging_features(): Bollinger Bands para uso futuro en RANGING.
    - compute_multi_timeframe(): wrapper legacy, mantener para compatibilidad.
    """

    @staticmethod
    def compute(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula las features necesarias para RegimeDetector y ScoringEngine.

        Features calculadas:
            EMA_20, EMA_50, EMA_200   — Estructura de tendencia
            RSI_14                    — Momentum (oscilador)
            MACDh_12_26_9             — Momentum (histograma)
            ATRr_14                   — Volatilidad absoluta
            ADX_14                    — Fuerza de la tendencia

        NO incluye Bollinger Bands — la estrategia no opera en RANGING.
        Usar compute_ranging_features() para añadirlas si se necesitan.

        Args:
            df: DataFrame OHLCV indexado por timestamp. Mínimo MIN_CANDLES_REQUIRED filas.

        Returns:
            df con columnas de indicadores añadidas. Las primeras filas con NaN
            (periodo de warmup) son eliminadas con dropna().
        """
        # Asegurar que los datos están ordenados
        df = df.sort_index()

        # 1. Estructura de tendencia (EMAs)
        df['EMA_20']  = EMAIndicator(close=df['close'], window=20).ema_indicator()
        df['EMA_50']  = EMAIndicator(close=df['close'], window=50).ema_indicator()
        df['EMA_200'] = EMAIndicator(close=df['close'], window=200).ema_indicator()

        # 2. Momentum: RSI y MACD
        df['RSI_14'] = RSIIndicator(close=df['close'], window=14).rsi()
        macd = MACD(close=df['close'], window_slow=26, window_fast=12, window_sign=9)
        df['MACDh_12_26_9'] = macd.macd_diff()

        # 3. Volatilidad: ATR (sin BB — no se usa en la estrategia actual)
        df['ATRr_14'] = AverageTrueRange(
            high=df['high'], low=df['low'], close=df['close'], window=14
        ).average_true_range()

        # 4. Fuerza de la tendencia: ADX
        df['ADX_14'] = ADXIndicator(
            high=df['high'], low=df['low'], close=df['close'], window=14
        ).adx()

        # Eliminar filas del periodo de warmup (NaN por lookback de indicadores)
        df.dropna(inplace=True)

        return df

    @staticmethod
    def compute_ranging_features(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula Bollinger Bands para estrategias de mean-reversion en régimen RANGING.

        ESTADO ACTUAL: DESHABILITADO.
        El backtest demostró que la estrategia de mean-reversion en Bollinger Bands
        pierde dinero de forma consistente en crypto (16/22 operaciones perdedoras).
        Solo se mantiene este método como preparación para refinamientos futuros.

        Llamar ÚNICAMENTE si:
            1. El régimen detectado es RANGING.
            2. La estrategia de RANGING ha sido validada out-of-sample.

        Args:
            df: DataFrame ya procesado por compute() (sin BB).

        Returns:
            df con columnas BBU_20_2.0 y BBL_20_2.0 añadidas.
        """
        bb = BollingerBands(close=df['close'], window=20, window_dev=2)
        df['BBU_20_2.0'] = bb.bollinger_hband()
        df['BBL_20_2.0'] = bb.bollinger_lband()
        return df

    @staticmethod
    def compute_multi_timeframe(
        df_lower: pd.DataFrame,
        df_higher: pd.DataFrame,
    ) -> tuple:
        """
        Wrapper de compatibilidad: calcula features en ambas temporalidades.

        NOTA: Este método NO alinea HTF/LTF sin look-ahead bias.
              Para backtest o análisis serio, usar:
              MarketDataFetcher.align_htf_to_ltf() de data_processor.py.

        Returns:
            (df_lower_features, df_higher_features)
        """
        df_higher_features = FeatureEngine.compute(df_higher.copy())
        df_lower_features  = FeatureEngine.compute(df_lower.copy())
        return df_lower_features, df_higher_features
