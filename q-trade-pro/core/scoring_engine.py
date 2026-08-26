import pandas as pd
from typing import Tuple, Dict, Any

class ScoringEngine:
    """
    Motor de señales profesional. Requiere MÚLTIPLES confirmaciones antes de dar entrada.

    Puntuación:
    - 0-79:  NO OPERAR
    - 80+:   ENTRADA (todas las condiciones alineadas)

    Filosofía: es mejor perderse una operación que entrar en una mala.
    """

    @staticmethod
    def evaluate(df_lower: pd.DataFrame, regime: str) -> Tuple[int, Dict[str, Any]]:
        if df_lower.empty or len(df_lower) < 3:
            return 0, {}

        # TRANSITION y regímenes desconocidos: nunca operamosss
        if regime in ['UNKNOWN', 'EXTREME_VOLATILITY', 'CHOP', 'TRANSITION']:
            return 0, {'signal': 'NEUTRAL', 'regime': regime, 'entry_price': 0, 'atr': 0}

        last       = df_lower.iloc[-1]
        prev       = df_lower.iloc[-2]

        rsi         = float(last.get('RSI_14',          50))
        macd_h      = float(last.get('MACDh_12_26_9',    0))
        macd_h_prev = float(prev.get('MACDh_12_26_9',    0))
        close       = float(last.get('close',             0))
        ema20       = float(last.get('EMA_20',            0))
        ema50       = float(last.get('EMA_50',            0))
        adx         = float(last.get('ADX_14',            0))
        atr         = float(last.get('ATRr_14', close * 0.005))
        bb_upper    = float(last.get('BBU_20_2.0',        0))
        bb_lower_b  = float(last.get('BBL_20_2.0',        0))

        score  = 0
        signal = 'NEUTRAL'

        # ── BULL_TREND: Solo LONG ─────────────────────────────────────────
        if regime == 'BULL_TREND':
            # ADX obligatorio
            if adx >= 20:
                score += 20
            elif adx >= 15:
                score += 10
            else:
                return 0, {'signal': 'NEUTRAL', 'regime': regime, 'entry_price': close, 'atr': atr}

            # Estructura alcista
            if close > ema20 and ema20 > ema50:
                score += 20
            elif close > ema20:
                score += 10

            # RSI en zona de pullback sano
            if 35 <= rsi <= 55:
                score += 25
            elif 55 < rsi <= 65:
                score += 10
            elif rsi > 70:
                score -= 30
            elif rsi < 30:
                score -= 20

            # MACD girando al alza
            if macd_h > 0 and macd_h > macd_h_prev:
                score += 25
            elif macd_h > 0:
                score += 15
            elif macd_h > macd_h_prev:
                score += 5

            if score >= 70:
                signal = 'LONG'

        # ── BEAR_TREND: Solo SHORT ────────────────────────────────────────
        elif regime == 'BEAR_TREND':
            if adx >= 20:
                score += 20
            elif adx >= 15:
                score += 10
            else:
                return 0, {'signal': 'NEUTRAL', 'regime': regime, 'entry_price': close, 'atr': atr}

            # Estructura bajista
            if close < ema20 and ema20 < ema50:
                score += 20
            elif close < ema20:
                score += 10

            # RSI en zona de rebote fallido
            if 45 <= rsi <= 65:
                score += 25
            elif 35 <= rsi < 45:
                score += 10
            elif rsi < 30:
                score -= 30
            elif rsi > 70:
                score -= 20

            # MACD girando a la baja
            if macd_h < 0 and macd_h < macd_h_prev:
                score += 25
            elif macd_h < 0:
                score += 15
            elif macd_h < macd_h_prev:
                score += 5

            if score >= 70:
                signal = 'SHORT'

        # ── RANGING — DESHABILITADO ───────────────────────────────────────────
        # El backtest demostró que la estrategia de Mean Reversion en Bollinger Bands
        # pierde dinero consistentemente en crypto (16/22 operaciones perdedoras).
        # Solo operamos en tendencias claras (BULL_TREND / BEAR_TREND).
        elif regime == 'RANGING':
            score = 0

        setup = {
            'signal':      signal,
            'regime':      regime,
            'entry_price': close,
            'atr':         atr,
        }

        return max(0, min(100, score)), setup
