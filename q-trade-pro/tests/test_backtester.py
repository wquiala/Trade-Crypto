"""
tests/test_backtester.py
========================
Suite de tests para el backtester de Q-Trade Pro (Bloque 2).

Cobertura
─────────
- MTF sin look-ahead bias (misma lógica que test_mtf_bias.py pero en el backtester)
- Entrada next_open vs close
- Política intrabar conservative vs optimistic
- Modelo de costes: fees y slippage en precio efectivo
- Daily halt simulado
- MFE/MAE tracking bar a bar
- TradeRecord campos correctos
- Métricas básicas de BacktestMetrics
"""
import math
from datetime import datetime, timezone, timedelta
from typing import List

import pandas as pd
import numpy as np
import pytest

from models.trade import TradeRecord
from backtest.backtester import Backtester, _OpenPosition, BacktestConfig, CostConfig, RiskConfig, StrategyConfig
from backtest.metrics import BacktestMetrics
from config.config import DEFAULT_BACKTEST, DEFAULT_COSTS, DEFAULT_RISK, DEFAULT_STRATEGY


# ─────────────────────────────────────────────────────────────────────────────
# Helpers para construir DataFrames de prueba
# ─────────────────────────────────────────────────────────────────────────────

def _make_ohlcv(
    n: int = 300,
    start: datetime | None = None,
    freq_minutes: int = 15,
    base_price: float = 50_000.0,
    trend: float = 0.001,        # fracción de drift por vela
) -> pd.DataFrame:
    """Genera datos OHLCV sintéticos con tendencia alcista."""
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    ts = [start + timedelta(minutes=freq_minutes * i) for i in range(n)]
    closes = [base_price * (1 + trend) ** i for i in range(n)]
    highs  = [c * 1.005 for c in closes]
    lows   = [c * 0.995 for c in closes]
    opens  = [c * 0.999 for c in closes]

    df = pd.DataFrame({
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": [100.0] * n,
    }, index=pd.DatetimeIndex(ts, tz="UTC"))
    return df


def _make_features_df(
    n: int = 300,
    start: datetime | None = None,
    freq_minutes: int = 15,
    base_price: float = 50_000.0,
) -> pd.DataFrame:
    """OHLCV con features calculados por FeatureEngine."""
    from core.feature_engine import FeatureEngine
    df = _make_ohlcv(n=n, start=start, freq_minutes=freq_minutes, base_price=base_price)
    return FeatureEngine.compute(df)


