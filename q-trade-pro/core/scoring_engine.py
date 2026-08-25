"""
core/scoring_engine.py
======================
Motor de señales de Q-Trade Pro.

Filosofía
─────────
El scoring evalúa la confluencia de múltiples factores técnicos.
Una señal solo se genera cuando todos los factores están alineados.

Escala de puntuación
────────────────────
Los pesos raw de los factores suman un máximo de 90 puntos:
    ADX:       máx 20  (strong=20, medium=10)
    Structure: máx 20  (full=20, partial=10)
    RSI:       máx 25  (ideal=25, ok=10, penalizaciones=-20/-30)
    MACD:      máx 25  (best=25, ok=15, turning=5)
    ─────────────────
    MAX RAW:        90

Se normaliza a escala 0-100 para consistencia:
    normalized_score = raw_score / 90 * 100

El threshold de entrada es el EQUIVALENTE NORMALIZADO del threshold raw de 80:
    80 / 90 * 100 = 88.888...

IMPORTANTE: NO se cambia el threshold a 80/100, porque eso haría la estrategia
más permisiva. El comportamiento es idéntico al sistema anterior.

Regímenes
─────────
- BULL_TREND:         Solo LONG
- BEAR_TREND:         Solo SHORT
- RANGING:            Deshabilitado (backtest demostró pérdidas consistentes)
- TRANSITION:         Sin operación
- EXTREME_VOLATILITY: Sin operación
- UNKNOWN:            Sin operación

Velas cerradas
──────────────
Este módulo opera sobre DataFrames de velas ya cerradas.
La fila iloc[-1] es la última vela CERRADA, no la vela en formación.
Garantizar esto es responsabilidad del llamador.
"""

from __future__ import annotations

import pandas as pd
from typing import Tuple, Dict, Any

from config.config import StrategyConfig, DEFAULT_STRATEGY

# Regímenes que nunca generan operación
_NO_TRADE_REGIMES = frozenset({
    "UNKNOWN",
    "EXTREME_VOLATILITY",
    "CHOP",
    "TRANSITION",
})


