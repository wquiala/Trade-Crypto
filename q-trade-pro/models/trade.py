"""
models/trade.py
===============
TradeRecord: representación completa e inmutable de una operación cerrada.

Diseño
──────
- Todos los campos se rellenan en el momento del CIERRE de la posición.
- pnl_r expresa el resultado en múltiplos de R (1R = riesgo inicial).
- mfe y mae también están en múltiplos de R para comparabilidad.
- La separación entre gross_pnl y net_pnl permite analizar el impacto de costes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class TradeRecord:
    """
    Registro completo de una operación cerrada.

    Campos de tiempo
    ────────────────
    - signal_time: timestamp de la vela que generó la señal (vela N cerrada).
    - entry_time:  timestamp de la vela en la que se ejecutó la entrada (vela N+1 con next_open).
    - exit_time:   timestamp de la vela en la que se cerró la posición.

    Campos de coste
    ───────────────
    - entry_fee_usd:      fee de entrada en USD.
    - exit_fee_usd:       fee de salida en USD.
    - entry_slippage_usd: slippage de entrada en USD.
    - exit_slippage_usd:  slippage de salida en USD.
    - gross_pnl:          PnL antes de costes.
    - net_pnl:            PnL después de todos los costes (el real).

    Campos de riesgo
    ────────────────
    - pnl_r: resultado en múltiplos de R (1R = riesgo monetario initial).
             +2.0 → ganancia de 2x el riesgo asumido.
             -1.0 → pérdida del stop loss completo.
    - mfe:   Maximum Favorable Excursion en R (mejor momento para el trade).
    - mae:   Maximum Adverse Excursion en R (peor momento para el trade).
    """

    # ── Identificadores ──────────────────────────────────────────────────────
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol:   str = ""

    # ── Señal ────────────────────────────────────────────────────────────────
    signal:  Literal["LONG", "SHORT"] = "LONG"
    regime:  str = "UNKNOWN"
    score:   float = 0.0                    # Score normalizado 0-100

    # ── Precios ──────────────────────────────────────────────────────────────
    entry_price:  float = 0.0              # Precio efectivo de entrada (con slippage)
    exit_price:   float = 0.0             # Precio efectivo de salida (con slippage)
    stop_loss:    float = 0.0
    take_profit:  float = 0.0

    # ── Sizing ───────────────────────────────────────────────────────────────
    size:              float = 0.0         # Contratos / monedas
    risk_amount_usd:   float = 0.0         # Riesgo monetario asumido (sin costes)

    # ── Costes (USD) ─────────────────────────────────────────────────────────
    entry_fee_usd:       float = 0.0
    exit_fee_usd:        float = 0.0
    entry_slippage_usd:  float = 0.0
    exit_slippage_usd:   float = 0.0

    @property
    def total_cost_usd(self) -> float:
        """Coste total de la operación en USD."""
        return (self.entry_fee_usd + self.exit_fee_usd
                + self.entry_slippage_usd + self.exit_slippage_usd)

    # ── PnL ──────────────────────────────────────────────────────────────────
    gross_pnl: float = 0.0                 # PnL bruto (sin costes)
    net_pnl:   float = 0.0                 # PnL neto (descontados costes)

    @property
    def pnl_r(self) -> float:
        """PnL neto en múltiplos de R. 0 si risk_amount_usd es 0."""
        if self.risk_amount_usd <= 0:
            return 0.0
        return self.net_pnl / self.risk_amount_usd

    # ── Excursiones ──────────────────────────────────────────────────────────
    mfe: float = 0.0                       # Maximum Favorable Excursion (en R)
    mae: float = 0.0                       # Maximum Adverse Excursion (en R)

    # ── Resultado ────────────────────────────────────────────────────────────
    exit_reason: Literal["TP", "SL", "EOD", "TIMEOUT"] = "SL"

    # ── Timing ───────────────────────────────────────────────────────────────
    signal_time:   datetime | None = None  # Vela N (señal)
    entry_time:    datetime | None = None  # Vela N+1 (entrada)
    exit_time:     datetime | None = None  # Vela de cierre
    duration_bars: int = 0                 # Duración en velas de 15m

    # ── Contexto de entrada ──────────────────────────────────────────────────
    entry_on: Literal["next_open", "close"] = "next_open"
    intrabar_policy: Literal["conservative", "optimistic"] = "conservative"
    capital_at_entry: float = 0.0          # Capital total al momento de entrar
    entry_features: dict = field(default_factory=dict) # Features al entrar

    def __repr__(self) -> str:
        return (
            f"TradeRecord({self.trade_id} | {self.symbol} {self.signal} | "
            f"regime={self.regime} | score={self.score:.1f} | "
            f"net_pnl={self.net_pnl:+.2f} | pnl_r={self.pnl_r:+.2f}R | "
            f"exit={self.exit_reason})"
        )
