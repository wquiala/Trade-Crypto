import asyncio
import uvicorn
import os
import time
from datetime import datetime, timezone
from typing import Dict
from dotenv import load_dotenv

# Cargar variables de entorno locales (API Keys)
load_dotenv()
from core.data_processor import MarketDataFetcher
from core.feature_engine import FeatureEngine
from core.regime_detector import RegimeDetector
from core.scoring_engine import ScoringEngine
from core.risk_manager import RiskManager
from execution.exchange_api import ExchangeClient
from execution.position_manager import PositionManager

# Importamos el backend de la API
from api.server import app, bot_state

# Capital base: será sobreescrito por el fetch_balance() real de BingX
CAPITAL_INICIAL_DIA = 0.0
LAST_RESET_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ── Lista de símbolos única (unificada y depurada de memecoins/microcaps) ─────
SYMBOLS_TO_TRADE = [
    'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT', 'XRP/USDT:USDT',
    'ADA/USDT:USDT', 'DOGE/USDT:USDT', 'AVAX/USDT:USDT', 'LINK/USDT:USDT',
    'SUI/USDT:USDT', 'NEAR/USDT:USDT', 'INJ/USDT:USDT', 'TAO/USDT:USDT', 'RENDER/USDT:USDT',
    'FET/USDT:USDT', 'APT/USDT:USDT', 'SEI/USDT:USDT', 'PAXG/USDT:USDT', 'ZEC/USDT:USDT'
]

# Cooldown por símbolo: tiempo mínimo de espera tras cerrar una posición (45 minutos)
SYMBOL_COOLDOWN: Dict[str, float] = {}

# Máximo de posiciones simultáneas (gestión de riesgo global)
MAX_CONCURRENT_POSITIONS = 10  # Total de posiciones abiertas
MAX_SAME_DIRECTION       = 5   # Máx en la misma dirección (evita sobreexposición correlada)

async def get_btc_regime(exchange: ExchangeClient) -> str:
    """Obtiene el régimen macro de 1h de Bitcoin como filtro direccional del mercado."""
    try:
        raw_btc = await exchange.fetch_ohlcv('BTC/USDT:USDT', timeframes=['1h'])
        df_1h_btc = MarketDataFetcher.normalize_klines(raw_btc['1h'])
        df_1h_btc_features = FeatureEngine.compute(df_1h_btc)
        return RegimeDetector.detect(df_1h_btc_features)
    except Exception as e:
        print(f"[BTC Filter] Error obteniendo régimen de BTC: {e}")
        return 'UNKNOWN'

async def analyze_symbol(symbol: str, exchange: ExchangeClient, pos_manager: PositionManager, btc_regime: str = 'UNKNOWN'):
    try:
        raw_data = await exchange.fetch_ohlcv(symbol, timeframes=['15m', '1h'])
        df_15m = MarketDataFetcher.normalize_klines(raw_data['15m'])
        df_1h  = MarketDataFetcher.normalize_klines(raw_data['1h'])

        df_15m_features = FeatureEngine.compute(df_15m)
        df_1h_features  = FeatureEngine.compute(df_1h)

        regime = RegimeDetector.detect(df_1h_features)
        score, setup = ScoringEngine.evaluate(df_15m_features, regime)

        # Actualizar estado para el Dashboard
        bot_state["market_scores"][symbol] = {
            "regime": regime,
            "score":  score,
            "signal": setup.get("signal", "NEUTRAL")
        }

        # Ignorar señales neutras o con score bajo
        if setup.get('signal') == 'NEUTRAL' or score < 70:
            return

        # ── FILTRO MACRO BITCOIN: Alineación con la tendencia dominante ──────
        if symbol != 'BTC/USDT:USDT':
            if setup.get('signal') == 'LONG' and btc_regime == 'BEAR_TREND':
                print(f"[{symbol}] 🚫 LONG descartado: BTC en BEAR_TREND (Riesgo sistemático de caída).")
                return
            elif setup.get('signal') == 'SHORT' and btc_regime == 'BULL_TREND':
                print(f"[{symbol}] 🚫 SHORT descartado: BTC en BULL_TREND (Contra-tendencia mayor).")
                return

        # No entrar si ya hay posición abierta en este símbolo
        if symbol in pos_manager.active_positions:
            return

        # No entrar si el bot está detenido
        if bot_state["kill_switch_active"]:
            return

        # Respetar cooldown del símbolo
        cooldown_until = SYMBOL_COOLDOWN.get(symbol, 0)
        if time.time() < cooldown_until:
            remaining = int(cooldown_until - time.time())
            print(f"[{symbol}] ⏳ Cooldown activo ({remaining}s). Saltando.")
            return

        # Límite global de posiciones simultáneas
        if len(pos_manager.active_positions) >= MAX_CONCURRENT_POSITIONS:
            print(f"[{symbol}] 🚫 Máximo de {MAX_CONCURRENT_POSITIONS} posiciones alcanzado. Saltando.")
            return

        # Límite por dirección: máx 3 en la misma dirección (LONG o SHORT)
        new_signal = setup.get('signal', 'NEUTRAL')
        same_dir = sum(1 for p in pos_manager.active_positions.values() if p.get('signal') == new_signal)
        if same_dir >= MAX_SAME_DIRECTION:
            print(f"[{symbol}] 🚫 Máx {MAX_SAME_DIRECTION} posiciones {new_signal} ya abiertas. Saltando.")
            return

        # ── ENTRADA APROBADA ──
        print(f"\n[{symbol}] 🎯 SETUP: {setup['signal']} | Score: {score} | Régimen: {regime}")
        approved, size = RiskManager.validate_and_size(setup, bot_state["capital"], CAPITAL_INICIAL_DIA)

        if approved:
            order = await exchange.execute_order(symbol, setup, size)
            if order:
                pos_manager.register_position(symbol, setup, size)
            else:
                print(f"[{symbol}] ⚠️ Orden rechazada por BingX.")

    except Exception as e:
        print(f"[analyze_symbol] Error en {symbol}: {e}")

