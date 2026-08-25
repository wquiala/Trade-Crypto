"""
tests/test_risk_manager.py
==========================
Tests del RiskManager, PortfolioRiskManager y Daily Halt.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.risk_manager import RiskManager
from core.portfolio_risk import PortfolioRiskManager
from config.config import RiskConfig, CostConfig


# ─────────────────────────────────────────────────────────────────────────────
# RiskManager — Position Sizing
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskManagerSizing:

    def _make_setup(self, signal="LONG", entry=50000.0, atr=500.0):
        return {"signal": signal, "entry_price": entry, "atr": atr, "regime": "BULL_TREND"}

    def test_basic_sizing_long(self):
        """El sizing debe calcular un tamaño que implique risk_amount en el SL.

        Parámetros: entry=$1, atr=$0.01, capital=$1000, risk=1%
        - risk_amount = 1000 * 0.01 = $10
        - sl_distance = 0.01 * 1.5 = $0.015
        - size = $10 / $0.015 = 666.67 units
        - notional = 666.67 * $1 = $666.67 < capital $1000 (sin margin cap)
        """
        setup = self._make_setup(entry=1.0, atr=0.01)
        risk_cfg = RiskConfig(risk_per_trade_pct=0.01, sl_atr_mult=1.5, leverage=1.0)
        cost_cfg = CostConfig(taker_fee_rate=0.0, entry_slippage=0.0, exit_slippage=0.0,
                              spread_bps=0.0, apply_funding=False)

        approved, size, details = RiskManager.validate_and_size(
            setup, current_capital=1000.0, risk_config=risk_cfg, cost_config=cost_cfg
        )

        assert approved
        assert size > 0

        # size = (1000 * 0.01) / (0.01 * 1.5) = 666.67 units
        expected_size = (1000.0 * 0.01) / (0.01 * 1.5)
        assert abs(size - expected_size) < 0.01, f"Size esperado {expected_size:.4f}, obtenido {size:.4f}"

    def test_fees_reduce_effective_size(self):
        """Con fees, el position size debe ser MENOR que sin fees (riesgo neto < bruto)."""
        # entry=$1, atr=$0.01 -> sl_dist=$0.015, notional~$667 con capital $10_000
        # Asegúrate que el notional esté bien por debajo del capital para evitar margin cap
        setup_no_fee   = self._make_setup(entry=1.0, atr=0.01)
        setup_with_fee = self._make_setup(entry=1.0, atr=0.01)

        risk_cfg = RiskConfig(risk_per_trade_pct=0.01, sl_atr_mult=1.5, leverage=1.0)
        no_fee_cfg   = CostConfig(taker_fee_rate=0.0, entry_slippage=0.0,
                                   exit_slippage=0.0, spread_bps=0.0)
        with_fee_cfg = CostConfig(taker_fee_rate=0.0005, entry_slippage=0.0002,
                                   exit_slippage=0.0002, spread_bps=0.0002)

        _, size_no_fee,   _ = RiskManager.validate_and_size(setup_no_fee,   1000.0, risk_cfg, no_fee_cfg)
        _, size_with_fee, _ = RiskManager.validate_and_size(setup_with_fee, 1000.0, risk_cfg, with_fee_cfg)

        assert size_with_fee < size_no_fee, (
            f"Con fees ({size_with_fee:.4f}), el size debe ser menor que sin fees ({size_no_fee:.4f})."
        )

    def test_sl_level_correct_long(self):
        """SL = entry - ATR * mult para LONG."""
        setup = self._make_setup(signal="LONG", entry=50000.0, atr=500.0)
        risk_cfg = RiskConfig(sl_atr_mult=1.5, tp_atr_mult=3.0, leverage=1.0)
        approved, _, details = RiskManager.validate_and_size(setup, 1000.0, risk_cfg)

        assert approved
        expected_sl = 50000.0 - (500.0 * 1.5)
        assert abs(details["stop_loss"] - expected_sl) < 0.01

    def test_sl_level_correct_short(self):
        """SL = entry + ATR * mult para SHORT."""
        setup = self._make_setup(signal="SHORT", entry=50000.0, atr=500.0)
        risk_cfg = RiskConfig(sl_atr_mult=1.5, tp_atr_mult=3.0, leverage=1.0)
        approved, _, details = RiskManager.validate_and_size(setup, 1000.0, risk_cfg)

        assert approved
        expected_sl = 50000.0 + (500.0 * 1.5)
        assert abs(details["stop_loss"] - expected_sl) < 0.01

    def test_tp_level_correct_long(self):
        """TP = entry + ATR * tp_mult para LONG."""
        setup = self._make_setup(signal="LONG", entry=50000.0, atr=500.0)
        risk_cfg = RiskConfig(sl_atr_mult=1.5, tp_atr_mult=3.0, leverage=1.0)
        approved, _, details = RiskManager.validate_and_size(setup, 1000.0, risk_cfg)

        expected_tp = 50000.0 + (500.0 * 3.0)
        assert abs(details["take_profit"] - expected_tp) < 0.01

    def test_rr_ratio_correct(self):
        """RR = tp_atr_mult / sl_atr_mult."""
        setup = self._make_setup(entry=50000.0, atr=500.0)
        risk_cfg = RiskConfig(sl_atr_mult=1.5, tp_atr_mult=3.0, leverage=1.0)
        _, _, details = RiskManager.validate_and_size(setup, 1000.0, risk_cfg)

        assert abs(details["rr_ratio"] - 2.0) < 1e-6

    def test_invalid_atr_rejected(self):
        """Setup con ATR=0 debe ser rechazado."""
        setup = {"signal": "LONG", "entry_price": 50000.0, "atr": 0.0}
        approved, size, _ = RiskManager.validate_and_size(setup, 1000.0)
        assert not approved
        assert size == 0.0

    def test_neutral_signal_rejected(self):
        """Señal NEUTRAL nunca genera una posición."""
        setup = {"signal": "NEUTRAL", "entry_price": 50000.0, "atr": 500.0}
        approved, size, _ = RiskManager.validate_and_size(setup, 1000.0)
        assert not approved
        assert size == 0.0

    def test_notional_vs_margin_with_leverage(self):
        """Con leverage=2, el margin debe ser la mitad del notional."""
        setup = self._make_setup(entry=100.0, atr=1.0)
        risk_cfg = RiskConfig(risk_per_trade_pct=0.02, sl_atr_mult=1.5,
                               tp_atr_mult=3.0, leverage=2.0)
        cost_cfg = CostConfig(taker_fee_rate=0.0, entry_slippage=0.0,
                               exit_slippage=0.0, spread_bps=0.0)

        approved, size, details = RiskManager.validate_and_size(setup, 1000.0, risk_cfg, cost_cfg)
        assert approved
        assert abs(details["margin"] - details["notional"] / 2.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# PortfolioRiskManager — Daily Halt
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyHalt:

    def test_halt_not_active_initially(self):
        """El daily halt no debe estar activo al inicio."""
        prm = PortfolioRiskManager()
        prm.initialize_day(capital=1000.0)
        assert not prm.is_daily_halt_active

    def test_halt_activates_when_loss_exceeds_limit(self):
        """
        Pérdida > MAX_DAILY_LOSS_PCT → halt activo.
        Por defecto MAX_DAILY_LOSS_PCT = 3%.
        """
        cfg = RiskConfig(max_daily_loss_pct=0.03)
        prm = PortfolioRiskManager(config=cfg)
        prm.initialize_day(capital=1000.0)

        # Capital cae de $1000 a $965 → pérdida del 3.5% (supera el 3%)
        prm.check_and_update_daily_state(current_capital=965.0)

        assert prm.is_daily_halt_active

    def test_halt_not_activates_below_threshold(self):
        """Pérdida < MAX_DAILY_LOSS_PCT → halt NO activo."""
        cfg = RiskConfig(max_daily_loss_pct=0.03)
        prm = PortfolioRiskManager(config=cfg)
        prm.initialize_day(capital=1000.0)

        # Capital cae de $1000 a $985 → pérdida del 1.5% (bajo el límite del 3%)
        prm.check_and_update_daily_state(current_capital=985.0)

        assert not prm.is_daily_halt_active

    def test_halt_persists_across_multiple_loops(self):
        """
        Una vez activado, el halt NO se resetea en siguientes iteraciones del loop.
        Este es el bug original de main.py (línea 123).
        """
        cfg = RiskConfig(max_daily_loss_pct=0.03)
        prm = PortfolioRiskManager(config=cfg)
        prm.initialize_day(capital=1000.0)

        # Activar el halt (pérdida del 4%)
        prm.check_and_update_daily_state(current_capital=960.0)
        assert prm.is_daily_halt_active, "El halt debería estar activo"

        # Simular 10 iteraciones adicionales del loop principal
        for i in range(10):
            prm.check_and_update_daily_state(current_capital=975.0)  # incluso si el capital "sube"
            assert prm.is_daily_halt_active, (
                f"El halt se desactivó en la iteración {i+1} del loop — BUG detectado"
            )

    def test_halt_resets_on_new_day(self, monkeypatch):
        """
        El halt SOLO se resetea cuando comienza un nuevo día UTC.
        """
        import core.portfolio_risk as pm_module

        cfg = RiskConfig(max_daily_loss_pct=0.03)
        prm = PortfolioRiskManager(config=cfg)
        prm.initialize_day(capital=1000.0)

        # Activar halt
        prm.check_and_update_daily_state(current_capital=960.0)
        assert prm.is_daily_halt_active

        # Simular que ha pasado a un nuevo día
        monkeypatch.setattr(
            pm_module.PortfolioRiskManager,
            "_today_utc",
            staticmethod(lambda: "2099-12-31")  # Día diferente al actual
        )

        # La siguiente llamada debe detectar el nuevo día y resetear el halt
        prm.check_and_update_daily_state(current_capital=1000.0)
        assert not prm.is_daily_halt_active, "El halt debería resetearse al comienzo de un nuevo día"

    def test_can_open_position_blocked_during_halt(self):
        """can_open_position debe retornar False cuando el halt está activo."""
        cfg = RiskConfig(max_daily_loss_pct=0.03)
        prm = PortfolioRiskManager(config=cfg)
        prm.initialize_day(capital=1000.0)

        # Activar halt
        prm.check_and_update_daily_state(current_capital=960.0)

        allowed, reason = prm.can_open_position(
            symbol="BTC/USDT:USDT",
            signal="LONG",
            new_risk_amount=20.0,
            positions={},
            current_prices={},
            current_capital=960.0,
        )

        assert not allowed
        assert "DAILY_HALT" in reason


# ─────────────────────────────────────────────────────────────────────────────
# PortfolioRiskManager — Portfolio Risk
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioRisk:

    def _make_position(self, signal="LONG", entry=50000.0, sl=49000.0, size=0.01):
        return {
            "signal": signal,
            "entry_price": entry,
            "stop_loss": sl,
            "take_profit": entry * 1.05,
            "size": size,
        }

    def test_portfolio_risk_calculation(self):
        """El riesgo del portfolio debe ser la suma de riesgos individuales."""
        prm = PortfolioRiskManager()

        # Posición 1: entry=50000, SL=49250, size=0.02 → risk = 750 * 0.02 = $15
        # Posición 2: entry=2000, SL=1970, size=0.5  → risk = 30 * 0.5 = $15
        positions = {
            "BTC/USDT:USDT": self._make_position(entry=50000.0, sl=49250.0, size=0.02),
            "ETH/USDT:USDT": self._make_position(entry=2000.0,  sl=1970.0,  size=0.5),
        }
        capital = 1000.0
        portfolio_risk_pct = prm.get_current_portfolio_risk(positions, capital)

        # Risk total = $15 + $15 = $30 → 3% de $1000
        assert abs(portfolio_risk_pct - 0.03) < 1e-4

    def test_max_portfolio_risk_blocks_new_trade(self):
        """Si el portfolio risk ya está al límite, no se pueden abrir más posiciones."""
        cfg = RiskConfig(max_portfolio_risk_pct=0.04)  # Límite 4%
        prm = PortfolioRiskManager(config=cfg)
        prm.initialize_day(capital=1000.0)

        # Posiciones actuales con 3.5% de riesgo
        positions = {
            "BTC/USDT:USDT": self._make_position(entry=50000.0, sl=49125.0, size=0.04),
        }
        # BTC: SL distance = 875, size = 0.04 → risk = 875 * 0.04 = $35 = 3.5%

        # Intentar añadir otra con 1% de riesgo → total sería 4.5% > límite 4%
        allowed, reason = prm.can_open_position(
            symbol="ETH/USDT:USDT",
            signal="LONG",
            new_risk_amount=10.0,  # 1% de $1000
            positions=positions,
            current_prices={},
            current_capital=1000.0,
        )

        assert not allowed
        assert "PORTFOLIO_RISK" in reason

    def test_max_long_exposure_blocks_new_long(self):
        """Si la exposición LONG alcanza el límite, rechazar nuevos LONG."""
        cfg = RiskConfig(max_long_exposure_pct=0.40)
        prm = PortfolioRiskManager(config=cfg)
        prm.initialize_day(capital=1000.0)

        # Posición LONG actual: 50 contratos a $10 = $500 = 50% del capital (supera el 40%)
        positions = {
            "SOL/USDT:USDT": {"signal": "LONG", "entry_price": 10.0, "stop_loss": 9.0,
                               "take_profit": 12.0, "size": 50.0},
        }
        prices = {"SOL/USDT:USDT": 10.0}

        allowed, reason = prm.can_open_position(
            symbol="BTC/USDT:USDT",
            signal="LONG",
            new_risk_amount=5.0,
            positions=positions,
            current_prices=prices,
            current_capital=1000.0,
        )

        assert not allowed
        assert "LONG_EXPOSURE" in reason

    def test_empty_portfolio_allows_new_position(self):
        """Portfolio vacío siempre debe permitir una nueva posición (si el risk es válido)."""
        cfg = RiskConfig(max_portfolio_risk_pct=0.06, max_concurrent_positions=7)
        prm = PortfolioRiskManager(config=cfg)
        prm.initialize_day(capital=1000.0)

        allowed, reason = prm.can_open_position(
            symbol="BTC/USDT:USDT",
            signal="LONG",
            new_risk_amount=20.0,  # 2% de $1000 — dentro del límite de 6%
            positions={},
            current_prices={},
            current_capital=1000.0,
        )

        assert allowed, f"Portfolio vacío debería permitir la posición. Razón: {reason}"


# ─────────────────────────────────────────────────────────────────────────────
# Scoring Engine — Threshold normalizado
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringThreshold:
    """Tests para verificar que la normalización del scoring no cambia el comportamiento."""

    def test_normalized_threshold_equivalent(self):
        """El threshold normalizado debe ser exactamente 80/90*100."""
        from config.config import StrategyConfig
        cfg = StrategyConfig()
        expected = 80 / 90 * 100
        assert abs(cfg.entry_threshold_normalized - expected) < 1e-6

    def test_max_score_is_90_raw(self):
        """El máximo teórico de score raw debe ser 90."""
        from config.config import StrategyConfig
        cfg = StrategyConfig()
        max_possible = (
            cfg.adx_weight_strong +
            cfg.structure_weight_full +
            cfg.rsi_weight_ideal +
            cfg.macd_weight_best
        )
        assert max_possible == 90, f"Max score esperado 90, obtenido {max_possible}"

    def test_score_normalizes_correctly(self):
        """Un score raw de 90 debe normalizarse a exactamente 100."""
        from core.scoring_engine import ScoringEngine
        from config.config import StrategyConfig
        cfg = StrategyConfig()
        normalized = ScoringEngine._normalize(90, cfg)
        assert abs(normalized - 100.0) < 1e-6

    def test_score_at_threshold_boundary(self):
        """Un score raw de 80 debe normalizarse a ~88.88, justo en el threshold."""
        from core.scoring_engine import ScoringEngine
        from config.config import StrategyConfig
        cfg = StrategyConfig()
        normalized = ScoringEngine._normalize(80, cfg)
        expected = 80 / 90 * 100
        assert abs(normalized - expected) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
