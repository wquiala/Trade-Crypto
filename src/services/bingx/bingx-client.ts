import axios, { AxiosInstance } from 'axios';
import crypto from 'crypto';
import { config } from '../../config/environment';

export interface KlineData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PositionData {
  symbol: string;
  positionId?: string;
  positionSide: 'LONG' | 'SHORT';
  entryPrice: number;
  markPrice: number;
  amount: number;
  leverage: number;
  unrealizedProfit: number;
  liquidationPrice: number;
  margin: number;
  takeProfit?: number;
  stopLoss?: number;
}

export interface OrderRequest {
  symbol: string;
  side: 'BUY' | 'SELL';
  positionSide?: 'LONG' | 'SHORT';
  type: 'MARKET' | 'LIMIT';
  quantity: number;
  price?: number;
  stopLoss?: number;
  takeProfit?: number;
  leverage?: number;
  reduceOnly?: boolean;
}

export interface AccountBalance {
  asset: string;
  balance: number;
  available: number;
  equity: number;
  shortUid?: string;
  isRealAccount: boolean;
}

export class BingXClient {
  private apiKey: string;
  private secretKey: string;
  private baseUrl: string;
  private http: AxiosInstance;
  private isDemoMode: boolean;

  private hasApiCredentials(): boolean {
    return Boolean(this.apiKey && this.secretKey);
  }

  private shouldUseDemoMode(): boolean {
    return this.isDemoMode || !this.hasApiCredentials();
  }

  // In-memory state for mock/demo simulation when API keys are not provided
  private mockBalance: number = 10000; // 10,000 USDT/VST
  private mockPositions: PositionData[] = [];
  private balanceCache: { data: AccountBalance; timestamp: number } | null = null;

  constructor() {
    this.apiKey = config.bingx.apiKey;
    this.secretKey = config.bingx.secretKey;
    this.baseUrl = config.bingx.baseUrl;
    this.isDemoMode = config.bingx.demoMode;

    this.http = axios.create({
      baseURL: this.baseUrl,
      timeout: 10000,
    });
  }

  /**
   * Firmar una cadena de parámetros usando HMAC SHA256
   */
  private sign(queryString: string): string {
    return crypto
      .createHmac('sha256', this.secretKey)
      .update(queryString)
      .digest('hex');
  }

  /**
   * Prepara los headers y los parámetros firmados con timestamp
   */
  private getSignedParams(params: Record<string, any> = {}): string {
    const timestamp = Date.now();
    const allParams: Record<string, any> = { ...params, timestamp };

    // Sort parameters alphabetically
    const sortedKeys = Object.keys(allParams).sort();

    // Unencoded query string for HMAC signature
    const rawQueryString = sortedKeys
      .map((key) => `${key}=${allParams[key]}`)
      .join('&');

    const signature = this.sign(rawQueryString);

    // Encoded query string for HTTP transmission
    const encodedQueryString = sortedKeys
      .map((key) => `${key}=${encodeURIComponent(allParams[key])}`)
      .join('&');

    return `${encodedQueryString}&signature=${signature}`;
  }

  /**
   * Obtener precio actual de un par (Público, no requiere API key)
   */
  async getTickerPrice(symbol: string = 'BTC-USDT'): Promise<{ symbol: string; price: number; high24h: number; low24h: number; volume24h: number; change24h: number }> {
    try {
      const response = await this.http.get('/openApi/swap/v2/quote/ticker', {
        params: { symbol }
      });

      if (response.data && response.data.code === 0 && response.data.data) {
        const d = response.data.data;
        return {
          symbol,
          price: parseFloat(d.lastPrice || d.price || '0'),
          high24h: parseFloat(d.highPrice || '0'),
          low24h: parseFloat(d.lowPrice || '0'),
          volume24h: parseFloat(d.volume || '0'),
          change24h: parseFloat(d.priceChangePercent || '0'),
        };
      }
    } catch (error) {
      console.error(`[BingXClient] Error real al consultar ticker ${symbol}:`, error);
      throw new Error(`No se pudo obtener el precio real de ${symbol}. Revisa conexión, credenciales o la API de BingX.`);
    }

    throw new Error(`No se pudo obtener el precio real de ${symbol}.`);
  }