async def ticker_loop(exchange: ExchangeClient, pos_manager: PositionManager):
    """Bucle rápido (2s) de monitoreo de precios en vivo y gestión de SL/TP/PnL"""
    global CAPITAL_INICIAL_DIA, LAST_RESET_DATE
    
    while True:
        try:
            # 0. Reseteo Diario a las 00:00 UTC (Circuit Breaker diario)
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if current_date != LAST_RESET_DATE:
                print(f"[DailyReset] 🌅 Nuevo día UTC ({current_date}). Reseteando base de capital diario...")
                LAST_RESET_DATE = current_date
                CAPITAL_INICIAL_DIA = bot_state["capital"]
                bot_state["initial_capital"] = bot_state["capital"]
                bot_state["kill_switch_active"] = False
                bot_state["status"] = "Running"
                bot_state["daily_pnl"] = 0.0

            # 1. Estado del bot: respetar kill switch si está activo
            if not bot_state.get("kill_switch_active", False):
                bot_state["status"] = "Running"
            else:
                bot_state["status"] = "KillSwitch"
            
            # 2. Obtener Precios en Vivo (BingX)
            market_prices = await exchange.fetch_tickers(SYMBOLS_TO_TRADE)
            bot_state["live_prices"] = market_prices
            
            # 3. Sincronizar PnL y Nuevas Posiciones desde BingX
            open_pos = await exchange.fetch_open_positions()
            open_symbols = {p['symbol'] for p in open_pos}
            
            # Remover posiciones que ya no existen en BingX (cerradas por SL/TP del exchange)
            for sym in list(pos_manager.active_positions.keys()):
                if sym not in open_symbols:
                    print(f"[{sym}] 🗑 Posición cerrada por BingX (SL/TP). Removiendo del tracker.")
                    # Activar cooldown de 45min para no volver a entrar inmediatamente
                    SYMBOL_COOLDOWN[sym] = time.time() + (45 * 60)
                    print(f"[{sym}] ⏳ Cooldown de 45min activado tras cierre en BingX.")
                    del pos_manager.active_positions[sym]
                    
            # Agregar nuevas y actualizar PnL
            for pos in open_pos:
                sym = pos['symbol']
                if sym not in pos_manager.active_positions:
                    # Detectada una posición abierta manualmente en BingX
                    size = float(pos.get('contracts', 0))
                    entry_price = float(pos.get('entryPrice', 0))
                    side = 'LONG' if pos['side'] == 'long' else 'SHORT'
                    atr_fallback = entry_price * 0.01
                    sl_dist = atr_fallback * 1.5  # Consistente con risk_manager (1.5x ATR)
                    tp_dist = atr_fallback * 3.0  # Consistente con risk_manager (3.0x ATR)
                    
                    pos_manager.active_positions[sym] = {
                        'signal': side,
                        'entry_price': entry_price,
                        'size': size,
                        'stop_loss': entry_price - sl_dist if side == 'LONG' else entry_price + sl_dist,
                        'take_profit': entry_price + tp_dist if side == 'LONG' else entry_price - tp_dist,
                        'atr': atr_fallback,
                        'breakeven_triggered': False,
                        'partial_taken': False,
                        'highest_price': entry_price,
                        'lowest_price': entry_price,
                        'unrealized_pnl': float(pos.get('unrealizedPnl', 0.0)),
                        'pnl_pct': float(pos.get('percentage', 0.0))
                    }
                    print(f"[TickerLoop] ➕ Detectada nueva posición manual en BingX: {sym}")
                else:
                    # Actualizar PnL de las existentes
                    pos_manager.active_positions[sym]['unrealized_pnl'] = float(pos.get('unrealizedPnl', 0.0))
                    pos_manager.active_positions[sym]['pnl_pct'] = float(pos.get('percentage', 0.0))
            
            # Gestionar SL/TP con precios reales
            if pos_manager.active_positions:
                await pos_manager.update_active_positions(market_prices)
                
            # 4. Actualización de posiciones para la API
            bot_state["active_positions"] = pos_manager.active_positions
        except Exception as e:
            print(f"[TickerLoop] Error: {e}")
            
        await asyncio.sleep(2)

