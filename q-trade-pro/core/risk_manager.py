"""
core/risk_manager.py
====================
Gestión de riesgo por operación individual.

Responsabilidades
─────────────────
1. Calcular el position sizing basado en la pérdida máxima asumida en el SL.
2. Incorporar fees, slippage y spread al cálculo de sizing y niveles.
3. Calcular stop loss y take profit.

Distinción notional / margin / risk
────────────────────────────────────
- risk_amount:      Máxima pérdida monetaria si el precio alcanza el SL.
                    = capital * risk_per_trade_pct
- notional:         Valor total de la posición = size * entry_price.
- margin:           Capital bloqueado = notional / leverage.

El sizing siempre se basa en risk_amount.
La fórmula es: size = effective_risk / sl_distance_after_costs

Modelo de costes
────────────────
Coste total por vuelta (round-trip):
    entry_fee       = notional * fee_rate
    exit_fee        = notional * fee_rate
    entry_slippage  = notional * entry_slippage_pct
    exit_slippage   = notional * exit_slippage_pct
    spread          = notional * spread_bps

El effective_risk_amount descuenta los costes de entrada:
    effective_risk = risk_amount - (notional * (entry_fee + entry_slippage + spread/2))

Nota sobre apalancamiento
──────────────────────────
Con leverage > 1:
    margin = notional / leverage
    Pero el riesgo monetario (pérdida en SL) no cambia:
        sl_distance * size = risk_amount (igual que sin leverage)
    Lo que cambia es que con leverage el mismo risk_amount controla
    mayor notional usando menos margin.
"""

from __future__ import annotations

from typing import Tuple, Dict, Any
import logging

from config.config import RiskConfig, CostConfig, DEFAULT_RISK, DEFAULT_COSTS

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Validación y sizing de operaciones individuales.

    No gestiona riesgo de portfolio (eso es PortfolioRiskManager).
    """

    @staticmethod
    def validate_and_size(
        setup: Dict[str, Any],
        current_capital: float,
        risk_config: RiskConfig = DEFAULT_RISK,
        cost_config: CostConfig = DEFAULT_COSTS,
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Valida el setup y calcula el tamaño de la posición.

        Args:
            setup:           Dict con signal, entry_price, atr.
            current_capital: Capital disponible actual.
            risk_config:     Parámetros de riesgo.
            cost_config:     Modelo de costes.

        Returns:
            (aprobado, position_size, sizing_details)

        Donde sizing_details contiene:
            - stop_loss
            - take_profit
            - risk_amount_gross:   Riesgo antes de descontar costes.
            - risk_amount_net:     Riesgo neto después de costes (lo que se arriesga realmente).
            - round_trip_cost_est: Estimación del coste total del trade.
            - notional:            Valor total de la posición.
            - margin:              Capital bloqueado (notional / leverage).
        """
        signal = setup.get("signal", "NEUTRAL")
        if signal == "NEUTRAL" or current_capital <= 0:
            return False, 0.0, {}

        entry_price: float = float(setup.get("entry_price", 0))
        atr: float         = float(setup.get("atr", 0))

        # Validaciones básicas
        if entry_price <= 0 or atr <= 0:
            logger.warning("RiskManager | entry_price=%.4f, atr=%.4f inválidos.", entry_price, atr)
            return False, 0.0, {}

        # ── Distancias de SL y TP ──────────────────────────────────────────────
        sl_distance = atr * risk_config.sl_atr_mult
        tp_distance = atr * risk_config.tp_atr_mult

        # ── Riesgo monetario bruto ─────────────────────────────────────────────
        risk_amount_gross = current_capital * risk_config.risk_per_trade_pct

        # ── Position size inicial (estimación antes de costes) ─────────────────
        size_estimate = risk_amount_gross / sl_distance

        # ── Estimación del notional ────────────────────────────────────────────
        notional_estimate = size_estimate * entry_price

        # ── Costes estimados de entrada ────────────────────────────────────────
        # Descontamos de risk_amount solo los costes de ENTRADA.
        # Los de salida los asumirá el PnL real.
        entry_cost_rate = (
            cost_config.fee_rate
            + cost_config.entry_slippage
            + cost_config.spread_bps / 2   # Mitad del spread en la entrada
        )
        entry_cost_amount = notional_estimate * entry_cost_rate

        # ── Riesgo neto (lo que realmente arriesgamos) ─────────────────────────
        risk_amount_net = risk_amount_gross - entry_cost_amount
        if risk_amount_net <= 0:
            logger.warning(
                "RiskManager | Los costes de entrada (%.4f) superan el riesgo disponible (%.4f).",
                entry_cost_amount,
                risk_amount_gross,
            )
            return False, 0.0, {}

        # ── Position size final ────────────────────────────────────────────────
        position_size = risk_amount_net / sl_distance

        # ── Notional y margin finales ──────────────────────────────────────────
        notional = position_size * entry_price
        margin   = notional / risk_config.leverage

        # Verificar que el margin no supera el capital disponible
        if margin > current_capital:
            logger.warning(
                "RiskManager | Margin requerido ($%.2f) > capital ($%.2f). Ajustando.",
                margin,
                current_capital,
            )
            position_size = (current_capital * risk_config.leverage) / entry_price
            notional = position_size * entry_price
            margin   = notional / risk_config.leverage

        # ── Estimación del coste total round-trip ──────────────────────────────
        round_trip_cost_est = notional * cost_config.total_round_trip_cost()

        # ── Niveles de SL y TP ────────────────────────────────────────────────
        if signal == "LONG":
            stop_loss   = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:  # SHORT
            stop_loss   = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        # Populate setup in-place (para compatibilidad con el motor de ejecución)
        setup["stop_loss"]   = stop_loss
        setup["take_profit"] = take_profit

        rr_ratio = tp_distance / sl_distance

        sizing_details = {
            "stop_loss":             stop_loss,
            "take_profit":           take_profit,
            "sl_distance":           sl_distance,
            "tp_distance":           tp_distance,
            "rr_ratio":              rr_ratio,
            "risk_amount_gross":     risk_amount_gross,
            "risk_amount_net":       risk_amount_net,
            "round_trip_cost_est":   round_trip_cost_est,
            "notional":              notional,
            "margin":                margin,
            "leverage":              risk_config.leverage,
        }

        logger.info(
            "RiskManager | %s %s | Entry: %.4f | SL: %.4f | TP: %.4f | "
            "ATR: %.4f | RR: 1:%.1f | Size: %.4f | RiskNet: $%.2f | "
            "Notional: $%.2f | CostEst: $%.2f",
            signal, setup.get("regime", ""),
            entry_price, stop_loss, take_profit,
            atr, rr_ratio, position_size,
            risk_amount_net, notional, round_trip_cost_est,
        )

        return True, position_size, sizing_details