  /**
   * Obtener Velas Japonesas (Klines) para análisis e interfaz visual
   */
  async getKlines(symbol: string = 'BTC-USDT', interval: string = '1m', limit: number = 100): Promise<KlineData[]> {
    try {
      const response = await this.http.get('/openApi/swap/v3/quote/klines', {
        params: { symbol, interval, limit }
      });

      if (response.data && response.data.code === 0 && Array.isArray(response.data.data)) {
        return response.data.data
          .map((item: any) => ({
            time: Math.floor(item.time / 1000),
            open: parseFloat(item.open),
            high: parseFloat(item.high),
            low: parseFloat(item.low),
            close: parseFloat(item.close),
            volume: parseFloat(item.volume || '0'),
          }))
          .sort((a: any, b: any) => a.time - b.time);
      }
    } catch (error: any) {
      console.error(`[BingXClient] Error real al consultar velas ${symbol}:`, error.message);
      throw new Error(`No se pudieron obtener las velas reales de ${symbol}.`);
    }

    throw new Error(`No se pudieron obtener las velas reales de ${symbol}.`);
  }

  /**
   * Consultar Balance de Cuenta (VST / Demo o Real)
   */
  async getAccountBalance(): Promise<AccountBalance> {
    if (!this.hasApiCredentials()) {
      throw new Error('BingX no está configurado para trading real: falta BINGX_API_KEY o BINGX_SECRET_KEY.');
    }

    if (this.balanceCache && Date.now() - this.balanceCache.timestamp < 3500) {
      return this.balanceCache.data;
    }

    try {
      const queryString = this.getSignedParams();
      const response = await this.http.get(`/openApi/swap/v2/user/balance?${queryString}`, {
        headers: { 'X-BX-APIKEY': this.apiKey }
      });

      if (response.data && response.data.code === 0) {
        const balanceData = response.data.data?.balance;
        const result = {
          asset: balanceData?.asset || 'USDT',
          balance: parseFloat(balanceData?.balance || '0'),
          available: parseFloat(balanceData?.availableMargin || '0'),
          equity: parseFloat(balanceData?.equity || '0'),
          shortUid: balanceData?.shortUid,
          isRealAccount: true,
        };
        this.balanceCache = { data: result, timestamp: Date.now() };
        return result;
      } else {
        throw new Error(response.data?.msg || 'Error en BingX API al obtener balance');
      }
    } catch (error: any) {
      if (this.balanceCache) {
        // Silenciar temporalmente el warning de frecuencia 100410 y devolver caché válida
        return this.balanceCache.data;
      }
      console.error('[BingXClient] Error fetching real balance:', error?.response?.data || error.message);
      throw new Error('Fallo de red al obtener el saldo real. Reintentando...');
    }
  }

