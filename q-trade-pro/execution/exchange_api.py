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
        """Obtiene el balance libre actual en USDT de la cuenta."""
        try:
            # Si no hay llaves API, devolveremos el monto estático de 1000
            if not self.exchange.apiKey or not self.exchange.secret:
                return 1000.0
            
            # Buscamos el saldo en la cuenta de futuros (swap) en BingX
            balance = await self.exchange.fetch_balance({'type': 'swap'})
            
            usdt_balance = float(balance.get('USDT', {}).get('free', 0.0))
            vst_balance = float(balance.get('VST', {}).get('free', 0.0))
            
            # En modo Testnet/Sandbox, BingX a veces usa 'VST' en lugar de 'USDT'
            return max(usdt_balance, vst_balance)
        except Exception as e:
            print(f"[Exchange] Error fetch_balance: {e}. Usando capital fallback ($1000).")
            return 1000.0
            
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
            signal       = setup['signal']
            position_side = signal          # 'LONG' o 'SHORT'
            order_side    = 'buy'  if signal == 'LONG' else 'sell'
            close_side    = 'sell' if signal == 'LONG' else 'buy'

            print(f"[Exchange] 🚀 {order_side.upper()} {size:.4f} {symbol} ({position_side})")

            # 1. Orden de mercado de entrada
            order = await self.exchange.create_order(
                symbol,
                type='market',
                side=order_side,
                amount=size,
                params={'positionSide': position_side}
            )
            print(f"[Exchange] 🟢 Posición abierta: {order['id']}")

            # 2. Precio de fill real (ajuste sobre el estimado del scoring)
            estimated_entry = setup['entry_price']
            real_fill       = order.get('average') or order.get('price') or estimated_entry
            price_offset    = real_fill - estimated_entry

            real_sl = setup['stop_loss']   + price_offset
            real_tp = setup['take_profit'] + price_offset

            # Actualizar setup con precios reales para el tracker
            setup['entry_price'] = real_fill
            setup['stop_loss']   = real_sl
            setup['take_profit'] = real_tp

            print(
                f"[Exchange] 📍 Fill: {real_fill:.4f} | "
                f"SL: {real_sl:.4f} | TP: {real_tp:.4f}"
            )

            # 3. Anclar Stop Loss
            sl_placed = False
            try:
                sl_order = await self.exchange.create_order(
                    symbol,
                    type='STOP_MARKET',
                    side=close_side,
                    amount=size,
                    params={'stopPrice': real_sl, 'positionSide': position_side}
                )
                print(f"[Exchange] 🛡 SL anclado @ {real_sl:.4f}: {sl_order['id']}")
                sl_placed = True
            except Exception as e:
                print(f"[Exchange] ⚠️ Error anclando SL: {e}")

            # 4. Anclar Take Profit (solo si SL está asegurado)
            if sl_placed:
                try:
                    tp_order = await self.exchange.create_order(
                        symbol,
                        type='TAKE_PROFIT_MARKET',
                        side=close_side,
                        amount=size,
                        params={'stopPrice': real_tp, 'positionSide': position_side}
                    )
                    print(f"[Exchange] 🎯 TP anclado @ {real_tp:.4f}: {tp_order['id']}")
                except Exception as e:
                    print(f"[Exchange] ⚠️ Error anclando TP: {e}")
            else:
                # Sin SL = sin protección → cerrar posición de emergencia
                print(f"[Exchange] 🔴 SL no anclado. Cerrando posición de emergencia.")
                try:
                    await self.exchange.create_order(
                        symbol, type='market', side=close_side, amount=size,
                        params={'reduceOnly': True, 'positionSide': position_side}
                    )
                except Exception as close_err:
                    print(f"[Exchange] ❌ Error cierre emergencia: {close_err}")
                return None

            return order

        except Exception as e:
            print(f"[Exchange] 🔴 Error ejecutando orden: {e}")
            return None

    async def close_position(self, symbol: str, side: str, size: float):
        """
        Cierra o reduce una posición.
        """
        close_side = 'sell' if side == 'LONG' else 'buy'
        position_side = side # 'LONG' o 'SHORT'
        print(f"[Exchange] 🛑 Cerrando {size} de {symbol} {side} (Enviando orden {close_side})")
        try:
            await self.exchange.create_order(
                symbol, 
                type='market', 
                side=close_side, 
                amount=size, 
                params={'reduceOnly': True, 'positionSide': position_side}
            )
        except Exception as e:
            print(f"[Exchange] Error ejecutando orden de cierre: {e}")

    async def close_connection(self):
        """
        Cierra la sesión aiohttp subyacente.
        """
        await self.exchange.close()