class ScoringEngine:
    """
    Motor de puntuación y generación de señales.

    Uso:
        score, setup = ScoringEngine.evaluate(df_closed_ltf, regime, config)

    El score retornado está en escala 0-100 (normalizado desde raw 0-90).
    El threshold de entrada equivalente es config.entry_threshold_normalized (~88.88).
    """

    @staticmethod
    def evaluate(
        df_lower: pd.DataFrame,
        regime: str,
        config: StrategyConfig = DEFAULT_STRATEGY,
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Evalúa el setup y devuelve (score_0_100, setup_dict).

        Args:
            df_lower: DataFrame LTF con features calculados. Solo velas CERRADAS.
                      La fila iloc[-1] es la última vela cerrada.
            regime:   Régimen detectado por RegimeDetector en el HTF.
            config:   Configuración de estrategia.

        Returns:
            (score, setup) donde:
                - score: int en escala 0-100.
                - setup: dict con signal, regime, entry_price, atr.

        Nota sobre entry_price:
            entry_price aquí es el close de la última vela cerrada.
            El backtester y el motor de ejecución deben usarlo como REFERENCIA,
            pero la entrada real se produce al open de la vela siguiente (next_open).
        """
        if df_lower.empty or len(df_lower) < 3:
            return 0, {}

        # Regímenes que nunca operan
        if regime in _NO_TRADE_REGIMES:
            return 0, {
                "signal": "NEUTRAL",
                "regime": regime,
                "entry_price": 0,
                "atr": 0,
            }

        # Extraer datos de las últimas dos velas CERRADAS
        last = df_lower.iloc[-1]
        prev = df_lower.iloc[-2]

        rsi         = float(last.get("RSI_14",          50))
        macd_h      = float(last.get("MACDh_12_26_9",    0))
        macd_h_prev = float(prev.get("MACDh_12_26_9",    0))
        close       = float(last.get("close",             0))
        ema20       = float(last.get("EMA_20",            0))
        ema50       = float(last.get("EMA_50",            0))
        adx         = float(last.get("ADX_14",            0))
        atr         = float(last.get("ATRr_14", close * 0.005))

        raw_score = 0
        signal    = "NEUTRAL"

        # ── BULL_TREND: Solo LONG ─────────────────────────────────────────────
        if regime == "BULL_TREND":
            # ADX obligatorio — si no hay fuerza suficiente, no operar
            if adx >= config.adx_strong_trend:
                raw_score += config.adx_weight_strong
            elif adx >= config.adx_trend_threshold:
                raw_score += config.adx_weight_medium
            else:
                # ADX demasiado débil: no operar en absoluto
                return 0, {
                    "signal": "NEUTRAL",
                    "regime": regime,
                    "entry_price": close,
                    "atr": atr,
                }

            # Estructura alcista en LTF
            if close > ema20 and ema20 > ema50:
                raw_score += config.structure_weight_full
            elif close > ema20:
                raw_score += config.structure_weight_partial

            # RSI: buscar pullback sano dentro de la tendencia
            if config.rsi_bull_ideal_low <= rsi <= config.rsi_bull_ideal_high:
                raw_score += config.rsi_weight_ideal
            elif config.rsi_bull_ideal_high < rsi <= config.rsi_bull_ok_high:
                raw_score += config.rsi_weight_ok
            elif rsi > config.rsi_bull_overbought:
                raw_score += config.rsi_penalty_extreme  # negativo
            elif rsi < config.rsi_bear_oversold:
                raw_score += config.rsi_penalty_severe   # negativo

            # MACD: confirmar momentum alcista
            if macd_h > 0 and macd_h > macd_h_prev:
                raw_score += config.macd_weight_best
            elif macd_h > 0:
                raw_score += config.macd_weight_ok
            elif macd_h > macd_h_prev:
                raw_score += config.macd_weight_turning

            # Normalizar y verificar threshold
            normalized = ScoringEngine._normalize(raw_score, config)
            if normalized >= config.entry_threshold_normalized:
                signal = "LONG"

        # ── BEAR_TREND: Solo SHORT ─────────────────────────────────────────────
        elif regime == "BEAR_TREND":
            # ADX obligatorio
            if adx >= config.adx_strong_trend:
                raw_score += config.adx_weight_strong
            elif adx >= config.adx_trend_threshold:
                raw_score += config.adx_weight_medium
            else:
                return 0, {
                    "signal": "NEUTRAL",
                    "regime": regime,
                    "entry_price": close,
                    "atr": atr,
                }

            # Estructura bajista en LTF
            if close < ema20 and ema20 < ema50:
                raw_score += config.structure_weight_full
            elif close < ema20:
                raw_score += config.structure_weight_partial

            # RSI: buscar rebote fallido dentro de la tendencia bajista
            if config.rsi_bear_ideal_low <= rsi <= config.rsi_bear_ideal_high:
                raw_score += config.rsi_weight_ideal
            elif config.rsi_bear_ok_low <= rsi < config.rsi_bear_ideal_low:
                raw_score += config.rsi_weight_ok
            elif rsi < config.rsi_bear_oversold:
                raw_score += config.rsi_penalty_extreme  # negativo
            elif rsi > config.rsi_bull_overbought:
                raw_score += config.rsi_penalty_severe   # negativo

            # MACD: confirmar momentum bajista
            if macd_h < 0 and macd_h < macd_h_prev:
                raw_score += config.macd_weight_best
            elif macd_h < 0:
                raw_score += config.macd_weight_ok
            elif macd_h < macd_h_prev:
                raw_score += config.macd_weight_turning

            # Normalizar y verificar threshold
            normalized = ScoringEngine._normalize(raw_score, config)
            if normalized >= config.entry_threshold_normalized:
                signal = "SHORT"

        # ── RANGING — DESHABILITADO ────────────────────────────────────────────
        # El backtest demostró pérdidas consistentes en RANGING (16/22 perdedoras).
        # Solo operamos en tendencias claras.
        # Las Bollinger Bands están reservadas en FeatureEngine para uso futuro.
        elif regime == "RANGING":
            raw_score = 0

        # Score final normalizado (0-100)
        final_score = ScoringEngine._normalize(raw_score, config)

        setup = {
            "signal":      signal,
            "regime":      regime,
            "entry_price": close,   # close de la vela cerrada N
            "atr":         atr,
            "raw_score":   raw_score,
        }

        return final_score, setup

    @staticmethod
    def _normalize(raw_score: int, config: StrategyConfig) -> float:
        """
        Normaliza el score raw (0-90 máximo) a escala 0-100.

        El threshold de entrada equivalente es:
            ENTRY_THRESHOLD_RAW / MAX_RAW_SCORE * 100
            = 80 / 90 * 100
            = 88.888...

        Esto preserva exactamente el mismo comportamiento que el threshold raw de 80.
        """
        clamped = max(0, min(config.MAX_RAW_SCORE, raw_score))
        return round(clamped / config.MAX_RAW_SCORE * 100, 2)
