"""
tests/test_integration_daily_halt.py
=====================================
Tests de INTEGRACIÓN que reproducen el flujo real de main.py
con respecto al Daily Halt.

Qué se verifica aquí
─────────────────────
1. daily_loss > limit  → halt activado
2. siguiente loop      → NO nuevas entradas
3. 10 loops después    → sigue sin entradas
4. nuevo día           → halt reseteado, entradas permitidas

Diferencia con test_risk_manager.py
─────────────────────────────────────
Los tests de test_risk_manager.py prueban el módulo PortfolioRiskManager
de forma aislada.

Este test reproduce el flujo COMPLETO de main.py:
- Simula el ticker_loop (actualiza daily halt con capital)
- Simula el analyze_symbol (consulta el halt antes de operar)
- Verifica que NO hay ningún reset incondicional entre medias

No se conecta a ningún exchange. No se ejecutan órdenes reales.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.portfolio_risk import PortfolioRiskManager
from config.config import RiskConfig


# ─────────────────────────────────────────────────────────────────────────────
# Simulación del flujo de main.py
# ─────────────────────────────────────────────────────────────────────────────

class MainLoopSimulator:
    """
    Simula el flujo de main.py sin conectarse a ningún exchange.

    Reproduce:
    - ticker_loop: actualiza el daily halt con el capital actual.
    - analyze_symbol: consulta el halt antes de intentar abrir una posición.
    - daily_reset: inicializa el día cuando cambia la fecha UTC.
    """

    def __init__(self, initial_capital: float, max_daily_loss_pct: float = 0.03):
        config = RiskConfig(max_daily_loss_pct=max_daily_loss_pct)
        self.portfolio_risk = PortfolioRiskManager(config=config)
        self.portfolio_risk.initialize_day(capital=initial_capital)
        self.capital = initial_capital
        self.entry_attempts: list[dict] = []   # log de intentos de entrada
        self.entries_opened: list[dict] = []   # entradas efectivamente abiertas

    def ticker_loop_iteration(self, current_capital: float, new_day: bool = False, new_day_str: str = "2099-12-31"):
        """
        Simula una iteración del ticker_loop de main.py.

        Notas importantes sobre la implementación real:
        - check_and_update_daily_state() puede ACTIVAR el halt pero NO lo desactiva.
        - El daily reset solo ocurre cuando cambia la fecha UTC.
        - NO hay ningún `kill_switch_active = False` incondicional.
        """
        self.capital = current_capital

        if new_day:
            # Simula el reset diario de main.py
            self.portfolio_risk.initialize_day(capital=current_capital)
        else:
            # Simula check_and_update_daily_state del ticker_loop
            self.portfolio_risk.check_and_update_daily_state(current_capital=current_capital)

    def analyze_symbol_iteration(self, symbol: str, signal: str = "LONG") -> bool:
        """
        Simula analyze_symbol de main.py.

        Returns:
            True si se habría abierto una posición, False si se bloqueó.
        """
        attempt = {"symbol": symbol, "signal": signal, "capital": self.capital}
        self.entry_attempts.append(attempt)

        # DAILY HALT CHECK — equivalente al check en analyze_symbol
        if self.portfolio_risk.is_daily_halt_active:
            attempt["blocked_by"] = "DAILY_HALT"
            return False

        # Aquí en la implementación real habría más checks (portfolio risk, etc.)
        # Para este test de integración solo verificamos el halt.
        self.entries_opened.append(attempt)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Tests de integración
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyHaltIntegration:
    """
    Reproduces el flujo completo descrito en el spec de la Fase 1.5:

        daily_loss > limit → halt
        siguiente loop     → NO nuevas entradas
        10 loops           → NO nuevas entradas
        nuevo día          → reset
    """

    def test_full_daily_halt_flow(self):
        """
        Flujo completo del daily halt tal como ocurre en main.py.

        Paso 1: Capital inicial = $1000
        Paso 2: Capital cae a $960 (pérdida del 4% > límite del 3%)
        Paso 3: ticker_loop detecta la pérdida → halt activo
        Paso 4: analyze_symbol intenta entrar → bloqueado
        Paso 5: 10 iteraciones más del loop → sigue bloqueado
        Paso 6: nuevo día → halt reseteado → entradas permitidas
        """
        sim = MainLoopSimulator(initial_capital=1000.0, max_daily_loss_pct=0.03)

        # ── PASO 1: Sin pérdidas, la entrada debe funcionar ──
        sim.ticker_loop_iteration(current_capital=1000.0)
        result_before_loss = sim.analyze_symbol_iteration("BTC/USDT:USDT", "LONG")
        assert result_before_loss, "Antes de pérdidas, la entrada debería estar permitida"
        assert not sim.portfolio_risk.is_daily_halt_active

        # ── PASO 2-3: Capital cae por debajo del límite ──
        sim.ticker_loop_iteration(current_capital=960.0)  # -4% > -3% límite
        assert sim.portfolio_risk.is_daily_halt_active, (
            "El daily halt debería activarse cuando la pérdida supera el límite"
        )

        # ── PASO 4: Primer intento de entrada bloqueado ──
        result = sim.analyze_symbol_iteration("BTC/USDT:USDT", "LONG")
        assert not result, "analyze_symbol debería bloquear la entrada cuando el halt está activo"

        # ── PASO 5: 10 iteraciones más del loop principal ──
        for i in range(10):
            # ticker_loop no resetea el halt — solo comprueba si empeoró
            sim.ticker_loop_iteration(current_capital=965.0)
            assert sim.portfolio_risk.is_daily_halt_active, (
                f"El halt se desactivó en la iteración {i+1} del loop — BUG detectado en main.py"
            )

            # analyze_symbol sigue bloqueado
            result = sim.analyze_symbol_iteration(f"ETH/USDT:USDT", "LONG")
            assert not result, (
                f"La entrada debería seguir bloqueada en la iteración {i+1}"
            )

        # ── PASO 6: Nuevo día → reset ──
        sim.ticker_loop_iteration(current_capital=965.0, new_day=True)
        assert not sim.portfolio_risk.is_daily_halt_active, (
            "El halt debería resetearse al inicio de un nuevo día"
        )

        # Ahora las entradas vuelven a estar permitidas
        result_after_reset = sim.analyze_symbol_iteration("SOL/USDT:USDT", "LONG")
        assert result_after_reset, "Después del reset diario, la entrada debería estar permitida"

    def test_halt_at_exact_threshold(self):
        """
        En el límite exacto (pérdida = 3.0%), el halt debe activarse.
        """
        sim = MainLoopSimulator(initial_capital=1000.0, max_daily_loss_pct=0.03)

        # Capital cae exactamente al 3%
        sim.ticker_loop_iteration(current_capital=970.0)  # -3.0%
        assert sim.portfolio_risk.is_daily_halt_active, (
            "El halt debe activarse cuando la pérdida alcanza exactamente el límite"
        )

    def test_no_halt_just_below_threshold(self):
        """
        Por debajo del límite (pérdida = 2.9%), el halt NO debe activarse.
        """
        sim = MainLoopSimulator(initial_capital=1000.0, max_daily_loss_pct=0.03)

        # Capital cae al 2.9%
        sim.ticker_loop_iteration(current_capital=971.0)  # -2.9%
        assert not sim.portfolio_risk.is_daily_halt_active, (
            "El halt NO debe activarse cuando la pérdida está por debajo del límite"
        )

    def test_halt_not_reset_by_capital_recovery(self):
        """
        Si el capital se recupera parcialmente DESPUÉS de que el halt está activo,
        el halt NO debe desactivarse. Solo el nuevo día lo puede resetear.
        """
        sim = MainLoopSimulator(initial_capital=1000.0, max_daily_loss_pct=0.03)

        # Activar halt
        sim.ticker_loop_iteration(current_capital=960.0)  # -4%
        assert sim.portfolio_risk.is_daily_halt_active

        # Capital "se recupera" parcialmente (sigue bajo el límite del inicio de día)
        sim.ticker_loop_iteration(current_capital=985.0)  # -1.5%
        assert sim.portfolio_risk.is_daily_halt_active, (
            "El halt NO debe desactivarse aunque el capital se recupere parcialmente. "
            "Solo un nuevo día puede resetearlo."
        )

    def test_multiple_symbols_all_blocked_during_halt(self):
        """
        Durante el halt, TODOS los símbolos quedan bloqueados,
        independientemente de la señal (LONG o SHORT).
        """
        sim = MainLoopSimulator(initial_capital=1000.0, max_daily_loss_pct=0.03)

        # Activar halt
        sim.ticker_loop_iteration(current_capital=960.0)

        symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
        for sym in symbols:
            for signal in ["LONG", "SHORT"]:
                result = sim.analyze_symbol_iteration(sym, signal)
                assert not result, (
                    f"[{sym}] {signal} debería estar bloqueado durante el daily halt"
                )

    def test_entries_before_halt_are_recorded(self):
        """
        Las entradas realizadas ANTES del halt deben quedar registradas.
        Solo se bloquean las entradas NUEVAS después del halt.
        """
        sim = MainLoopSimulator(initial_capital=1000.0, max_daily_loss_pct=0.03)

        # Entrada antes del halt
        sim.ticker_loop_iteration(current_capital=1000.0)
        sim.analyze_symbol_iteration("BTC/USDT:USDT", "LONG")   # Debe abrirse

        # Activar halt
        sim.ticker_loop_iteration(current_capital=960.0)

        # Entrada después del halt
        sim.analyze_symbol_iteration("ETH/USDT:USDT", "LONG")   # Debe bloquearse

        assert len(sim.entries_opened) == 1, (
            f"Solo debería haber 1 entrada abierta (antes del halt), pero hay {len(sim.entries_opened)}"
        )
        assert sim.entries_opened[0]["symbol"] == "BTC/USDT:USDT"


# ─────────────────────────────────────────────────────────────────────────────
# Test de documentación de costes
# ─────────────────────────────────────────────────────────────────────────────

class TestCostModel:
    """
    Verifica el modelo de costes y que el spread NO se contabiliza dos veces.

    Precio efectivo de ejecución
    ─────────────────────────────
    LONG:
        effective_entry = market_price * (1 + entry_fee + entry_slippage + spread_bps/2)
        effective_exit  = market_price * (1 - exit_fee  - exit_slippage  - spread_bps/2)

    SHORT:
        effective_entry = market_price * (1 - entry_fee - entry_slippage - spread_bps/2)
        effective_exit  = market_price * (1 + exit_fee  + exit_slippage  + spread_bps/2)

    El spread se divide entre 2 porque representa la distancia bid-ask.
    La entrada "compra" al ask (market_price + spread/2).
    La salida "vende" al bid (market_price - spread/2).
    El coste del spread por vuelta completa es spread_bps completo (entrada + salida = spread_bps/2 × 2 = spread_bps).
    """

    def test_spread_not_double_counted(self):
        """
        El spread se aplica media vez en entrada y media vez en salida.
        El coste total del spread por vuelta = spread_bps, NO 2 × spread_bps.
        """
        from config.config import CostConfig

        spread_bps = 0.0004  # 4 bps
        cost = CostConfig(
            taker_fee_rate=0.0,
            entry_slippage=0.0,
            exit_slippage=0.0,
            spread_bps=spread_bps,
        )

        total = cost.total_round_trip_cost()

        # El total debe incluir spread_bps solo UNA vez (ya está en total_round_trip_cost)
        expected = spread_bps  # solo el spread, sin fees ni slippage
        assert abs(total - expected) < 1e-10, (
            f"Spread contabilizado incorrectamente. Esperado {expected:.6f}, obtenido {total:.6f}"
        )

    def test_total_cost_is_sum_of_components(self):
        """
        El coste total round-trip debe ser la suma exacta de todos los componentes,
        cada uno contado UNA SOLA VEZ.
        """
        from config.config import CostConfig

        fee = 0.0005
        slippage_in  = 0.0002
        slippage_out = 0.0002
        spread = 0.0002

        cost = CostConfig(
            taker_fee_rate=fee,
            entry_slippage=slippage_in,
            exit_slippage=slippage_out,
            spread_bps=spread,
        )

        total = cost.total_round_trip_cost()

        # Componentes:
        # - fee entrada: fee
        # - fee salida: fee
        # - slippage entrada: slippage_in
        # - slippage salida: slippage_out
        # - spread: spread (UNA vez, ya dividido internamente entre entrada/salida)
        expected = fee + fee + slippage_in + slippage_out + spread
        assert abs(total - expected) < 1e-10, (
            f"Coste total incorrecto. Esperado {expected:.6f} ({expected*100:.4f}%), "
            f"obtenido {total:.6f} ({total*100:.4f}%)"
        )

    def test_no_fees_gives_only_spread(self):
        """Sin fees ni slippage, el único coste es el spread."""
        from config.config import CostConfig

        cost = CostConfig(
            taker_fee_rate=0.0,
            entry_slippage=0.0,
            exit_slippage=0.0,
            spread_bps=0.0003,
        )
        assert abs(cost.total_round_trip_cost() - 0.0003) < 1e-10

    def test_risk_manager_uses_only_entry_costs(self):
        """
        El RiskManager descuenta del risk_amount solo los costes de ENTRADA,
        no los de salida. Los de salida afectan al PnL real, no al sizing.
        """
        from core.risk_manager import RiskManager
        from config.config import RiskConfig, CostConfig

        setup = {"signal": "LONG", "entry_price": 1.0, "atr": 0.01, "regime": "BULL_TREND"}
        capital = 1000.0
        risk_cfg = RiskConfig(risk_per_trade_pct=0.01, sl_atr_mult=1.5, leverage=1.0)

        # Solo fees de entrada (sin exit)
        cost_entry_only = CostConfig(
            taker_fee_rate=0.0005,  # entrada
            entry_slippage=0.0002,
            exit_slippage=0.0,     # sin slippage de salida
            spread_bps=0.0,
        )
        _, size1, details1 = RiskManager.validate_and_size(
            {"signal": "LONG", "entry_price": 1.0, "atr": 0.01, "regime": "BULL_TREND"},
            capital, risk_cfg, cost_entry_only
        )

        # Con fees de entrada + salida
        cost_both = CostConfig(
            taker_fee_rate=0.0005,
            entry_slippage=0.0002,
            exit_slippage=0.0002,  # con slippage de salida
            spread_bps=0.0,
        )
        _, size2, details2 = RiskManager.validate_and_size(
            {"signal": "LONG", "entry_price": 1.0, "atr": 0.01, "regime": "BULL_TREND"},
            capital, risk_cfg, cost_both
        )

        # El exit_slippage NO debe afectar al sizing (solo al PnL real)
        # Por tanto size1 debe ser igual a size2
        assert abs(size1 - size2) < 0.01, (
            f"El exit_slippage NO debería afectar al sizing: size1={size1:.4f}, size2={size2:.4f}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test de importación y compilación de módulos
# ─────────────────────────────────────────────────────────────────────────────

class TestModuleImports:
    """
    Verifica que todos los módulos modificados en el Bloque 1 y Fase 1.5
    se importan correctamente sin errores.
    """

    def test_config_imports(self):
        from config.config import (
            StrategyConfig, CostConfig, RiskConfig,
            BacktestConfig, ExecutionConfig,
            DEFAULT_STRATEGY, DEFAULT_COSTS, DEFAULT_RISK,
            DEFAULT_BACKTEST, DEFAULT_EXECUTION,
        )
        assert DEFAULT_STRATEGY.MAX_RAW_SCORE == 90
        assert DEFAULT_RISK.max_daily_loss_pct == 0.03
        assert DEFAULT_BACKTEST.entry_on == "next_open"
        assert not DEFAULT_EXECUTION.live_trading  # False por defecto

    def test_data_processor_imports(self):
        from core.data_processor import MarketDataFetcher
        import inspect
        assert hasattr(MarketDataFetcher, "align_htf_to_ltf")
        assert hasattr(MarketDataFetcher, "normalize_klines")
        assert "htf_duration_minutes" in inspect.signature(MarketDataFetcher.align_htf_to_ltf).parameters

    def test_scoring_engine_imports(self):
        from core.scoring_engine import ScoringEngine
        from config.config import DEFAULT_STRATEGY
        assert hasattr(ScoringEngine, "evaluate")
        assert hasattr(ScoringEngine, "_normalize")
        assert abs(DEFAULT_STRATEGY.entry_threshold_normalized - (80/90*100)) < 1e-6

    def test_risk_manager_imports(self):
        from core.risk_manager import RiskManager
        assert hasattr(RiskManager, "validate_and_size")

    def test_portfolio_risk_imports(self):
        from core.portfolio_risk import PortfolioRiskManager
        prm = PortfolioRiskManager()
        assert hasattr(prm, "initialize_day")
        assert hasattr(prm, "check_and_update_daily_state")
        assert hasattr(prm, "is_daily_halt_active")
        assert hasattr(prm, "can_open_position")
        assert hasattr(prm, "get_current_portfolio_risk")
        assert hasattr(prm, "get_current_exposures")

    def test_live_trading_false_by_default(self):
        """CRÍTICO: LIVE_TRADING debe ser False por defecto."""
        import os
        # Asegurar que no hay LIVE_TRADING=true en el entorno de test
        os.environ.pop("LIVE_TRADING", None)
        from config.config import ExecutionConfig
        cfg = ExecutionConfig()
        assert not cfg.live_trading, "LIVE_TRADING debe ser False por defecto"
        assert not cfg.validate_live(), "validate_live() debe retornar False sin LIVE_TRADING=true"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
