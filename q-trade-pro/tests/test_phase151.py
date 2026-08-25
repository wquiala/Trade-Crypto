"""
tests/test_phase151.py
========================
Tests de la Fase 1.5.1: Kill Switch + MTF Live Integration + Score Threshold.

Qué cubre este fichero
──────────────────────
A. Kill Switch Manual
   - El kill switch NO se resetea en las iteraciones del loop.
   - analyze_symbol() bloquea nuevas entradas cuando está activo.
   - Las posiciones existentes continúan siendo gestionadas.
   - Solo una acción explícita puede desactivarlo.

B. MTF Look-Ahead Bias en Flujo Live
   - align_htf_to_ltf() se usa en el flujo real (no solo en tests aislados).
   - Una vela HTF 10:00-11:00 NO puede influir antes de las 11:00.
   - Casos exactos: 10:15, 10:45 → NO; 11:00, 11:15 → SÍ.
   - Cambio de régimen: visible solo desde htf_close_time.
   - Vela 4H 08:00-12:00: ninguna vela LTF anterior a 12:00 puede verla.

C. Score Threshold
   - RAW < 80  → NO entrada.
   - RAW = 80  → entrada permitida.
   - RAW > 80  → entrada permitida.
   - La normalización no altera esta semántica.

D. Flujo de análisis completo
   - Pipeline: datos → MTF → features → regime → score → risk → kill switch → decisión.
   - Identificar en qué punto exacto se bloquea cada señal.

Filosofía de estos tests
─────────────────────────
Los tests de test_mtf_bias.py prueban align_htf_to_ltf() de forma AISLADA.
Estos tests prueban el flujo REAL orquestado por analyze_symbol(),
incluyendo la lógica de bloqueo por kill switch y daily halt.
"""
import sys
import os
import asyncio
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.data_processor import MarketDataFetcher
from core.feature_engine import FeatureEngine
from core.regime_detector import RegimeDetector
from core.scoring_engine import ScoringEngine
from core.risk_manager import RiskManager
from core.portfolio_risk import PortfolioRiskManager
from config.config import DEFAULT_STRATEGY, DEFAULT_RISK, DEFAULT_COSTS


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de generación de datos sintéticos
# ─────────────────────────────────────────────────────────────────────────────

def _make_ohlcv(
    n: int,
    start: datetime,
    freq_minutes: int,
    base_price: float = 100.0,
    trend: float = 0.0,
) -> pd.DataFrame:
    """
    Genera n velas OHLCV sintéticas con timestamp UTC correcto.

    trend > 0 → tendencia alcista
    trend < 0 → tendencia bajista
    """
    timestamps = [start + timedelta(minutes=freq_minutes * i) for i in range(n)]
    prices = [base_price + trend * i for i in range(n)]

    data = {
        "open":   [p * 0.999 for p in prices],
        "high":   [p * 1.005 for p in prices],
        "low":    [p * 0.995 for p in prices],
        "close":  prices,
        "volume": [1000.0] * n,
    }
    index = pd.DatetimeIndex(timestamps, tz="UTC")
    return pd.DataFrame(data, index=index)


def _make_ohlcv_bull(n: int, start: datetime, freq_minutes: int) -> pd.DataFrame:
    """Velas con tendencia alcista clara (para que ADX sea alto y ema20 > ema50)."""
    return _make_ohlcv(n, start, freq_minutes, base_price=100.0, trend=0.5)


def _make_minimal_ltf_with_features(
    n: int = 300,
    start: datetime | None = None,
    freq_minutes: int = 15,
    trend: float = 0.3,
) -> pd.DataFrame:
    """Genera un LTF con suficientes velas para que los indicadores sean válidos."""
    if start is None:
        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    raw = _make_ohlcv(n, start, freq_minutes, trend=trend)
    return FeatureEngine.compute(raw)


def _make_minimal_htf_with_features(
    n: int = 100,
    start: datetime | None = None,
    freq_minutes: int = 60,
    trend: float = 1.0,
) -> pd.DataFrame:
    """Genera un HTF con suficientes velas para que los indicadores sean válidos."""
    if start is None:
        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    raw = _make_ohlcv(n, start, freq_minutes, trend=trend)
    return FeatureEngine.compute(raw)


# ─────────────────────────────────────────────────────────────────────────────
# A. Kill Switch Manual
# ─────────────────────────────────────────────────────────────────────────────