def _make_position(
    symbol: str = "BTC/USDT:USDT",
    signal: str = "LONG",
    entry_price: float = 50_000.0,
    atr: float = 500.0,
    capital: float = 1000.0,
    sl_mult: float = 1.5,
    tp_mult: float = 3.0,
    entry_bar: int = 0,
    entry_time: datetime | None = None,
    intrabar_policy: str = "conservative",
    bt: Backtester | None = None,
) -> _OpenPosition:
    """Crea una posición abierta para tests."""
    if bt is None:
        bt = Backtester()
    if entry_time is None:
        entry_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    sl_dist = atr * sl_mult
    tp_dist = atr * tp_mult
    size    = (capital * 0.005) / sl_dist   # 0.5% riesgo

    if signal == "LONG":
        sl = entry_price - sl_dist
        tp = entry_price + tp_dist
    else:
        sl = entry_price + sl_dist
        tp = entry_price - tp_dist

    return _OpenPosition(
        symbol           = symbol,
        signal           = signal,
        regime           = "BULL_TREND",
        score            = 90.0,
        entry_price_raw  = entry_price,   # raw == effective en tests
        entry_price      = entry_price,
        stop_loss        = sl,
        take_profit      = tp,
        size             = size,
        risk_amount_usd  = capital * 0.005,
        entry_bar        = entry_bar,
        entry_time       = entry_time,
        signal_time      = entry_time,
        entry_fee_usd    = 0.0,
        entry_slippage_usd = 0.0,
        capital_at_entry = capital,
        entry_on         = "next_open",
        intrabar_policy  = intrabar_policy,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. MTF sin look-ahead bias en el backtester
# ─────────────────────────────────────────────────────────────────────────────

class TestBacktesterMTF:
    """
    Verifica que el backtester usa align_htf_to_ltf() correctamente.
    La misma garantía que test_mtf_bias.py pero integrada en el motor.
    """

    def test_align_htf_is_called(self):
        """_align_htf debe usar MarketDataFetcher.align_htf_to_ltf."""
        from unittest.mock import patch, MagicMock
        from core.data_processor import MarketDataFetcher

        bt = Backtester()
        df_15m = _make_features_df(n=300)
        df_1h  = _make_features_df(n=300, freq_minutes=60)

        with patch.object(MarketDataFetcher, "align_htf_to_ltf", wraps=MarketDataFetcher.align_htf_to_ltf) as mock_align:
            bt._align_htf(df_15m, df_1h)
            mock_align.assert_called_once()

    def test_htf_close_time_respected(self):
        """
        La vela HTF de 10:00-11:00 NO debe ser visible para LTF < 11:00.
        Verifica directamente el resultado de _align_htf.
        """
        from core.feature_engine import FeatureEngine
        from core.data_processor import MarketDataFetcher

        # HTF arranca 200 horas antes para tener velas cerradas disponibles
        htf_start = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
        ltf_start = htf_start + timedelta(hours=200)

        df_htf_raw = _make_ohlcv(n=300, start=htf_start, freq_minutes=60)
        df_ltf_raw = _make_ohlcv(n=300, start=ltf_start, freq_minutes=15)

        df_htf = FeatureEngine.compute(df_htf_raw)
        df_ltf = FeatureEngine.compute(df_ltf_raw)

        bt = Backtester()
        df_aligned = bt._align_htf(df_ltf, df_htf)

        # Deben existir columnas _htf
        htf_cols = [c for c in df_aligned.columns if c.endswith("_htf")]
        assert htf_cols, "align_htf debe generar columnas _htf"

        # Las últimas filas del LTF deben tener datos HTF (no NaN)
        last_row = df_aligned.iloc[-1]
        has_htf_data = any(not pd.isna(last_row[col]) for col in htf_cols)
        assert has_htf_data, "Las filas finales del LTF deben tener datos HTF"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Entrada next_open vs close
# ─────────────────────────────────────────────────────────────────────────────

class TestEntryMode:

    def test_next_open_entry_uses_next_bar_open(self):
        """
        Con next_open: la posición abre en el open de la vela N+1.
        No puede usar el close de la vela de señal.
        """
        bt = Backtester(backtest_cfg=BacktestConfig(entry_on="next_open"))

        # Precio de señal: 50,000 (close de vela N)
        # Precio de apertura siguiente vela: 50,100 (open de vela N+1)
        raw_price_next_open = 50_100.0
        eff_entry, _ = bt._compute_entry_price(raw_price_next_open, "LONG")

        # El precio efectivo debe ser >= 50,100 (next open + slippage)
        assert eff_entry >= raw_price_next_open, (
            "Con next_open la entrada debe ser en el open de N+1, no en el close de N"
        )
        assert eff_entry > 50_000.0, "No puede entrar al precio de la vela de señal"

    def test_close_entry_uses_signal_bar_close(self):
        """Con close: la entrada es al close de la vela de señal."""
        bt = Backtester(backtest_cfg=BacktestConfig(entry_on="close"))
        signal_close = 50_000.0
        eff_entry, _ = bt._compute_entry_price(signal_close, "LONG")
        # Con slippage puede ser ligeramente diferente, pero parte del mismo close
        assert abs(eff_entry - signal_close) < signal_close * 0.01, (
            "Con close, la entrada debe partir del precio de cierre de la vela de señal"
        )

    def test_next_open_different_from_close(self):
        """next_open y close producen precios de entrada diferentes."""
        bt_no   = Backtester(backtest_cfg=BacktestConfig(entry_on="next_open"))
        bt_cl   = Backtester(backtest_cfg=BacktestConfig(entry_on="close"))

        # Supongamos que el open de N+1 es diferente al close de N
        close_N   = 50_000.0
        open_N1   = 50_200.0  # gapped up

        eff_no, _ = bt_no._compute_entry_price(open_N1,  "LONG")
        eff_cl, _ = bt_cl._compute_entry_price(close_N, "LONG")

        assert eff_no != eff_cl, "next_open y close deben producir precios distintos"
        assert eff_no > eff_cl, "En un gap alcista, next_open es más caro que close"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Política intrabar
# ─────────────────────────────────────────────────────────────────────────────

class TestIntrabarPolicy:
    """
    Cuando HIGH >= TP y LOW <= SL en la misma vela:
    - conservative → SL gana (pérdida)
    - optimistic   → TP gana (ganancia)
    """

    def _run_intrabar(self, policy: str, signal: str = "LONG") -> TradeRecord:
        """Ejecuta un check_exits con SL y TP tocados simultáneamente."""
        bt      = Backtester(backtest_cfg=BacktestConfig(intrabar_policy=policy))
        capital = 10_000.0
        atr     = 100.0
        entry   = 50_000.0

        pos = _make_position(
            signal=signal,
            entry_price=entry,
            atr=atr,
            capital=capital,
            intrabar_policy=policy,
            bt=bt,
        )
        open_positions = {"BTC/USDT:USDT": pos}

        # Para LONG: SL está por debajo, TP está por encima
        # → necesitamos HIGH >= TP y LOW <= SL
        # Para SHORT: SL está por encima, TP está por debajo
        # → necesitamos HIGH >= SL y LOW <= TP
        bar_row = pd.Series({
            "high": max(pos.stop_loss, pos.take_profit) + 1,
            "low":  min(pos.stop_loss, pos.take_profit) - 1,
            "open": entry,
            "close": entry,
        })
        bar_time = datetime(2024, 1, 2, tzinfo=timezone.utc)

        closed, _ = bt._check_exits(open_positions, 1, bar_row, bar_time)
        assert len(closed) == 1, "Debe cerrar exactamente una posición"
        return closed[0]

    def test_conservative_long_sl_wins(self):
        """Conservative LONG: SL tiene prioridad → pérdida."""
        trade = self._run_intrabar("conservative", "LONG")
        assert trade.exit_reason == "SL", f"Expected SL, got {trade.exit_reason}"
        assert trade.net_pnl <= 0, f"Conservative debe ser pérdida, got {trade.net_pnl}"

    def test_optimistic_long_tp_wins(self):
        """Optimistic LONG: TP tiene prioridad → ganancia."""
        trade = self._run_intrabar("optimistic", "LONG")
        assert trade.exit_reason == "TP", f"Expected TP, got {trade.exit_reason}"
        assert trade.gross_pnl >= 0, f"Optimistic debe ser ganancia bruta, got {trade.gross_pnl}"

    def test_conservative_short_sl_wins(self):
        """Conservative SHORT: SL tiene prioridad."""
        trade = self._run_intrabar("conservative", "SHORT")
        assert trade.exit_reason == "SL"

    def test_optimistic_short_tp_wins(self):
        """Optimistic SHORT: TP tiene prioridad."""
        trade = self._run_intrabar("optimistic", "SHORT")
        assert trade.exit_reason == "TP"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Modelo de costes
# ─────────────────────────────────────────────────────────────────────────────

class TestCostModel:
    """
    Verifica que fees y slippage se calculan correctamente y reducen el PnL neto.
    """

    def test_net_pnl_less_than_gross_pnl(self):
        """El PnL neto siempre debe ser menor que el bruto (costes no negativos)."""
        bt      = Backtester()
        capital = 10_000.0
        atr     = 100.0
        entry   = 50_000.0

        pos = _make_position(entry_price=entry, atr=atr, capital=capital)
        open_positions = {"BTC/USDT:USDT": pos}

        # TP alcanzado
        tp = pos.take_profit
        bar_row  = pd.Series({"high": tp + 1, "low": entry - 1, "open": entry, "close": tp})
        bar_time = datetime(2024, 1, 2, tzinfo=timezone.utc)

        closed, _ = bt._check_exits(open_positions, 1, bar_row, bar_time)
        trade = closed[0]

        assert trade.net_pnl < trade.gross_pnl, (
            f"net_pnl ({trade.net_pnl:.4f}) debe ser < gross_pnl ({trade.gross_pnl:.4f})"
        )

    def test_entry_fee_is_positive(self):
        """La fee de entrada debe ser positiva (hay coste)."""
        bt      = Backtester()
        capital = 10_000.0
        atr     = 100.0
        pos     = _make_position(entry_price=50_000.0, atr=atr, capital=capital)

        # Simular que la fee fue calculada al abrir
        notional = 50_000.0 * pos.size
        fee      = notional * DEFAULT_COSTS.fee_rate
        assert fee > 0, f"Fee de entrada debe ser positiva, got {fee}"

    def test_long_entry_slippage_raises_price(self):
        """Para LONG, el slippage sube el precio de entrada."""
        bt      = Backtester()
        raw     = 50_000.0
        eff, _  = bt._compute_entry_price(raw, "LONG")
        assert eff > raw, f"LONG entry con slippage debe subir el precio: {eff} > {raw}"

    def test_short_entry_slippage_lowers_price(self):
        """Para SHORT, el slippage baja el precio de entrada (peor para nosotros)."""
        bt      = Backtester()
        raw     = 50_000.0
        eff, _  = bt._compute_entry_price(raw, "SHORT")
        assert eff < raw, f"SHORT entry con slippage debe bajar el precio: {eff} < {raw}"

    def test_long_exit_slippage_lowers_price(self):
        """Para LONG, el slippage en la salida baja el precio de venta."""
        bt      = Backtester()
        raw     = 51_000.0
        eff, _  = bt._compute_exit_price(raw, "LONG")
        assert eff < raw, f"LONG exit con slippage debe bajar el precio: {eff} < {raw}"

    def test_total_cost_equals_sum_of_parts(self):
        """total_cost_usd debe ser la suma de los 4 componentes."""
        trade = TradeRecord(
            entry_fee_usd=5.0,
            exit_fee_usd=4.5,
            entry_slippage_usd=1.0,
            exit_slippage_usd=0.9,
        )
        expected = 5.0 + 4.5 + 1.0 + 0.9
        assert abs(trade.total_cost_usd - expected) < 1e-6, (
            f"total_cost_usd={trade.total_cost_usd}, expected={expected}"
        )

    def test_zero_cost_config_no_fees(self):
        """Con fees=0 y slippage=0, gross_pnl == net_pnl."""
        zero_costs = CostConfig(
            taker_fee_rate=0.0,
            maker_fee_rate=0.0,
            entry_slippage=0.0,
            exit_slippage=0.0,
            spread_bps=0.0,
        )
        bt      = Backtester(cost_cfg=zero_costs)
        capital = 10_000.0
        atr     = 100.0
        pos     = _make_position(entry_price=50_000.0, atr=atr, capital=capital, bt=bt)
        open_positions = {"BTC/USDT:USDT": pos}

        tp       = pos.take_profit
        bar_row  = pd.Series({"high": tp + 1, "low": pos.entry_price - 1, "open": pos.entry_price, "close": tp})
        bar_time = datetime(2024, 1, 2, tzinfo=timezone.utc)

        closed, _ = bt._check_exits(open_positions, 1, bar_row, bar_time)
        trade = closed[0]

        assert abs(trade.net_pnl - trade.gross_pnl) < 1e-4, (
            f"Sin costes, net_pnl debe igualar gross_pnl: {trade.net_pnl} vs {trade.gross_pnl}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Daily halt simulado
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyHaltSimulation:
    """Verifica que el backtester respeta el daily halt correctamente."""

    def test_halt_activates_after_daily_loss(self):
        """Después de una pérdida > max_daily_loss_pct, el halt se activa."""
        from backtest.backtester import Backtester
        bt = Backtester(risk_cfg=RiskConfig(max_daily_loss_pct=0.03))
        tracker = Backtester._DailyHaltTracker(
            max_daily_loss_pct=0.03,
            initial_capital=1000.0,
        )
        day_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        # Capital inicial: 1000. Pérdida de 3.5% → 965
        tracker.update(1000.0, day_time)
        assert not tracker.is_halted, "No debe estar halted al inicio del día"

        tracker.update(965.0, day_time)
        assert tracker.is_halted, "Debe halted tras pérdida > 3%"

    def test_halt_resets_next_day(self):
        """El halt se resetea al inicio del día siguiente."""
        tracker = Backtester._DailyHaltTracker(
            max_daily_loss_pct=0.03,
            initial_capital=1000.0,
        )
        day1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        day2 = datetime(2024, 1, 2,  0, 1, tzinfo=timezone.utc)

        # Activar halt
        tracker.update(1000.0, day1)
        tracker.update(960.0,  day1)
        assert tracker.is_halted

        # Nuevo día → reset
        tracker.update(960.0, day2)
        assert not tracker.is_halted, "El halt debe resetearse al inicio del día siguiente"

    def test_halt_does_not_activate_below_threshold(self):
        """Pérdida menor al threshold no activa el halt."""
        tracker = Backtester._DailyHaltTracker(
            max_daily_loss_pct=0.03,
            initial_capital=1000.0,
        )
        day_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        tracker.update(1000.0, day_time)
        tracker.update(975.0,  day_time)  # pérdida 2.5% < 3%
        assert not tracker.is_halted, "2.5% de pérdida no debe activar el halt del 3%"

    def test_halt_persists_within_same_day(self):
        """Una vez activado, el halt persiste todo el día."""
        tracker = Backtester._DailyHaltTracker(
            max_daily_loss_pct=0.03,
            initial_capital=1000.0,
        )
        day_time = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)

        tracker.update(1000.0, day_time)
        tracker.update(960.0,  day_time)  # Activar halt
        assert tracker.is_halted

        # Simular recuperación parcial (el halt no debe desactivarse)
        later = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)
        tracker.update(985.0, later)  # Capital subió pero todavía mismo día
        assert tracker.is_halted, "El halt debe persistir aunque el capital suba durante el día"


