"""
backtest/metrics.py
===================
Cálculo de métricas cuantitativas de rendimiento para backtesting.

Todas las métricas se calculan sobre una lista de TradeRecord.
Los métodos son estáticos y no tienen estado.

Categorías
──────────
- Rendimiento: PnL, retorno, CAGR
- Ratios de riesgo-ajustado: Sharpe, Sortino, Calmar
- Edge: Profit Factor, Expectancy (en R), Kelly%
- Drawdown: Max Drawdown, duración
- Costes: fees, slippage totales
- Excursiones: MFE/MAE distribuciones
- Desglose: por símbolo, régimen, mes
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Any

import pandas as pd
import numpy as np

from models.trade import TradeRecord


class BacktestMetrics:
    """
    Calcula métricas de rendimiento sobre una lista de TradeRecord.
    """

    @staticmethod
    def compute_all(
        trades: List[TradeRecord],
        initial_capital: float,
        equity_curve: List[float],
    ) -> Dict[str, Any]:
        """
        Calcula todas las métricas disponibles.

        Args:
            trades:          Lista de TradeRecord cerrados.
            initial_capital: Capital inicial del backtest.
            equity_curve:    Lista de valores de capital (uno por trade cerrado + inicial).

        Returns:
            Diccionario con todas las métricas calculadas.
        """
        if not trades:
            return {"error": "No hay operaciones cerradas."}

        m: Dict[str, Any] = {}

        # ── Métricas básicas ──────────────────────────────────────────────────
        m.update(BacktestMetrics._performance(trades, initial_capital, equity_curve))

        # ── Ratios riesgo-ajustado ────────────────────────────────────────────
        m.update(BacktestMetrics._risk_ratios(equity_curve))

        # ── Edge ─────────────────────────────────────────────────────────────
        m.update(BacktestMetrics._edge(trades))

        # ── Drawdown ─────────────────────────────────────────────────────────
        m.update(BacktestMetrics._drawdown(equity_curve))

        # ── Costes ───────────────────────────────────────────────────────────
        m.update(BacktestMetrics._costs(trades))

        # ── MFE / MAE ────────────────────────────────────────────────────────
        m.update(BacktestMetrics._excursions(trades))

        # ── Desglose ─────────────────────────────────────────────────────────
        m["by_symbol"] = BacktestMetrics._by_symbol(trades)
        m["by_regime"] = BacktestMetrics._by_regime(trades)
        m["by_month"]  = BacktestMetrics._by_month(trades)

        return m

    # ── Rendimiento ───────────────────────────────────────────────────────────

    @staticmethod
    def _performance(
        trades: List[TradeRecord],
        initial_capital: float,
        equity_curve: List[float],
    ) -> Dict[str, Any]:
        wins   = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]

        total_pnl_net  = sum(t.net_pnl  for t in trades)
        total_pnl_gross = sum(t.gross_pnl for t in trades)
        final_capital  = equity_curve[-1] if equity_curve else initial_capital

        win_rate = len(wins) / len(trades) * 100 if trades else 0.0
        avg_win  = sum(t.net_pnl for t in wins)   / len(wins)   if wins   else 0.0
        avg_loss = sum(t.net_pnl for t in losses) / len(losses) if losses else 0.0

        # CAGR: calculamos desde el primer al último trade.
        # Si hay pocos trades muy concentrados, la duración es mínima y el CAGR explota.
        # Usamos max(duration_real, backtest_months/12 años) como denominador.
        if len(trades) >= 2 and trades[0].entry_time and trades[-1].exit_time:
            duration_days = max(
                1,
                (trades[-1].exit_time - trades[0].entry_time).days
            )
            years = duration_days / 365.25
            if years > 0 and initial_capital > 0 and final_capital > 0:
                cagr = ((final_capital / initial_capital) ** (1 / years) - 1) * 100
                # Clamp: CAGR irreal si el periodo es demasiado corto
                cagr = max(-100.0, min(cagr, 10_000.0))
            else:
                cagr = 0.0
        else:
            cagr = 0.0

        # Duración promedio
        durations = [t.duration_bars * 15 / 60 for t in trades if t.duration_bars > 0]
        avg_duration_h = sum(durations) / len(durations) if durations else 0.0

        return {
            "total_trades":    len(trades),
            "winning_trades":  len(wins),
            "losing_trades":   len(losses),
            "win_rate_pct":    round(win_rate, 2),
            "initial_capital": round(initial_capital, 2),
            "final_capital":   round(final_capital, 2),
            "total_pnl_net":   round(total_pnl_net, 2),
            "total_pnl_gross": round(total_pnl_gross, 2),
            "return_pct":      round((final_capital / initial_capital - 1) * 100, 2),
            "cagr_pct":        round(cagr, 2),
            "avg_win_usd":     round(avg_win, 2),
            "avg_loss_usd":    round(avg_loss, 2),
            "avg_rr_real":     round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0.0,
            "avg_duration_h":  round(avg_duration_h, 2),
        }

    # ── Ratios riesgo-ajustado ─────────────────────────────────────────────────

    @staticmethod
    def _risk_ratios(equity_curve: List[float]) -> Dict[str, Any]:
        """Sharpe, Sortino, Calmar usando la equity curve."""
        if len(equity_curve) < 2:
            return {"sharpe": 0.0, "sortino": 0.0, "calmar": 0.0}

        eq = pd.Series(equity_curve)
        returns = eq.pct_change().dropna()

        if returns.std() == 0:
            sharpe = 0.0
        else:
            # Anualizar: trades en 15m → ~26,280 periodos/año
            # Usamos número de observaciones para estimar
            sharpe = (returns.mean() / returns.std()) * math.sqrt(len(returns))

        downside = returns[returns < 0]
        if len(downside) == 0 or downside.std() == 0:
            sortino = 0.0
        else:
            sortino = (returns.mean() / downside.std()) * math.sqrt(len(returns))

        # Calmar = CAGR / Max Drawdown
        max_dd = BacktestMetrics._max_drawdown_pct(equity_curve)
        calmar = 0.0  # Se calcula con CAGR en compute_all

        return {
            "sharpe":  round(sharpe, 3),
            "sortino": round(sortino, 3),
            "calmar":  round(calmar, 3),  # Completado en compute_all
        }

    # ── Edge ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _edge(trades: List[TradeRecord]) -> Dict[str, Any]:
        wins   = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]

        gross_wins   = sum(t.net_pnl for t in wins)
        gross_losses = abs(sum(t.net_pnl for t in losses))

        # Profit Factor
        if gross_losses == 0:
            profit_factor = float("inf")
        else:
            profit_factor = round(gross_wins / gross_losses, 3)

        # Expectancy en R
        pnl_r_values = [t.pnl_r for t in trades]
        expectancy_r = round(sum(pnl_r_values) / len(pnl_r_values), 4) if pnl_r_values else 0.0

        # Kelly% = WR - (1 - WR) / RR
        wr = len(wins) / len(trades) if trades else 0
        avg_win_r  = sum(t.pnl_r for t in wins)   / len(wins)   if wins   else 0
        avg_loss_r = sum(t.pnl_r for t in losses) / len(losses) if losses else 0
        if avg_loss_r != 0:
            kelly_pct = round((wr - (1 - wr) / abs(avg_win_r / avg_loss_r)) * 100, 2)
        else:
            kelly_pct = 0.0

        # Rachas
        max_consec_wins   = BacktestMetrics._max_streak(trades, win=True)
        max_consec_losses = BacktestMetrics._max_streak(trades, win=False)

        return {
            "profit_factor":       profit_factor,
            "expectancy_r":        expectancy_r,
            "kelly_pct":           kelly_pct,
            "max_consec_wins":     max_consec_wins,
            "max_consec_losses":   max_consec_losses,
            "avg_win_r":           round(avg_win_r, 3),
            "avg_loss_r":          round(avg_loss_r, 3),
        }

    @staticmethod
    def _max_streak(trades: List[TradeRecord], win: bool) -> int:
        max_s = cur_s = 0
        for t in trades:
            if (t.net_pnl > 0) == win:
                cur_s += 1
                max_s = max(max_s, cur_s)
            else:
                cur_s = 0
        return max_s

    # ── Drawdown ─────────────────────────────────────────────────────────────

    @staticmethod
    def _drawdown(equity_curve: List[float]) -> Dict[str, Any]:
        max_dd_pct = BacktestMetrics._max_drawdown_pct(equity_curve)

        eq     = pd.Series(equity_curve)
        peak   = eq.cummax()
        dd_abs = peak - eq

        # Duración máxima del drawdown (en número de trades)
        in_dd     = False
        max_dur   = cur_dur = 0
        for val, pk in zip(eq, peak):
            if val < pk:
                in_dd   = True
                cur_dur += 1
                max_dur  = max(max_dur, cur_dur)
            else:
                in_dd   = False
                cur_dur = 0

        return {
            "max_drawdown_pct":      round(max_dd_pct, 2),
            "max_drawdown_usd":      round(float(dd_abs.max()), 2),
            "max_drawdown_duration": max_dur,   # en número de trades
        }

    @staticmethod
    def _max_drawdown_pct(equity_curve: List[float]) -> float:
        eq   = pd.Series(equity_curve)
        peak = eq.cummax()
        dd   = ((eq - peak) / peak * 100)
        return float(dd.min()) if not dd.empty else 0.0

    # ── Costes ───────────────────────────────────────────────────────────────

    @staticmethod
    def _costs(trades: List[TradeRecord]) -> Dict[str, Any]:
        total_fees      = sum(t.entry_fee_usd + t.exit_fee_usd for t in trades)
        total_slippage  = sum(t.entry_slippage_usd + t.exit_slippage_usd for t in trades)
        total_costs     = sum(t.total_cost_usd for t in trades)
        avg_cost        = total_costs / len(trades) if trades else 0.0

        return {
            "total_fees_usd":     round(total_fees, 2),
            "total_slippage_usd": round(total_slippage, 2),
            "total_costs_usd":    round(total_costs, 2),
            "avg_cost_per_trade": round(avg_cost, 2),
        }

    # ── MFE / MAE ─────────────────────────────────────────────────────────────

    @staticmethod
    def _excursions(trades: List[TradeRecord]) -> Dict[str, Any]:
        mfe_values = [t.mfe for t in trades if t.mfe > 0]
        mae_values = [t.mae for t in trades if t.mae > 0]

        wins   = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]

        return {
            "mfe_avg_r":        round(sum(mfe_values) / len(mfe_values), 3) if mfe_values else 0.0,
            "mfe_median_r":     round(float(np.median(mfe_values)), 3) if mfe_values else 0.0,
            "mae_avg_r":        round(sum(mae_values) / len(mae_values), 3) if mae_values else 0.0,
            "mae_median_r":     round(float(np.median(mae_values)), 3) if mae_values else 0.0,
            # MFE de operaciones ganadoras: ¿cuánto espacio tuvieron?
            "mfe_winners_avg":  round(sum(t.mfe for t in wins) / len(wins), 3) if wins else 0.0,
            # MAE de operaciones perdedoras: ¿alcanzaron el SL de forma directa?
            "mae_losers_avg":   round(sum(t.mae for t in losses) / len(losses), 3) if losses else 0.0,
        }

    # ── Desglose ─────────────────────────────────────────────────────────────

    @staticmethod
    def _by_symbol(trades: List[TradeRecord]) -> Dict[str, Dict]:
        result = defaultdict(lambda: {"n": 0, "net_pnl": 0.0, "wins": 0})
        for t in trades:
            result[t.symbol]["n"]       += 1
            result[t.symbol]["net_pnl"] += t.net_pnl
            if t.net_pnl > 0:
                result[t.symbol]["wins"] += 1
        # Añadir win_rate
        for sym in result:
            n = result[sym]["n"]
            result[sym]["win_rate_pct"] = round(result[sym]["wins"] / n * 100, 1) if n > 0 else 0.0
            result[sym]["net_pnl"]      = round(result[sym]["net_pnl"], 2)
        return dict(sorted(result.items(), key=lambda x: x[1]["net_pnl"], reverse=True))

    @staticmethod
    def _by_regime(trades: List[TradeRecord]) -> Dict[str, Dict]:
        result = defaultdict(lambda: {"n": 0, "net_pnl": 0.0, "wins": 0})
        for t in trades:
            result[t.regime]["n"]       += 1
            result[t.regime]["net_pnl"] += t.net_pnl
            if t.net_pnl > 0:
                result[t.regime]["wins"] += 1
        for reg in result:
            n = result[reg]["n"]
            result[reg]["win_rate_pct"] = round(result[reg]["wins"] / n * 100, 1) if n > 0 else 0.0
            result[reg]["net_pnl"]      = round(result[reg]["net_pnl"], 2)
        return dict(result)

    @staticmethod
    def _by_month(trades: List[TradeRecord]) -> Dict[str, Dict]:
        result = defaultdict(lambda: {"n": 0, "net_pnl": 0.0, "wins": 0})
        for t in trades:
            if t.entry_time:
                key = t.entry_time.strftime("%Y-%m")
                result[key]["n"]       += 1
                result[key]["net_pnl"] += t.net_pnl
                if t.net_pnl > 0:
                    result[key]["wins"] += 1
        for month in result:
            n = result[month]["n"]
            result[month]["win_rate_pct"] = round(result[month]["wins"] / n * 100, 1) if n > 0 else 0.0
            result[month]["net_pnl"]      = round(result[month]["net_pnl"], 2)
        return dict(sorted(result.items()))

    # ── Impresión ─────────────────────────────────────────────────────────────

    @staticmethod
    def print_report(m: Dict[str, Any]) -> None:
        """Imprime el informe de métricas en consola."""
        if "error" in m:
            print(f"⚠️  {m['error']}")
            return

        sep = "═" * 64
        print(f"\n{sep}")
        print("         BACKTEST REPORT — Q-Trade Pro")
        print(sep)
        print(f"  Capital inicial:        ${m['initial_capital']:>12,.2f}")
        print(f"  Capital final:          ${m['final_capital']:>12,.2f}   ({m['return_pct']:+.2f}%)")
        print(f"  PnL neto:               ${m['total_pnl_net']:>+12,.2f}")
        print(f"  PnL bruto:              ${m['total_pnl_gross']:>+12,.2f}")
        print(f"  Costes totales:         ${m['total_costs_usd']:>12,.2f}")
        print(f"  CAGR:                   {m['cagr_pct']:>11.2f}%")
        print("─" * 64)
        print(f"  Total operaciones:      {m['total_trades']:>12}")
        print(f"  Ganadoras:              {m['winning_trades']:>9} ({m['win_rate_pct']:.1f}%)")
        print(f"  Perdedoras:             {m['losing_trades']:>9} ({100 - m['win_rate_pct']:.1f}%)")
        print(f"  Ganancia media:         ${m['avg_win_usd']:>+12,.2f}")
        print(f"  Pérdida media:          ${m['avg_loss_usd']:>+12,.2f}")
        print(f"  Ratio R:B real:         {m['avg_rr_real']:>12.2f}x")
        print(f"  Duración media:         {m['avg_duration_h']:>10.1f}h")
        print("─" * 64)
        print(f"  Profit Factor:          {m['profit_factor']:>12.3f}  (>1.0 = rentable)")
        print(f"  Expectancy:             {m['expectancy_r']:>+12.4f}R por trade")
        print(f"  Kelly%:                 {m['kelly_pct']:>11.1f}%")
        print(f"  Sharpe:                 {m['sharpe']:>12.3f}")
        print(f"  Sortino:                {m['sortino']:>12.3f}")
        print(f"  Max Drawdown:           {m['max_drawdown_pct']:>11.2f}%")
        print(f"  Max racha ganadora:     {m['max_consec_wins']:>12}")
        print(f"  Max racha perdedora:    {m['max_consec_losses']:>12}")
        print("─" * 64)
        print("  MFE/MAE (en R):")
        print(f"    MFE promedio:         {m['mfe_avg_r']:>+12.3f}R")
        print(f"    MAE promedio:         {m['mae_avg_r']:>+12.3f}R")
        print("─" * 64)
        print("  PnL por régimen:")
        for reg, rd in m.get("by_regime", {}).items():
            icon = "🟢" if rd["net_pnl"] > 0 else "🔴"
            print(f"    {reg:20} ${rd['net_pnl']:>+10,.2f}  ({rd['n']} trades, {rd['win_rate_pct']}% WR) {icon}")
        print("─" * 64)
        print("  PnL por símbolo:")
        for sym, sd in list(m.get("by_symbol", {}).items())[:10]:
            icon = "🟢" if sd["net_pnl"] > 0 else "🔴"
            print(f"    {sym:20} ${sd['net_pnl']:>+10,.2f}  ({sd['n']} trades) {icon}")
        print("─" * 64)
        print("  PnL por mes:")
        for month, md in m.get("by_month", {}).items():
            icon = "🟢" if md["net_pnl"] > 0 else "🔴"
            print(f"    {month}    ${md['net_pnl']:>+10,.2f}  ({md['n']} trades) {icon}")
        print(sep)

        # Veredicto
        pf = m["profit_factor"]
        wr = m["win_rate_pct"]
        dd = abs(m["max_drawdown_pct"])
        if pf > 1.3 and wr > 40 and dd < 20:
            verdict = "✅ EDGE DEMOSTRADO — Candidato a producción"
        elif pf > 1.1 and wr > 35:
            verdict = "🟡 EDGE MARGINAL — Seguir validando OOS"
        else:
            verdict = "🔴 SIN EDGE — No desplegar. Revisar estrategia."

        print(f"  VEREDICTO: {verdict}")
        print(sep + "\n")