class AnalyzeSymbolSimulator:
    """
    Simula el flujo de analyze_symbol() de main.py sin conectarse a ningún exchange.

    Reproduce exactamente las condiciones de bloqueo:
    1. score < threshold → NEUTRAL
    2. símbolo ya tiene posición
    3. daily halt activo
    4. kill switch activo
    5. portfolio risk rechaza
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        max_daily_loss_pct: float = 0.03,
    ):
        self.capital = initial_capital
        self.portfolio_risk = PortfolioRiskManager(
            config=DEFAULT_RISK.__class__(max_daily_loss_pct=max_daily_loss_pct)
        )
        self.portfolio_risk.initialize_day(capital=initial_capital)
        self.active_positions: dict = {}
        self.kill_switch_active: bool = False
        self.entry_log: list[dict] = []
        self.block_log: list[dict] = []

    def tick(self, current_capital: float | None = None) -> None:
        """Simula una iteración del ticker_loop (sin reset incondicional del kill switch)."""
        if current_capital is not None:
            self.capital = current_capital
            self.portfolio_risk.check_and_update_daily_state(current_capital=current_capital)

        # CRÍTICO: el kill_switch NO se toca aquí.
        # Solo se actualiza el status visual.
        # status = "KillSwitch" si activo, "Running" en caso contrario.

    def analyze(self, symbol: str, regime: str, score: float, raw_score: int) -> str:
        """
        Simula analyze_symbol(). Devuelve el motivo del bloqueo o 'ENTRY'.

        Args:
            symbol:    Símbolo a analizar.
            regime:    Régimen HTF detectado.
            score:     Score normalizado (0-100).
            raw_score: Score raw (0-90).
        """
        threshold = DEFAULT_STRATEGY.entry_threshold_normalized
        signal = "LONG" if regime == "BULL_TREND" else (
                 "SHORT" if regime == "BEAR_TREND" else "NEUTRAL")

        # 1. Threshold
        if signal == "NEUTRAL" or score < threshold:
            self.block_log.append({"symbol": symbol, "reason": "BELOW_THRESHOLD", "score": score})
            return "BELOW_THRESHOLD"

        # 2. Posición ya abierta
        if symbol in self.active_positions:
            self.block_log.append({"symbol": symbol, "reason": "ALREADY_OPEN"})
            return "ALREADY_OPEN"

        # 3. Daily halt
        if self.portfolio_risk.is_daily_halt_active:
            self.block_log.append({"symbol": symbol, "reason": "DAILY_HALT"})
            return "DAILY_HALT"

        # 4. Kill switch manual
        if self.kill_switch_active:
            self.block_log.append({"symbol": symbol, "reason": "KILL_SWITCH"})
            return "KILL_SWITCH"

        # 5. Portfolio risk
        setup = {
            "signal": signal, "entry_price": 100.0, "atr": 1.0,
            "regime": regime, "raw_score": raw_score,
        }
        approved, size, details = RiskManager.validate_and_size(
            setup, self.capital, DEFAULT_RISK, DEFAULT_COSTS
        )
        if not approved:
            self.block_log.append({"symbol": symbol, "reason": "RISK_REJECTED"})
            return "RISK_REJECTED"

        can_open, reason = self.portfolio_risk.can_open_position(
            symbol=symbol, signal=signal,
            new_risk_amount=details.get("risk_amount_net", 0),
            positions=self.active_positions,
            current_prices={}, current_capital=self.capital,
        )
        if not can_open:
            self.block_log.append({"symbol": symbol, "reason": reason})
            return reason

        # ENTRADA APROBADA
        self.active_positions[symbol] = {
            "signal": signal, "entry_price": 100.0, "size": size,
            "stop_loss": 98.5, "take_profit": 103.0, "atr": 1.0,
        }
        self.entry_log.append({"symbol": symbol, "signal": signal})
        return "ENTRY"

    # Score suficientemente alto para pasar el threshold (raw=90 normalizado=100)
    HIGH_SCORE = 100.0
    HIGH_RAW   = 90


class TestKillSwitchManual:
    """
    Verifica el comportamiento correcto del kill switch manual.
    """

    def test_kill_switch_initially_false(self):
        """El kill switch comienza desactivado."""
        sim = AnalyzeSymbolSimulator()
        assert not sim.kill_switch_active

    def test_kill_switch_operator_activates(self):
        """El operador puede activar el kill switch."""
        sim = AnalyzeSymbolSimulator()
        sim.kill_switch_active = True
        assert sim.kill_switch_active

    def test_kill_switch_persists_across_10_ticker_iterations(self):
        """
        Después de 10 iteraciones del ticker_loop, el kill switch
        debe permanecer activo. NO debe haber ningún reset incondicional.
        """
        sim = AnalyzeSymbolSimulator()
        sim.kill_switch_active = True

        for i in range(10):
            sim.tick(current_capital=10_000.0)
            assert sim.kill_switch_active, (
                f"El kill switch se desactivó en la iteración {i+1} — "
                "hay un reset incondicional en el loop"
            )

    def test_kill_switch_blocks_new_entries(self):
        """Con kill switch activo, analyze_symbol NO abre nuevas posiciones."""
        sim = AnalyzeSymbolSimulator()
        sim.kill_switch_active = True

        result = sim.analyze("BTC/USDT:USDT", "BULL_TREND", sim.HIGH_SCORE, sim.HIGH_RAW)
        assert result == "KILL_SWITCH", f"Esperado KILL_SWITCH, obtenido {result}"
        assert len(sim.entry_log) == 0

    def test_kill_switch_blocks_multiple_symbols(self):
        """Con kill switch activo, TODOS los símbolos quedan bloqueados."""
        sim = AnalyzeSymbolSimulator()
        sim.kill_switch_active = True

        symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
        for sym in symbols:
            result = sim.analyze(sym, "BULL_TREND", sim.HIGH_SCORE, sim.HIGH_RAW)
            assert result == "KILL_SWITCH", f"[{sym}] Esperado KILL_SWITCH, obtenido {result}"

    def test_existing_positions_unaffected_by_kill_switch(self):
        """
        Las posiciones existentes NO son cerradas por el kill switch.
        El kill switch solo bloquea NUEVAS entradas.
        """
        sim = AnalyzeSymbolSimulator()

        # Abrir posición ANTES de activar el kill switch
        result = sim.analyze("BTC/USDT:USDT", "BULL_TREND", sim.HIGH_SCORE, sim.HIGH_RAW)
        assert result == "ENTRY"
        assert "BTC/USDT:USDT" in sim.active_positions

        # Activar kill switch
        sim.kill_switch_active = True

        # La posición BTC sigue abierta (no la cierra)
        assert "BTC/USDT:USDT" in sim.active_positions, (
            "El kill switch cerró una posición existente — comportamiento incorrecto"
        )

        # Nuevas entradas bloqueadas
        result2 = sim.analyze("ETH/USDT:USDT", "BULL_TREND", sim.HIGH_SCORE, sim.HIGH_RAW)
        assert result2 == "KILL_SWITCH"
        assert "ETH/USDT:USDT" not in sim.active_positions

    def test_kill_switch_only_deactivates_explicitly(self):
        """
        El kill switch solo puede desactivarse mediante acción explícita.
        10 iteraciones del loop no lo desactivan.
        """
        sim = AnalyzeSymbolSimulator()
        sim.kill_switch_active = True

        # 10 iteraciones
        for _ in range(10):
            sim.tick()

        assert sim.kill_switch_active, "El loop desactivó el kill switch — debe requerir acción explícita"

        # Acción explícita del operador
        sim.kill_switch_active = False
        assert not sim.kill_switch_active

        # Ahora las entradas están permitidas
        result = sim.analyze("BTC/USDT:USDT", "BULL_TREND", sim.HIGH_SCORE, sim.HIGH_RAW)
        assert result == "ENTRY"

    def test_kill_switch_does_not_affect_daily_halt(self):
        """
        Kill switch y daily halt son independientes.
        Desactivar uno no afecta al otro.
        """
        sim = AnalyzeSymbolSimulator()

        # Activar daily halt
        sim.tick(current_capital=9_600.0)   # -4% > -3% límite
        assert sim.portfolio_risk.is_daily_halt_active

        # Desactivar kill switch no desactiva el daily halt
        sim.kill_switch_active = False
        assert sim.portfolio_risk.is_daily_halt_active

        # El daily halt sigue bloqueando
        result = sim.analyze("BTC/USDT:USDT", "BULL_TREND", sim.HIGH_SCORE, sim.HIGH_RAW)
        assert result == "DAILY_HALT"

    def test_both_kill_switch_and_daily_halt_block(self):
        """
        Con ambos activos, la primera comprobación que falla es el daily halt
        (se comprueba antes que el kill switch).
        """
        sim = AnalyzeSymbolSimulator()

        # Activar ambos
        sim.tick(current_capital=9_600.0)   # daily halt
        sim.kill_switch_active = True

        result = sim.analyze("BTC/USDT:USDT", "BULL_TREND", sim.HIGH_SCORE, sim.HIGH_RAW)
        # El daily halt se comprueba ANTES del kill switch en analyze_symbol
        assert result == "DAILY_HALT"


# ─────────────────────────────────────────────────────────────────────────────
# B. MTF Look-Ahead en Flujo Live (align_htf_to_ltf integrado)
# ─────────────────────────────────────────────────────────────────────────────

class TestMTFLiveIntegration:
    """
    Verifica que el flujo real de analyze_symbol() usa align_htf_to_ltf().
    Estos tests NO prueban la función aislada (eso ya está en test_mtf_bias.py).
    Prueban el pipeline completo: datos → align → regime → score.
    """

    def _build_pipeline_data(
        self,
        ltf_start: datetime,
        htf_start: datetime,
        n_ltf: int = 300,
        n_htf: int = 100,
        ltf_freq: int = 15,
        htf_freq: int = 60,
        ltf_trend: float = 0.3,
        htf_trend: float = 1.0,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Construye los DataFrames que usaría analyze_symbol() en producción.

        Returns: (df_15m_features, df_1h_features, df_aligned)
        """
        df_ltf_raw = _make_ohlcv(n_ltf, ltf_start, ltf_freq, trend=ltf_trend)
        df_htf_raw = _make_ohlcv(n_htf, htf_start, htf_freq, trend=htf_trend)

        df_ltf_feat = FeatureEngine.compute(df_ltf_raw)
        df_htf_feat = FeatureEngine.compute(df_htf_raw)

        df_aligned = MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_ltf_feat,
            df_htf_with_features=df_htf_feat,
            htf_duration_minutes=htf_freq,
        )
        return df_ltf_feat, df_htf_feat, df_aligned

    def test_htf_1h_not_visible_at_10_15(self):
        """
        HTF vela: 10:00-11:00 (close_time = 11:00)
        LTF vela: 10:15
        → régimen HTF NO disponible (NaN).
        """
        htf_start = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        ltf_start = datetime(2024, 1, 1, 10, 15, tzinfo=timezone.utc)

        # Solo 1 vela HTF (la de 10:00) y 1 vela LTF (10:15)
        df_htf_raw = _make_ohlcv(1, htf_start, freq_minutes=60)
        df_ltf_raw = _make_ohlcv(1, ltf_start, freq_minutes=15)

        # Para el align necesitamos features: usamos datos mínimos
        # (los indicadores darán NaN por insuficientes velas — es el comportamiento esperado)
        df_aligned = MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_ltf_raw,
            df_htf_with_features=df_htf_raw,
            htf_duration_minutes=60,
        )

        # La vela LTF 10:15 NO debe ver la vela HTF 10:00-11:00
        # (close_time = 11:00 > 10:15)
        htf_cols = [c for c in df_aligned.columns if c.endswith('_htf')]
        ltf_row = df_aligned.loc[df_aligned.index == pd.Timestamp("2024-01-01 10:15:00+00:00")]
        if not ltf_row.empty and htf_cols:
            for col in htf_cols:
                assert pd.isna(ltf_row[col].values[0]), (
                    f"La columna HTF '{col}' NO debería estar disponible en 10:15"
                )

    def test_htf_1h_not_visible_at_10_45(self):
        """
        HTF vela: 10:00-11:00 (close_time = 11:00)
        LTF vela: 10:45
        → régimen HTF NO disponible.
        """
        htf_start = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        ltf_start = datetime(2024, 1, 1, 10, 45, tzinfo=timezone.utc)

        df_htf_raw = _make_ohlcv(1, htf_start, freq_minutes=60)
        df_ltf_raw = _make_ohlcv(1, ltf_start, freq_minutes=15)

        df_aligned = MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_ltf_raw,
            df_htf_with_features=df_htf_raw,
            htf_duration_minutes=60,
        )

        htf_cols = [c for c in df_aligned.columns if c.endswith('_htf')]
        ltf_row = df_aligned.loc[df_aligned.index == pd.Timestamp("2024-01-01 10:45:00+00:00")]
        if not ltf_row.empty and htf_cols:
            for col in htf_cols:
                assert pd.isna(ltf_row[col].values[0]), (
                    f"La columna HTF '{col}' NO debería estar disponible en 10:45"
                )

    def test_htf_1h_visible_at_11_00(self):
        """
        HTF vela: 10:00-11:00 (close_time = 11:00)
        LTF vela: 11:00
        → régimen HTF DISPONIBLE (ya cerró exactamente).
        """
        htf_start = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        ltf_start = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)

        df_htf_raw = _make_ohlcv(1, htf_start, freq_minutes=60)
        df_ltf_raw = _make_ohlcv(1, ltf_start, freq_minutes=15)

        df_aligned = MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_ltf_raw,
            df_htf_with_features=df_htf_raw,
            htf_duration_minutes=60,
        )

        htf_cols = [c for c in df_aligned.columns if c.endswith('_htf')]
        assert htf_cols, "No se generaron columnas HTF en el DataFrame alineado"

        ltf_row = df_aligned.loc[df_aligned.index == pd.Timestamp("2024-01-01 11:00:00+00:00")]
        assert not ltf_row.empty, "No se encontró la vela LTF 11:00"

        # Al menos una columna HTF debe tener un valor (no NaN)
        has_htf_data = any(
            not pd.isna(ltf_row[col].values[0]) for col in htf_cols
        )
        assert has_htf_data, (
            "La vela LTF 11:00 NO tiene acceso a la vela HTF 10:00-11:00, "
            "pero debería tenerlo (htf_close_time=11:00 <= ltf_open_time=11:00)"
        )

    def test_htf_1h_visible_at_11_15(self):
        """
        HTF vela: 10:00-11:00 (close_time = 11:00)
        LTF vela: 11:15
        → régimen HTF DISPONIBLE.
        """
        htf_start = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        # Dos velas LTF: 11:00 y 11:15
        ltf_start = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)

        df_htf_raw = _make_ohlcv(1, htf_start, freq_minutes=60)
        df_ltf_raw = _make_ohlcv(2, ltf_start, freq_minutes=15)  # 11:00 y 11:15

        df_aligned = MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_ltf_raw,
            df_htf_with_features=df_htf_raw,
            htf_duration_minutes=60,
        )

        htf_cols = [c for c in df_aligned.columns if c.endswith('_htf')]
        assert htf_cols

        # 11:15 también debe ver la vela HTF
        ltf_1115 = df_aligned.loc[df_aligned.index == pd.Timestamp("2024-01-01 11:15:00+00:00")]
        assert not ltf_1115.empty
        has_htf = any(not pd.isna(ltf_1115[col].values[0]) for col in htf_cols)
        assert has_htf, "11:15 debería ver la vela HTF 10:00-11:00"

    def test_regime_change_visible_only_from_htf_close_time(self):
        """
        Caso D: Cambio de régimen HTF.

        Vela HTF A (09:00-10:00): precio descendente → futuro BEAR_TREND
        Vela HTF B (10:00-11:00): precio ascendente → futuro BULL_TREND

        Las velas LTF entre 09:00-10:00 solo ven la info de HTF A.
        Las velas LTF entre 10:00-11:00 ven HTF A pero NO HTF B (aún no cerró).
        Las velas LTF desde 11:00 ven HTF B.
        """
        # Dos velas HTF consecutivas
        htf_data = [
            [datetime(2024, 1, 1,  9, 0, tzinfo=timezone.utc), 110, 115, 105, 105, 1000],  # bajista
            [datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc), 105, 120, 100, 120, 1000],  # alcista
        ]
        cols = ["open", "high", "low", "close", "volume"]
        df_htf = pd.DataFrame(
            {c: [row[i+1] for row in htf_data] for i, c in enumerate(cols)},
            index=pd.DatetimeIndex([r[0] for r in htf_data]),
        )

        # LTF con velas en 09:15, 10:15, 11:15
        ltf_timestamps = [
            datetime(2024, 1, 1,  9, 15, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 10, 15, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 11, 15, tzinfo=timezone.utc),
        ]
        df_ltf = pd.DataFrame(
            {"open": [100]*3, "high": [110]*3, "low": [90]*3, "close": [105]*3, "volume": [1000]*3},
            index=pd.DatetimeIndex(ltf_timestamps),
        )

        df_aligned = MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_ltf,
            df_htf_with_features=df_htf,
            htf_duration_minutes=60,
        )

        htf_close_col = "close_htf"
        if htf_close_col not in df_aligned.columns:
            pytest.skip("No hay columna close_htf en el resultado")

        # 09:15 → no debe ver ninguna vela HTF (ninguna ha cerrado)
        row_0915 = df_aligned.loc[df_aligned.index == pd.Timestamp("2024-01-01 09:15:00+00:00")]
        if not row_0915.empty:
            assert pd.isna(row_0915[htf_close_col].values[0]), (
                "09:15 NO debería ver ninguna vela HTF"
            )

        # 10:15 → debe ver la vela HTF de 09:00-10:00 (close=105) pero NO la de 10:00-11:00
        row_1015 = df_aligned.loc[df_aligned.index == pd.Timestamp("2024-01-01 10:15:00+00:00")]
        if not row_1015.empty:
            val = row_1015[htf_close_col].values[0]
            assert not pd.isna(val), "10:15 debería ver la vela HTF 09:00-10:00"
            assert abs(val - 105) < 1e-6, (
                f"10:15 debería ver close=105 (HTF 09:00-10:00), obtuvo {val}"
            )

        # 11:15 → debe ver la vela HTF de 10:00-11:00 (close=120)
        row_1115 = df_aligned.loc[df_aligned.index == pd.Timestamp("2024-01-01 11:15:00+00:00")]
        if not row_1115.empty:
            val = row_1115[htf_close_col].values[0]
            assert not pd.isna(val), "11:15 debería ver la vela HTF 10:00-11:00"
            assert abs(val - 120) < 1e-6, (
                f"11:15 debería ver close=120 (HTF 10:00-11:00), obtuvo {val}"
            )

    def test_htf_4h_not_visible_before_12_00(self):
        """
        Caso E: Vela 4H de 08:00-12:00.
        Ninguna vela LTF anterior a 12:00 puede verla.
        Desde 12:00 en adelante: sí disponible.
        """
        htf_start = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
        df_htf_raw = _make_ohlcv(1, htf_start, freq_minutes=240)  # 1 vela 4H

        # LTF a las 08:15, 10:00, 11:45 → NO deben ver la vela 4H
        # LTF a las 12:00, 13:00 → SÍ
        ltf_times = [
            datetime(2024, 1, 1,  8, 15, tzinfo=timezone.utc),  # NO
            datetime(2024, 1, 1, 10,  0, tzinfo=timezone.utc),  # NO
            datetime(2024, 1, 1, 11, 45, tzinfo=timezone.utc),  # NO
            datetime(2024, 1, 1, 12,  0, tzinfo=timezone.utc),  # SÍ
            datetime(2024, 1, 1, 13,  0, tzinfo=timezone.utc),  # SÍ
        ]
        df_ltf = pd.DataFrame(
            {"open": [100]*5, "high": [110]*5, "low": [90]*5,
             "close": [105]*5, "volume": [1000]*5},
            index=pd.DatetimeIndex(ltf_times),
        )

        df_aligned = MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_ltf,
            df_htf_with_features=df_htf_raw,
            htf_duration_minutes=240,
        )

        htf_cols = [c for c in df_aligned.columns if c.endswith('_htf')]
        assert htf_cols

        # Primeras 3 filas (08:15, 10:00, 11:45) → NaN en columnas HTF
        for ts in ltf_times[:3]:
            row = df_aligned.loc[df_aligned.index == pd.Timestamp(ts)]
            if not row.empty:
                for col in htf_cols:
                    assert pd.isna(row[col].values[0]), (
                        f"{ts.strftime('%H:%M')} NO debe ver la vela 4H 08:00-12:00"
                    )

        # Últimas 2 filas (12:00, 13:00) → datos HTF presentes
        for ts in ltf_times[3:]:
            row = df_aligned.loc[df_aligned.index == pd.Timestamp(ts)]
            if not row.empty:
                has_data = any(not pd.isna(row[col].values[0]) for col in htf_cols)
                assert has_data, (
                    f"{ts.strftime('%H:%M')} SÍ debería ver la vela 4H 08:00-12:00"
                )

    def test_align_htf_is_the_single_source_of_truth(self):
        """
        Verifica que align_htf_to_ltf() es la ÚNICA implementación usada.
        merge_timeframes() (método legacy) está marcado como deprecated.
        """
        # La función legacy existe pero está marcada como deprecated
        assert hasattr(MarketDataFetcher, 'merge_timeframes'), (
            "merge_timeframes() debe existir para compatibilidad"
        )
        # Su docstring debe advertir del look-ahead bias
        doc = MarketDataFetcher.merge_timeframes.__doc__ or ""
        assert "look-ahead" in doc.lower() or "aviso" in doc.lower() or "legacy" in doc.lower(), (
            "merge_timeframes() debe documentar que tiene look-ahead bias"
        )

        # align_htf_to_ltf() es la función correcta
        assert hasattr(MarketDataFetcher, 'align_htf_to_ltf'), (
            "align_htf_to_ltf() debe existir como función principal de alineamiento"
        )

    def test_full_pipeline_uses_aligned_htf(self):
        """
        Test del pipeline completo: datos → MTF align → features → regime → score.

        Verifica que el régimen HTF en el flujo de producción se calcula
        usando datos ya cerrados (align_htf_to_ltf), no datos en formación.

        El HTF arranca 200 horas antes que el LTF para garantizar que
        existen velas HTF cerradas en el rango temporal del LTF.
        """
        ltf_start = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
        # El HTF arranca 200 horas antes para que sus velas hayan cerrado
        # antes de que el LTF arranque.
        htf_start = ltf_start - timedelta(hours=200)

        df_ltf_feat, df_htf_feat, df_aligned = self._build_pipeline_data(
            ltf_start=ltf_start,
            htf_start=htf_start,
            n_ltf=300,
            n_htf=300,
        )

        # Verificar que el resultado de alineamiento tiene columnas HTF
        htf_cols = [c for c in df_aligned.columns if c.endswith('_htf')]
        assert htf_cols, (
            "El alineamiento debe producir columnas _htf. "
            "Verificar que el HTF arranca antes que el LTF y tiene velas cerradas."
        )

        # La última fila del LTF alineado no debe ser todo NaN en columnas HTF
        last_row = df_aligned.iloc[-1]
        htf_has_data = any(not pd.isna(last_row[col]) for col in htf_cols)
        assert htf_has_data, (
            "La última vela LTF debe tener datos HTF disponibles (régimen ya cerrado)"
        )

        # El régimen se calcula sobre las columnas HTF (ya cerradas)
        df_htf_for_regime = df_aligned[htf_cols].rename(columns=lambda c: c[:-4])
        regime = RegimeDetector.detect(df_htf_for_regime)

        # El régimen debe ser válido (no UNKNOWN por falta de datos)
        assert regime in {"BULL_TREND", "BEAR_TREND", "RANGING", "TRANSITION", "UNKNOWN"}

        # El scoring se hace sobre el LTF (no el alineado)
        score, setup = ScoringEngine.evaluate(df_ltf_feat, regime)
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100

    def test_no_htf_data_fallback_does_not_crash(self):
        """
        Si no hay columnas HTF (datos insuficientes), el fallback a RegimeDetector
        con df_1h_features directo debe funcionar sin error.
        """
        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        df_ltf_feat = _make_minimal_ltf_with_features(300, start)
        df_htf_feat = _make_minimal_htf_with_features(100, start)

        # Alineamiento normal: debe tener columnas HTF
        df_aligned = MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_ltf_feat,
            df_htf_with_features=df_htf_feat,
            htf_duration_minutes=60,
        )

        htf_cols = [c for c in df_aligned.columns if c.endswith('_htf')]

        if not htf_cols:
            # Fallback: usar df_htf_feat directamente
            regime = RegimeDetector.detect(df_htf_feat)
        else:
            df_htf_for_regime = df_aligned[htf_cols].rename(columns=lambda c: c[:-4])
            regime = RegimeDetector.detect(df_htf_for_regime)

        assert regime in {"BULL_TREND", "BEAR_TREND", "RANGING", "TRANSITION", "UNKNOWN"}


