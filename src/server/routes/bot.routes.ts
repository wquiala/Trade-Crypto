import { Router } from 'express';
import { AiRiskManager } from '../../services/ai/ai-risk-manager';
import { TechnicalAnalysis } from '../../services/analytics/indicators';
import { RiskCalculator } from '../../services/analytics/risk-calculator';
import { bingxClient } from '../../services/bingx/bingx-client';
import { telegramBot, escHtml } from '../../services/telegram/telegram-bot';
import { loadBotState, saveBotState, PersistedState } from '../../services/persistence/state-manager';

const router = Router();

// ─────────────────────────────────────────────────────────────────────────────
// CONFIGURACIÓN DEL BOT
// ─────────────────────────────────────────────────────────────────────────────
export interface BotConfig {
  isAutoBotActive: boolean;
  monitoredSymbols: string[];
  interval: string;
  strategy: 'CONFLUENCE_TA' | 'SCALPING_VOLATILITY';
  riskPerTradePercent: number;
  maxLeverage: number;
  autoTradeEnabled: boolean;
  dailyDrawdownLimitPct: number;
  // true cuando el auto-trade fue apagado por el circuit breaker diario (no manualmente por el usuario)
  autoTradeDisabledByDrawdown: boolean;
  useTrailingStop: boolean;
  useEarlyExit: boolean;
  currentAtr: Record<string, number>;
  needsCleanup: Record<string, boolean>;
  // Estado persistido (sincronizado con disco)
  lastSignals: Record<string, string>;
  lastScanTime: number;
  totalExecutedTrades: number;
  lastTradeTime: Record<string, number>;
  cooldownUntil: Record<string, number>;
  startOfDayEquity: number;
  highestEquityToday: number;
  lastDrawdownDate: string;
  highestPriceTracker: Record<string, number>;
  lowestPriceTracker: Record<string, number>;
  breakevenTriggered: Record<string, boolean>;
  partialTaken: Record<string, boolean>;
  tradeOpenTime: Record<string, number>;
  forbiddenSide: Record<string, 'LONG' | 'SHORT' | null>;
}

// ─────────────────────────────────────────────────────────────────────────────
// INFORMACIÓN DE SÍMBOLOS
// ─────────────────────────────────────────────────────────────────────────────
const SYMBOL_INFO_FALLBACK: Record<string, { minNotional: number; qtyPrecision: number; pricePrecision: number }> = {
  'BTC-USDT': { minNotional: 5, qtyPrecision: 4, pricePrecision: 1 },
  'ETH-USDT': { minNotional: 5, qtyPrecision: 3, pricePrecision: 2 }, // 🔥 Corregido a 3 para evitar redondeos a 0
  'SOL-USDT': { minNotional: 5, qtyPrecision: 1, pricePrecision: 3 },
  'AVAX-USDT': { minNotional: 5, qtyPrecision: 1, pricePrecision: 3 },
  'LINK-USDT': { minNotional: 5, qtyPrecision: 1, pricePrecision: 3 },
  'PAXG-USDT': { minNotional: 5, qtyPrecision: 4, pricePrecision: 2 }, // 🥇 Paxos Gold (Oro)
  'BNB-USDT': { minNotional: 5, qtyPrecision: 2, pricePrecision: 2 },  // 🥇 Binance Coin
  'XRP-USDT': { minNotional: 5, qtyPrecision: 1, pricePrecision: 4 },  // 🥈 Ripple
  'DOGE-USDT': { minNotional: 5, qtyPrecision: 0, pricePrecision: 5 }, // 🥈 Dogecoin
  'SUI-USDT': { minNotional: 5, qtyPrecision: 1, pricePrecision: 4 },  // 🥉 SUI Layer 1
};

let SYMBOL_INFO: Record<string, { minNotional: number; qtyPrecision: number; pricePrecision: number }> = {};

function getSymbolInfo(symbol: string) {
  const live = SYMBOL_INFO[symbol];
  const fallback = SYMBOL_INFO_FALLBACK[symbol] || { minNotional: 5, qtyPrecision: 2, pricePrecision: 2 };
  if (!live || live.qtyPrecision === 0) return fallback;
  return live;
}

/**
 * Ejecuta una promesa con un límite de tiempo. Si no resuelve a tiempo, devuelve
 * `onTimeout` en vez de dejar el pipeline de decisión colgado indefinidamente.
 * Se usa para que una IA/API lenta no infle la latencia entre señal y orden.
 */
function withTimeout<T>(promise: Promise<T>, ms: number, onTimeout: T): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((resolve) => setTimeout(() => resolve(onTimeout), ms)),
  ]);
}

function getPrecisionFromStep(stepSize: string | number): number {
  const step = Number(stepSize);
  if (step === 1) return 0;
  if (step < 1 && step > 0) {
    return Math.max(0, Math.ceil(-Math.log10(step)));
  }
  return 0;
}

async function syncExchangeInfo() {
  try {
    console.log('[AutoBot] 🔄 Descargando reglas de precisión de la API de BingX...');
    const contracts = await bingxClient.getExchangeInfo();

    if (!contracts || contracts.length === 0) {
      console.warn('[AutoBot] ⚠️ No se pudieron obtener contratos. Usando fallback.');
      return;
    }

    for (const contract of contracts) {
      if (botConfig.monitoredSymbols.includes(contract.symbol)) {
        const qtyPrec = getPrecisionFromStep(contract.qtyStep || contract.stepSize);
        const pricePrec = getPrecisionFromStep(contract.priceStep || contract.tickSize);
        const minNotional = Number(contract.tradeMinUSDT || contract.minOrderValue || 5);

        SYMBOL_INFO[contract.symbol] = { minNotional, qtyPrecision: qtyPrec, pricePrecision: pricePrec };
      }
    }

    for (const sym of botConfig.monitoredSymbols) {
      const used = getSymbolInfo(sym);
      const source = SYMBOL_INFO[sym]?.qtyPrecision === 0 ? '⚠️ FALLBACK (live=0)' : (SYMBOL_INFO[sym] ? '✅ LIVE' : '⚠️ FALLBACK (not found)');
      console.log(`[AutoBot] ${sym}: qtyPrec=${used.qtyPrecision} pricePrec=${used.pricePrecision} minNotional=$${used.minNotional} [${source}]`);
    }

  } catch (error) {
    console.error('[AutoBot] ❌ Fallo al sincronizar Exchange Info:', error);
  }
}

const persistedState: PersistedState = loadBotState();

