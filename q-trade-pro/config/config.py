"""
config/config.py
================
Configuración centralizada de Q-Trade Pro.

REGLA: ningún número mágico debe existir fuera de este fichero.
Todos los parámetros de estrategia, riesgo, ejecución y backtest
están aquí definidos y son sobreescribibles mediante variables de entorno.

Principio de diseño
-------------------
- Los dataclasses son inmutables por convención (no usar __post_init__ mutador).
- Los thresholds de estrategia NO deben optimizarse hasta tener un backtester
  libre de look-ahead bias y validado out-of-sample.
- LIVE_TRADING debe ser False por defecto: nunca enviar órdenes reales
  accidentalmente.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategyConfig:
    """Parámetros de la estrategia de trading.

    Filosofía (NO CAMBIAR sin análisis OOS):
    ─────────────────────────────────────────
    HTF → detección de régimen → LTF → scoring → validación de riesgo → ejecución.

    Threshold de entrada normalizado
    ─────────────────────────────────
    El scoring raw máximo es 90 (ADX 20 + Structure 20 + RSI 25 + MACD 25).
    Se normaliza a escala 0-100.
    El threshold de entrada equivalente al «80 raw» es:
        80 / 90 * 100 = 88.888...

    NO bajar este threshold sin evidencia OOS clara.
    """
    # ── Régimen HTF ───────────────────────────────────────────────────────────
    adx_ranging_threshold: float = 18.0     # ADX < X → RANGING
    adx_trend_threshold: float = 20.0       # ADX >= X para ser candidato a TREND
    adx_strong_trend: float = 25.0          # ADX >= X → puntuación ADX máxima

    # ── Volatilidad extrema ───────────────────────────────────────────────────
    extreme_vol_percentile: float = 0.95    # ATR/close > P95 → EXTREME_VOLATILITY
    extreme_vol_lookback: int = 200         # Número de velas para calcular el percentil

    # ── Scoring ───────────────────────────────────────────────────────────────
    # Pesos del sistema de puntuación (deben sumar MAX_RAW_SCORE)
    adx_weight_strong: int = 20             # ADX >= adx_strong_trend
    adx_weight_medium: int = 10             # adx_trend_threshold <= ADX < adx_strong_trend
    structure_weight_full: int = 20         # close > ema20 > ema50 (bull) / inverso (bear)
    structure_weight_partial: int = 10      # Solo una de las condiciones de estructura
    rsi_weight_ideal: int = 25              # RSI en zona de pullback ideal
    rsi_weight_ok: int = 10                 # RSI en zona aceptable
    rsi_penalty_extreme: int = -30          # RSI sobrecomprado/sobrevendido (señal contraria)
    rsi_penalty_severe: int = -20           # RSI adverso severo
    macd_weight_best: int = 25              # MACD en dirección y acelerando
    macd_weight_ok: int = 15               # MACD en dirección pero sin acelerar
    macd_weight_turning: int = 5            # MACD girando en la dirección correcta

    # Máximo teórico de puntuación raw (suma de pesos positivos)
    MAX_RAW_SCORE: int = 90  # ADX(20) + Structure(20) + RSI(25) + MACD(25) = 90

    # Threshold de entrada expresado en escala raw
    # Por defecto 80 (80/90 = 88.89% normalizado). Para pruebas puede configurarse en .env
    ENTRY_THRESHOLD_RAW: int = field(
        default_factory=lambda: int(os.getenv("ENTRY_THRESHOLD_RAW", os.getenv("SCORE_THRESHOLD", "80")))
    )

    @property
    def entry_threshold_normalized(self) -> float:
        """Threshold en escala 0-100. Equivalente exacto al threshold raw."""
        return self.ENTRY_THRESHOLD_RAW / self.MAX_RAW_SCORE * 100

    # ── RSI zones (BULL_TREND) ────────────────────────────────────────────────
    rsi_bull_ideal_low: float = 35.0        # RSI ideal pullback: zona baja
    rsi_bull_ideal_high: float = 55.0       # RSI ideal pullback: zona alta
    rsi_bull_ok_high: float = 65.0          # RSI aceptable
    rsi_bull_overbought: float = 70.0       # RSI sobrecomprado (penalización)

    # ── RSI zones (BEAR_TREND) ────────────────────────────────────────────────
    rsi_bear_ideal_low: float = 45.0        # RSI ideal rebote fallido: zona baja
    rsi_bear_ideal_high: float = 65.0       # RSI ideal rebote fallido: zona alta
    rsi_bear_ok_low: float = 35.0           # RSI aceptable
    rsi_bear_oversold: float = 30.0         # RSI sobrevendido (penalización)

    # ── Timeframes ────────────────────────────────────────────────────────────
    htf: str = '1h'                         # Higher Time Frame para régimen
    ltf: str = '15m'                        # Lower Time Frame para señal
    htf_minutes: int = 60                   # Duración en minutos del HTF

    # ── Indicadores ──────────────────────────────────────────────────────────
    ema_short: int = 20
    ema_medium: int = 50
    ema_long: int = 200
    rsi_period: int = 14
    adx_period: int = 14
    atr_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20                     # Bollinger Bands (reservado para RANGING)
    bb_std: float = 2.0

    # Número mínimo de velas para que los indicadores sean válidos
    MIN_CANDLES_REQUIRED: int = 210         # EMA200 necesita 200 + margen


# ─────────────────────────────────────────────────────────────────────────────
# COST MODEL CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CostConfig:
    """Modelo de costes completo para backtesting y live.

    Perpetual Futures (BingX)
    ─────────────────────────
    - Taker fee: 0.05% por lado (entrada y salida)
    - Maker fee: 0.02% por lado
    - Funding: cada 8h, por defecto 0.01% (variable)
    - Spread: modelado como bps adicionales

    Coste total por vuelta (round-trip):
        entry_fee + exit_fee + entry_slippage + exit_slippage + spread
    """
    # Fees (como fracción, no porcentaje: 0.0005 = 0.05%)
    taker_fee_rate: float = 0.0005          # BingX perpetual taker
    maker_fee_rate: float = 0.0002          # BingX perpetual maker
    use_taker_fee: bool = True              # Por defecto: taker (market orders)

    # Slippage estimado (como fracción del precio)
    entry_slippage: float = 0.0002          # 2 bps de slippage en entrada
    exit_slippage: float = 0.0002           # 2 bps de slippage en salida

    # Spread (bps expresado como fracción)
    spread_bps: float = 0.0002              # 2 bps de spread típico en majors

    # Funding rate (perpetual futures)
    # Si no hay datos históricos reales, usar estimación conservadora
    funding_rate_per_8h: float = 0.0001     # 0.01% cada 8h (aproximación)
    apply_funding: bool = False             # Desactivado por defecto (sin datos históricos)

    @property
    def fee_rate(self) -> float:
        """Fee por lado según tipo de orden."""
        return self.taker_fee_rate if self.use_taker_fee else self.maker_fee_rate

    def total_round_trip_cost(self) -> float:
        """Coste total de una vuelta completa como fracción del notional."""
        return (
            self.fee_rate           # entrada
            + self.fee_rate         # salida
            + self.entry_slippage
            + self.exit_slippage
            + self.spread_bps
        )


# ─────────────────────────────────────────────────────────────────────────────
# RISK CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RiskConfig:
    """Parámetros de gestión de riesgo.

    Distinción importante
    ─────────────────────
    - risk_amount: pérdida monetaria máxima asumida en el SL.
    - margin: capital bloqueado por la posición (notional / leverage).
    - notional_exposure: valor total de la posición (size * price).

    El sizing se hace siempre sobre risk_amount, nunca sobre margin.
    """
    # ── Risk per trade ────────────────────────────────────────────────────────
    risk_per_trade_pct: float = field(
        default_factory=lambda: float(os.getenv("RISK_PER_TRADE_PCT", "0.005"))
    )

    # ── SL / TP ───────────────────────────────────────────────────────────────
    sl_atr_mult: float = 1.5                # Stop Loss = 1.5x ATR
    tp_atr_mult: float = 3.0               # Take Profit = 3.0x ATR → RR 1:2

    # ── Leverage ──────────────────────────────────────────────────────────────
    leverage: float = field(
        default_factory=lambda: float(os.getenv("LEVERAGE", "3.0"))
    )
    # NOTA: leverage afecta margin y notional pero NO risk_amount.
    # El riesgo siempre se mide en términos de pérdida en SL.

    # ── Posiciones simultáneas ────────────────────────────────────────────────
    max_concurrent_positions: int = 7
    max_same_direction: int = 5

    # ── Portfolio risk agregado ───────────────────────────────────────────────
    # Suma del riesgo individual de todas las posiciones abiertas.
    # Si abrir una nueva posición supera este límite: rechazar.
    max_portfolio_risk_pct: float = 0.06    # 6% riesgo total del portfolio

    # Exposición máxima por dirección (como % del capital)
    max_long_exposure_pct: float = 0.40     # Máx 40% del capital en LONG (notional)
    max_short_exposure_pct: float = 0.40    # Máx 40% del capital en SHORT (notional)

    # Exposición máxima en un solo activo (como % del capital)
    max_asset_exposure_pct: float = 0.15    # Máx 15% del capital en un mismo símbolo

    # ── Daily Loss Limit ──────────────────────────────────────────────────────
    # Si el PnL del día supera esta pérdida: activar daily halt.
    # El halt persiste durante todo el día y solo se resetea al inicio del día siguiente.
    max_daily_loss_pct: float = 0.03        # 3% de pérdida diaria máxima

    # ── Cooldown ──────────────────────────────────────────────────────────────
    symbol_cooldown_minutes: int = 15       # Espera tras cierre de posición


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BacktestConfig:
    """Parámetros del backtester.

    Semántica de ejecución
    ──────────────────────
    Señal generada en la vela cerrada N.
    Ejecución (por defecto) en el open de la vela N+1.

    Política intrabar
    ─────────────────
    Cuando HIGH >= TP y LOW <= SL en la misma vela:
    - "conservative": SL tiene prioridad (comportamiento más pesimista).
    - "optimistic":   TP tiene prioridad.
    - "random":       Aleatorio (útil para tests de sensibilidad, pero no reproducible).

    Para análisis serio: siempre usar "conservative".
    """
    initial_capital: float = 1000.0
    entry_on: Literal["close", "next_open"] = "next_open"
    intrabar_policy: Literal["conservative", "optimistic", "random"] = "conservative"
    data_source: str = "binance"            # Exchange para datos históricos
    backtest_months: int = 6


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExecutionConfig:
    """Parámetros de ejecución.

    Safety por defecto
    ──────────────────
    LIVE_TRADING = False.

    Para activar órdenes reales se requiere EXPLÍCITAMENTE:
    1. LIVE_TRADING=true en el fichero .env
    2. Una validación adicional en el motor de ejecución.

    Nunca debe enviarse una orden real accidentalmente.
    """
    live_trading: bool = field(
        default_factory=lambda: os.getenv("LIVE_TRADING", "false").lower() == "true"
    )
    paper_trading: bool = field(
        default_factory=lambda: os.getenv("PAPER_TRADING", "true").lower() == "true"
    )
    exchange_id: str = "bingx"
    testnet: bool = field(
        default_factory=lambda: os.getenv("TESTNET", "false").lower() == "true"
    )

    def validate_live(self) -> bool:
        """Validación adicional requerida antes de permitir órdenes reales."""
        if not self.live_trading:
            return False
        # Verificar variable de entorno explícita
        env_val = os.getenv("LIVE_TRADING", "").strip().lower()
        if env_val != "true":
            return False
        # Verificar que no estamos en modo paper simultáneamente
        if self.paper_trading:
            return False
        return True


# ─────────────────────────────────────────────────────────────────────────────
# INSTANCIAS GLOBALES (valores por defecto)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_STRATEGY = StrategyConfig()
DEFAULT_COSTS    = CostConfig()
DEFAULT_RISK     = RiskConfig()
DEFAULT_BACKTEST = BacktestConfig()
DEFAULT_EXECUTION = ExecutionConfig()
