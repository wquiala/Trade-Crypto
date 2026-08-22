from typing import Tuple, Dict, Any

class RiskManager:
    """
    Gestión de capital profesional.
    - Riesgo fijo: 2% del capital por operación
    - SL: 1.5x ATR (suficiente margen para no ser barrido por ruido)
    - TP: 3.0x ATR (ratio Riesgo:Beneficio de 1:2)
    - Máximo 3 posiciones simultáneas (controlado en main.py)
    """

    MAX_RISK_PER_TRADE_PCT = 0.02   # 2% por trade (mayor agresividad)
    SL_ATR_MULT            = 1.5    # Stop Loss = 1.5x ATR
    TP_ATR_MULT            = 3.0    # Take Profit = 3.0x ATR  →  RR = 1:2

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

        entry_price = setup['entry_price']
        atr         = setup['atr']

        if entry_price <= 0 or atr <= 0:
            return False, 0.0

        sl_distance = atr * RiskManager.SL_ATR_MULT
        tp_distance = atr * RiskManager.TP_ATR_MULT

        # Riesgo monetario máximo por trade
        max_monetary_risk = current_capital * RiskManager.MAX_RISK_PER_TRADE_PCT

        # Tamaño (contratos/monedas) = Riesgo€ / Distancia_SL
        position_size = max_monetary_risk / sl_distance

        # Calcular niveles de salida
        if setup['signal'] == 'LONG':
            setup['stop_loss']   = entry_price - sl_distance
            setup['take_profit'] = entry_price + tp_distance
        else:  # SHORT
            setup['stop_loss']   = entry_price + sl_distance
            setup['take_profit'] = entry_price - tp_distance

        rr_ratio = tp_distance / sl_distance
        print(
            f"[RiskManager] {setup['signal']} {setup.get('regime','')} | "
            f"Entry: {entry_price:.4f} | SL: {setup['stop_loss']:.4f} | "
            f"TP: {setup['take_profit']:.4f} | ATR: {atr:.4f} | "
            f"RR: 1:{rr_ratio:.1f} | Size: {position_size:.4f} | "
            f"Riesgo: ${max_monetary_risk:.2f}"
        )

        return True, position_size