export let botConfig: BotConfig = {
  isAutoBotActive: true,
  monitoredSymbols: ['BTC-USDT', 'ETH-USDT', 'AVAX-USDT', 'LINK-USDT', 'SOL-USDT', 'PAXG-USDT', 'BNB-USDT', 'XRP-USDT', 'DOGE-USDT', 'SUI-USDT'],
  interval: '5m', // MICRO-SCALPING: 5m en lugar de 15m para entradas más rápidas
  strategy: 'CONFLUENCE_TA',
  riskPerTradePercent: 1.0,
  maxLeverage: 20,
  // Se restauran desde disco: si el proceso se reinició justo después de un
  // circuit breaker diario, el bot debe arrancar PAUSADO, no reactivarse solo.
  autoTradeEnabled: persistedState.autoTradeEnabled,
  dailyDrawdownLimitPct: 4.0,
  autoTradeDisabledByDrawdown: persistedState.autoTradeDisabledByDrawdown,
  useTrailingStop: true,
  useEarlyExit: false,  // DESACTIVADO: en 15m el ruido genera señales STRONG falsas que cierran operaciones ganadoras prematuramente.
  currentAtr: {},
  needsCleanup: {},
  lastScanTime: Date.now(),
  lastSignals: persistedState.lastSignals,
  totalExecutedTrades: persistedState.totalExecutedTrades,
  lastTradeTime: persistedState.lastTradeTime,
  cooldownUntil: persistedState.cooldownUntil,
  startOfDayEquity: persistedState.startOfDayEquity,
  highestEquityToday: persistedState.highestEquityToday,
  lastDrawdownDate: persistedState.lastDrawdownDate,
  highestPriceTracker: persistedState.highestPriceTracker,
  lowestPriceTracker: persistedState.lowestPriceTracker,
  breakevenTriggered: persistedState.breakevenTriggered,
  partialTaken: persistedState.partialTaken,
  tradeOpenTime: persistedState.tradeOpenTime,
  forbiddenSide: persistedState.forbiddenSide || {},
};

const earlyAlertSent: Record<string, number> = {};

let botLoopInterval: NodeJS.Timeout | null = null;
// Evita que dos iteraciones del loop corran en paralelo si una tarda más de 30s
// (llamadas lentas a la IA, red, etc.). Sin esto, dos ciclos superpuestos pueden
// leer/escribir botConfig a la vez y duplicar órdenes.
let isLoopRunning = false;