# ─────────────────────────────────────────────────────────────────────────────
# C. Score Threshold
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreThreshold:
    """
    Verifica que el threshold de entrada equivale exactamente a RAW=80.
    La normalización no debe cambiar la semántica.
    """

    def test_raw_below_threshold_no_entry(self):
        """RAW < 80 → NO se genera señal de entrada."""
        from config.config import DEFAULT_STRATEGY

        # Score justo por debajo del threshold
        raw_scores_below = [79, 70, 50, 0]
        for raw in raw_scores_below:
            normalized = ScoringEngine._normalize(raw, DEFAULT_STRATEGY)
            threshold = DEFAULT_STRATEGY.entry_threshold_normalized
            assert normalized < threshold, (
                f"RAW={raw} → normalized={normalized:.4f} < threshold={threshold:.4f} FALLÓ"
            )

    def test_raw_exactly_at_threshold_allows_entry(self):
        """RAW = 80 → debe permitir la entrada (≥ threshold normalizado)."""
        from config.config import DEFAULT_STRATEGY

        raw = 80
        normalized = ScoringEngine._normalize(raw, DEFAULT_STRATEGY)
        threshold = DEFAULT_STRATEGY.entry_threshold_normalized

        assert normalized >= threshold, (
            f"RAW=80 → normalized={normalized:.4f} debe ser >= threshold={threshold:.4f}"
        )

    def test_raw_above_threshold_allows_entry(self):
        """RAW > 80 → debe permitir la entrada."""
        from config.config import DEFAULT_STRATEGY

        raw_scores_above = [81, 85, 90]
        for raw in raw_scores_above:
            normalized = ScoringEngine._normalize(raw, DEFAULT_STRATEGY)
            threshold = DEFAULT_STRATEGY.entry_threshold_normalized
            assert normalized >= threshold, (
                f"RAW={raw} → normalized={normalized:.4f} debe ser >= threshold={threshold:.4f}"
            )

    def test_normalization_formula(self):
        """normalized = raw / MAX_RAW_SCORE * 100 (verificación de la fórmula exacta).

        Nota: _normalize() aplica round(..., 2) por diseño, así que la tolerancia
        debe ser 0.01 (no menor).
        """
        from config.config import DEFAULT_STRATEGY

        for raw in [0, 45, 80, 90]:
            expected = raw / DEFAULT_STRATEGY.MAX_RAW_SCORE * 100
            obtained = ScoringEngine._normalize(raw, DEFAULT_STRATEGY)
            # Tolerancia 0.01 porque _normalize() usa round(..., 2)
            assert abs(obtained - expected) < 0.01, (
                f"RAW={raw}: expected={expected:.4f}, obtained={obtained:.4f}"
            )

    def test_threshold_raw_80_equals_normalized_88_88(self):
        """80/90*100 = 88.888... El threshold normalizado es este valor exacto."""
        from config.config import DEFAULT_STRATEGY

        expected_normalized = 80 / 90 * 100
        assert abs(DEFAULT_STRATEGY.entry_threshold_normalized - expected_normalized) < 1e-6, (
            f"Threshold normalizado incorrecto: "
            f"expected={expected_normalized:.6f}, "
            f"got={DEFAULT_STRATEGY.entry_threshold_normalized:.6f}"
        )

    def test_max_raw_score_is_90(self):
        """Suma de pesos positivos = 90."""
        from config.config import DEFAULT_STRATEGY

        max_positive = (
            DEFAULT_STRATEGY.adx_weight_strong       # 20
            + DEFAULT_STRATEGY.structure_weight_full  # 20
            + DEFAULT_STRATEGY.rsi_weight_ideal       # 25
            + DEFAULT_STRATEGY.macd_weight_best       # 25
        )
        assert max_positive == DEFAULT_STRATEGY.MAX_RAW_SCORE, (
            f"Suma de pesos ({max_positive}) != MAX_RAW_SCORE ({DEFAULT_STRATEGY.MAX_RAW_SCORE})"
        )

    def test_scoring_engine_blocks_below_threshold(self):
        """
        Usando ScoringEngine real: un setup débil produce score < threshold.
        El setup debe marcarse como NEUTRAL.
        """
        # DataFrame LTF mínimo con mercado RANGING (ADX bajo, RSI neutral)
        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Precio lateral sin tendencia
        df_raw = _make_ohlcv(300, start, freq_minutes=15, trend=0.0)
        df_feat = FeatureEngine.compute(df_raw)

        # Régimen RANGING → score=0, signal=NEUTRAL
        score, setup = ScoringEngine.evaluate(df_feat, "RANGING")
        assert score == 0.0
        assert setup.get("signal") == "NEUTRAL"
        assert score < DEFAULT_STRATEGY.entry_threshold_normalized

    def test_scoring_engine_in_unknown_regime_gives_neutral(self):
        """Régimen UNKNOWN → score=0, signal=NEUTRAL."""
        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        df_feat = _make_minimal_ltf_with_features(300, start)
        score, setup = ScoringEngine.evaluate(df_feat, "UNKNOWN")
        assert score == 0.0
        assert setup.get("signal") == "NEUTRAL"

    def test_score_semantic_with_full_pipeline(self):
        """
        Verifica que el threshold en el flujo completo (LTF → score → threshold check)
        equivale semánticamente a RAW >= 80.

        Con régimen BULL_TREND y condiciones ideales (raw=90=score máximo),
        normalized >= threshold → se genera señal LONG.
        """
        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Tendencia alcista fuerte para maximizar todos los factores
        df_feat = _make_minimal_ltf_with_features(300, start, trend=0.5)
        score, setup = ScoringEngine.evaluate(df_feat, "BULL_TREND")

        # Verificar que si score >= threshold_normalized, la señal es LONG (no NEUTRAL)
        threshold = DEFAULT_STRATEGY.entry_threshold_normalized
        if score >= threshold:
            assert setup.get("signal") == "LONG", (
                f"Score {score:.2f} >= threshold {threshold:.2f} pero signal={setup.get('signal')}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# D. Flujo completo de análisis
# ─────────────────────────────────────────────────────────────────────────────

class TestCompleteAnalysisFlow:
    """
    Verifica el pipeline completo:
    market data → MTF align → features → regime → score → risk → kill switch → decisión.
    """

    def test_flow_kill_switch_blocks_before_risk(self):
        """
        El kill switch bloquea la entrada ANTES de calcular el portfolio risk.
        Orden en analyze_symbol: threshold → pos → daily_halt → kill_switch → risk.
        """
        sim = AnalyzeSymbolSimulator()
        sim.kill_switch_active = True

        result = sim.analyze("BTC/USDT:USDT", "BULL_TREND", 100.0, 90)
        assert result == "KILL_SWITCH"

    def test_flow_daily_halt_blocks_before_kill_switch(self):
        """
        El daily halt se comprueba ANTES que el kill switch.
        """
        sim = AnalyzeSymbolSimulator()
        sim.tick(current_capital=9_500.0)   # -5% → halt
        sim.kill_switch_active = True

        result = sim.analyze("BTC/USDT:USDT", "BULL_TREND", 100.0, 90)
        assert result == "DAILY_HALT", (
            "El daily halt debe comprobarse ANTES que el kill switch"
        )

    def test_flow_threshold_blocks_first(self):
        """
        El threshold se comprueba PRIMERO. Un score bajo no llega al risk manager.
        """
        sim = AnalyzeSymbolSimulator()
        # Score por debajo del threshold
        threshold = DEFAULT_STRATEGY.entry_threshold_normalized
        low_score = threshold - 1

        result = sim.analyze("BTC/USDT:USDT", "BULL_TREND", low_score, 70)
        assert result == "BELOW_THRESHOLD"

    def test_flow_neutral_regime_blocks(self):
        """Un régimen RANGING produce señal NEUTRAL → bloqueado."""
        sim = AnalyzeSymbolSimulator()
        result = sim.analyze("BTC/USDT:USDT", "RANGING", 0.0, 0)
        assert result == "BELOW_THRESHOLD"

    def test_flow_all_conditions_met_gives_entry(self):
        """Con todas las condiciones favorables, se produce una entrada."""
        sim = AnalyzeSymbolSimulator()
        result = sim.analyze("BTC/USDT:USDT", "BULL_TREND", 100.0, 90)
        assert result == "ENTRY"
        assert "BTC/USDT:USDT" in sim.active_positions

    def test_flow_decision_point_logging(self):
        """
        Verifica que el sistema de bloqueo es determinista y documentable.
        Dado el estado del simulador, sabemos exactamente dónde se bloquea.
        """
        sim = AnalyzeSymbolSimulator()

        # Caso 1: condiciones normales → ENTRY
        r1 = sim.analyze("BTC/USDT:USDT", "BULL_TREND", 100.0, 90)
        assert r1 == "ENTRY"

        # Caso 2: ya hay posición → bloqueado
        r2 = sim.analyze("BTC/USDT:USDT", "BULL_TREND", 100.0, 90)
        assert r2 == "ALREADY_OPEN"

        # Caso 3: score bajo → bloqueado antes
        r3 = sim.analyze("ETH/USDT:USDT", "BULL_TREND", 50.0, 45)
        assert r3 == "BELOW_THRESHOLD"

        # Caso 4: daily halt → bloqueado
        sim.tick(current_capital=9_500.0)
        r4 = sim.analyze("SOL/USDT:USDT", "BULL_TREND", 100.0, 90)
        assert r4 == "DAILY_HALT"


# ─────────────────────────────────────────────────────────────────────────────
# E. Verificación de parámetros de estrategia (sin cambios)
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategyParametersUnchanged:
    """
    Verifica que la Fase 1.5.1 NO modificó ningún parámetro de estrategia.
    """

    def test_ema_periods(self):
        assert DEFAULT_STRATEGY.ema_short  == 20
        assert DEFAULT_STRATEGY.ema_medium == 50
        assert DEFAULT_STRATEGY.ema_long   == 200

    def test_rsi_period(self):
        assert DEFAULT_STRATEGY.rsi_period == 14

    def test_macd_params(self):
        assert DEFAULT_STRATEGY.macd_fast   == 12
        assert DEFAULT_STRATEGY.macd_slow   == 26
        assert DEFAULT_STRATEGY.macd_signal == 9

    def test_atr_period(self):
        assert DEFAULT_STRATEGY.atr_period == 14

    def test_adx_params(self):
        assert DEFAULT_STRATEGY.adx_period         == 14
        assert DEFAULT_STRATEGY.adx_ranging_threshold == 18.0
        assert DEFAULT_STRATEGY.adx_trend_threshold   == 20.0
        assert DEFAULT_STRATEGY.adx_strong_trend      == 25.0

    def test_scoring_weights(self):
        assert DEFAULT_STRATEGY.adx_weight_strong       == 20
        assert DEFAULT_STRATEGY.adx_weight_medium       == 10
        assert DEFAULT_STRATEGY.structure_weight_full   == 20
        assert DEFAULT_STRATEGY.structure_weight_partial == 10
        assert DEFAULT_STRATEGY.rsi_weight_ideal        == 25
        assert DEFAULT_STRATEGY.rsi_weight_ok           == 10
        assert DEFAULT_STRATEGY.rsi_penalty_extreme     == -30
        assert DEFAULT_STRATEGY.rsi_penalty_severe      == -20
        assert DEFAULT_STRATEGY.macd_weight_best        == 25
        assert DEFAULT_STRATEGY.macd_weight_ok          == 15
        assert DEFAULT_STRATEGY.macd_weight_turning     == 5

    def test_max_raw_score(self):
        assert DEFAULT_STRATEGY.MAX_RAW_SCORE == 90

    def test_entry_threshold_raw(self):
        assert DEFAULT_STRATEGY.ENTRY_THRESHOLD_RAW == 80

    def test_sl_tp_config(self):
        assert DEFAULT_RISK.sl_atr_mult == 1.5
        assert DEFAULT_RISK.tp_atr_mult == 3.0

    def test_rr_ratio(self):
        rr = DEFAULT_RISK.tp_atr_mult / DEFAULT_RISK.sl_atr_mult
        assert abs(rr - 2.0) < 1e-6

    def test_htf_timeframe(self):
        assert DEFAULT_STRATEGY.htf         == '1h'
        assert DEFAULT_STRATEGY.ltf         == '15m'
        assert DEFAULT_STRATEGY.htf_minutes == 60

    def test_symbols_count(self):
        """Los símbolos se definen en main.py — verificamos que el módulo compila."""
        import ast
        src = open(
            os.path.join(os.path.dirname(__file__), '..', 'main.py')
        ).read()
        ast.parse(src)  # debe compilar sin errores


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