  /**
   * Obtener Posiciones Activas
   *
   * ⚠️ FIX CRÍTICO: antes, si la petición a BingX fallaba, este método atrapaba el
   * error, lo logueaba, y devolvía `this.mockPositions` (en la práctica `[]`).
   * Eso hacía que el loop principal creyera "no hay posiciones abiertas" cuando en
   * realidad no se pudo verificar nada — con el riesgo real de que el bot abriera
   * una SEGUNDA posición sobre un símbolo que ya tenía una activa en el exchange.
   *
   * Ahora: si hay credenciales configuradas, un fallo de red/API SIEMPRE relanza
   * el error. Es responsabilidad del caller (el loop del bot) decidir qué hacer
   * ante la incertidumbre — y la decisión correcta es "saltar este ciclo", no
   * "asumir que está limpio".
   */
  async getActivePositions(symbol?: string): Promise<PositionData[]> {
    if (!this.hasApiCredentials()) {
      throw new Error('BingX no está configurado para trading real: falta BINGX_API_KEY o BINGX_SECRET_KEY.');
    }

    const params = symbol ? { symbol } : {};
    const queryString = this.getSignedParams(params);
    const response = await this.http.get(`/openApi/swap/v2/user/positions?${queryString}`, {
      headers: { 'X-BX-APIKEY': this.apiKey }
    });

    if (!response.data || response.data.code !== 0) {
      throw new Error(response.data?.msg || 'Error en BingX API al obtener posiciones activas');
    }

    let positions = response.data.data
      .filter((p: any) => parseFloat(p.positionAmt) !== 0)
      .map((p: any) => ({
        symbol: p.symbol,
        positionId: p.positionId,
        positionSide: p.positionSide,
        entryPrice: parseFloat(p.avgPrice || p.entryPrice || '0'),
        markPrice: parseFloat(p.markPrice || '0'),
        amount: parseFloat(p.positionAmt || '0'),
        leverage: parseInt(p.leverage || '1'),
        unrealizedProfit: parseFloat(p.unrealizedProfit || '0'),
        liquidationPrice: parseFloat(p.liquidationPrice || '0'),
        margin: parseFloat(p.isolatedMargin || p.margin || '0') ||
          ((parseFloat(p.positionAmt || '0') * parseFloat(p.avgPrice || p.entryPrice || '0')) / parseInt(p.leverage || '1')),
      }));

    // Fetch open orders to merge TP and SL info.
    // Este bloque secundario sí puede degradar sin abortar: si falla, simplemente
    // no tendremos takeProfit/stopLoss anotados en el objeto, pero las posiciones
    // en sí (lo crítico) ya se obtuvieron con éxito arriba.
    try {
      const ordersQueryStr = symbol ? this.getSignedParams({ symbol }) : this.getSignedParams();
      const ordersRes = await this.http.get(`/openApi/swap/v2/trade/openOrders?${ordersQueryStr}`, {
        headers: { 'X-BX-APIKEY': this.apiKey }
      });
      if (ordersRes.data && ordersRes.data.code === 0 && ordersRes.data.data?.orders) {
        const orders = ordersRes.data.data.orders;
        positions = positions.map((pos: PositionData) => {
          const posOrders = orders.filter((o: any) => o.symbol === pos.symbol && o.positionSide === pos.positionSide);
          const tpOrder = posOrders.find((o: any) => o.type === 'TAKE_PROFIT_MARKET');
          const slOrder = posOrders.find((o: any) => o.type === 'STOP_MARKET');
          return {
            ...pos,
            takeProfit: tpOrder ? parseFloat(tpOrder.stopPrice) : undefined,
            stopLoss: slOrder ? parseFloat(slOrder.stopPrice) : undefined,
          };
        });
      }
    } catch (e) {
      console.error('[BingXClient] Error fetching open orders for positions (no crítico, se continúa sin TP/SL anotado):', e);
    }

    return positions;
  }

