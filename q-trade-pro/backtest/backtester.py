"""
backtest/backtester.py
======================
Motor de backtesting sin look-ahead bias para Q-Trade Pro.

Diseño
──────
- MTF: usa MarketDataFetcher.align_htf_to_ltf() — misma función que en live.
  La vela HTF 10:00-11:00 NO es visible para señales LTF antes de las 11:00.
- Entrada: next_open por defecto (open de vela N+1 tras señal en vela N).
           close disponible únicamente para comparación.
- Intrabar: cuando HIGH >= TP y LOW <= SL en la misma vela:
            "conservative" → SL primero (pesimista, default).
            "optimistic"   → TP primero.
- Costes: fees + slippage descontados en el precio efectivo de ejecución.
- Daily halt: simula el mismo PortfolioRiskManager del flujo live.
- MFE/MAE: actualizados bar a bar para cada posición abierta.

Uso
───
    python -m backtest.backtester
    python -m backtest.backtester --months 3 --entry-on close
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import math
import sys
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config.config import (
    BacktestConfig,
    CostConfig,
    DEFAULT_BACKTEST,
    DEFAULT_COSTS,
    DEFAULT_RISK,
    DEFAULT_STRATEGY,
    RiskConfig,
    StrategyConfig,
)
from core.data_processor import MarketDataFetcher
from core.feature_engine import FeatureEngine
from core.regime_detector import RegimeDetector
from core.scoring_engine import ScoringEngine
from models.trade import TradeRecord
from backtest.metrics import BacktestMetrics

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Símbolos por defecto (mismos que main.py)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SYMBOLS = [
    'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT',
    'XRP/USDT:USDT', 'ADA/USDT:USDT', 'DOGE/USDT:USDT', 'AVAX/USDT:USDT',
    'LINK/USDT:USDT',
]


# ─────────────────────────────────────────────────────────────────────────────
# Posición abierta (estado interno del backtester)
# ─────────────────────────────────────────────────────────────────────────────

class _OpenPosition:
    """Estado de una posición abierta durante el backtest."""

    def __init__(
        self,
        symbol: str,
        signal: str,
        regime: str,
        score: float,
        entry_price_raw: float,   # precio RAW de referencia (sin slippage)
        entry_price: float,       # precio efectivo de ejecución (con slippage)
        stop_loss: float,
        take_profit: float,
        size: float,
        risk_amount_usd: float,
        entry_bar: int,
        entry_time: datetime,
        signal_time: datetime,
        entry_fee_usd: float,
        entry_slippage_usd: float,
        capital_at_entry: float,
        entry_on: str,
        intrabar_policy: str,
        entry_features: dict = None,
    ):
        self.symbol = symbol
        self.signal = signal
        self.regime = regime
        self.score  = score

        self.entry_price_raw = entry_price_raw   # precio de referencia (sin slippage)
        self.entry_price     = entry_price       # precio efectivo (con slippage)
        self.stop_loss       = stop_loss
        self.take_profit     = take_profit
        self.size            = size
        self.risk_amount_usd = risk_amount_usd

        self.entry_bar   = entry_bar
        self.entry_time  = entry_time
        self.signal_time = signal_time

        self.entry_fee_usd      = entry_fee_usd
        self.entry_slippage_usd = entry_slippage_usd
        self.capital_at_entry   = capital_at_entry
        self.entry_on           = entry_on
        self.intrabar_policy    = intrabar_policy
        self.entry_features     = entry_features or {}

        # Excursiones (actualizadas bar a bar)
        self.mfe_usd: float = 0.0   # Maximum Favorable Excursion (USD)
        self.mae_usd: float = 0.0   # Maximum Adverse Excursion (USD)


# ─────────────────────────────────────────────────────────────────────────────
# Backtester principal
# ─────────────────────────────────────────────────────────────────────────────

class Backtester:
    """
    Motor de backtesting bar-a-bar para Q-Trade Pro.

    Atributos
    ─────────
    strategy_cfg: parámetros de la estrategia.
    cost_cfg:     modelo de costes (fees + slippage).
    risk_cfg:     gestión de riesgo.
    backtest_cfg: configuración del backtest (entry_on, intrabar_policy, etc).
    """

    def __init__(
        self,
        strategy_cfg: StrategyConfig = DEFAULT_STRATEGY,
        cost_cfg: CostConfig = DEFAULT_COSTS,
        risk_cfg: RiskConfig = DEFAULT_RISK,
        backtest_cfg: BacktestConfig = DEFAULT_BACKTEST,
        symbols: Optional[List[str]] = None,
        adx_threshold: int = 20,
    ):
        self.strategy_cfg  = strategy_cfg
        self.cost_cfg      = cost_cfg
        self.risk_cfg      = risk_cfg
        self.backtest_cfg  = backtest_cfg
        self.symbols       = symbols or DEFAULT_SYMBOLS
        self.adx_threshold = adx_threshold   # umbral ADX para regime detection

    # ── Descarga ──────────────────────────────────────────────────────────────

    async def _fetch_symbol(self, exchange, symbol: str) -> Optional[Dict]:
        """Descarga datos 15m y 1h para un símbolo. Devuelve None si falla.

        Paginación:
        ───────────
        Binance Futures tiene un límite real de 1000 velas por petición
        (aunque se soliciten más). Si pedimos 1440 y devuelve 1000,
        la comparación `len(batch) < page_limit` falla y rompe el bucle
        después de la primera página.

        Solución: usar 1000 como límite real y parar cuando el timestamp
        del último dato descargado supere el momento actual.
        """
        months = self.backtest_cfg.backtest_months
        now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        since  = int(
            (pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=months)).timestamp() * 1000
        )
        page_limit = 1000   # Límite real de Binance Futures por petición

        async def _paginate(tf: str) -> list:
            out, cur_since = [], since
            while True:
                try:
                    batch = await exchange.fetch_ohlcv(
                        symbol, tf, since=cur_since, limit=page_limit
                    )
                except Exception as e:
                    logger.warning(f"fetch_ohlcv error {symbol} {tf}: {e}")
                    break
                if not batch:
                    break
                out.extend(batch)
                last_ts = batch[-1][0]  # ms
                # Parar si ya alcanzamos el presente o si fue la última página
                if last_ts >= now_ms or len(batch) < page_limit:
                    break
                cur_since = last_ts + 1
                await asyncio.sleep(0.2)
            return out

        raw_15m = await _paginate("15m")
        raw_1h  = await _paginate("1h")

        if not raw_15m or not raw_1h:
            return None

        return {"15m": raw_15m, "1h": raw_1h}

    async def download(self) -> Dict[str, Dict]:
        """Descarga datos históricos de Binance para todos los símbolos."""
        import ccxt.async_support as ccxt_async
        print(f"📥 Descargando {self.backtest_cfg.backtest_months} meses de datos de Binance...")
        exchange = ccxt_async.binance({"enableRateLimit": True})
        data: Dict[str, Dict] = {}
        for sym in self.symbols:
            print(f"   {sym}...", end=" ", flush=True)
            result = await self._fetch_symbol(exchange, sym)
            if result:
                data[sym] = result
                n15 = len(result["15m"])
                print(f"✓ {n15} velas 15m")
            else:
                print("✗ sin datos")
            await asyncio.sleep(0.3)
        await exchange.close()
        return data

    # ── Preparación de datos ──────────────────────────────────────────────────

    def _prepare_symbol_data(
        self, raw: Dict
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Normaliza y calcula features para 15m y 1h.

        Returns:
            (df_15m_feat, df_1h_feat) o (None, None) si hay insuficientes datos.
        """
        df_15m = MarketDataFetcher.normalize_klines(raw["15m"])
        df_1h  = MarketDataFetcher.normalize_klines(raw["1h"])

        min_candles = 210  # EMA_200 + margen
        if len(df_15m) < min_candles or len(df_1h) < min_candles:
            return None, None

        df_15m_feat = FeatureEngine.compute(df_15m.copy())
        df_1h_feat  = FeatureEngine.compute(df_1h.copy())

        return df_15m_feat, df_1h_feat

    def _align_htf(
        self, df_15m_feat: pd.DataFrame, df_1h_feat: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Alinea HTF al LTF usando htf_close_time (sin look-ahead bias).

        La vela 1h de 10:00-11:00 solo es visible para señales LTF >= 11:00.
        """
        return MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_15m_feat,
            df_htf_with_features=df_1h_feat,
            htf_duration_minutes=self.strategy_cfg.htf_minutes,
        )

    # ── Sizing ────────────────────────────────────────────────────────────────

    def _compute_entry_price(
        self, raw_price: float, signal: str
    ) -> Tuple[float, float]:
        """
        Calcula el precio efectivo de entrada con slippage y spread.

        Para LONG: el precio sube (pagamos más).
        Para SHORT: el precio baja (recibimos menos).

        Returns:
            (effective_price, slippage_usd_per_contract)
        """
        slip_frac = self.cost_cfg.entry_slippage + self.cost_cfg.spread_bps / 2
        if signal == "LONG":
            effective = raw_price * (1 + slip_frac)
        else:
            effective = raw_price * (1 - slip_frac)
        slippage_usd = abs(effective - raw_price)
        return effective, slippage_usd

    def _compute_exit_price(
        self, raw_price: float, signal: str
    ) -> Tuple[float, float]:
        """
        Calcula el precio efectivo de salida con slippage y spread.

        Para LONG: vendemos y el precio baja.
        Para SHORT: recompramos y el precio sube.

        Returns:
            (effective_price, slippage_usd_per_notional)
        """
        slip_frac = self.cost_cfg.exit_slippage + self.cost_cfg.spread_bps / 2
        if signal == "LONG":
            effective = raw_price * (1 - slip_frac)
        else:
            effective = raw_price * (1 + slip_frac)
        slippage_usd = abs(effective - raw_price)
        return effective, slippage_usd

    def _size_position(
        self, capital: float, atr: float, entry_price: float
    ) -> Tuple[float, float]:
        """
        Calcula el tamaño de la posición.

        Returns:
            (size_in_contracts, risk_amount_usd)
        """
        sl_distance   = atr * self.risk_cfg.sl_atr_mult
        risk_amt_usd  = capital * self.risk_cfg.risk_per_trade_pct
        size          = risk_amt_usd / sl_distance if sl_distance > 0 else 0.0
        return size, risk_amt_usd

    # ── Cierre de posición ────────────────────────────────────────────────────

    def _close_position(
        self,
        pos: _OpenPosition,
        exit_price_raw: float,
        exit_reason: str,
        exit_bar: int,
        exit_time: datetime,
    ) -> Tuple[TradeRecord, float]:
        """
        Cierra una posición y devuelve (TradeRecord, net_pnl).
        """
        exit_price_eff, exit_slip_per_unit = self._compute_exit_price(exit_price_raw, pos.signal)

        notional_exit   = exit_price_eff * pos.size
        exit_fee_usd    = notional_exit * self.cost_cfg.fee_rate
        exit_slip_usd   = exit_slip_per_unit * pos.size

        # PnL bruto: usa el precio RAW de referencia (SL/TP/close), sin slippage.
        # Esto hace que gross_pnl sea la ganancia "ideal" antes de cualquier coste.
        if pos.signal == "LONG":
            gross_pnl = (exit_price_raw - pos.entry_price_raw) * pos.size
        else:
            gross_pnl = (pos.entry_price_raw - exit_price_raw) * pos.size

        # PnL neto: gross_pnl menos TODOS los costes explícitos (fees + slippage).
        # fees    → pagados al exchange sobre el notional ejecutado
        # slippage → diferencia entre precio referencia y precio efectivo de ejecución
        net_pnl = gross_pnl - pos.entry_fee_usd - exit_fee_usd - pos.entry_slippage_usd - exit_slip_usd

        # MFE/MAE en R
        r_unit = pos.risk_amount_usd if pos.risk_amount_usd > 0 else 1.0
        mfe_r  = pos.mfe_usd / r_unit
        mae_r  = pos.mae_usd / r_unit

        record = TradeRecord(
            symbol          = pos.symbol,
            signal          = pos.signal,
            regime          = pos.regime,
            score           = pos.score,
            entry_price     = pos.entry_price,
            exit_price      = exit_price_eff,
            stop_loss       = pos.stop_loss,
            take_profit     = pos.take_profit,
            size            = pos.size,
            risk_amount_usd = pos.risk_amount_usd,
            entry_fee_usd   = pos.entry_fee_usd,
            exit_fee_usd    = exit_fee_usd,
            entry_slippage_usd = pos.entry_slippage_usd,
            exit_slippage_usd  = exit_slip_usd,
            gross_pnl       = round(gross_pnl, 4),
            net_pnl         = round(net_pnl, 4),
            mfe             = round(mfe_r, 4),
            mae             = round(mae_r, 4),
            exit_reason     = exit_reason,
            signal_time     = pos.signal_time,
            entry_time      = pos.entry_time,
            exit_time       = exit_time,
            duration_bars   = max(0, exit_bar - pos.entry_bar),
            entry_on        = pos.entry_on,
            intrabar_policy = pos.intrabar_policy,
            capital_at_entry = pos.capital_at_entry,
            entry_features  = pos.entry_features,
        )
        return record, net_pnl

    # ── Actualización bar-a-bar (MFE/MAE) ────────────────────────────────────

    def _update_excursions(self, pos: _OpenPosition, high: float, low: float) -> None:
        """Actualiza MFE y MAE de la posición con la vela actual."""
        if pos.signal == "LONG":
            favorable = (high - pos.entry_price) * pos.size
            adverse   = (pos.entry_price - low)  * pos.size
        else:
            favorable = (pos.entry_price - low)  * pos.size
            adverse   = (high - pos.entry_price) * pos.size

        pos.mfe_usd = max(pos.mfe_usd, favorable)
        pos.mae_usd = max(pos.mae_usd, adverse)

    # ── Check SL/TP ───────────────────────────────────────────────────────────

    def _check_exits(
        self,
        open_positions: Dict[str, _OpenPosition],
        bar_index: int,
        bar_row: pd.Series,
        bar_time: datetime,
    ) -> Tuple[List[TradeRecord], float]:
        """
        Comprueba si alguna posición ha alcanzado su SL o TP en esta vela.

        Returns:
            (lista de trades cerrados, PnL neto total de los cierres)
        """
        closed_trades: List[TradeRecord]  = []
        total_net_pnl: float = 0.0
        to_remove: List[str] = []

        high  = float(bar_row.get("high",  0))
        low   = float(bar_row.get("low",   0))

        for sym, pos in open_positions.items():
            # Actualizar excursiones antes de comprobar salida
            self._update_excursions(pos, high, low)

            hit_sl = hit_tp = False
            exit_price_raw = 0.0

            if pos.signal == "LONG":
                hit_sl = low  <= pos.stop_loss
                hit_tp = high >= pos.take_profit
            else:
                hit_sl = high >= pos.stop_loss
                hit_tp = low  <= pos.take_profit

            # Política intrabar: ambos tocados en la misma vela
            if hit_sl and hit_tp:
                if pos.intrabar_policy == "conservative":
                    hit_tp = False    # SL gana
                else:
                    hit_sl = False    # TP gana

            if hit_tp:
                exit_price_raw = pos.take_profit
                exit_reason    = "TP"
            elif hit_sl:
                exit_price_raw = pos.stop_loss
                exit_reason    = "SL"
            else:
                continue  # Posición sigue abierta

            record, net_pnl = self._close_position(
                pos, exit_price_raw, exit_reason, bar_index, bar_time
            )
            closed_trades.append(record)
            total_net_pnl += net_pnl
            to_remove.append(sym)

        for sym in to_remove:
            del open_positions[sym]

        return closed_trades, total_net_pnl

    # ── Daily halt ────────────────────────────────────────────────────────────

    class _DailyHaltTracker:
        """Simulación del daily halt equivalente al PortfolioRiskManager live."""

        def __init__(self, max_daily_loss_pct: float, initial_capital: float):
            self._max_loss_pct   = max_daily_loss_pct
            self._day_start_cap  = initial_capital
            self._current_day    = ""
            self._halted         = False

        def update(self, current_capital: float, bar_time: datetime) -> None:
            """Actualiza el estado del daily halt."""
            day = bar_time.strftime("%Y-%m-%d")
            if day != self._current_day:
                # Nuevo día → reset
                self._current_day   = day
                self._day_start_cap = current_capital
                self._halted        = False
            else:
                loss_pct = (self._day_start_cap - current_capital) / self._day_start_cap
                if loss_pct >= self._max_loss_pct:
                    self._halted = True

        @property
        def is_halted(self) -> bool:
            return self._halted

    # ── Backtest de un símbolo ────────────────────────────────────────────────

    def _run_symbol(
        self,
        symbol: str,
        df_15m: pd.DataFrame,
        df_aligned: pd.DataFrame,
        initial_capital: float,
    ) -> Tuple[List[TradeRecord], List[float]]:
        """
        Ejecuta el backtest bar-a-bar para un símbolo.

        Returns:
            (trades cerrados, equity curve del símbolo)
        """
        trades: List[TradeRecord] = []
        equity: List[float]       = [initial_capital]
        capital = initial_capital

        open_positions: Dict[str, _OpenPosition] = {}
        pending_entry: Optional[Dict]             = None   # Señal esperando next_open

        halt_tracker = self._DailyHaltTracker(
            self.risk_cfg.max_daily_loss_pct, initial_capital
        )

        last_signal_bar = -999   # Cooldown de señal

        bars = df_15m.index.tolist()
        n    = len(bars)

        for i, ts in enumerate(bars):
            if i >= len(df_aligned):
                break

            bar_row  = df_15m.iloc[i]
            bar_time = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts

            # 1. Comprobar cierres (SL/TP) de posiciones abiertas
            if open_positions:
                closed, net_pnl_closed = self._check_exits(
                    open_positions, i, bar_row, bar_time
                )
                if closed:
                    capital += net_pnl_closed
                    trades.extend(closed)
                    equity.append(capital)

            # 2. Actualizar daily halt
            halt_tracker.update(capital, bar_time)

            # 3. Ejecutar entrada pendiente (modo next_open)
            if (
                pending_entry is not None
                and self.backtest_cfg.entry_on == "next_open"
            ):
                pe = pending_entry
                pending_entry = None

                # Verificar que no haya posición abierta en este símbolo
                if symbol not in open_positions and not halt_tracker.is_halted:
                    open_bar_price = float(bar_row.get("open", 0))
                    if open_bar_price > 0:
                        eff_entry, slip_usd = self._compute_entry_price(
                            open_bar_price, pe["signal"]
                        )
                        notional_entry = eff_entry * pe["size"]
                        entry_fee_usd  = notional_entry * self.cost_cfg.fee_rate
                        entry_slip_usd = slip_usd * pe["size"]

                        # SL/TP calculados sobre el precio RAW de referencia
                        sl_dist = pe["atr"] * self.risk_cfg.sl_atr_mult
                        tp_dist = pe["atr"] * self.risk_cfg.tp_atr_mult
                        if pe["signal"] == "LONG":
                            sl = open_bar_price - sl_dist
                            tp = open_bar_price + tp_dist
                        else:
                            sl = open_bar_price + sl_dist
                            tp = open_bar_price - tp_dist

                        open_positions[symbol] = _OpenPosition(
                            symbol           = symbol,
                            signal           = pe["signal"],
                            regime           = pe["regime"],
                            score            = pe["score"],
                            entry_price_raw  = open_bar_price,
                            entry_price      = eff_entry,
                            stop_loss        = sl,
                            take_profit      = tp,
                            size             = pe["size"],
                            risk_amount_usd  = pe["risk_amount_usd"],
                            entry_bar        = i,
                            entry_time       = bar_time,
                            signal_time      = pe["signal_time"],
                            entry_fee_usd    = entry_fee_usd,
                            entry_slippage_usd = entry_slip_usd,
                            capital_at_entry = capital,
                            entry_on         = self.backtest_cfg.entry_on,
                            intrabar_policy  = self.backtest_cfg.intrabar_policy,
                            entry_features   = pe.get("features", {}),
                        )

            # 4. Detectar régimen desde datos HTF alineados
            aligned_row = df_aligned.iloc[i]
            htf_cols = [c for c in df_aligned.columns if c.endswith("_htf")]
            if not htf_cols:
                continue

            # Reconstruir mini-DataFrame para RegimeDetector
            htf_data = {c[:-4]: aligned_row[c] for c in htf_cols}
            if any(pd.isna(v) for v in htf_data.values()):
                continue  # HTF aún no disponible (periodo de warmup)

            df_htf_row = pd.DataFrame([htf_data])
            regime = RegimeDetector.detect(df_htf_row, adx_threshold=self.adx_threshold)

            # 5. Scoring en 15m
            if i < 2:
                continue

            df_ltf_window = df_15m.iloc[max(0, i - 10): i + 1]
            score, setup = ScoringEngine.evaluate(df_ltf_window, regime)

            signal = setup.get("signal", "NEUTRAL")
            atr    = float(setup.get("atr", 0))

            # 6. Decisión de entrada
            if (
                signal in ("LONG", "SHORT")
                and score >= self.strategy_cfg.entry_threshold_normalized
                and symbol not in open_positions
                and not halt_tracker.is_halted
                and atr > 0
                and (i - last_signal_bar) >= 4  # cooldown de 4 velas (1h)
            ):
                size, risk_amt = self._size_position(capital, atr, float(setup.get("entry_price", 0)))

                if size > 0:
                    entry_features = df_aligned.iloc[i].to_dict()
                    close_prices = df_15m['close']
                    entry_features["ret_3"] = (close_prices.iloc[i] / close_prices.iloc[i-3] - 1) if i >= 3 else 0.0
                    entry_features["ret_6"] = (close_prices.iloc[i] / close_prices.iloc[i-6] - 1) if i >= 6 else 0.0
                    entry_features["ret_12"] = (close_prices.iloc[i] / close_prices.iloc[i-12] - 1) if i >= 12 else 0.0

                    if self.backtest_cfg.entry_on == "next_open":
                        # Programar entrada en la siguiente vela
                        pending_entry = {
                            "signal":         signal,
                            "regime":         regime,
                            "score":          score,
                            "atr":            atr,
                            "size":           size,
                            "risk_amount_usd": risk_amt,
                            "signal_time":    bar_time,
                            "features":       entry_features,
                        }
                    else:
                        # Modo close: entrada inmediata al close de esta vela
                        close_price = float(bar_row.get("close", 0))
                        eff_entry, slip_usd = self._compute_entry_price(close_price, signal)
                        notional_entry = eff_entry * size
                        entry_fee_usd  = notional_entry * self.cost_cfg.fee_rate
                        entry_slip_usd = slip_usd * size

                        sl_dist = atr * self.risk_cfg.sl_atr_mult
                        tp_dist = atr * self.risk_cfg.tp_atr_mult
                        if signal == "LONG":
                            sl = close_price - sl_dist
                            tp = close_price + tp_dist
                        else:
                            sl = close_price + sl_dist
                            tp = close_price - tp_dist

                        open_positions[symbol] = _OpenPosition(
                            symbol           = symbol,
                            signal           = signal,
                            regime           = regime,
                            score            = score,
                            entry_price_raw  = close_price,
                            entry_price      = eff_entry,
                            stop_loss        = sl,
                            take_profit      = tp,
                            size             = size,
                            risk_amount_usd  = risk_amt,
                            entry_bar        = i,
                            entry_time       = bar_time,
                            signal_time      = bar_time,
                            entry_fee_usd    = entry_fee_usd,
                            entry_slippage_usd = entry_slip_usd,
                            capital_at_entry = capital,
                            entry_on         = self.backtest_cfg.entry_on,
                            intrabar_policy  = self.backtest_cfg.intrabar_policy,
                            entry_features   = entry_features,
                        )

                    last_signal_bar = i

        # Forzar cierre de posiciones abiertas al final del backtest
        if open_positions and len(df_15m) > 0:
            last_row  = df_15m.iloc[-1]
            last_time = df_15m.index[-1]
            last_time = last_time.to_pydatetime() if hasattr(last_time, "to_pydatetime") else last_time
            last_close = float(last_row.get("close", 0))

            for pos in list(open_positions.values()):
                record, net_pnl = self._close_position(
                    pos, last_close, "EOD", n - 1, last_time
                )
                capital += net_pnl
                trades.append(record)

            equity.append(capital)

        return trades, equity

    # ── Backtest completo ─────────────────────────────────────────────────────

    def run(self, data: Dict[str, Dict]) -> Dict:
        """
        Ejecuta el backtest para todos los símbolos.

        Args:
            data: Resultado de download() — {sym: {"15m": [...], "1h": [...]}}

        Returns:
            Diccionario con trades, equity_curve y métricas.
        """
        initial_capital = self.backtest_cfg.initial_capital
        all_trades:  List[TradeRecord] = []
        equity:      List[float]       = [initial_capital]
        capital      = initial_capital

        for sym, raw in data.items():
            print(f"\n  📊 {sym}...", end=" ", flush=True)
            df_15m, df_1h = self._prepare_symbol_data(raw)
            if df_15m is None:
                print("✗ datos insuficientes")
                continue

            df_aligned = self._align_htf(df_15m, df_1h)

            sym_trades, sym_equity = self._run_symbol(
                sym, df_15m, df_aligned, initial_capital
            )

            n_signals = len(sym_trades)
            n_wins    = sum(1 for t in sym_trades if t.net_pnl > 0)
            print(f"✓ {n_signals} trades ({n_wins} wins)")

            # Integrar PnL del símbolo en la equity global
            for t in sym_trades:
                capital += t.net_pnl
                equity.append(capital)
                all_trades.append(t)

        # Ordenar trades por entry_time
        all_trades.sort(key=lambda t: t.entry_time or datetime.min)

        metrics = BacktestMetrics.compute_all(all_trades, initial_capital, equity)

        # Calmar requiere CAGR y max drawdown
        if metrics.get("cagr_pct", 0) != 0 and metrics.get("max_drawdown_pct", 0) != 0:
            metrics["calmar"] = round(
                abs(metrics["cagr_pct"] / metrics["max_drawdown_pct"]), 3
            )

        return {
            "trades":       all_trades,
            "equity_curve": equity,
            "metrics":      metrics,
            "config": {
                "entry_on":       self.backtest_cfg.entry_on,
                "intrabar_policy": self.backtest_cfg.intrabar_policy,
                "backtest_months": self.backtest_cfg.backtest_months,
                "initial_capital": self.backtest_cfg.initial_capital,
                "symbols":         self.symbols,
                "fee_rate":        self.cost_cfg.fee_rate,
                "slippage_entry":  self.cost_cfg.entry_slippage,
                "slippage_exit":   self.cost_cfg.exit_slippage,
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    print("=" * 64)
    print("   BACKTESTER — Q-Trade Pro (sin look-ahead bias)")
    print("=" * 64)
    print(f"  Entrada:       {args.entry_on}")
    print(f"  Intrabar:      {args.intrabar_policy}")
    print(f"  Meses:         {args.months}")
    print(f"  Capital:       ${args.capital:,.0f}")
    print(f"  Símbolos:      {len(DEFAULT_SYMBOLS)}")
    print(f"  ADX threshold: {args.adx}")
    print(f"  SL mult:       {args.sl_mult}x ATR")
    print(f"  TP mult:       {args.tp_mult}x ATR")

    backtest_cfg = BacktestConfig(
        initial_capital  = args.capital,
        entry_on         = args.entry_on,
        intrabar_policy  = args.intrabar_policy,
        backtest_months  = args.months,
    )

    # Override de riesgo si se especifican en CLI
    risk_cfg = RiskConfig(
        risk_per_trade_pct = DEFAULT_RISK.risk_per_trade_pct,
        sl_atr_mult        = args.sl_mult,
        tp_atr_mult        = args.tp_mult,
        max_daily_loss_pct = DEFAULT_RISK.max_daily_loss_pct,
    )

    bt = Backtester(
        backtest_cfg = backtest_cfg,
        risk_cfg     = risk_cfg,
        adx_threshold = args.adx,
    )
    data = await bt.download()

    if not data:
        print("❌ Sin datos. Verifica la conexión.")
        return

    print("\n⚙️  Ejecutando backtest bar-a-bar...")
    result = bt.run(data)

    BacktestMetrics.print_report(result["metrics"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Q-Trade Pro Backtester")
    parser.add_argument(
        "--entry-on",
        choices=["next_open", "close"],
        default="next_open",
        help="Modo de entrada: next_open (default, realista) o close (comparación)",
    )
    parser.add_argument(
        "--intrabar-policy",
        choices=["conservative", "optimistic"],
        default="conservative",
        help="Política cuando SL y TP se tocan en la misma vela",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="Meses de datos históricos a descargar",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=1000.0,
        help="Capital inicial del backtest",
    )
    parser.add_argument(
        "--adx",
        type=int,
        default=20,
        help="Umbral ADX mínimo para considerar tendencia (default=20, original=25)",
    )
    parser.add_argument(
        "--sl-mult",
        type=float,
        default=DEFAULT_RISK.sl_atr_mult,
        help="Múltiplo ATR para Stop Loss (default=1.5)",
    )
    parser.add_argument(
        "--tp-mult",
        type=float,
        default=DEFAULT_RISK.tp_atr_mult,
        help="Múltiplo ATR para Take Profit (default=3.0)",
    )
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