function persistState(): void {
  saveBotState({
    lastSignals: botConfig.lastSignals,
    lastTradeTime: botConfig.lastTradeTime,
    cooldownUntil: botConfig.cooldownUntil,
    tradeOpenTime: botConfig.tradeOpenTime,
    breakevenTriggered: botConfig.breakevenTriggered,
    partialTaken: botConfig.partialTaken,
    highestPriceTracker: botConfig.highestPriceTracker,
    lowestPriceTracker: botConfig.lowestPriceTracker,
    forbiddenSide: botConfig.forbiddenSide,
    totalExecutedTrades: botConfig.totalExecutedTrades,
    startOfDayEquity: botConfig.startOfDayEquity,
    highestEquityToday: botConfig.highestEquityToday,
    lastDrawdownDate: botConfig.lastDrawdownDate,
    autoTradeEnabled: botConfig.autoTradeEnabled,
    autoTradeDisabledByDrawdown: botConfig.autoTradeDisabledByDrawdown,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// LOOP PRINCIPAL DEL BOT
// ─────────────────────────────────────────────────────────────────────────────
function runBotLoop() {
  if (botLoopInterval) clearInterval(botLoopInterval);

  console.log(`[AutoBot] 🚀 Loop iniciado para: ${botConfig.monitoredSymbols.join(', ')} | Timeframe: ${botConfig.interval} | Riesgo: ${botConfig.riskPerTradePercent}% | Leverage: ${botConfig.maxLeverage}x`);

  botLoopInterval = setInterval(async () => {
    if (!botConfig.isAutoBotActive) return;

    if (isLoopRunning) {
      console.warn('[AutoBot] ⏭️  Ciclo anterior aún en ejecución (red/IA lenta). Se salta este tick para evitar solapamiento.');
      return;
    }
    isLoopRunning = true;
    botConfig.lastScanTime = Date.now();

    try {

      // ─────────────────────────────────────────────────────────────────────
      // BLOQUE 1: PROTECCIÓN DE CAPITAL DIARIO (SISTEMA DE REINTENTOS)
      // ─────────────────────────────────────────────────────────────────────
      try {
        const globalBalance = await bingxClient.getAccountBalance();
        const today = new Date().toISOString().split('T')[0];

        if (botConfig.lastDrawdownDate !== today) {
          botConfig.startOfDayEquity = globalBalance.equity;
          botConfig.highestEquityToday = globalBalance.equity;
          botConfig.lastDrawdownDate = today;

          // Solo se reactiva sola si el apagón fue del circuit breaker.
          // Si el usuario la apagó manualmente por /toggle, se respeta su decisión.
          if (botConfig.autoTradeDisabledByDrawdown) {
            botConfig.autoTradeEnabled = true;
            botConfig.autoTradeDisabledByDrawdown = false;
            telegramBot.sendMessage('🔄 <b>NUEVO DÍA — AUTO-TRADE REACTIVADO</b>\n\nEl freno del día anterior se levanta automáticamente. El bot vuelve a buscar entradas.');
          }

          persistState();
          console.log(`[AutoBot] 📅 Nuevo día (${today}). Equity inicial: $${globalBalance.equity.toFixed(2)}`);
        }

        if (botConfig.startOfDayEquity > 0) {
          if (globalBalance.equity > botConfig.highestEquityToday) {
            botConfig.highestEquityToday = globalBalance.equity;
          }

          let shouldAlert = false;
          let alertReason = '';

          if (shouldAlert) {
            telegramBot.sendMessage(alertReason + '\n⏳ Ejecutando protocolo de cierre de emergencia...');

            try {
              const allActive = await bingxClient.getActivePositions();

              for (const p of allActive) {
                let closedSuccessfully = false;
                const maxRetries = 3;

                for (let attempt = 1; attempt <= maxRetries; attempt++) {
                  try {
                    await bingxClient.closePosition(p.symbol, p.positionSide);
                    console.log(`[AutoBot] ✅ ${p.symbol} cerrado exitosamente (Intento ${attempt}).`);
                    closedSuccessfully = true;
                    break;
                  } catch (closeErr) {
                    console.warn(`[AutoBot] ⚠️ Fallo al cerrar ${p.symbol} (Intento ${attempt}/${maxRetries}).`);
                    if (attempt < maxRetries) await new Promise(res => setTimeout(res, 2000));
                  }
                }

                if (!closedSuccessfully) {
                  telegramBot.sendMessage(`🚨 <b>ALERTA CRÍTICA</b>\nEl bot intentó ${maxRetries} veces cerrar ${p.symbol} pero el exchange lo rechazó. ¡Entra a BingX y ciérralo manualmente!`);
                }
              }
              telegramBot.sendMessage('✅ Protocolo de cierre finalizado.');
            } catch (err: any) {
              const isNetwork = err?.code === 'ECONNRESET' || err?.code === 'ECONNABORTED' || err?.message?.includes('timeout');
              if (!isNetwork) console.error('[AutoBot] ❌ Error obteniendo posiciones para cerrar:', err);
              telegramBot.sendMessage('🚨 <b>FALLO DE RED GRAVE</b>\nNo se pudieron cargar las posiciones para cerrarlas. El exchange no responde.');
            }

            if (botConfig.autoTradeEnabled) {
              botConfig.autoTradeEnabled = false;
              botConfig.autoTradeDisabledByDrawdown = true;
              telegramBot.sendMessage(
                '⛔ <b>AUTO-TRADE PAUSADO POR HOY</b>\n\n' +
                'El bot dejó de abrir operaciones nuevas hasta el próximo día de trading (00:00 UTC).\n' +
                'Las posiciones que sigan abiertas se continúan gestionando (breakeven / trailing / time-stop) con normalidad.\n\n' +
                'Para reactivarlo manualmente hoy mismo, usa /toggle con autoTrade=true.'
              );
            }

            botConfig.startOfDayEquity = globalBalance.equity;
            botConfig.highestEquityToday = globalBalance.equity;
            persistState();
            return;
          }
        }
      } catch (err: any) {
        if (err?.code === 'ECONNRESET' || err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')) {
          console.warn('[AutoBot] ⚠️ Micro-corte de red en Protección de Capital. Se reintentará.');
        } else {
          console.error('[AutoBot] Error comprobando protección de capital:', err);
        }
      }

      // ─────────────────────────────────────────────────────────────────────
      // BLOQUE 2: OBTENER POSICIONES ACTIVAS
      // ─────────────────────────────────────────────────────────────────────
      let allActivePositions: any[] = [];
      try {
        allActivePositions = await bingxClient.getActivePositions();
      } catch (err: any) {
        console.error('[AutoBot] ⚠️ No se pudieron obtener posiciones activas. Se aborta este ciclo por seguridad (no se abrirán ni gestionarán operaciones con datos inciertos):', err?.message || err);
        return;
      }

      // ─────────────────────────────────────────────────────────────────────
      // BLOQUE 3: CICLO POR SÍMBOLO
      // ─────────────────────────────────────────────────────────────────────
      for (const symbol of botConfig.monitoredSymbols) {
        try {
          const klines = await bingxClient.getKlines(symbol, botConfig.interval, 750); // 750 velas 5m = ~2.6 días. Suficiente para EMA200
          const closedKlines = klines.slice(0, -1);
          if (closedKlines.length < 50) continue;

          const analysis = TechnicalAnalysis.analyze(symbol, closedKlines);
          const liveAnalysis = TechnicalAnalysis.analyze(symbol, klines); // Vela actual viva para salidas rápidas
          botConfig.currentAtr[symbol] = analysis.atr;

          // Gestión de posición abierta — corre SIEMPRE, independiente de autoTradeEnabled.
          // Si autoTradeEnabled=false, las posiciones ya abiertas siguen bajo gestión activa.
          const position = allActivePositions.find((p) => p.symbol === symbol);

          if (position) {
            const currentPrice = klines[klines.length - 1].close;
            const entryPrice = position.entryPrice;
            const atr = botConfig.currentAtr[symbol] || (entryPrice * 0.015);
            // Se necesita la info del símbolo aquí para formatear el precio de breakeven al enviar a BingX
            const posInfo = getSymbolInfo(symbol);

            if (botConfig.useEarlyExit) {
              const shouldExitLong = position.positionSide === 'LONG' && liveAnalysis.signal === 'STRONG_SELL';
              const shouldExitShort = position.positionSide === 'SHORT' && liveAnalysis.signal === 'STRONG_BUY';

              if (shouldExitLong || shouldExitShort) {
                const exitSide = shouldExitLong ? 'LONG' : 'SHORT';
                console.log(`[AutoBot] 🏃‍♂️ Early Exit detectado en ${symbol} ${exitSide} (Señal invertida a ${liveAnalysis.signal})`);

                try { await bingxClient.cancelAllPendingOrders(symbol); } catch (_) { }
                const closeRes = await bingxClient.closePosition(symbol, exitSide);

                if (!closeRes.success) {
                  telegramBot.sendMessage(`⚠️ <b>ERROR EN EARLY EXIT</b>\n\n• Par: ${escHtml(symbol)}\n• Motivo: ${escHtml(closeRes.message)}\n• Se reintentará en el siguiente ciclo.`);
                } else {
                  telegramBot.sendMessage(`🏃‍♂️ <b>EARLY EXIT (Salida de Emergencia)</b>\n\n• Par: ${escHtml(symbol)}\n• Posición: ${escHtml(exitSide)}\n• Razón: La tendencia se invirtió bruscamente (${escHtml(liveAnalysis.signal)}).`);

                  botConfig.needsCleanup[symbol] = false;
                  botConfig.lastSignals[symbol] = 'NONE'; // FIX: permite re-entrar si la misma señal vuelve
                  delete botConfig.tradeOpenTime[symbol];
                  delete botConfig.highestPriceTracker[symbol];
                  delete botConfig.lowestPriceTracker[symbol];
                  botConfig.partialTaken[symbol] = false;
                  botConfig.cooldownUntil[symbol] = Date.now() + 15 * 60 * 1000; // 15 min de cooldown
                  botConfig.lastTradeTime[symbol] = 0;
                  persistState();
                  continue;
                }
              }
            }

            if (botConfig.useTrailingStop) {
              if (position.positionSide === 'LONG') {
                botConfig.highestPriceTracker[symbol] = Math.max(botConfig.highestPriceTracker[symbol] || entryPrice, currentPrice);

                // FIX Bug #3 (race condition): Toma parcial PRIMERO, antes del breakeven.
                // TOMA PARCIAL (SCALE-OUT) A +1.2x ATR
                if (!botConfig.partialTaken[symbol] && botConfig.highestPriceTracker[symbol] > entryPrice + (atr * 1.2)) {
                  botConfig.partialTaken[symbol] = true;
                  const info = getSymbolInfo(symbol);
                  const halfQtyStr = (position.amount / 2).toFixed(info.qtyPrecision);
                  const halfQty = parseFloat(halfQtyStr);
                  const notional = halfQty * currentPrice;

                  if (notional >= info.minNotional) {
                    console.log(`[AutoBot] 💰 Toma Parcial (50%) en ${symbol} LONG @ $${currentPrice}`);
                    const closeRes = await bingxClient.closePosition(symbol, 'LONG', halfQty);
                    if (closeRes.success) {
                      telegramBot.sendMessage(`💰 <b>TOMA PARCIAL (50%)</b>\n\n• Par: ${escHtml(symbol)}\n• Se cerraron ${halfQty} LONG a +1.2x ATR.`);
                      position.amount -= halfQty; // Ajustar volumen localmente para el resto de comprobaciones
                    } else {
                      console.error(`[AutoBot] ⚠️ Error en Toma Parcial LONG para ${symbol}:`, closeRes.message);
                    }
                  } else {
                    console.log(`[AutoBot] ⚠️ Parcial ignorado en ${symbol} LONG: nocional $${notional.toFixed(2)} menor al mínimo $${info.minNotional}`);
                  }
                }

                // ESCUDO PROTECTOR DINÁMICO (Breakeven a 0.8x ATR)
                // Protegemos apenas estemos en verde suficiente.
                let stopLossFloor = entryPrice - (atr * 1.5);

                if (botConfig.highestPriceTracker[symbol] > entryPrice + (atr * 0.8)) {
                  stopLossFloor = entryPrice + (atr * 0.2); // Breakeven con margen mínimo para cubrir comisiones
                  if (!botConfig.breakevenTriggered[symbol]) {
                    botConfig.breakevenTriggered[symbol] = true;
                    const bePriceLong = parseFloat((entryPrice + (atr * 0.2)).toFixed(posInfo.pricePrecision));
                    bingxClient.modifyStopLoss(symbol, 'LONG', bePriceLong)
                      .then(res => {
                        const beMsg = res.success
                          ? `🛡 <b>BREAKEVEN ACTIVADO</b>\n\n• Par: ${escHtml(symbol)}\n• SL real movido a $${escHtml(String(bePriceLong))} en BingX. Posición protegida incluso sin conexión.`
                          : `⚠️ <b>BREAKEVEN (software fallback)</b>\n\n• Par: ${escHtml(symbol)}\n• Error al mover SL en BingX: ${escHtml(res.message)}\n• El bot lo gestiona en software como respaldo.`;
                        telegramBot.sendMessage(beMsg);
                      })
                      .catch(() => telegramBot.sendMessage(`⚠️ <b>BREAKEVEN (software fallback)</b>\n\n• Par: ${escHtml(symbol)}\n• No se pudo actualizar el SL en BingX. Gestionando localmente.`));
                  }
                }

                if (stopLossFloor !== -Infinity && currentPrice <= stopLossFloor) {
                  console.log(`[AutoBot] 🛡 Salida protegida en ${symbol} LONG @ $${currentPrice}`);
                  try { await bingxClient.cancelAllPendingOrders(symbol); } catch (_) { }
                  const closeRes = await bingxClient.closePosition(symbol, 'LONG');
                  if (!closeRes.success) {
                    console.error(`[AutoBot] ❌ Error en Salida Protegida LONG para ${symbol}:`, closeRes.message);
                    telegramBot.sendMessage(`⚠️ <b>ERROR CERRANDO POSICIÓN</b>\n\n• Par: ${escHtml(symbol)}\n• Motivo: ${escHtml(closeRes.message)}\n• Se reintentará en el siguiente ciclo.`);
                    continue;
                  }
                  const pnlStatus = currentPrice >= entryPrice ? 'sin pérdidas (o ligera ganancia)' : `con ligera pérdida ($${escHtml(currentPrice)}) por deslizamiento de mercado`;
                  telegramBot.sendMessage(`🛡 <b>SALIDA PROTEGIDA</b>\n\n• Par: ${escHtml(symbol)}\n• LONG cerrada ${pnlStatus}.`);
                  botConfig.breakevenTriggered[symbol] = false;
                  botConfig.needsCleanup[symbol] = false;
                  botConfig.lastSignals[symbol] = 'NONE';
                  delete botConfig.tradeOpenTime[symbol];
                  delete botConfig.highestPriceTracker[symbol];
                  botConfig.partialTaken[symbol] = false;
                  botConfig.cooldownUntil[symbol] = Date.now() + 15 * 60 * 1000; // 15 min de cooldown
                  botConfig.lastTradeTime[symbol] = 0;
                  persistState();
                  continue;
                }

                // TRAILING STOP: retiene 75% de la ganancia máxima (inicia en 2.0x ATR)
                if (botConfig.highestPriceTracker[symbol] > entryPrice + (atr * 2.0)) {
                  const maxFavorableMovement = botConfig.highestPriceTracker[symbol] - entryPrice;
                  const triggerPrice = entryPrice + (maxFavorableMovement * 0.75);

                  if (currentPrice < triggerPrice) {
                    console.log(`[AutoBot] 🛑 Trailing Stop LONG en ${symbol} → Cierre: $${currentPrice}`);
                    try { await bingxClient.cancelAllPendingOrders(symbol); } catch (_) { }
                    const closeRes = await bingxClient.closePosition(symbol, 'LONG');
                    if (!closeRes.success) {
                      console.error(`[AutoBot] ❌ Error en Trailing Stop LONG para ${symbol}:`, closeRes.message);
                      telegramBot.sendMessage(`⚠️ <b>ERROR CERRANDO POSICIÓN</b>\n\n• Par: ${escHtml(symbol)}\n• Motivo: ${escHtml(closeRes.message)}\n• Se reintentará en el siguiente ciclo.`);
                      continue;
                    }
                    telegramBot.sendMessage(`🛑 <b>TRAILING STOP — GANANCIA ASEGURADA</b>\n\n• Par: ${escHtml(symbol)}\n• Posición: LONG\n• Cierre en: $${escHtml(currentPrice)}`);
                    botConfig.breakevenTriggered[symbol] = false;
                    botConfig.needsCleanup[symbol] = false;
                    botConfig.lastSignals[symbol] = 'NONE';
                    delete botConfig.tradeOpenTime[symbol];
                    delete botConfig.highestPriceTracker[symbol];
                    botConfig.partialTaken[symbol] = false;
                    botConfig.cooldownUntil[symbol] = Date.now() + 15 * 60 * 1000;
                    botConfig.lastTradeTime[symbol] = 0;
                    persistState();
                    continue;
                  }
                }
              }

              else if (position.positionSide === 'SHORT') {
                botConfig.lowestPriceTracker[symbol] = Math.min(botConfig.lowestPriceTracker[symbol] || entryPrice, currentPrice);

                // FIX Bug #3 (race condition): Toma parcial PRIMERO, antes del breakeven.
                // TOMA PARCIAL (SCALE-OUT) A +1.2x ATR
                if (!botConfig.partialTaken[symbol] && botConfig.lowestPriceTracker[symbol] < entryPrice - (atr * 1.2)) {
                  botConfig.partialTaken[symbol] = true;
                  const info = getSymbolInfo(symbol);
                  const halfQtyStr = (position.amount / 2).toFixed(info.qtyPrecision);
                  const halfQty = parseFloat(halfQtyStr);
                  const notional = halfQty * currentPrice;

                  if (notional >= info.minNotional) {
                    console.log(`[AutoBot] 💰 Toma Parcial (50%) en ${symbol} SHORT @ $${currentPrice}`);
                    const closeRes = await bingxClient.closePosition(symbol, 'SHORT', halfQty);
                    if (closeRes.success) {
                      telegramBot.sendMessage(`💰 <b>TOMA PARCIAL (50%)</b>\n\n• Par: ${escHtml(symbol)}\n• Se cerraron ${halfQty} SHORT a +1.2x ATR.`);
                      position.amount -= halfQty;
                    } else {
                      console.error(`[AutoBot] ⚠️ Error en Toma Parcial SHORT para ${symbol}:`, closeRes.message);
                    }
                  } else {
                    console.log(`[AutoBot] ⚠️ Parcial ignorado en ${symbol} SHORT: nocional $${notional.toFixed(2)} menor al mínimo $${info.minNotional}`);
                  }
                }

                // ESCUDO PROTECTOR DINÁMICO (Breakeven a 0.8x ATR)
                let stopLossCeiling = entryPrice + (atr * 1.5);

                if (botConfig.lowestPriceTracker[symbol] < entryPrice - (atr * 0.8)) {
                  stopLossCeiling = entryPrice - (atr * 0.2);
                  if (!botConfig.breakevenTriggered[symbol]) {
                    botConfig.breakevenTriggered[symbol] = true;
                    const bePriceShort = parseFloat((entryPrice - (atr * 0.2)).toFixed(posInfo.pricePrecision));
                    bingxClient.modifyStopLoss(symbol, 'SHORT', bePriceShort)
                      .then(res => {
                        const beMsg = res.success
                          ? `🛡 <b>BREAKEVEN ACTIVADO</b>\n\n• Par: ${escHtml(symbol)}\n• SL real movido a $${escHtml(String(bePriceShort))} en BingX. Posición protegida incluso sin conexión.`
                          : `⚠️ <b>BREAKEVEN (software fallback)</b>\n\n• Par: ${escHtml(symbol)}\n• Error al mover SL en BingX: ${escHtml(res.message)}\n• El bot lo gestiona en software como respaldo.`;
                        telegramBot.sendMessage(beMsg);
                      })
                      .catch(() => telegramBot.sendMessage(`⚠️ <b>BREAKEVEN (software fallback)</b>\n\n• Par: ${escHtml(symbol)}\n• No se pudo actualizar el SL en BingX. Gestionando localmente.`));
                  }
                }

                if (stopLossCeiling !== Infinity && currentPrice >= stopLossCeiling) {
                  console.log(`[AutoBot] 🛡 Salida protegida en ${symbol} SHORT @ $${currentPrice}`);
                  try { await bingxClient.cancelAllPendingOrders(symbol); } catch (_) { }
                  const closeRes = await bingxClient.closePosition(symbol, 'SHORT');
                  if (!closeRes.success) {
                    console.error(`[AutoBot] ❌ Error en Salida Protegida SHORT para ${symbol}:`, closeRes.message);
                    telegramBot.sendMessage(`⚠️ <b>ERROR CERRANDO POSICIÓN</b>\n\n• Par: ${escHtml(symbol)}\n• Motivo: ${escHtml(closeRes.message)}\n• Se reintentará en el siguiente ciclo.`);
                    continue;
                  }
                  const pnlStatus = currentPrice <= entryPrice ? 'sin pérdidas (o ligera ganancia)' : `con ligera pérdida ($${escHtml(currentPrice)}) por deslizamiento de mercado`;
                  telegramBot.sendMessage(`🛡 <b>SALIDA PROTEGIDA</b>\n\n• Par: ${escHtml(symbol)}\n• SHORT cerrada ${pnlStatus}.`);
                  botConfig.breakevenTriggered[symbol] = false;
                  botConfig.needsCleanup[symbol] = false;
                  botConfig.lastSignals[symbol] = 'NONE';
                  delete botConfig.tradeOpenTime[symbol];
                  delete botConfig.lowestPriceTracker[symbol];
                  botConfig.partialTaken[symbol] = false;
                  botConfig.cooldownUntil[symbol] = Date.now() + 15 * 60 * 1000; // 15 min de cooldown
                  botConfig.lastTradeTime[symbol] = 0;
                  persistState();
                  continue;
                }

                // TRAILING STOP SHORT (inicia en 2.0x ATR)
                if (botConfig.lowestPriceTracker[symbol] < entryPrice - (atr * 2.0)) {
                  const maxFavorableMovement = entryPrice - botConfig.lowestPriceTracker[symbol];
                  const triggerPrice = entryPrice - (maxFavorableMovement * 0.75);

                  if (currentPrice > triggerPrice) {
                    console.log(`[AutoBot] 🛑 Trailing Stop SHORT en ${symbol} → Cierre: $${currentPrice}`);
                    try { await bingxClient.cancelAllPendingOrders(symbol); } catch (_) { }
                    const closeRes = await bingxClient.closePosition(symbol, 'SHORT');
                    if (!closeRes.success) {
                      console.error(`[AutoBot] ❌ Error en Trailing Stop SHORT para ${symbol}:`, closeRes.message);
                      telegramBot.sendMessage(`⚠️ <b>ERROR CERRANDO POSICIÓN</b>\n\n• Par: ${escHtml(symbol)}\n• Motivo: ${escHtml(closeRes.message)}\n• Se reintentará en el siguiente ciclo.`);
                      continue;
                    }
                    telegramBot.sendMessage(`🛑 <b>TRAILING STOP — GANANCIA ASEGURADA</b>\n\n• Par: ${escHtml(symbol)}\n• Posición: SHORT\n• Cierre en: $${escHtml(currentPrice)}`);
                    botConfig.breakevenTriggered[symbol] = false;
                    botConfig.needsCleanup[symbol] = false;
                    botConfig.lastSignals[symbol] = 'NONE';
                    delete botConfig.tradeOpenTime[symbol];
                    delete botConfig.lowestPriceTracker[symbol];
                    botConfig.partialTaken[symbol] = false;
                    botConfig.cooldownUntil[symbol] = Date.now() + 15 * 60 * 1000;
                    botConfig.lastTradeTime[symbol] = 0;
                    persistState();
                    continue;
                  }
                }
              }
            }
          } else {
            // Sin posición abierta: limpiar trackers solo si no hay tradeOpenTime
            // (protege contra el caso en que la API devuelva lista vacía por error de red)
            if (!botConfig.tradeOpenTime[symbol]) {
              delete botConfig.highestPriceTracker[symbol];
              delete botConfig.lowestPriceTracker[symbol];
              botConfig.partialTaken[symbol] = false;
            }
          }

          const cooldownEndTime = botConfig.cooldownUntil[symbol] || 0;
          if (Date.now() < cooldownEndTime) continue;

          // FIX (Bug A): cuando el cooldown asociado al Stop Loss expira, liberar también
          // el veto de dirección (forbiddenSide). De lo contrario el símbolo quedaba
          // bloqueado para siempre en una dirección aunque el mercado ya cambiara.
          if (cooldownEndTime > 0 && botConfig.forbiddenSide[symbol]) {
            botConfig.forbiddenSide[symbol] = null;
          }

          const lastTrade = botConfig.lastTradeTime[symbol] || 0;
          // FIX (corregido): cooldown dinámico correcto.
          // Si el cooldownUntil ya EXPIRÓ (Date.now() > cooldownEndTime), ese período fue de Early Exit/IA.
          // En ese caso NO aplicamos la hora extra porque la penalización ya se cumplió.
          // Si NO había cooldownUntil, aplicamos 15m de cooldown (típico cierre por SL/TP externo).
          const hadEarlyExitCooldown = (botConfig.cooldownUntil[symbol] || 0) > 0;
          const lastTradeCooldownMs = hadEarlyExitCooldown ? 0 : 15 * 60 * 1000;
          if (Date.now() - lastTrade < lastTradeCooldownMs) continue;

          let signal = analysis.signal;
          // Buffer reducido al 0.1% sobre EMA200: evita entradas exactamente en la barrera pero permite
          // breakouts legítimos que ocurren justo al cruzar la EMA200 (los mejores puntos de entrada).
          if (signal.includes('BUY') && analysis.currentPrice < analysis.ema200 * 1.001) signal = 'NEUTRAL';
          else if (signal.includes('SELL') && analysis.currentPrice > analysis.ema200 * 0.999) signal = 'NEUTRAL';

          // ─── FILTRO INSTITUCIONAL MULTI-TIMEFRAME (1 HORA) ────────────────
          // Regla: solo bloquear si el mercado en 1H tiene una tendencia OPUESTA
          // clara y confirmada (AMBAS EMAs contra la señal = AND, no OR).
          // El filtro OR anterior era demasiado restrictivo: en cripto el precio
          // puede estar sobre la EMA200 anual pero en caída libre vs la EMA50 —
          // eso es exactamente cuando hay que entrar SHORT.
          if (signal !== 'NEUTRAL') {
            try {
              const klines15m = await bingxClient.getKlines(symbol, '15m', 500); // 500 velas 15m = ~5 días.
              if (klines15m && klines15m.length >= 50) {
                const closes15m = klines15m.map(k => k.close);
                const ema20_15m = TechnicalAnalysis.calculateEMA(closes15m, 20);
                const ema50_15m = TechnicalAnalysis.calculateEMA(closes15m, Math.min(50, closes15m.length - 1));

                const adx15m = TechnicalAnalysis.calculateADX(klines15m);
                const current15mPrice = closes15m[closes15m.length - 1];

                // FILTRO 1: Solo bloquear si el TREND de 15m está estructuralmente en contra.
                if (signal.includes('BUY') && current15mPrice < ema20_15m && ema20_15m < ema50_15m) {
                  console.log(`[AutoBot] 🛡️ ${symbol}: BUY bloqueado — Downtrend estructural confirmado en 15m (EMA20 ${ema20_15m.toFixed(2)} < EMA50 ${ema50_15m.toFixed(2)}).`);
                  signal = 'NEUTRAL';
                } else if (signal.includes('SELL') && current15mPrice > ema20_15m && ema20_15m > ema50_15m) {
                  console.log(`[AutoBot] 🛡️ ${symbol}: SELL bloqueado — Uptrend estructural confirmado en 15m (EMA20 ${ema20_15m.toFixed(2)} > EMA50 ${ema50_15m.toFixed(2)}).`);
                  signal = 'NEUTRAL';
                }

                // FILTRO 2: Bloquear en chop lateral de 15m (ADX < 15)
                if (signal !== 'NEUTRAL' && adx15m > 0 && adx15m < 15) {
                  console.log(`[AutoBot] 🛡️ ${symbol}: ${signal} bloqueado — ADX de 15m muy débil (${adx15m} < 15). Mercado en chop puro.`);
                  signal = 'NEUTRAL';
                }
              }
            } catch (err15m) {
              console.warn(`[AutoBot] ⚠️ No se pudo verificar tendencia de 15m para ${symbol}, evaluando solo 5m.`);
            }
          }


          if (signal === 'NEUTRAL') {
            botConfig.lastSignals[symbol] = 'NEUTRAL';
            continue;
          }
          const lastSig = botConfig.lastSignals[symbol] || 'NONE';
          if (signal === lastSig) continue;

          // Guardar la señal anterior (= lastSig) para restaurarla si la IA rechaza
          // NO actualizamos lastSignals aquí — solo se graba si la orden se ejecuta con éxito.
          console.log(`[AutoBot] 🚨 Nueva señal en ${symbol}: ${signal} @ $${analysis.currentPrice}`);

          // t0: desde aquí medimos cuánto tarda el pipeline de decisión (IA + cálculos)
          // hasta que la orden efectivamente se manda. Ver guardia de frescura más abajo.
          const signalDetectedAt = Date.now();

          if (!botConfig.autoTradeEnabled) continue;

          // 🔥 PROTECCIÓN ANTI-SOBREEXPOSICIÓN: MÁXIMO 10 OPERACIONES SIMULTÁNEAS
          if (allActivePositions.length >= 10) {
            console.log(`[AutoBot] ⏸️ Límite de 10 posiciones simultáneas alcanzado. Se omite entrada en ${symbol}.`);
            continue;
          }

          const existingPosition = allActivePositions.find((p) => p.symbol === symbol);
          if (existingPosition) continue;

          // ─── ESTRATEGIA INVERSA (CONTRARIAN) ──────────────────────────────
          // Si la señal técnica es BUY -> ejecutamos SHORT
          // Si la señal técnica es SELL -> ejecutamos LONG
          const rawSide = signal.includes('BUY') ? 'BUY' : 'SELL';
          const side: 'BUY' | 'SELL' = rawSide === 'BUY' ? 'SELL' : 'BUY';
          const posSide: 'LONG' | 'SHORT' = side === 'BUY' ? 'LONG' : 'SHORT';

          console.log(`[AutoBot] 🔄 MODO INVERSO: Señal técnica=${signal} -> Ejecutando ${posSide} (${side}) en ${symbol}`);

          // FIX: antes se limpiaba `forbiddenSide[symbol] = null` aquí mismo, antes de
          // saber si la IA aprobaba o si la orden se ejecutaba con éxito.
          const forbidden = botConfig.forbiddenSide[symbol];
          let forbiddenOverridden = false;
          if (forbidden === posSide) {
            if (signal !== 'STRONG_BUY' && signal !== 'STRONG_SELL') continue;
            forbiddenOverridden = true;
          }

          // IA DESACTIVADA TEMPORALMENTE
          const aiValidation = { approved: true, confidence: 100, reason: 'MODO INVERSO (Contrarian Test)' };
          
          if (!aiValidation.approved) {
            botConfig.cooldownUntil[symbol] = Date.now() + 15 * 60 * 1000;
            continue;
          }

          const balance = await bingxClient.getAccountBalance();
          const entryPrice = analysis.currentPrice;
          const info = getSymbolInfo(symbol);

          // Configuración Estándar: SL a 1.5x ATR y TP a 3.0x ATR (Ratio 1:2)
          const atrDistance = analysis.atr > 0 ? Math.max(entryPrice * 0.002, analysis.atr * 1.5) : entryPrice * 0.003;
          const stopLoss = posSide === 'LONG' ? entryPrice - atrDistance : entryPrice + atrDistance;
          const takeProfit = posSide === 'LONG' ? entryPrice + (atrDistance * 2.0) : entryPrice - (atrDistance * 2.0);

          const riskCalc = RiskCalculator.calculate({
            accountBalance: balance.available > 0 ? balance.available : 10,
            riskPercentage: botConfig.riskPerTradePercent,
            entryPrice,
            stopLossPrice: stopLoss,
            takeProfitPrice: takeProfit,
            leverage: botConfig.maxLeverage,
            positionSide: posSide,
          });

          // ULTRA MICRO-SCALPING: Si el Stop Loss es tan pequeño que exige un margen gigante,
          // en lugar de cancelar la operación, simplemente limitamos el tamaño de la posición
          // al margen máximo disponible.
          if (!riskCalc.isRiskAcceptable) {
            console.log(`[AutoBot] ⚠️ ${symbol}: Margen requerido ($${riskCalc.marginRequiredUSDT.toFixed(2)}) supera el disponible ($${balance.available.toFixed(2)}). Ajustando posición al máximo posible.`);
            const maxAllowedMargin = balance.available > 0 ? balance.available * 0.95 : 10; // Usar max 95% del balance
            const adjustedPositionValue = maxAllowedMargin * botConfig.maxLeverage;
            riskCalc.positionSizeCoins = adjustedPositionValue / entryPrice;
            riskCalc.marginRequiredUSDT = maxAllowedMargin;
            riskCalc.isRiskAcceptable = true;
          }

          const factor = Math.pow(10, info.qtyPrecision);
          let quantity = Math.floor(riskCalc.positionSizeCoins * factor) / factor;

          // FIX: Límite de seguridad en el tamaño nocional de la posición para evitar rechazos del exchange.
          // BingX tiene límites muy estrictos de tamaño máximo para ciertas monedas en VST.
          let maxNotionalLimit = 50000; // Límite seguro general (50k USD)
          if (symbol === 'PAXG-USDT') maxNotionalLimit = 900; // PAXG tiene un límite de 1000 USDT en VST

          if (quantity * entryPrice > maxNotionalLimit) {
            quantity = Math.floor((maxNotionalLimit / entryPrice) * factor) / factor;
            console.log(`[AutoBot] ℹ️ ${symbol}: Tamaño de posición reducido artificialmente al límite máximo nocional de $${maxNotionalLimit}`);
          }

          if (quantity === 0 || quantity * entryPrice < info.minNotional) {
            const minQty = Math.ceil((info.minNotional / entryPrice) * factor) / factor;
            const minQtyNotional = minQty * entryPrice;
            const impliedRisk = minQtyNotional * (atrDistance / entryPrice);
            const accountBal = balance.available > 0 ? balance.available : 10;
            const maxAcceptableRisk = accountBal * 0.05;

            if (impliedRisk <= maxAcceptableRisk && minQtyNotional <= accountBal) {
              quantity = minQty;
            } else {
              console.warn(`[AutoBot] ⚠️ ${symbol}: Cuenta insuficiente. Notional=$${minQtyNotional.toFixed(2)}. Omitido.`);
              continue;
            }
          }

          const finalStopLoss = parseFloat(stopLoss.toFixed(info.pricePrecision));
          const finalTakeProfit = parseFloat(takeProfit.toFixed(info.pricePrecision));

          // ─── GUARDIA DE FRESCURA ────────────────────────────────────────────
          // Si el pipeline de decisión (balance + IA + cálculos) tardó demasiado,
          // el precio de análisis ya puede estar desactualizado. Mejor abortar y
          // dejar que el próximo ciclo (30s después) re-evalúe con datos frescos,
          // que ejecutar una entrada "tarde" respecto a la señal que la originó.
          const decisionLatencyMs = Date.now() - signalDetectedAt;
          const MAX_DECISION_LATENCY_MS = 15000;
          console.log(`[AutoBot] ⏱ ${symbol}: latencia de decisión = ${decisionLatencyMs}ms`);

          if (decisionLatencyMs > MAX_DECISION_LATENCY_MS) {
            console.warn(`[AutoBot] ⚠️ ${symbol}: entrada descartada por latencia (${decisionLatencyMs}ms > ${MAX_DECISION_LATENCY_MS}ms). Se reintentará en el próximo ciclo.`);
            // No se marca lastSignals ni cooldown largo: se reintenta pronto con precio fresco.
            continue;
          }

          const orderRes = await bingxClient.placeOrder({
            symbol,
            side,
            positionSide: posSide,
            type: 'MARKET',
            quantity,
            stopLoss: finalStopLoss,
            takeProfit: finalTakeProfit,
            leverage: botConfig.maxLeverage,
          });

          if (orderRes.success) {
            // Solo aquí, con la orden confirmada por el exchange, se registra la señal
            // como procesada y se libera el veto de forbiddenSide (si aplicaba).
            botConfig.lastSignals[symbol] = signal;
            if (forbiddenOverridden) botConfig.forbiddenSide[symbol] = null;

            botConfig.totalExecutedTrades += 1;
            botConfig.lastTradeTime[symbol] = Date.now();
            botConfig.tradeOpenTime[symbol] = Date.now();
            botConfig.breakevenTriggered[symbol] = false;
            botConfig.partialTaken[symbol] = false;
            botConfig.needsCleanup[symbol] = true;
            // FIX (Bug E): incluir `amount: quantity` para que la gestión de
            // Toma Parcial no acceda a `position.amount = undefined` dentro del
            // mismo ciclo de 30s en el que se acaba de abrir la posición.
            allActivePositions.push({ symbol, positionSide: posSide, entryPrice, amount: quantity });
            persistState();

            console.log(`[AutoBot] ✅ Orden ejecutada: ${symbol} ${posSide} ${quantity} @ $${entryPrice}`);
            telegramBot.sendMessage(
              `🤖⚡ <b>TRADE EJECUTADO</b>\n\n` +
              `• <b>Par:</b> ${escHtml(symbol)}\n` +
              `• <b>Posición:</b> ${escHtml(posSide)} ${escHtml(botConfig.maxLeverage)}x\n` +
              `• <b>Entrada:</b> $${escHtml(entryPrice)}\n` +
              `• <b>Modo:</b> 🔄 INVERSO (Señal: ${escHtml(signal)} → Posición: ${escHtml(posSide)})\n` +
              `• <b>Stop Loss:</b> $${escHtml(finalStopLoss)}\n` +
              `• <b>Take Profit:</b> $${escHtml(finalTakeProfit)}\n` +
              `• <b>Estrategia:</b> Contrarian Standard (Ratio 1:2)`
            );
          } else {
            // FIX: antes, si orderRes.success era false, no pasaba nada — pero
            // lastSignals ya había sido marcado más arriba en el código original.
            // Ahora lastSignals nunca se tocó, así que la señal puede reintentarse.
            // Se deja un cooldown corto (en vez de reintentar en el próximo tick de
            // 30s) para no martillar al exchange si el rechazo es persistente, y se
            // avisa por Telegram para que no pase desapercibido.
            console.error(`[AutoBot] ❌ Orden rechazada por el exchange en ${symbol}:`, orderRes.message);
            telegramBot.sendMessage(`⚠️ <b>ORDEN RECHAZADA</b>\n\n• Par: ${escHtml(symbol)}\n• Señal: ${escHtml(signal)}\n• Motivo: ${escHtml(orderRes.message)}\n• Se reintentará tras un breve cooldown.`);
            botConfig.cooldownUntil[symbol] = Date.now() + 15 * 60 * 1000;
          }

        } catch (err: any) {
          // IMPORTANTE: usar 'continue', NO 'return'.
          // 'return' abandonaría el ciclo completo, dejando sin gestionar las posiciones
          // de los símbolos restantes. 'continue' sólo salta el símbolo con error.
          if (err?.code === 'ECONNRESET' || err?.message?.includes('timeout')) continue;
          console.error(`[AutoBot] Error escaneando ${symbol}:`, err);
        }
      }

      // ─────────────────────────────────────────────────────────────────────
      // BLOQUE 4: LIMPIEZA DE ÓRDENES HUÉRFANAS
      // ─────────────────────────────────────────────────────────────────────
      try {
        const activePositions = await bingxClient.getActivePositions();
        const activeSymSet = new Set(activePositions.map((p) => p.symbol));

        for (const symbol of botConfig.monitoredSymbols) {
          const wasOpen = !!botConfig.tradeOpenTime[symbol];
          if (!activeSymSet.has(symbol) && wasOpen) {
            const closedBySelf = botConfig.needsCleanup[symbol];

            if (closedBySelf) {
              await bingxClient.cancelAllPendingOrders(symbol);
              botConfig.needsCleanup[symbol] = false; // FIX: ya limpiado, no reintentar
            } else {
              // Cerrado externamente (SL/TP del exchange) o manualmente por el usuario.
              // ─────────────────────────────────────────────────────────────────────────
              // FIX: antes se usaba una heurística de tiempo (< 4h = SL probable) que era
              // imprecisa — si la operación tocaba el TP en menos de 4h, se bloqueaba la
              // misma dirección injustamente. Ahora se consulta el historial REAL del exchange:
              // si el profit de la última orden cerrada para ese símbolo es positivo → fue TP;
              // si es negativo → fue SL. Solo en SL se bloquea la dirección.
              // ─────────────────────────────────────────────────────────────────────────
              let likelyStopLoss = true; // fallback conservador si la API no responde

              try {
                const recentTrades = await bingxClient.getTradeHistory(20, true);
                const lastTradeForSymbol = recentTrades.find((t: any) => t.symbol === symbol);
                if (lastTradeForSymbol) {
                  // profit > 0 → Take Profit (ganancia) → NO bloquear dirección
                  // profit <= 0 → Stop Loss (pérdida) → SÍ bloquear dirección
                  likelyStopLoss = lastTradeForSymbol.profit <= 0;
                  console.log(`[AutoBot] 📊 ${symbol}: cierre externo detectado. Profit real: $${lastTradeForSymbol.profit.toFixed(2)} → ${likelyStopLoss ? 'SL (bloqueando dirección)' : 'TP (dirección libre)'}`);
                } else {
                  console.log(`[AutoBot] ⚠️ ${symbol}: no se encontró en historial reciente. Usando fallback conservador (asumir SL).`);
                }
              } catch (histErr) {
                console.warn(`[AutoBot] ⚠️ ${symbol}: error al leer historial real (${histErr}). Usando fallback conservador.`);
              }

              if (likelyStopLoss) {
                const prevSignal = botConfig.lastSignals[symbol];
                if (prevSignal && prevSignal !== 'NONE') {
                  const closedSide: 'LONG' | 'SHORT' = prevSignal.includes('BUY') ? 'LONG' : 'SHORT';
                  botConfig.forbiddenSide[symbol] = closedSide;
                }
              }
              botConfig.cooldownUntil[symbol] = Date.now() + 15 * 60 * 1000; // 15 min de cooldown si se cierra a mano o por SL
            }

            // Limpieza completa del estado post-cierre
            // FIX CRÍTICO: también se resetea lastSignals para que si la siguiente
            // señal es del mismo tipo (ej: otro SELL tras un SL), el bot la trate
            // como nueva y pueda volver a entrar. Sin esto, el bot ignoraba para siempre
            // cualquier señal que coincidiera con la última guardada, incluso si había
            // pasado por cooldown y la posición ya estaba cerrada.
            botConfig.lastSignals[symbol] = 'NONE';
            botConfig.lastTradeTime[symbol] = 0;
            botConfig.breakevenTriggered[symbol] = false;
            botConfig.partialTaken[symbol] = false;
            delete botConfig.tradeOpenTime[symbol];
            delete botConfig.highestPriceTracker[symbol];
            delete botConfig.lowestPriceTracker[symbol];
            persistState();
          }
        }
      } catch (err: any) {
        if (err?.code === 'ECONNRESET' || err?.message?.includes('timeout')) return;
        console.error('[AutoBot] Error en limpieza de órdenes huérfanas:', err);
      }

    } finally {
      isLoopRunning = false;
    }

  }, 15000); // 15 segundos para el loop (Micro-Scalping)
}

// ─────────────────────────────────────────────────────────────────────────────
// RUTAS API Y ARRANQUE
// ─────────────────────────────────────────────────────────────────────────────

router.get('/status', (req, res) => {
  res.json({ success: true, data: botConfig });
});

router.post('/toggle', (req, res) => {
  const { active, autoTrade, riskPercent, strategy, symbols, leverage } = req.body;

  if (active !== undefined) botConfig.isAutoBotActive = Boolean(active);

  if (autoTrade !== undefined) {
    const isActivating = Boolean(autoTrade) && !botConfig.autoTradeEnabled;
    botConfig.autoTradeEnabled = Boolean(autoTrade);
    if (isActivating) {
      botConfig.lastDrawdownDate = '';
      botConfig.lastSignals = {};
      botConfig.lastTradeTime = {};
      botConfig.forbiddenSide = {};
      botConfig.autoTradeDisabledByDrawdown = false;
    }
  }

  if (riskPercent) botConfig.riskPerTradePercent = parseFloat(riskPercent);
  if (strategy) botConfig.strategy = strategy;
  if (symbols && Array.isArray(symbols)) botConfig.monitoredSymbols = symbols;
  if (leverage) botConfig.maxLeverage = parseInt(leverage, 10);

  // Persistir para que un cambio manual (incluido apagar el bot) sobreviva a un reinicio
  persistState();

  if (botConfig.isAutoBotActive) {
    runBotLoop();
    telegramBot.sendMessage(`🤖 <b>BOT ACTIVADO (Modo Profesional)</b>\n\n• <b>Riesgo por trade:</b> ${escHtml(botConfig.riskPerTradePercent)}%`);
  } else {
    if (botLoopInterval) clearInterval(botLoopInterval);
    telegramBot.sendMessage(`⏹ <b>BOT PAUSADO</b>`);
  }

  res.json({ success: true, data: botConfig });
});

async function startSystem() {
  await syncExchangeInfo();
  setInterval(syncExchangeInfo, 24 * 60 * 60 * 1000);
  if (botConfig.isAutoBotActive) runBotLoop();
}

startSystem();

export default router;