async def trading_loop(exchange: ExchangeClient, pos_manager: PositionManager):
    """Bucle principal (15s) de análisis OHLCV e inteligencia de mercado"""
    while True:
        try:
            # 0. Obtener Régimen Macro de Bitcoin (Filtro Direccional)
            btc_regime = await get_btc_regime(exchange)

            # 1. Análisis Concurrente (Velas OHLCV) con filtro macro
            tasks = [analyze_symbol(sym, exchange, pos_manager, btc_regime) for sym in SYMBOLS_TO_TRADE]
            await asyncio.gather(*tasks)
        except Exception as e:
            print(f"[TradingLoop] Error: {e}")
            
        await asyncio.sleep(15)

async def history_loop(exchange: ExchangeClient):
    """Bucle (30s) para obtener historial de operaciones y calcular PnL Diario"""
    while True:
        try:
            all_trades = []
            for sym in SYMBOLS_TO_TRADE:
                try:
                    # Usamos fetch_closed_orders porque expone el realizedPnl (a diferencia de fetch_my_trades)
                    orders = await exchange.exchange.fetch_closed_orders(sym, limit=20)
                    all_trades.extend(orders)
                except:
                    pass
            
            all_trades.sort(key=lambda x: x['timestamp'], reverse=True)
            
            # Formatear la lista para el frontend de forma segura
            formatted_history = []
            for t in all_trades[:20]:
                info = t.get('info', {})
                # BingX retorna el PnL como 'profit' o 'realizedPnl' dependiendo del endpoint
                pnl = info.get('profit', info.get('realizedPnl', 0.0))
                if pnl == '': pnl = 0.0
                
                formatted_history.append({
                    "timestamp": t['timestamp'],
                    "symbol": t['symbol'],
                    "side": t['side'],
                    "amount": t['amount'],
                    "price": t.get('price', t.get('average', 0)),
                    "cost": t.get('cost', 0),
                    "realized_pnl": float(pnl)
                })
                
            bot_state["trade_history"] = formatted_history
            
            # Calcular PnL Diario usando la equidad
            try:
                current_capital = await exchange.fetch_balance()
                if current_capital > 0:
                    bot_state["capital"] = current_capital
                    if bot_state.get("initial_capital", 0.0) <= 0:
                        bot_state["initial_capital"] = current_capital
                    daily_pnl = current_capital - bot_state["initial_capital"]
                    bot_state["daily_pnl"] = daily_pnl
            except Exception as bal_err:
                print(f"[HistoryLoop] Error al actualizar balance y PnL: {bal_err}")
                
        except Exception as e:
            print(f"[HistoryLoop] Error: {e}")
            
        await asyncio.sleep(30)

async def main():
    print("🚀 Iniciando Q-Trade Pro + API Server")
    
    exchange = ExchangeClient(exchange_id='bingx', testnet=False)
    pos_manager = PositionManager(exchange, SYMBOL_COOLDOWN)
    
    # Obtener el Capital Real de BingX antes de arrancar
    print("⏳ Conectando a BingX para sincronizar capital y posiciones...")
    global CAPITAL_INICIAL_DIA
    CAPITAL_INICIAL_DIA = await exchange.fetch_balance()
    bot_state["capital"] = CAPITAL_INICIAL_DIA
    bot_state["initial_capital"] = CAPITAL_INICIAL_DIA
    bot_state["kill_switch_active"] = False
    print(f"✅ Capital sincronizado: ${CAPITAL_INICIAL_DIA:.2f} USDT")
    
    # Sincronizar posiciones huérfanas
    await pos_manager.sync_positions_from_exchange()
    
    # Configurar el servidor web (FastAPI) para que corra asíncronamente
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    
    # Lanzar ambas tareas: El servidor web y el bot
    try:
        await asyncio.gather(
            server.serve(),
            ticker_loop(exchange, pos_manager),
            trading_loop(exchange, pos_manager),
            history_loop(exchange)
        )
    except KeyboardInterrupt:
        print("\n🛑 Apagando Q-Trade Pro...")
    finally:
        await exchange.close_connection()

if __name__ == '__main__':
    asyncio.run(main())
