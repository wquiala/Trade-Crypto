"""
core/data_processor.py
======================
Normalización de datos OHLCV y alineación multi-timeframe (MTF) sin look-ahead bias.

REGLA FUNDAMENTAL — MTF sin look-ahead bias
============================================
Una vela HTF con open_time=T y duración D minutos:
    - open_time  = T
    - close_time = T + D minutos

Esta vela SOLO puede aportar información al LTF cuando:
    ltf_candle_open_time >= htf_close_time

Es decir: si la vela HTF de 10:00-11:00 cierra a las 11:00,
ninguna vela LTF con timestamp < 11:00 puede verla.

Vela LTF 10:15 → NO puede ver la vela HTF 10:00-11:00.
Vela LTF 10:45 → NO puede ver la vela HTF 10:00-11:00.
Vela LTF 11:00 → SÍ puede ver la vela HTF 10:00-11:00 (ya cerró).
Vela LTF 11:15 → SÍ puede ver la vela HTF 10:00-11:00.

Implementación
──────────────
1. Calcular close_time de cada vela HTF: index + pd.Timedelta(minutes=htf_duration).
2. Re-indexar el DataFrame HTF por close_time.
3. merge_asof(direction='backward') sobre el LTF, usando el close_time como clave.

Esto garantiza que el merge_asof solo encuentra velas HTF cuyo close_time <= ltf_timestamp.
"""

from __future__ import annotations

import pandas as pd
from typing import List, Dict


class MarketDataFetcher:
    """
    Normalización de datos OHLCV crudos de CCXT.
    """

    @staticmethod
    def normalize_klines(raw_data: List[List]) -> pd.DataFrame:
        """
        Convierte la respuesta OHLCV cruda de ccxt a un DataFrame de pandas.

        El timestamp devuelto por ccxt representa el open_time de la vela.
        IMPORTANTE: no es el close_time.

        Args:
            raw_data: Lista de listas [timestamp_ms, open, high, low, close, volume]

        Returns:
            DataFrame indexado por open_time (UTC, timezone-aware).
        """
        if not raw_data:
            return pd.DataFrame()

        df = pd.DataFrame(
            raw_data,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

        # Convertir timestamp a datetime UTC
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)

        # Garantizar orden cronológico
        df.sort_index(inplace=True)

        # Convertir a float
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # Eliminar duplicados de timestamp (pueden ocurrir en algunos exchanges)
        df = df[~df.index.duplicated(keep="last")]

        return df

    @staticmethod
    def align_htf_to_ltf(
        df_ltf: pd.DataFrame,
        df_htf_with_features: pd.DataFrame,
        htf_duration_minutes: int,
    ) -> pd.DataFrame:
        """
        Alinea características HTF al LTF SIN look-ahead bias.

        El concepto clave es htf_close_time:
            htf_close_time = htf_open_time + htf_duration_minutes

        Una vela HTF solo puede aportar información al LTF cuando:
            ltf_open_time >= htf_close_time

        Ejemplo explícito:
            HTF vela: open=10:00, close=11:00 (duración 60 min)
            LTF 10:15 → NO puede ver esta vela (11:00 > 10:15)
            LTF 10:45 → NO puede ver esta vela (11:00 > 10:45)
            LTF 11:00 → SÍ puede ver esta vela (11:00 <= 11:00)
            LTF 11:15 → SÍ puede ver esta vela (11:00 <= 11:15)

        Args:
            df_ltf: DataFrame LTF indexado por open_time. Ya debe tener features LTF.
            df_htf_with_features: DataFrame HTF indexado por open_time, con features calculados.
            htf_duration_minutes: Duración de cada vela HTF en minutos (ej: 60 para 1h).

        Returns:
            df_ltf con columnas HTF añadidas (sufijo '_htf').
            Las columnas HTF de las primeras velas LTF que no tienen vela HTF previa
            disponible tendrán NaN — estas filas DEBEN descartarse antes de operar.
        """
        if df_ltf.empty or df_htf_with_features.empty:
            return df_ltf

        # Paso 1: Calcular el close_time de cada vela HTF
        # El índice del DataFrame HTF es el open_time.
        # close_time = open_time + duración HTF
        htf = df_htf_with_features.copy()
        htf.index = htf.index + pd.Timedelta(minutes=htf_duration_minutes)
        # Ahora el índice de `htf` representa: "este régimen está disponible a partir de este momento"

        # Paso 2: Añadir sufijo para distinguir columnas HTF de LTF
        htf_cols = {col: f"{col}_htf" for col in htf.columns}
        htf = htf.rename(columns=htf_cols)

        # Paso 3: Normalizar la precisión del índice datetime antes del merge.
        # normalize_klines() produce datetime64[ms, UTC] (timestamp de Binance en ms).
        # La suma de pd.Timedelta eleva la precisión a datetime64[us, UTC].
        # merge_asof requiere que ambas claves sean del mismo dtype exacto.
        ltf_sorted = df_ltf.sort_index()
        htf_sorted = htf.sort_index()

        # Convertir ambos al mismo dtype para evitar MergeError
        target_dtype = "datetime64[us, UTC]"
        ltf_sorted.index = ltf_sorted.index.astype(target_dtype)
        htf_sorted.index = htf_sorted.index.astype(target_dtype)

        # Paso 4: merge_asof con direction='backward'
        # Para cada fila LTF, busca la última fila HTF cuyo índice <= ltf_timestamp
        # Esto equivale a buscar la última vela HTF cuyo close_time <= ltf_open_time
        merged = pd.merge_asof(
            ltf_sorted,
            htf_sorted,
            left_index=True,
            right_index=True,
            direction="backward",
        )

        return merged

    @staticmethod
    def merge_timeframes(
        df_lower: pd.DataFrame,
        df_higher: pd.DataFrame,
        higher_tf: str = "1h"
    ) -> pd.DataFrame:
        """
        Método legacy mantenido por compatibilidad con código existente.

        AVISO: Este método NO elimina look-ahead bias correctamente.
        Usar align_htf_to_ltf() para cualquier backtest o análisis serio.
        """
        df_higher_renamed = df_higher.add_suffix(f"_{higher_tf}")
        df_merged = df_lower.join(df_higher_renamed, how="left").ffill()
        return df_merged
