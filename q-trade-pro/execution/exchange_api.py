import asyncio
import ccxt.async_support as ccxt
from typing import Dict, Any, List
import os

class ExchangeClient:
    """
    Wrapper asíncrono para interactuar con la API del Exchange usando CCXT.
    """
    
    def __init__(self, exchange_id='bingx', testnet=True):
        api_key = os.environ.get('BINGX_API_KEY', '')
        secret = os.environ.get('BINGX_SECRET', '')
        
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)
            
    async def fetch_balance(self) -> float:
        """Obtiene el balance total (equity) actual en USDT de la cuenta."""
        try:
            if not self.exchange.apiKey or not self.exchange.secret:
                return 73.0
            
            balance = await self.exchange.fetch_balance({'type': 'swap'})
            
            # Priorizar 'total' (equidad total: balance + margen en posiciones + unrealized PnL)
            usdt_total = float(balance.get('total', {}).get('USDT', 0.0))
            if usdt_total <= 0:
                usdt_total = float(balance.get('USDT', {}).get('total', 0.0))
            if usdt_total <= 0:
                usdt_total = float(balance.get('USDT', {}).get('free', 0.0))

            vst_total = float(balance.get('total', {}).get('VST', 0.0))
            if vst_total <= 0:
                vst_total = float(balance.get('VST', {}).get('total', 0.0))
            
            capital = max(usdt_total, vst_total)
            return capital if capital > 0 else 73.0
        except Exception as e:
            print(f"[Exchange] Error fetch_balance: {e}")
            return 0.0
            
    async def fetch_ohlcv(self, symbol: str, timeframes: List[str]) -> Dict[str, List]:
        """
        Descarga velas (OHLCV) en múltiples temporalidades concurrentemente.
        """
        tasks = []
        for tf in timeframes:
            tasks.append(self.exchange.fetch_ohlcv(symbol, timeframe=tf, limit=500))
            
        results = await asyncio.gather(*tasks)
        return {tf: data for tf, data in zip(timeframes, results)}

    async def fetch_tickers(self, symbols: List[str]) -> Dict[str, float]:
        """
        Obtiene el precio actual de una lista de símbolos usando un solo request.
        Para evitar errores por BadSymbol, pedimos todos y filtramos localmente.
        """
        try:
            tickers = await self.exchange.fetch_tickers(symbols)
            return {sym: tickers[sym]['last'] for sym in symbols if sym in tickers}
        except Exception as e:
            print(f"[Exchange] Error fetch_tickers general: {e}")
            return {}

    async def fetch_open_positions(self) -> List[Dict[str, Any]]:
        """
        Descarga las posiciones abiertas actuales desde BingX.
        """
        try:
            if not self.exchange.apiKey:
                return []
            positions = await self.exchange.fetch_positions()
            # Filtrar solo posiciones con tamaño mayor a 0
            open_pos = [p for p in positions if float(p.get('contracts', 0)) > 0]
            return open_pos
        except Exception as e:
            print(f"[Exchange] Error fetch_open_positions: {e}")
            return []

    async def execute_order(self, symbol: str, setup: Dict[str, Any], size: float):
        """
        Envía una orden al exchange.
        1. Abre la posición con orden de mercado.
        2. Usa el precio de fill real para ajustar SL/TP.
        3. Ancla SL en BingX. Si falla, cierra posición de emergencia.
        4. Ancla TP en BingX solo si SL fue confirmado.
        """
        try:
            # Asegurar que los mercados estén cargados para obtener reglas de precisión
            if not self.exchange.markets:
                await self.exchange.load_markets()

            signal        = setup['signal']
            position_side = signal          # 'LONG' o 'SHORT'
            order_side    = 'buy'  if signal == 'LONG' else 'sell'
            close_side    = 'sell' if signal == 'LONG' else 'buy'

            # Formatear el tamaño con la precisión exacta del contrato BingX
            formatted_size = float(self.exchange.amount_to_precision(symbol, size))
            if formatted_size <= 0:
                print(f"[Exchange] ⚠️ Tamaño {size} menor al mínimo permitido para {symbol}. Cancelando orden.")
                return None

            print(f"[Exchange] 🚀 {order_side.upper()} {formatted_size} {symbol} ({position_side})")

            # 1. Orden de mercado de entrada
            order = await self.exchange.create_order(
                symbol,
                type='market',
                side=order_side,
                amount=formatted_size,
                params={'positionSide': position_side}
            )
            print(f"[Exchange] 🟢 Posición abierta: {order['id']}")

            # 2. Precio de fill real (ajuste sobre el estimado del scoring)
            estimated_entry = setup['entry_price']
            real_fill       = order.get('average') or order.get('price') or estimated_entry
            price_offset    = real_fill - estimated_entry

            real_sl = setup['stop_loss']   + price_offset
            real_tp = setup['take_profit'] + price_offset

            # Ajustar precios a la precisión del par en BingX
            formatted_sl = float(self.exchange.price_to_precision(symbol, real_sl))
            formatted_tp = float(self.exchange.price_to_precision(symbol, real_tp))

            # Actualizar setup con precios reales para el tracker
            setup['entry_price'] = real_fill
            setup['stop_loss']   = formatted_sl
            setup['take_profit'] = formatted_tp

            print(
                f"[Exchange] 📍 Fill: {real_fill:.4f} | "
                f"SL: {formatted_sl:.4f} | TP: {formatted_tp:.4f}"
            )

            # 3. Anclar Stop Loss (intento de trigger order condicional en BingX)
            try:
                sl_order = await self.exchange.create_trigger_order(
                    symbol,
                    type='market',
                    side=close_side,
                    amount=formatted_size,
                    triggerPrice=formatted_sl,
                    params={'positionSide': position_side, 'reduceOnly': True}
                )
                print(f"[Exchange] 🛡 SL trigger anclado en exchange @ {formatted_sl:.4f}: {sl_order.get('id')}")
            except Exception as e:
                print(f"[Exchange] ℹ️ SL en exchange omitido ({e}). PositionManager protegerá SL @ {formatted_sl:.4f} por software.")

            # 4. Anclar Take Profit (intento de trigger order condicional en BingX)
            try:
                tp_order = await self.exchange.create_trigger_order(
                    symbol,
                    type='market',
                    side=close_side,
                    amount=formatted_size,
                    triggerPrice=formatted_tp,
                    params={'positionSide': position_side, 'reduceOnly': True}
                )
                print(f"[Exchange] 🎯 TP trigger anclado en exchange @ {formatted_tp:.4f}: {tp_order.get('id')}")
            except Exception as e:
                print(f"[Exchange] ℹ️ TP en exchange omitido ({e}). PositionManager gestionará TP @ {formatted_tp:.4f} por software.")

            return order

        except Exception as e:
            print(f"[Exchange] 🔴 Error ejecutando orden: {e}")
            return None

    async def close_position(self, symbol: str, side: str, size: float):
        """
        Cierra o reduce una posición con precisión adecuada.
        """
        if not self.exchange.markets:
            await self.exchange.load_markets()
        formatted_size = float(self.exchange.amount_to_precision(symbol, size))
        close_side = 'sell' if side == 'LONG' else 'buy'
        position_side = side # 'LONG' o 'SHORT'
        print(f"[Exchange] 🛑 Cerrando {formatted_size} de {symbol} {side} (Enviando orden {close_side})")
        try:
            await self.exchange.create_order(
                symbol, 
                type='market', 
                side=close_side, 
                amount=formatted_size, 
                params={'reduceOnly': True, 'positionSide': position_side}
            )
        except Exception as e:
            print(f"[Exchange] Error ejecutando orden de cierre: {e}")

    async def update_stop_loss_order(self, symbol: str, side: str, size: float, new_stop_price: float) -> bool:
        """
        Cancela el Stop Loss anterior y ancla el nuevo precio (Breakeven o Trailing) en BingX.
        """
        try:
            if not self.exchange.markets:
                await self.exchange.load_markets()

            formatted_size = float(self.exchange.amount_to_precision(symbol, size))
            formatted_sl   = float(self.exchange.price_to_precision(symbol, new_stop_price))
            close_side     = 'sell' if side == 'LONG' else 'buy'
            position_side  = side

            # 1. Cancelar órdenes de Stop Loss existentes en BingX para este símbolo
            try:
                open_orders = await self.exchange.fetch_open_orders(symbol)
                for o in open_orders:
                    o_type = str(o.get('type', '')).upper()
                    if 'STOP' in o_type and o.get('side') == close_side:
                        await self.exchange.cancel_order(o['id'], symbol)
            except Exception as cancel_err:
                print(f"[Exchange] Nota al cancelar SL previo en {symbol}: {cancel_err}")

            # 2. Anclar la nueva orden STOP_MARKET
            sl_order = await self.exchange.create_order(
                symbol,
                type='STOP_MARKET',
                side=close_side,
                amount=formatted_size,
                params={'stopPrice': formatted_sl, 'positionSide': position_side}
            )
            print(f"[Exchange] 🛡 SL actualizado @ {formatted_sl:.4f} para {symbol}: {sl_order['id']}")
            return True
        except Exception as e:
            print(f"[Exchange] Error actualizando Stop Loss para {symbol}: {e}")
            return False

    async def close_connection(self):
        """
        Cierra la sesión aiohttp subyacente.
        """
        await self.exchange.close()
