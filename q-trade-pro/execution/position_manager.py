import time
from typing import Dict, Any

class PositionManager:
    """
    Gestiona el ciclo de vida de las posiciones abiertas (SL, Breakeven, Trailing Stop).
    """
    
    COOLDOWN_SECONDS = 45 * 60  # 45 minutos de cooldown tras un Stop Loss
    
    def __init__(self, exchange_client, cooldown_dict: Dict[str, float] = None):
        self.exchange = exchange_client
        self.active_positions: Dict[str, Dict[str, Any]] = {}
        self.cooldown_dict = cooldown_dict if cooldown_dict is not None else {}
        
    def register_position(self, symbol: str, setup: Dict[str, Any], size: float):
        """
        Registra una nueva posición recién abierta.
        """
        self.active_positions[symbol] = {
            'signal': setup['signal'],
            'entry_price': setup['entry_price'],
            'size': size,
            'stop_loss': setup['stop_loss'],
            'take_profit': setup['take_profit'],
            'atr': setup['atr'],
            'entry_time': time.time(),
            'breakeven_triggered': False,
            'partial_taken': False,
            'highest_price': setup['entry_price'],
            'lowest_price': setup['entry_price'],
            'unrealized_pnl': 0.0,
            'pnl_pct': 0.0
        }
        print(f"[PositionManager] 📝 Posición registrada en {symbol}: {setup['signal']} @ {setup['entry_price']}")

    async def sync_positions_from_exchange(self):
        """
        Descarga las posiciones de BingX y las carga en la memoria del bot.
        """
        print("[PositionManager] 🔄 Sincronizando posiciones abiertas con BingX...")
        open_pos = await self.exchange.fetch_open_positions()
        
        for pos in open_pos:
            symbol = pos['symbol']
            size = float(pos.get('contracts', 0))
            entry_price = float(pos.get('entryPrice', 0))
            side = 'LONG' if pos['side'] == 'long' else 'SHORT'
            
            # Si ya la tenemos, la saltamos
            if symbol in self.active_positions:
                continue
                
            # Calcular ATR aproximado del precio actual (1% default fallback) para rearmar Stop Loss
            atr_fallback = entry_price * 0.01
            sl_distance = atr_fallback * 1.5
            
            stop_loss = entry_price - sl_distance if side == 'LONG' else entry_price + sl_distance
            tp_distance = atr_fallback * 3.0  # Consistente con TP 3.0x ATR
            take_profit = entry_price + tp_distance if side == 'LONG' else entry_price - tp_distance
            
            self.active_positions[symbol] = {
                'signal': side,
                'entry_price': entry_price,
                'size': size,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'atr': atr_fallback,
                'entry_time': time.time(),
                'breakeven_triggered': False,
                'partial_taken': False,
                'highest_price': entry_price,
                'lowest_price': entry_price,
                'unrealized_pnl': float(pos.get('unrealizedPnl', 0.0)),
                'pnl_pct': float(pos.get('percentage', 0.0))
            }
            print(f"[PositionManager] ✅ Posición recuperada: {symbol} {side} @ {entry_price}")

    async def update_active_positions(self, market_prices: Dict[str, float]):
        """
        Gestiona activamente las posiciones abiertas:
        1. Actualiza métricas de PnL y extremos (highest/lowest).
        2. Activa Breakeven automático si el precio avanza >= +1.0x ATR.
        3. Aplica Trailing Stop dinámico si el precio avanza >= +1.8x ATR.
        4. Ejecuta Salida por Tiempo si la posición lleva >= 3h sin progreso.
        """
        for symbol, pos in list(self.active_positions.items()):
            current_price = market_prices.get(symbol)
            if not current_price:
                continue

            entry_price = pos['entry_price']
            size        = pos['size']
            atr         = pos.get('atr', entry_price * 0.01)
            side        = pos['signal']

            # Actualizar trackers de precio máximo y mínimo
            pos['highest_price'] = max(pos['highest_price'], current_price)
            pos['lowest_price']  = min(pos['lowest_price'], current_price)

            # Calcular PnL no realizado
            if side == 'LONG':
                pos['unrealized_pnl'] = (current_price - entry_price) * size
                favorable_dist        = current_price - entry_price
            else:  # SHORT
                pos['unrealized_pnl'] = (entry_price - current_price) * size
                favorable_dist        = entry_price - current_price

            invested = entry_price * size
            pos['pnl_pct'] = (pos['unrealized_pnl'] / invested * 100) if invested > 0 else 0.0

            # ── 1. Breakeven Automático (+1.0x ATR a favor) ───────────────────
            if favorable_dist >= (1.0 * atr) and not pos.get('breakeven_triggered', False):
                # Buffer de 0.1x ATR para cubrir comisiones de maker/taker
                new_sl = entry_price + (0.1 * atr) if side == 'LONG' else entry_price - (0.1 * atr)
                pos['stop_loss'] = new_sl
                pos['breakeven_triggered'] = True
                print(f"[PositionManager] 🛡 BREAKEVEN activado para {symbol} @ {new_sl:.4f} (Riesgo Cero)")
                await self.exchange.update_stop_loss_order(symbol, side, size, new_sl)

            # ── 2. Trailing Stop Dinámico (+1.8x ATR a favor) ──────────────────
            elif favorable_dist >= (1.8 * atr):
                if side == 'LONG':
                    candidate_sl = pos['highest_price'] - (1.5 * atr)
                    if candidate_sl > pos['stop_loss']:
                        pos['stop_loss'] = candidate_sl
                        print(f"[PositionManager] 📈 TRAILING STOP subido para {symbol} @ {candidate_sl:.4f}")
                        await self.exchange.update_stop_loss_order(symbol, 'LONG', size, candidate_sl)
                else:  # SHORT
                    candidate_sl = pos['lowest_price'] + (1.5 * atr)
                    if candidate_sl < pos['stop_loss']:
                        pos['stop_loss'] = candidate_sl
                        print(f"[PositionManager] 📉 TRAILING STOP bajado para {symbol} @ {candidate_sl:.4f}")
                        await self.exchange.update_stop_loss_order(symbol, 'SHORT', size, candidate_sl)

            # ── 3. Salida por Tiempo / Inactividad (3 Horas) ──────────────────
            TIME_EXIT_SECONDS = 3 * 3600
            elapsed = time.time() - pos.get('entry_time', time.time())
            if elapsed >= TIME_EXIT_SECONDS and favorable_dist < (0.5 * atr):
                print(f"[PositionManager] ⏱ SALIDA POR TIEMPO: {symbol} sin progreso tras {elapsed/3600:.1f}h. Cerrando posición.")
                await self.exchange.close_position(symbol, side, size)
                if self.cooldown_dict is not None:
                    self.cooldown_dict[symbol] = time.time() + (45 * 60)
                del self.active_positions[symbol]
                continue

            # Log informativo
            emoji = '🟢' if pos['unrealized_pnl'] >= 0 else '🔴'
            be_tag = " [BE]" if pos.get('breakeven_triggered') else ""
            print(f"[PosTracker] {emoji} {symbol} {side}{be_tag} | Precio: {current_price:.4f} "
                  f"| PnL: ${pos['unrealized_pnl']:+.2f} ({pos['pnl_pct']:+.2f}%) "
                  f"| SL: {pos['stop_loss']:.4f} | TP: {pos['take_profit']:.4f}")