  /**
   * Ejecutar o colocar una orden (Spot o Perpetual Swap)
   */
  async placeOrder(order: OrderRequest): Promise<{ success: boolean; orderId?: string; message: string }> {
    if (!order.quantity || order.quantity <= 0) {
      return { success: false, message: 'La cantidad de la orden debe ser mayor que cero.' };
    }

    const leverage = order.leverage || 10;
    const posSide = order.positionSide || (order.side === 'BUY' ? 'LONG' : 'SHORT');

    if (!this.hasApiCredentials()) {
      throw new Error('BingX no está configurado para trading real: falta BINGX_API_KEY o BINGX_SECRET_KEY.');
    }

    try {
      // FIX (Bug B): BingX requiere una llamada separada para fijar el apalancamiento
      // antes de la orden. Si el usuario lo cambió manualmente en la UI de BingX,
      // la orden se ejecutaría con ese apalancamiento incorrecto — el riesgo real
      // sería mayor al calculado por el RiskCalculator. Se fuerza aquí el correcto.
      try {
        const leverageParams = {
          symbol: order.symbol,
          side: order.positionSide || (order.side === 'BUY' ? 'LONG' : 'SHORT'),
          leverage,
        };
        const leverageQuery = this.getSignedParams(leverageParams);
        await this.http.post(`/openApi/swap/v2/trade/leverage?${leverageQuery}`, null, {
          headers: { 'X-BX-APIKEY': this.apiKey }
        });
      } catch (leverageErr: any) {
        // Si falla el cambio de apalancamiento, NO abortar — puede que ya esté correcto
        // o que el exchange lo rechace por posición ya abierta. Loguear y continuar.
        console.warn(`[BingXClient] ⚠️ No se pudo fijar leverage en ${order.symbol}: ${leverageErr?.response?.data?.msg || leverageErr.message}. Se continúa con el leverage actual.`);
      }

      const params = {
        symbol: order.symbol,
        side: order.side,
        positionSide: posSide,
        type: order.type,
        quantity: order.quantity,
        ...(order.price ? { price: order.price } : {}),
        ...(order.stopLoss ? { stopLoss: JSON.stringify({ type: 'STOP_MARKET', stopPrice: order.stopLoss }) } : {}),
        ...(order.takeProfit ? { takeProfit: JSON.stringify({ type: 'TAKE_PROFIT_MARKET', stopPrice: order.takeProfit }) } : {}),
        ...(order.reduceOnly ? { reduceOnly: true } : {}),
      };

      const queryString = this.getSignedParams(params);
      const response = await this.http.post(`/openApi/swap/v2/trade/order?${queryString}`, null, {
        headers: { 'X-BX-APIKEY': this.apiKey }
      });

      if (response.data && response.data.code === 0) {
        return {
          success: true,
          orderId: response.data.data?.order?.orderId,
          message: `Orden enviada a BingX correctamente (${order.symbol})`,
        };
      } else {
        return {
          success: false,
          message: response.data?.msg || 'Error al procesar orden en BingX',
        };
      }
    } catch (error: any) {
      const msg = error?.response?.data?.msg || error.message;
      return { success: false, message: `Error BingX API: ${msg}` };
    }
  }

  /**
   * Cerrar Posición Activa (Total o Parcial)
   */
  async closePosition(symbol: string, positionSide: 'LONG' | 'SHORT', quantity?: number): Promise<{ success: boolean; message: string }> {
    if (!this.hasApiCredentials()) {
      throw new Error('BingX no está configurado para trading real: falta BINGX_API_KEY o BINGX_SECRET_KEY.');
    }

    // Para BingX API real: cerrar enviando una orden inversa
    const side = positionSide === 'LONG' ? 'SELL' : 'BUY';
    const active = (await this.getActivePositions(symbol)).find(p => p.positionSide === positionSide);

    if (!active) {
      return { success: false, message: 'No se encontró la posición activa en BingX' };
    }

    const closingQty = quantity !== undefined ? quantity : active.amount;

    return this.placeOrder({
      symbol,
      side,
      positionSide,
      type: 'MARKET',
      quantity: closingQty,
      // reduceOnly no es soportado en Hedge Mode de BingX
    });
  }

