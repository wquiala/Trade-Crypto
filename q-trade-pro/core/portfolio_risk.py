"""
core/portfolio_risk.py
=======================
Gestión del riesgo agregado del portfolio.

Responsabilidades
─────────────────
1. Calcular el riesgo total actual del portfolio (suma de riesgos individuales).
2. Decidir si se puede abrir una nueva posición sin superar los límites.
3. Gestionar el Daily Halt: un kill switch persistente durante el día de trading.
4. Controlar la exposición por dirección (LONG/SHORT) y por activo.

Daily Halt — semántica
───────────────────────
El daily halt se activa cuando las pérdidas del día superan MAX_DAILY_LOSS_PCT.
Una vez activado:
    - NO se abren nuevas posiciones.
    - Se mantiene activo durante toda la sesión.
    - Solo se resetea cuando comienza un nuevo día UTC.

IMPORTANTE: El daily halt NO debe resetearse en cada iteración del loop principal.
Solo se resetea explícitamente mediante reset_daily_state().

Arquitectura para correlación
──────────────────────────────
El sistema está preparado para añadir modelos de correlación en el futuro.
Por ahora se controla mediante:
    - MAX_LONG_EXPOSURE_PCT: límite de exposición total LONG
    - MAX_SHORT_EXPOSURE_PCT: límite de exposición total SHORT
    - MAX_ASSET_EXPOSURE_PCT: límite de exposición en un mismo activo
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, Optional
import logging

from config.config import RiskConfig, DEFAULT_RISK

logger = logging.getLogger(__name__)


class PortfolioRiskManager:
    """
    Gestión del riesgo agregado y del Daily Trading Halt.

    Instanciar una vez y reutilizar durante toda la sesión.
    """

    def __init__(self, config: RiskConfig = DEFAULT_RISK):
        self.config = config

        # ── Daily halt state (persistente durante el día) ──────────────────
        self._daily_halt_active: bool = False
        self._current_trading_day: str = self._today_utc()
        self._start_of_day_capital: float = 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Interfaz pública — Daily Halt
    # ─────────────────────────────────────────────────────────────────────────

    def initialize_day(self, capital: float) -> None:
        """
        Inicializar el estado del día.
        Llamar UNA VEZ al inicio de cada día de trading.
        """
        self._start_of_day_capital = capital
        self._daily_halt_active = False
        self._current_trading_day = self._today_utc()
        logger.info(
            "DailyReset | Nuevo día %s | Capital inicial: $%.2f",
            self._current_trading_day,
            capital,
        )

    def check_and_update_daily_state(self, current_capital: float) -> None:
        """
        Verificar si se ha alcanzado el límite de pérdida diaria.

        Si las pérdidas del día superan MAX_DAILY_LOSS_PCT:
            → Activa el daily halt (persistente hasta el día siguiente).

        Este método debe llamarse en cada iteración del loop principal,
        pero NUNCA resetea el halt — solo lo activa si procede.
        """
        today = self._today_utc()

        # Si es un día nuevo: resetear automáticamente
        if today != self._current_trading_day:
            logger.info(
                "DailyReset | Día anterior: %s → Nuevo día: %s",
                self._current_trading_day,
                today,
            )
            self.initialize_day(current_capital)
            return

        if self._daily_halt_active:
            # Ya está activo: no hacer nada (esperar al día siguiente)
            return

        if self._start_of_day_capital <= 0:
            return

        daily_pnl_pct = (current_capital - self._start_of_day_capital) / self._start_of_day_capital

        if daily_pnl_pct <= -self.config.max_daily_loss_pct:
            self._daily_halt_active = True
            logger.critical(
                "DAILY_HALT | Pérdida diaria del %.2f%% supera límite del %.2f%%. "
                "NO nuevas posiciones hasta mañana.",
                abs(daily_pnl_pct * 100),
                self.config.max_daily_loss_pct * 100,
            )

    @property
    def is_daily_halt_active(self) -> bool:
        """True si el trading diario está suspendido por pérdidas."""
        return self._daily_halt_active

    @property
    def start_of_day_capital(self) -> float:
        return self._start_of_day_capital

    # ─────────────────────────────────────────────────────────────────────────
    # Interfaz pública — Portfolio Risk
    # ─────────────────────────────────────────────────────────────────────────

    def get_current_portfolio_risk(
        self,
        positions: Dict[str, Dict[str, Any]],
        current_capital: float,
    ) -> float:
        """
        Calcula el riesgo agregado actual del portfolio como fracción del capital.

        El riesgo de cada posición = distancia al SL * size.
        Esto es la máxima pérdida esperada si todos los SL se ejecutan.
        """
        if current_capital <= 0:
            return 1.0  # asumir riesgo máximo si el capital es inválido

        total_risk = 0.0
        for sym, pos in positions.items():
            entry = float(pos.get("entry_price", 0))
            sl    = float(pos.get("stop_loss", 0))
            size  = float(pos.get("size", 0))

            if entry <= 0 or sl <= 0 or size <= 0:
                continue

            sl_distance = abs(entry - sl)
            position_risk = sl_distance * size
            total_risk += position_risk

        return total_risk / current_capital

    def get_current_exposures(
        self,
        positions: Dict[str, Dict[str, Any]],
        current_prices: Dict[str, float],
        current_capital: float,
    ) -> Dict[str, float]:
        """
        Calcula las exposiciones actuales del portfolio.

        Returns:
            {
                "total_long_pct":  exposición LONG total / capital,
                "total_short_pct": exposición SHORT total / capital,
                "by_asset": { "BTC/USDT:USDT": exposición_pct, ... }
            }
        """
        if current_capital <= 0:
            return {"total_long_pct": 0.0, "total_short_pct": 0.0, "by_asset": {}}

        long_exposure = 0.0
        short_exposure = 0.0
        by_asset: Dict[str, float] = {}

        for sym, pos in positions.items():
            size   = float(pos.get("size", 0))
            signal = pos.get("signal", "NEUTRAL")
            price  = current_prices.get(sym, pos.get("entry_price", 0))
            notional = size * float(price)

            if signal == "LONG":
                long_exposure += notional
            elif signal == "SHORT":
                short_exposure += notional

            by_asset[sym] = notional / current_capital

        return {
            "total_long_pct":  long_exposure / current_capital,
            "total_short_pct": short_exposure / current_capital,
            "by_asset":        by_asset,
        }

    def can_open_position(
        self,
        symbol: str,
        signal: str,
        new_risk_amount: float,
        positions: Dict[str, Dict[str, Any]],
        current_prices: Dict[str, float],
        current_capital: float,
    ) -> tuple[bool, str]:
        """
        Verifica si se puede abrir una nueva posición.

        Checks en orden:
        1. Daily halt activo.
        2. Portfolio risk total.
        3. Exposición por dirección (LONG/SHORT).
        4. Exposición por activo.
        5. Límite de posiciones simultáneas.
        6. Límite por dirección.

        Returns:
            (permitido: bool, motivo_rechazo: str)
        """
        # 1. Daily halt
        if self._daily_halt_active:
            return False, "DAILY_HALT_ACTIVE"

        if current_capital <= 0:
            return False, "INVALID_CAPITAL"

        # 2. Portfolio risk total
        current_portfolio_risk = self.get_current_portfolio_risk(positions, current_capital)
        new_risk_pct = new_risk_amount / current_capital
        projected_risk = current_portfolio_risk + new_risk_pct

        if projected_risk > self.config.max_portfolio_risk_pct:
            return False, (
                f"MAX_PORTFOLIO_RISK | Riesgo actual {current_portfolio_risk:.2%} + "
                f"nuevo {new_risk_pct:.2%} = {projected_risk:.2%} > "
                f"límite {self.config.max_portfolio_risk_pct:.2%}"
            )

        # 3. Exposición por dirección
        exposures = self.get_current_exposures(positions, current_prices, current_capital)
        if signal == "LONG":
            if exposures["total_long_pct"] >= self.config.max_long_exposure_pct:
                return False, (
                    f"MAX_LONG_EXPOSURE | {exposures['total_long_pct']:.2%} >= "
                    f"{self.config.max_long_exposure_pct:.2%}"
                )
        elif signal == "SHORT":
            if exposures["total_short_pct"] >= self.config.max_short_exposure_pct:
                return False, (
                    f"MAX_SHORT_EXPOSURE | {exposures['total_short_pct']:.2%} >= "
                    f"{self.config.max_short_exposure_pct:.2%}"
                )

        # 4. Exposición por activo
        asset_exposure = exposures["by_asset"].get(symbol, 0.0)
        if asset_exposure >= self.config.max_asset_exposure_pct:
            return False, (
                f"MAX_ASSET_EXPOSURE | {symbol} {asset_exposure:.2%} >= "
                f"{self.config.max_asset_exposure_pct:.2%}"
            )

        # 5. Límite de posiciones simultáneas
        if len(positions) >= self.config.max_concurrent_positions:
            return False, f"MAX_POSITIONS | {len(positions)} >= {self.config.max_concurrent_positions}"

        # 6. Límite por dirección
        same_dir = sum(1 for p in positions.values() if p.get("signal") == signal)
        if same_dir >= self.config.max_same_direction:
            return False, f"MAX_SAME_DIRECTION | {same_dir} {signal} >= {self.config.max_same_direction}"

        return True, ""

    # ─────────────────────────────────────────────────────────────────────────
    # Utilidades privadas
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _today_utc() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