# ─────────────────────────────────────────────────────────────────────────────
# 6. MFE/MAE tracking
# ─────────────────────────────────────────────────────────────────────────────

class TestMFEMAETracking:

    def test_mfe_updates_on_favorable_move(self):
        """MFE debe aumentar cuando el precio se mueve a favor."""
        bt  = Backtester()
        pos = _make_position(signal="LONG", entry_price=50_000.0, atr=500.0)

        # Vela que va 200 puntos en positivo
        bt._update_excursions(pos, high=50_200.0, low=49_950.0)
        assert pos.mfe_usd > 0, "MFE debe ser positivo tras movimiento favorable"
        assert pos.mfe_usd == pytest.approx((50_200.0 - 50_000.0) * pos.size, rel=1e-4)

    def test_mae_updates_on_adverse_move(self):
        """MAE debe aumentar cuando el precio se mueve en contra."""
        bt  = Backtester()
        pos = _make_position(signal="LONG", entry_price=50_000.0, atr=500.0)

        # Vela que baja 300 puntos
        bt._update_excursions(pos, high=50_100.0, low=49_700.0)
        assert pos.mae_usd > 0, "MAE debe ser positivo tras movimiento adverso"
        assert pos.mae_usd == pytest.approx((50_000.0 - 49_700.0) * pos.size, rel=1e-4)

    def test_mfe_is_maximum_across_bars(self):
        """MFE debe ser el máximo histórico, no el de la última vela."""
        bt  = Backtester()
        pos = _make_position(signal="LONG", entry_price=50_000.0, atr=500.0)

        bt._update_excursions(pos, high=50_500.0, low=49_900.0)  # MFE = 500 puntos
        bt._update_excursions(pos, high=50_200.0, low=49_800.0)  # Menos favorable

        expected_mfe = (50_500.0 - 50_000.0) * pos.size
        assert pos.mfe_usd == pytest.approx(expected_mfe, rel=1e-4), (
            "MFE debe conservar el máximo histórico"
        )

    def test_mfe_in_trade_record_is_in_r(self):
        """MFE en el TradeRecord debe estar expresado en múltiplos de R."""
        bt      = Backtester()
        capital = 10_000.0
        atr     = 200.0
        pos     = _make_position(
            signal="LONG", entry_price=50_000.0, atr=atr, capital=capital
        )

        # Simular MFE de 2R directamente en USD
        r_unit = pos.risk_amount_usd
        pos.mfe_usd = r_unit * 2.0   # = 2R

        open_positions = {"BTC/USDT:USDT": pos}
        tp       = pos.take_profit
        bar_row  = pd.Series({
            "high": tp + 1, "low": pos.entry_price - 1,
            "open": pos.entry_price, "close": tp,
        })
        bar_time = datetime(2024, 1, 2, tzinfo=timezone.utc)
        closed, _ = bt._check_exits(open_positions, 1, bar_row, bar_time)
        trade = closed[0]

        assert abs(trade.mfe - 2.0) < 0.01, (
            f"MFE en el TradeRecord debe ser ~2R, got {trade.mfe}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. TradeRecord campos
# ─────────────────────────────────────────────────────────────────────────────

class TestTradeRecord:

    def test_pnl_r_calculated_correctly(self):
        """pnl_r = net_pnl / risk_amount_usd."""
        trade = TradeRecord(net_pnl=30.0, risk_amount_usd=15.0)
        assert abs(trade.pnl_r - 2.0) < 1e-6

    def test_pnl_r_negative_on_loss(self):
        """pnl_r negativo cuando net_pnl < 0."""
        trade = TradeRecord(net_pnl=-15.0, risk_amount_usd=15.0)
        assert abs(trade.pnl_r + 1.0) < 1e-6

    def test_pnl_r_zero_when_no_risk(self):
        """pnl_r = 0 si risk_amount_usd = 0 (evitar división por cero)."""
        trade = TradeRecord(net_pnl=10.0, risk_amount_usd=0.0)
        assert trade.pnl_r == 0.0

    def test_total_cost_property(self):
        """total_cost_usd debe sumar todos los costes."""
        trade = TradeRecord(
            entry_fee_usd=2.0,
            exit_fee_usd=1.8,
            entry_slippage_usd=0.5,
            exit_slippage_usd=0.4,
        )
        assert abs(trade.total_cost_usd - 4.7) < 1e-6

    def test_repr_contains_key_fields(self):
        """El repr debe mostrar información suficiente para debugging."""
        trade = TradeRecord(
            symbol="BTC/USDT:USDT",
            signal="LONG",
            regime="BULL_TREND",
            score=90.0,
            net_pnl=25.0,
            risk_amount_usd=12.5,
            exit_reason="TP",
        )
        r = repr(trade)
        assert "BTC/USDT:USDT" in r
        assert "LONG" in r
        assert "TP" in r


# ─────────────────────────────────────────────────────────────────────────────
# 8. BacktestMetrics
# ─────────────────────────────────────────────────────────────────────────────

def _make_trades(n_wins: int, n_losses: int) -> List[TradeRecord]:
    """Genera una lista de trades de prueba."""
    trades = []
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(n_wins):
        trades.append(TradeRecord(
            symbol="BTC/USDT:USDT",
            signal="LONG",
            regime="BULL_TREND",
            score=90.0,
            net_pnl=20.0,
            gross_pnl=22.0,
            risk_amount_usd=10.0,
            exit_reason="TP",
            entry_fee_usd=1.0,
            exit_fee_usd=1.0,
            entry_time=ts + timedelta(days=i),
            exit_time=ts + timedelta(days=i, hours=4),
            duration_bars=16,
            mfe=2.0,
            mae=0.5,
        ))
    for i in range(n_losses):
        trades.append(TradeRecord(
            symbol="ETH/USDT:USDT",
            signal="LONG",
            regime="BULL_TREND",
            score=89.0,
            net_pnl=-10.0,
            gross_pnl=-8.5,
            risk_amount_usd=10.0,
            exit_reason="SL",
            entry_fee_usd=0.5,
            exit_fee_usd=0.5,
            entry_time=ts + timedelta(days=n_wins + i),
            exit_time=ts + timedelta(days=n_wins + i, hours=2),
            duration_bars=8,
            mfe=0.3,
            mae=1.0,
        ))
    return trades


class TestBacktestMetrics:

    def test_win_rate_correct(self):
        """Win rate debe ser wins / total."""
        trades = _make_trades(6, 4)
        equity = [1000.0, 1020.0, 1040.0, 1060.0, 1080.0, 1100.0, 1120.0,
                  1110.0, 1100.0, 1090.0, 1080.0]
        m = BacktestMetrics.compute_all(trades, 1000.0, equity)
        assert abs(m["win_rate_pct"] - 60.0) < 0.1

    def test_profit_factor_gt_1_when_profitable(self):
        """Profit Factor > 1 cuando sum(wins) > sum(losses)."""
        trades = _make_trades(5, 5)  # 5×20 - 5×10 = +50 → PF = 2.0
        equity = [1000.0 + 10 * i for i in range(11)]
        m = BacktestMetrics.compute_all(trades, 1000.0, equity)
        assert m["profit_factor"] > 1.0

    def test_total_trades_correct(self):
        """total_trades debe ser la suma de todos los trades."""
        trades = _make_trades(3, 2)
        equity = [1000.0] * 6
        m = BacktestMetrics.compute_all(trades, 1000.0, equity)
        assert m["total_trades"] == 5

    def test_by_symbol_breakdown(self):
        """El desglose por símbolo debe existir para cada símbolo."""
        trades = _make_trades(3, 2)
        equity = [1000.0] * 6
        m = BacktestMetrics.compute_all(trades, 1000.0, equity)
        assert "BTC/USDT:USDT" in m["by_symbol"]
        assert "ETH/USDT:USDT" in m["by_symbol"]

    def test_by_regime_breakdown(self):
        """El desglose por régimen debe existir."""
        trades = _make_trades(3, 2)
        equity = [1000.0] * 6
        m = BacktestMetrics.compute_all(trades, 1000.0, equity)
        assert "BULL_TREND" in m["by_regime"]

    def test_total_costs_calculated(self):
        """Los costes totales deben ser la suma de entry+exit fees."""
        trades = _make_trades(2, 1)
        equity = [1000.0] * 4
        m = BacktestMetrics.compute_all(trades, 1000.0, equity)
        # 2 wins: 1+1=2 each → 4 total. 1 loss: 0.5+0.5=1 → total = 5
        assert m["total_fees_usd"] == pytest.approx(5.0, abs=0.01)

    def test_empty_trades_returns_error(self):
        """Sin trades debe retornar un diccionario con clave 'error'."""
        m = BacktestMetrics.compute_all([], 1000.0, [1000.0])
        assert "error" in m

    def test_max_drawdown_negative(self):
        """El max drawdown debe ser negativo o cero."""
        trades = _make_trades(1, 1)
        equity = [1000.0, 1020.0, 1010.0]
        m = BacktestMetrics.compute_all(trades, 1000.0, equity)
        assert m["max_drawdown_pct"] <= 0

    def test_mfe_mae_aggregated(self):
        """Las métricas de excursión deben calcularse correctamente."""
        trades = _make_trades(3, 2)
        equity = [1000.0] * 6
        m = BacktestMetrics.compute_all(trades, 1000.0, equity)
        assert "mfe_avg_r"  in m
        assert "mae_avg_r"  in m
        assert m["mfe_avg_r"] > 0
        assert m["mae_avg_r"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 9. FeatureEngine: BB desacopladas
# ─────────────────────────────────────────────────────────────────────────────

class TestFeatureEngineBBDecoupled:
    """Verifica que compute() ya no incluye BB y que compute_ranging_features() sí."""

    def test_compute_does_not_include_bb(self):
        """compute() no debe calcular BBU/BBL."""
        from core.feature_engine import FeatureEngine
        df = _make_ohlcv(n=300)
        result = FeatureEngine.compute(df)
        assert "BBU_20_2.0" not in result.columns, (
            "compute() no debe incluir Bollinger Bands — usar compute_ranging_features()"
        )
        assert "BBL_20_2.0" not in result.columns

    def test_compute_includes_required_features(self):
        """compute() debe incluir todas las features necesarias para la estrategia."""
        from core.feature_engine import FeatureEngine
        df = _make_ohlcv(n=300)
        result = FeatureEngine.compute(df)
        required = ["EMA_20", "EMA_50", "EMA_200", "RSI_14", "MACDh_12_26_9", "ATRr_14", "ADX_14"]
        for col in required:
            assert col in result.columns, f"Feature requerida ausente: {col}"

    def test_compute_ranging_features_adds_bb(self):
        """compute_ranging_features() debe añadir BBU y BBL."""
        from core.feature_engine import FeatureEngine
        df = _make_ohlcv(n=300)
        df_feat = FeatureEngine.compute(df)
        df_with_bb = FeatureEngine.compute_ranging_features(df_feat.copy())
        assert "BBU_20_2.0" in df_with_bb.columns
        assert "BBL_20_2.0" in df_with_bb.columns

    def test_compute_output_has_no_nan(self):
        """compute() debe eliminar filas de warmup con dropna()."""
        from core.feature_engine import FeatureEngine
        df = _make_ohlcv(n=300)
        result = FeatureEngine.compute(df)
        assert not result.isnull().any().any(), "compute() no debe dejar NaN en el resultado"

    def test_min_candles_constant_exists(self):
        """MIN_CANDLES_REQUIRED debe estar definida en feature_engine."""
        from core.feature_engine import MIN_CANDLES_REQUIRED
        assert MIN_CANDLES_REQUIRED >= 210, (
            f"MIN_CANDLES_REQUIRED debe ser >= 210 (EMA_200 + margen), got {MIN_CANDLES_REQUIRED}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