  /**
   * Modificar Stop Loss de una posición activa (Breakeven)
   * Cancela las órdenes pendientes de SL/TP y coloca un nuevo SL al precio deseado
   */
  async modifyStopLoss(symbol: string, positionSide: 'LONG' | 'SHORT', newStopLossPrice: number): Promise<{ success: boolean; message: string }> {
    if (!this.apiKey || !this.secretKey) {
      return { success: true, message: `[DEMO] Stop Loss modificado a $${newStopLossPrice}` };
    }

    try {
      // 1. Obtener órdenes pendientes de la posición para cancelar el SL actual
      const pendingQuery = this.getSignedParams({ symbol });
      const pendingRes = await this.http.get(`/openApi/swap/v2/trade/openOrders?${pendingQuery}`, {
        headers: { 'X-BX-APIKEY': this.apiKey }
      });

      if (pendingRes.data && pendingRes.data.code === 0 && Array.isArray(pendingRes.data.data?.orders)) {
        for (const order of pendingRes.data.data.orders) {
          // Cancelar órdenes STOP_MARKET (Stop Loss) de la misma posición
          if (order.type === 'STOP_MARKET' && order.positionSide === positionSide) {
            const cancelQuery = this.getSignedParams({ symbol, orderId: order.orderId });
            await this.http.delete(`/openApi/swap/v2/trade/order?${cancelQuery}`, {
              headers: { 'X-BX-APIKEY': this.apiKey }
            });
            console.log(`[BingXClient] Cancelada orden SL antigua (orderId: ${order.orderId})`);
          }
        }
      }

      // 2. Colocar nuevo Stop Loss al precio de Breakeven
      const side = positionSide === 'LONG' ? 'SELL' : 'BUY';
      const active = (await this.getActivePositions(symbol)).find(p => p.positionSide === positionSide);

      if (!active) {
        return { success: false, message: `Posición ${positionSide} en ${symbol} no encontrada` };
      }

      const newSLParams = {
        symbol,
        side,
        positionSide,
        type: 'STOP_MARKET',
        quantity: active.amount,
        stopPrice: newStopLossPrice,
      };

      const slQuery = this.getSignedParams(newSLParams);
      const slRes = await this.http.post(`/openApi/swap/v2/trade/order?${slQuery}`, null, {
        headers: { 'X-BX-APIKEY': this.apiKey }
      });

      if (slRes.data && slRes.data.code === 0) {
        return { success: true, message: `Stop Loss modificado a $${newStopLossPrice} (Breakeven) en ${symbol}` };
      } else {
        return { success: false, message: slRes.data?.msg || 'Error al modificar SL en BingX' };
      }
    } catch (error: any) {
      return { success: false, message: `Error API BingX modifyStopLoss: ${error?.response?.data?.msg || error.message}` };
    }
  }

  /**
   * Cancelar todas las órdenes pendientes de un símbolo (útil para limpiar SL/TP huérfanos)
   */
  async cancelAllPendingOrders(symbol: string): Promise<{ success: boolean; message: string }> {
    if (!this.apiKey || !this.secretKey) {
      return { success: true, message: `[DEMO] Órdenes pendientes canceladas para ${symbol}` };
    }

    try {
      const queryString = this.getSignedParams({ symbol });
      const response = await this.http.delete(`/openApi/swap/v2/trade/allOpenOrders?${queryString}`, {
        headers: { 'X-BX-APIKEY': this.apiKey }
      });

      if (response.data && response.data.code === 0) {
        return { success: true, message: `Todas las órdenes pendientes canceladas en ${symbol}` };
      } else {
        return { success: false, message: response.data?.msg || 'Error al cancelar órdenes pendientes en BingX' };
      }
    } catch (error: any) {
      return { success: false, message: `Error API BingX cancelAllPendingOrders: ${error?.response?.data?.msg || error.message}` };
    }
  }
  private cachedTradeHistory: any[] = [];
  private lastTradeHistoryFetchTime = 0;

