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
from core.portfolio_risk import PortfolioRiskManager
from config.config import DEFAULT_RISK, DEFAULT_COSTS, DEFAULT_EXECUTION, DEFAULT_STRATEGY
from execution.exchange_api import ExchangeClient
from execution.position_manager import PositionManager

# Importamos el backend de la API
from api.server import app, bot_state

# Capital base si no hay API Keys, pero será sobreescrito por el fetch_balance()
CAPITAL_INICIAL_DIA = 1000.0
LAST_RESET_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ── SEGURIDAD: Modo de ejecución ─────────────────────────────────────────────
# Por defecto: PAPER_TRADING. No se ejecutan órdenes reales sin LIVE_TRADING=true en .env.
_execution_config = DEFAULT_EXECUTION
PAPER_TRADING_MODE = not _execution_config.validate_live()
if PAPER_TRADING_MODE:
    print("[SAFETY] 🟡 PAPER TRADING MODE — Las órdenes NO se enviarán a BingX.")
    print("[SAFETY]    Para activar ejecución real: LIVE_TRADING=true en .env")
else:
    print("[SAFETY] 🔴 LIVE TRADING MODE — Las órdenes se enviarán a BingX.")

# ── Lista de símbolos (definida UNA SOLA VEZ) ─────────────────────────────────
# Cualquier cambio aquí se aplica automáticamente a los 3 bucles.
SYMBOLS_TO_TRADE = [
    'BTC/USDT:USDT',  'ETH/USDT:USDT',   'SOL/USDT:USDT',  'BNB/USDT:USDT',
    'XRP/USDT:USDT',  'ADA/USDT:USDT',   'DOGE/USDT:USDT', 'AVAX/USDT:USDT',
    'LINK/USDT:USDT', 'SUI/USDT:USDT',   'NEAR/USDT:USDT', 'INJ/USDT:USDT',
    'TAO/USDT:USDT',  'RENDER/USDT:USDT','FET/USDT:USDT',  'APT/USDT:USDT',
    'SEI/USDT:USDT',  '1000PEPE/USDT:USDT', 'WIF/USDT:USDT',
    'HYPE/USDT:USDT', 'BLESS/USDT:USDT', 'BANK/USDT:USDT',
    'PURR/USDT:USDT'
]

# ── Cooldown y gestión de riesgo ─────────────────────────────────────────────
SYMBOL_COOLDOWN: Dict[str, float] = {}

# Instancia global del gestor de riesgo de portfolio.
# Es el ÚNICO responsable del daily halt — main.py NO debe tocar kill_switch_active
# excepto para reflejar el estado del portfolio_risk en bot_state (solo UI).
portfolio_risk = PortfolioRiskManager(config=DEFAULT_RISK)

