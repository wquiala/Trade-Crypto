from typing import Tuple, Dict, Any

class RiskManager:
    """
    Gestión de capital profesional.
    - Riesgo fijo: 2% del capital por operación
    - SL: 1.5x ATR (suficiente margen para no ser barrido por ruido)
    - TP: 3.0x ATR (ratio Riesgo:Beneficio de 1:2)
    - Máximo apalancamiento efectivo: 3x capital
    """

    MAX_RISK_PER_TRADE_PCT = 0.02   # 2% por trade
    SL_ATR_MULT            = 1.5    # Stop Loss = 1.5x ATR
    TP_ATR_MULT            = 3.0    # Take Profit = 3.0x ATR (ratio R:B 1:2)
    MAX_LEVERAGE           = 3.0    # Límite máximo de apalancamiento notional

    @staticmethod
    def validate_and_size(
        setup: Dict[str, Any],
        current_capital: float,
        start_of_day_capital: float
    ) -> Tuple[bool, float]:
        """
        Valida el setup y devuelve (aprobado, tamaño_posición_en_monedas).
        """
        if setup.get('signal') == 'NEUTRAL' or current_capital <= 0:
            return False, 0.0

        entry_price = float(setup.get('entry_price', 0))
        atr         = float(setup.get('atr', 0))

        if entry_price <= 0 or atr <= 0:
            return False, 0.0

        sl_distance = atr * RiskManager.SL_ATR_MULT
        tp_distance = atr * RiskManager.TP_ATR_MULT

        # Riesgo monetario máximo por trade (pérdida asumida si toca SL)
        max_monetary_risk = current_capital * RiskManager.MAX_RISK_PER_TRADE_PCT

        # Tamaño inicial basado en riesgo monetario = Riesgo / Distancia_SL
        position_size = max_monetary_risk / sl_distance

        # Protección: limitar el notional total según el apalancamiento máximo permitido
        max_notional = current_capital * RiskManager.MAX_LEVERAGE
        notional_initial = position_size * entry_price
        if notional_initial > max_notional:
            position_size = max_notional / entry_price

        # Calcular niveles de salida
        if setup['signal'] == 'LONG':
            setup['stop_loss']   = entry_price - sl_distance
            setup['take_profit'] = entry_price + tp_distance
        else:  # SHORT
            setup['stop_loss']   = entry_price + sl_distance
            setup['take_profit'] = entry_price - tp_distance

        rr_ratio = tp_distance / sl_distance
        final_notional = position_size * entry_price
        print(
            f"[RiskManager] {setup['signal']} {setup.get('regime','')} | "
            f"Entry: {entry_price:.4f} | SL: {setup['stop_loss']:.4f} | "
            f"TP: {setup['take_profit']:.4f} | ATR: {atr:.4f} | "
            f"RR: 1:{rr_ratio:.1f} | Size: {position_size:.4f} | "
            f"Notional: ${final_notional:.2f} | Riesgo: ${max_monetary_risk:.2f}"
        )

        return True, position_size