  /**
   * Obtener historial de operaciones cerradas (órdenes llenadas con reduceOnly o que representan un cierre).
   * Se consultan 7 días en 1 sola petición y se cachea por 15s para no bloquear el exchange por rate-limit.
   */
  async getTradeHistory(limit: number = 20, forceRefresh: boolean = false): Promise<any[]> {
    if (!this.apiKey || !this.secretKey) {
      return [];
    }

    const now = Date.now();
    if (!forceRefresh && (now - this.lastTradeHistoryFetchTime < 15000) && this.cachedTradeHistory.length > 0) {
      return this.cachedTradeHistory.slice(0, limit);
    }

    try {
      const endTime = now;
      const startTime = endTime - (7 * 24 * 60 * 60 * 1000); // 7 días en 1 sola petición
      const queryString = this.getSignedParams({
        limit: 500, // Máximo permitido por petición en BingX
        startTime: startTime,
        endTime: endTime
      });

      const response = await this.http.get(`/openApi/swap/v2/trade/allOrders?${queryString}`, {
        headers: { 'X-BX-APIKEY': this.apiKey }
      });

      if (response.data && response.data.code === 0 && response.data.data?.orders) {
        const orders = response.data.data.orders;

        // Filtrar órdenes cerradas reales:
        // BingX puede devolver reduceOnly=false en cierres por SL/TP (es un bug de su API).
        // Filtramos por: estado FILLED + (reduceOnly=true OR tipo es cierre OR tiene profit no nulo)
        const closedOrders = orders.filter((o: any) =>
          o.status === 'FILLED' && (
            o.reduceOnly === true ||
            o.type === 'STOP_MARKET' ||
            o.type === 'TAKE_PROFIT_MARKET' ||
            (parseFloat(o.profit || '0') !== 0) // tiene profit registrado = es cierre real
          )
        );

        // Ordenar por tiempo de forma descendente (más recientes primero)
        closedOrders.sort((a: any, b: any) => parseInt(b.time || '0', 10) - parseInt(a.time || '0', 10));

        this.cachedTradeHistory = closedOrders.map((o: any) => ({
          symbol: o.symbol,
          positionSide: o.positionSide, // LONG o SHORT
          side: o.side, // BUY o SELL
          price: parseFloat(o.avgPrice || '0'),
          quantity: parseFloat(o.executedQty || '0'),
          profit: parseFloat(o.profit || '0'),
          commission: parseFloat(o.commission || '0'),
          netProfit: parseFloat(o.profit || '0') + parseFloat(o.commission || '0'),
          time: parseInt(o.time || '0', 10)
        }));

        this.lastTradeHistoryFetchTime = now;
      }

      return this.cachedTradeHistory.slice(0, limit);
    } catch (error: any) {
      console.error('[BingXClient] Error fetching trade history:', error?.response?.data?.msg || error.message);
      // Si el exchange da error temporal (ej. rate limit), devolver la caché anterior para que nunca quede vacío
      return this.cachedTradeHistory.slice(0, limit);
    }
  }

  /**
   * Obtiene la ganancia/pérdida realizada en el día actual (operaciones cerradas hoy)
   * Utiliza el historial cacheado para máxima velocidad y eficiencia de API.
   */
  async getTodayRealizedPnL(forceRefresh: boolean = false): Promise<{
    closedOrdersCount: number;
    realizedPnL: number;
    realizedNetPnL: number;
  }> {
    try {
      const orders = await this.getTradeHistory(100, forceRefresh);
      const startOfDay = new Date().setHours(0, 0, 0, 0);
      const todayOrders = orders.filter((o: any) => o.time >= startOfDay);

      let realizedPnL = 0;
      let realizedNetPnL = 0;
      for (const o of todayOrders) {
        const profit = o.profit || 0;
        const netProfit = o.netProfit || 0;
        realizedPnL += profit;
        realizedNetPnL += netProfit;
      }

      return {
        closedOrdersCount: todayOrders.length,
        realizedPnL,
        realizedNetPnL
      };
    } catch (error: any) {
      console.error('[BingXClient] Error fetching today realized PnL:', error.message || error);
      return { closedOrdersCount: 0, realizedPnL: 0, realizedNetPnL: 0 };
    }
  }

  public async getExchangeInfo(): Promise<any[]> {
    try {
      // El endpoint oficial de BingX para futuros perpetuos es:
      const response = await this.http.get('/openApi/swap/v2/quote/contracts');

      // BingX devuelve el éxito con code === 0
      if (response.data && response.data.code === 0) {
        return response.data.data;
      }

      console.warn('[BingX] Respuesta inesperada en getExchangeInfo:', response.data);
      return [];
    } catch (error) {
      console.error('[BingX] Error obteniendo exchange info:', error);
      return []; // Devolvemos un array vacío para que el bot no crashee y use el fallback
    }
  }
}

export const bingxClient = new BingXClient();