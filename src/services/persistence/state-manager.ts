import fs from 'fs';
import path from 'path';

const STATE_FILE = path.resolve(process.cwd(), 'bot-state.json');

/**
 * Estado persistente del bot (subconjunto de BotConfig que NO debe perderse en reinicios)
 */
export interface PersistedState {
  lastSignals: Record<string, string>;
  lastTradeTime: Record<string, number>;
  cooldownUntil: Record<string, number>;
  tradeOpenTime: Record<string, number>;
  breakevenTriggered: Record<string, boolean>;
  partialTaken: Record<string, boolean>;
  highestPriceTracker: Record<string, number>;
  lowestPriceTracker: Record<string, number>;
  forbiddenSide: Record<string, 'LONG' | 'SHORT' | null>; // Dirección perdedora reciente
  totalExecutedTrades: number;
  startOfDayEquity: number;
  highestEquityToday: number;
  lastDrawdownDate: string;
  // Se persisten para que el circuit breaker diario sobreviva a un reinicio del proceso.
  // Sin esto, un reinicio justo después de un freno de emergencia reactivaría el
  // auto-trade aunque el bot siga "castigado" por el resto del día.
  autoTradeEnabled: boolean;
  autoTradeDisabledByDrawdown: boolean;
  savedAt?: string;
}

const defaultState: PersistedState = {
  lastSignals: {},
  lastTradeTime: {},
  cooldownUntil: {},
  tradeOpenTime: {},
  breakevenTriggered: {},
  partialTaken: {},
  highestPriceTracker: {},
  lowestPriceTracker: {},
  forbiddenSide: {},
  totalExecutedTrades: 0,
  startOfDayEquity: 0,
  highestEquityToday: 0,
  lastDrawdownDate: '',
  autoTradeEnabled: true,
  autoTradeDisabledByDrawdown: false,
};

/**
 * Carga el estado del bot desde disco. Retorna el estado por defecto si no existe el archivo.
 */
export function loadBotState(): PersistedState {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const raw = fs.readFileSync(STATE_FILE, 'utf-8');
      const parsed = JSON.parse(raw) as PersistedState;
      console.log(`[StateManager] ✅ Estado del bot restaurado desde disco (guardado: ${parsed.savedAt || 'N/A'})`);

      // Limpiar cooldowns expirados al cargar (cooldowns que ya pasaron no tienen sentido)
      const now = Date.now();
      for (const symbol of Object.keys(parsed.cooldownUntil || {})) {
        if (parsed.cooldownUntil[symbol] < now) {
          delete parsed.cooldownUntil[symbol];
        }
      }

      return { ...defaultState, ...parsed };
    }
  } catch (err) {
    console.warn('[StateManager] ⚠️ No se pudo leer bot-state.json. Iniciando con estado limpio.', err);
  }

  console.log('[StateManager] 🆕 Iniciando con estado limpio (primera ejecución o archivo no encontrado).');
  return { ...defaultState };
}

/**
 * Guarda el estado actual del bot en disco de forma síncrona para garantizar que no se pierde.
 */
export function saveBotState(state: PersistedState): void {
  try {
    const toSave: PersistedState = {
      ...state,
      savedAt: new Date().toISOString(),
    };
    fs.writeFileSync(STATE_FILE, JSON.stringify(toSave, null, 2), 'utf-8');
  } catch (err) {
    console.error('[StateManager] ❌ Error guardando estado en disco:', err);
  }
}