async def analyze_symbol(symbol: str, exchange: ExchangeClient, pos_manager: PositionManager):
    try:
        raw_data = await exchange.fetch_ohlcv(symbol, timeframes=['15m', '1h'])
        df_15m = MarketDataFetcher.normalize_klines(raw_data['15m'])
        df_1h  = MarketDataFetcher.normalize_klines(raw_data['1h'])

        # Calcular features en ambos timeframes
        df_15m_features = FeatureEngine.compute(df_15m)
        df_1h_features  = FeatureEngine.compute(df_1h)

        # ── MTF ALIGNMENT ─────────────────────────────────────────────
        # Alinea el HTF al LTF usando htf_close_time para evitar look-ahead bias.
        # Una vela HTF de 10:00-11:00 SOLO puede influir en velas LTF >= 11:00.
        # Esto utiliza la ÚNICA implementación de alineamiento MTF del proyecto.
        df_aligned = MarketDataFetcher.align_htf_to_ltf(
            df_ltf=df_15m_features,
            df_htf_with_features=df_1h_features,
            htf_duration_minutes=DEFAULT_STRATEGY.htf_minutes,  # 60 min para 1h
        )

        # El régimen HTF se determina sobre la última fila del LTF alineado.
        # Esta fila contiene el régimen de la última vela HTF cerrada ANTES del
        # timestamp actual, sin incluir nunca la vela HTF aún en formación.
        # El régimen se calcula sobre las columnas HTF alineadas.
        # Verificación explícita: si no existen columnas '_htf' (datos insuficientes)
        # se usa el fallback directo. En producción normal SIEMPRE habrá columnas HTF.
        htf_cols = [c for c in df_aligned.columns if c.endswith('_htf')]
        if df_aligned.empty or not htf_cols:
            # Fallback: sin datos HTF suficientes (arranque inicial, datos escasos)
            regime = RegimeDetector.detect(df_1h_features)
        else:
            # Ruta principal: régimen calculado exclusivamente sobre datos HTF ya cerrados.
            df_htf_for_regime = df_aligned[htf_cols].rename(columns=lambda c: c[:-4])
            regime = RegimeDetector.detect(df_htf_for_regime)

        score, setup = ScoringEngine.evaluate(df_15m_features, regime)

        # ── LOGGING DE DIAGNÓSTICO DEL SCORE ──────────────────────────────
        # Permite responder: "¿Por qué el bot no entró?"
        # SIN modificar la estrategia, los pesos ni los thresholds.
        last_ltf = df_15m_features.iloc[-1] if not df_15m_features.empty else {}
        _adx       = float(last_ltf.get('ADX_14', 0))
        _rsi       = float(last_ltf.get('RSI_14', 0))
        _macd_h    = float(last_ltf.get('MACDh_12_26_9', 0))
        _close     = float(last_ltf.get('close', 0))
        _ema20     = float(last_ltf.get('EMA_20', 0))
        _ema50     = float(last_ltf.get('EMA_50', 0))
        _raw_score = setup.get('raw_score', 0)
        _thr_raw   = DEFAULT_STRATEGY.ENTRY_THRESHOLD_RAW
        _thr_norm  = DEFAULT_STRATEGY.entry_threshold_normalized
        _signal    = setup.get('signal', 'NEUTRAL')
        _struct    = 'FULL' if (_close > _ema20 and _ema20 > _ema50) else (
                     'PARTIAL' if _close > _ema20 else 'NONE')

        import logging as _logging
        _diag_logger = _logging.getLogger('score_diag')
        _diag_logger.info(
            'SCORE | %s | regime=%s | signal=%s | raw=%d/%d | norm=%.2f/%.2f | '
            'ADX=%.1f | RSI=%.1f | MACDh=%.5f | struct=%s',
            symbol, regime, _signal,
            _raw_score, _thr_raw,
            score, _thr_norm,
            _adx, _rsi, _macd_h, _struct,
        )

        # Actualizar estado para el Dashboard
        bot_state["market_scores"][symbol] = {
            "regime": regime,
            "score":  score,
            "signal": setup.get("signal", "NEUTRAL"),
            # campos de diagnóstico accesibles desde la API
            "raw_score":  _raw_score,
            "adx":        round(_adx, 2),
            "rsi":        round(_rsi, 2),
            "macd_h":     round(_macd_h, 5),
            "structure":  _struct,
        }

        # Ignorar señales neutras o bajo threshold
        if setup.get('signal') == 'NEUTRAL' or score < DEFAULT_STRATEGY.entry_threshold_normalized:
            return

        # No entrar si ya hay posición abierta en este símbolo
        if symbol in pos_manager.active_positions:
            return

        # ── DAILY HALT ─────────────────────────────────────────────────────────
        # El daily halt es gestionado por PortfolioRiskManager.
        # main.py NO resetea el halt — solo lo consulta.
        if portfolio_risk.is_daily_halt_active:
            print(f"[{symbol}] 🛑 Daily halt activo. No se abren nuevas posiciones.")
            return

        # ── KILL SWITCH MANUAL (dashboard) ────────────────────────────────────
        # Este es el kill switch manual del dashboard, independiente del daily halt.
        if bot_state.get("kill_switch_active", False):
            return

        # Respetar cooldown del símbolo
        cooldown_until = SYMBOL_COOLDOWN.get(symbol, 0)
        if time.time() < cooldown_until:
            remaining = int(cooldown_until - time.time())
            print(f"[{symbol}] ⏳ Cooldown activo ({remaining}s). Saltando.")
            return

        # ── PORTFOLIO RISK ─────────────────────────────────────────────────────
        # El RiskManager calcula el risk_amount para esta operación.
        approved, size, sizing_details = RiskManager.validate_and_size(
            setup,
            current_capital=bot_state["capital"],
            risk_config=DEFAULT_RISK,
            cost_config=DEFAULT_COSTS,
        )
        if not approved:
            return

        risk_amount = sizing_details.get("risk_amount_net", 0)
        current_prices = bot_state.get("live_prices", {})

        can_open, reason = portfolio_risk.can_open_position(
            symbol=symbol,
            signal=setup.get("signal", "NEUTRAL"),
            new_risk_amount=risk_amount,
            positions=pos_manager.active_positions,
            current_prices=current_prices,
            current_capital=bot_state["capital"],
        )
        if not can_open:
            print(f"[{symbol}] 🚫 Portfolio risk: {reason}")
            return

        # ── ENTRADA APROBADA ──
        print(f"\n[{symbol}] 🎯 SETUP: {setup['signal']} | Score: {score} | Régimen: {regime}")

        if PAPER_TRADING_MODE:
            # Paper trading: registrar sin enviar orden real
            print(f"[{symbol}] 📋 PAPER ORDER — {setup['signal']} | Size: {size:.4f} | Entry: {setup.get('entry_price', 0):.4f}")
            pos_manager.register_position(symbol, setup, size)
        else:
            # Live trading: validación adicional antes de enviar
            if not _execution_config.validate_live():
                print(f"[{symbol}] ❌ LIVE_TRADING no validado. Abortando orden.")
                return
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
            # 0. Reseteo Diario a las 00:00 UTC
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if current_date != LAST_RESET_DATE:
                print(f"[DailyReset] 🌅 Nuevo día UTC ({current_date}). Reseteando capital diario...")
                LAST_RESET_DATE = current_date
                CAPITAL_INICIAL_DIA = bot_state["capital"]
                bot_state["initial_capital"] = bot_state["capital"]
                bot_state["daily_pnl"] = 0.0

            # 1. Estado del bot: NO se resetea kill_switch_active aquí.
            # El kill switch manual solo puede desactivarse mediante acción explícita
            # (API del dashboard o reinicio del proceso).
            # Nota: bot_state["status"] se actualiza respetando el kill switch.
            if not bot_state.get("kill_switch_active", False):
                bot_state["status"] = "Running"
            else:
                bot_state["status"] = "KillSwitch"
            
            # 2. Obtener Precios en Vivo (BingX)
            market_prices = await exchange.fetch_tickers(SYMBOLS_TO_TRADE)
            bot_state["live_prices"] = market_prices
            
            # 3. Sincronizar PnL y Nuevas Posiciones desde BingX (Solo en LIVE TRADING)
            if not PAPER_TRADING_MODE:
                open_pos = await exchange.fetch_open_positions()
                open_symbols = {p['symbol'] for p in open_pos}
                
                # Remover posiciones que ya no existen en BingX (cerradas por SL/TP del exchange)
                for sym in list(pos_manager.active_positions.keys()):
                    if sym not in open_symbols:
                        print(f"[{sym}] 🗑 Posición cerrada por BingX (SL/TP). Removiendo del tracker.")
                        # Activar cooldown de 15min para no volver a entrar inmediatamente
                        SYMBOL_COOLDOWN[sym] = time.time() + (15 * 60)
                        print(f"[{sym}] ⏳ Cooldown de 15min activado tras cierre en BingX.")
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
                        sl_dist = atr_fallback * 1.0  # Consistente con risk_manager (1.0x ATR)
                        
                        pos_manager.active_positions[sym] = {
                            'signal': side,
                            'entry_price': entry_price,
                            'size': size,
                            'stop_loss': entry_price - sl_dist if side == 'LONG' else entry_price + sl_dist,
                            'take_profit': entry_price + (sl_dist * 2) if side == 'LONG' else entry_price - (sl_dist * 2),
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
                
            # Actualización de posiciones para la API
            bot_state["active_positions"] = pos_manager.active_positions
        except Exception as e:
            print(f"[TickerLoop] Error: {e}")
            
        await asyncio.sleep(2)

async def trading_loop(exchange: ExchangeClient, pos_manager: PositionManager):
    """Bucle principal (15s) de análisis OHLCV e inteligencia de mercado"""
    while True:
        # 1. Análisis Concurrente (Velas OHLCV)
        tasks = [analyze_symbol(sym, exchange, pos_manager) for sym in SYMBOLS_TO_TRADE]
        await asyncio.gather(*tasks)

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
                bot_state["capital"] = current_capital
                bot_state["daily_pnl"] = current_capital - bot_state["initial_capital"]
            except:
                pass
                
        except Exception as e:
            print(f"[HistoryLoop] Error: {e}")
            
        await asyncio.sleep(30)

async def main():
    print("🚀 Iniciando Q-Trade Pro + API Server")
    
    exchange = ExchangeClient(
        exchange_id=_execution_config.exchange_id,
        testnet=_execution_config.testnet
    )
    pos_manager = PositionManager(exchange, SYMBOL_COOLDOWN)
    
    # Obtener el Capital Real de BingX antes de arrancar
    print("⏳ Conectando a BingX para sincronizar capital y posiciones...")
    global CAPITAL_INICIAL_DIA
    CAPITAL_INICIAL_DIA = await exchange.fetch_balance()
    bot_state["capital"] = CAPITAL_INICIAL_DIA
    bot_state["initial_capital"] = CAPITAL_INICIAL_DIA
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
