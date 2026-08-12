import { KlineData } from '../bingx/bingx-client';

export interface IndicatorAnalysis {
  symbol: string;
  currentPrice: number;
  rsi: number;
  ema20: number;
  ema50: number;
  ema200: number;
  macd: {
    macdLine: number;
    signalLine: number;
    histogram: number;
  };
  bollinger: {
    upper: number;
    middle: number;
    lower: number;
  };
  atr: number;
  volumeSMA?: number;
  adx?: number;
  signal: 'STRONG_BUY' | 'BUY' | 'NEUTRAL' | 'SELL' | 'STRONG_SELL';
  summary: string;
}

export class TechnicalAnalysis {
  /**
   * Calcular Media Móvil Exponencial (EMA)
   */
  static calculateEMA(prices: number[], period: number): number {
    if (prices.length < period) return prices[prices.length - 1] || 0;
    const k = 2 / (period + 1);
    let ema = prices.slice(0, period).reduce((a, b) => a + b, 0) / period;
    for (let i = period; i < prices.length; i++) {
      ema = prices[i] * k + ema * (1 - k);
    }
    return parseFloat(ema.toFixed(2));
  }

  /**
   * Calcular RSI (Relative Strength Index) — Wilder's Smoothing Method
   */
  static calculateRSI(prices: number[], period: number = 14): number {
    if (prices.length <= period) return 50;

    let gains = 0;
    let losses = 0;

    for (let i = 1; i <= period; i++) {
      const change = prices[i] - prices[i - 1];
      if (change >= 0) gains += change;
      else losses -= change;
    }

    let avgGain = gains / period;
    let avgLoss = losses / period;

    for (let i = period + 1; i < prices.length; i++) {
      const change = prices[i] - prices[i - 1];
      if (change >= 0) {
        avgGain = (avgGain * (period - 1) + change) / period;
        avgLoss = (avgLoss * (period - 1)) / period;
      } else {
        avgGain = (avgGain * (period - 1)) / period;
        avgLoss = (avgLoss * (period - 1) - change) / period;
      }
    }

    if (avgLoss === 0) return 100;
    const rs = avgGain / avgLoss;
    const rsi = 100 - 100 / (1 + rs);
    return parseFloat(rsi.toFixed(2));
  }

  /**
   * Calcular serie completa de EMA (uso interno para MACD y ADX)
   */
  private static calculateEMASeries(values: number[], period: number): number[] {
    if (values.length < period) return values;
    const k = 2 / (period + 1);
    const result: number[] = [];
    let ema = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
    for (let i = 0; i < period; i++) result.push(ema);
    for (let i = period; i < values.length; i++) {
      ema = values[i] * k + ema * (1 - k);
      result.push(ema);
    }
    return result;
  }

  /**
   * Calcular MACD Real (EMA12 - EMA26, Signal EMA9)
   */
  static calculateMACD(prices: number[], fast: number = 12, slow: number = 26, signalPeriod: number = 9) {
    if (prices.length < slow + signalPeriod) {
      return { macdLine: 0, signalLine: 0, histogram: 0 };
    }

    const kFast = 2 / (fast + 1);
    const kSlow = 2 / (slow + 1);

    let emaFastVal = prices.slice(0, fast).reduce((a, b) => a + b, 0) / fast;
    let emaSlowVal = prices.slice(0, slow).reduce((a, b) => a + b, 0) / slow;

    const macdSeries: number[] = [];

    for (let i = 0; i < prices.length; i++) {
      if (i >= fast) {
        emaFastVal = prices[i] * kFast + emaFastVal * (1 - kFast);
      }
      if (i >= slow) {
        emaSlowVal = prices[i] * kSlow + emaSlowVal * (1 - kSlow);
        macdSeries.push(emaFastVal - emaSlowVal);
      }
    }

    if (macdSeries.length < signalPeriod) {
      const last = macdSeries[macdSeries.length - 1] || 0;
      return { macdLine: parseFloat(last.toFixed(4)), signalLine: 0, histogram: parseFloat(last.toFixed(4)) };
    }

    const signalSeries = this.calculateEMASeries(macdSeries, signalPeriod);

    const macdLine = macdSeries[macdSeries.length - 1];
    const signalLine = signalSeries[signalSeries.length - 1];
    const histogram = macdLine - signalLine;

    return {
      macdLine: parseFloat(macdLine.toFixed(4)),
      signalLine: parseFloat(signalLine.toFixed(4)),
      histogram: parseFloat(histogram.toFixed(4)),
    };
  }

  /**
   * Calcular Bandas de Bollinger
   */
  static calculateBollinger(prices: number[], period: number = 20, multiplier: number = 2) {
    if (prices.length < period) {
      const p = prices[prices.length - 1] || 0;
      return { upper: p * 1.02, middle: p, lower: p * 0.98 };
    }

    const slice = prices.slice(-period);
    const middle = slice.reduce((a, b) => a + b, 0) / period;
    const variance = slice.reduce((sum, p) => sum + Math.pow(p - middle, 2), 0) / period;
    const stdDev = Math.sqrt(variance);

    return {
      upper: parseFloat((middle + multiplier * stdDev).toFixed(2)),
      middle: parseFloat(middle.toFixed(2)),
      lower: parseFloat((middle - multiplier * stdDev).toFixed(2)),
    };
  }

  /**
   * Calcular ATR (Average True Range) — Wilder's Method
   */
  static calculateATR(klines: KlineData[], period: number = 14): number {
    if (klines.length < period + 1) return 0;

    const trs: number[] = [];
    for (let i = 1; i < klines.length; i++) {
      const high = klines[i].high;
      const low = klines[i].low;
      const prevClose = klines[i - 1].close;

      const tr = Math.max(
        high - low,
        Math.abs(high - prevClose),
        Math.abs(low - prevClose)
      );
      trs.push(tr);
    }

    // Wilder's smoothing (más preciso que simple average)
    let atr = trs.slice(0, period).reduce((a, b) => a + b, 0) / period;
    for (let i = period; i < trs.length; i++) {
      atr = (atr * (period - 1) + trs[i]) / period;
    }

    return parseFloat(atr.toFixed(2));
  }

  /**
   * Calcular ADX (Average Directional Index) — Fuerza de la tendencia
   * ADX > 25: tendencia fuerte. ADX > 40: tendencia muy fuerte.
   */
  static calculateADX(klines: KlineData[], period: number = 14): number {
    if (klines.length < period * 2) return 0;

    const plusDM: number[] = [];
    const minusDM: number[] = [];
    const trs: number[] = [];

    for (let i = 1; i < klines.length; i++) {
      const upMove = klines[i].high - klines[i - 1].high;
      const downMove = klines[i - 1].low - klines[i].low;

      plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
      minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0);

      const tr = Math.max(
        klines[i].high - klines[i].low,
        Math.abs(klines[i].high - klines[i - 1].close),
        Math.abs(klines[i].low - klines[i - 1].close)
      );
      trs.push(tr);
    }

    // Wilder's smoothed values
    let smoothTR = trs.slice(0, period).reduce((a, b) => a + b, 0);
    let smoothPlusDM = plusDM.slice(0, period).reduce((a, b) => a + b, 0);
    let smoothMinusDM = minusDM.slice(0, period).reduce((a, b) => a + b, 0);

    const dxValues: number[] = [];

    for (let i = period; i < trs.length; i++) {
      smoothTR = smoothTR - smoothTR / period + trs[i];
      smoothPlusDM = smoothPlusDM - smoothPlusDM / period + plusDM[i];
      smoothMinusDM = smoothMinusDM - smoothMinusDM / period + minusDM[i];

      const plusDI = (smoothPlusDM / smoothTR) * 100;
      const minusDI = (smoothMinusDM / smoothTR) * 100;
      const diSum = plusDI + minusDI;

      if (diSum > 0) {
        dxValues.push((Math.abs(plusDI - minusDI) / diSum) * 100);
      }
    }

    if (dxValues.length < period) return 0;

    // ADX = Wilder's smoothing of DX
    let adx = dxValues.slice(0, period).reduce((a, b) => a + b, 0) / period;
    for (let i = period; i < dxValues.length; i++) {
      adx = (adx * (period - 1) + dxValues[i]) / period;
    }

    return parseFloat(adx.toFixed(2));
  }

  /**
   * Calcular Media Móvil Simple (SMA)
   */
  static calculateSMA(values: number[], period: number): number {
    if (values.length < period) return values.length > 0 ? values[values.length - 1] : 0;
    const slice = values.slice(-period);
    const sum = slice.reduce((a, b) => a + b, 0);
    return parseFloat((sum / period).toFixed(2));
  }

  /**
   * Detectar si el MACD cruzó recientemente (últimas N velas) — Señal de momentum
   */
  private static detectMACDCrossover(prices: number[], lookback: number = 3): 'BULLISH' | 'BEARISH' | 'NONE' {
    if (prices.length < 30 + lookback) return 'NONE';

    // Calcular MACD para las últimas N+1 barras
    const histograms: number[] = [];
    for (let offset = lookback; offset >= 0; offset--) {
      const slice = prices.slice(0, prices.length - offset);
      const m = this.calculateMACD(slice);
      histograms.push(m.histogram);
    }

    // Buscar cruce en las últimas N barras
    for (let i = 1; i < histograms.length; i++) {
      if (histograms[i - 1] < 0 && histograms[i] > 0) return 'BULLISH';
      if (histograms[i - 1] > 0 && histograms[i] < 0) return 'BEARISH';
    }

    return 'NONE';
  }

  /**
   * Análisis técnico completo — Sistema de puntuación profesional
   * 
   * FILOSOFÍA: Operar solo con confluencia clara de múltiples indicadores
   * en la dirección de la tendencia macro. RSI en zona de momentum (no extremo).
   */
  static analyze(symbol: string, klines: KlineData[]): IndicatorAnalysis {
    const closes = klines.map((k) => k.close);
    const volumes = klines.map((k) => k.volume);
    const currentPrice = closes[closes.length - 1] || 0;
    const currentVolume = volumes[volumes.length - 1] || 0;

    const rsi = this.calculateRSI(closes, 14);
    const ema20 = this.calculateEMA(closes, 20);
    const ema50 = this.calculateEMA(closes, 50);
    const ema200 = this.calculateEMA(closes, Math.min(200, closes.length - 1));
    const macd = this.calculateMACD(closes);
    const bollinger = this.calculateBollinger(closes);
    const atr = this.calculateATR(klines);
    const adx = this.calculateADX(klines);
    const volumeSMA = this.calculateSMA(volumes, 20);

    // ─────────────────────────────────────────────────────────────────────────
    // FILTRO 1: VOLATILIDAD MÍNIMA (Anti-Chop)
    // Solo operar si hay suficiente volatilidad real para justificar el riesgo.
    // En fin de semana la barra es más alta por menor liquidez institucional.
    // ─────────────────────────────────────────────────────────────────────────
    const isWeekend = [0, 6].includes(new Date().getUTCDay());
    const minAtrPercent = isWeekend ? 0.15 : 0.05; // Reducido para no filtrar demasiado
    const atrPercent = currentPrice > 0 ? (atr / currentPrice) * 100 : 0;

    if (atrPercent > 0 && atrPercent < minAtrPercent) {
      return {
        symbol, currentPrice, rsi, ema20, ema50, ema200, macd, bollinger, atr, volumeSMA, adx,
        signal: 'NEUTRAL',
        summary: `Volatilidad insuficiente (ATR ${atrPercent.toFixed(2)}% < mín ${minAtrPercent}%${isWeekend ? ' - Fin de Semana' : ''}). Mercado en rango muerto.`
      };
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FILTRO 2: ADX — Confirmar que hay tendencia real (no chop lateral)
    // ADX < 18: mercado en rango/lateral → NEUTRAL obligatorio
    // ─────────────────────────────────────────────────────────────────────────
    const MIN_ADX = isWeekend ? 22 : 20;
    if (adx > 0 && adx < MIN_ADX) {
      return {
        symbol, currentPrice, rsi, ema20, ema50, ema200, macd, bollinger, atr, volumeSMA, adx,
        signal: 'NEUTRAL',
        summary: `ADX débil (${adx} < mín ${MIN_ADX}${isWeekend ? ' en Fin de Semana' : ''}) — Mercado sin tendencia definida (chop). Esperando breakout.`
      };
    }

    // ─────────────────────────────────────────────────────────────────────────
    // DETERMINACIÓN DEL RÉGIMEN DE TENDENCIA
    // ─────────────────────────────────────────────────────────────────────────
    const macroEma = ema200 > 0 ? ema200 : ema50;
    const isMacroBullish = currentPrice >= macroEma;
    const isMacroBearish = currentPrice < macroEma;

    // Tendencia de corto plazo: EMA20 por encima de EMA50
    const isShortTermBullish = currentPrice > ema20 && ema20 > ema50;
    const isShortTermBearish = currentPrice < ema20 && ema20 < ema50;

    // ─────────────────────────────────────────────────────────────────────────
    // SISTEMA DE PUNTUACIÓN (0–8 puntos posibles)
    // ─────────────────────────────────────────────────────────────────────────
    let buyScore = 0;
    let sellScore = 0;

    // ── RSI: Zona de momentum (no extremo, sino momentum saludable) ──
    // FIX: unificada la lógica para evitar asimetrías donde el RSI 66 permitía entrada
    // pero sumaba tan pocos puntos que nunca llegaba al umbral de confluencia.
    if (rsi <= 35) {
      // Sobreventa profunda — rebote potente si hay tendencia alcista macro
      if (isMacroBullish) buyScore += 2.0;
    } else if (rsi > 35 && rsi <= 50) {
      // Zona de acumulación alcista
      if (isMacroBullish) buyScore += 1.5;
    } else if (rsi > 50 && rsi < 68) {
      // Momentum alcista en marcha (hasta 67.99 — el 68 exacto es umbral SELL)
      if (isMacroBullish && isShortTermBullish) buyScore += 2.0;
      else if (isMacroBullish) buyScore += 1.5;
    }

    // RSI SELL — zonas mutuamente excluyentes respecto a BUY
    // (no se puntúa SELL en las mismas zonas que puntuamos BUY para evitar señales ambiguas)
    if (rsi >= 68) {
      // Sobrecompra profunda — corrección potente si hay tendencia bajista macro
      if (isMacroBearish) sellScore += 2.0;
    } else if (rsi < 68 && rsi >= 50) {
      // Zona de distribución bajista
      if (isMacroBearish) sellScore += 1.5;
    } else if (rsi < 50 && rsi >= 32) {
      // Momentum bajista en marcha
      if (isMacroBearish && isShortTermBearish) sellScore += 2.0;
      else if (isMacroBearish) sellScore += 1.5;
    }

    // ── Estructura de EMAs (alineación tendencial) ──
    if (isShortTermBullish && isMacroBullish) buyScore += 1.5;
    else if (isShortTermBearish && isMacroBearish) sellScore += 1.5;
    else if (isMacroBullish && currentPrice > ema50) buyScore += 0.5;
    else if (isMacroBearish && currentPrice < ema50) sellScore += 0.5;

    // ── MACD — Dirección y cruce reciente ──
    const macdCross = this.detectMACDCrossover(closes, 4);
    if (macd.histogram > 0) {
      buyScore += isMacroBullish ? 1.5 : 0.5;
      if (macdCross === 'BULLISH') buyScore += 1.0; // Cruce alcista reciente: bonus
    } else if (macd.histogram < 0) {
      sellScore += isMacroBearish ? 1.5 : 0.5;
      if (macdCross === 'BEARISH') sellScore += 1.0; // Cruce bajista reciente: bonus
    }

    // ── Bollinger Bands — Contexto de precio ──
    if (currentPrice <= bollinger.lower && isMacroBullish) buyScore += 1.0;  // Dip buying en tendencia alcista
    if (currentPrice >= bollinger.upper && isMacroBearish) sellScore += 1.0; // Short en tendencia bajista

    // ── Volumen — Confirmación institucional ──
    const isHighVolume = currentVolume > volumeSMA * 1.15;
    if (isHighVolume) {
      if (isShortTermBullish && currentPrice > ema20) buyScore += 0.5;
      if (isShortTermBearish && currentPrice < ema20) sellScore += 0.5;
    }

    // ── ADX — Bonus por tendencia fuerte ──
    if (adx >= 30) {
      if (isMacroBullish && buyScore > sellScore) buyScore += 0.5;
      if (isMacroBearish && sellScore > buyScore) sellScore += 0.5;
    }

    const canBuyRsi = rsi >= 30 && rsi < 68;   // Estrictamente < 68 para no solapar con zona SELL
    const canSellRsi = rsi >= 32 && rsi <= 70;

    // ─────────────────────────────────────────────────────────────────────────
    // VETO ANTI-TREN (Solo cuando hay tendencia MUY fuerte confirmada por ADX)
    // ─────────────────────────────────────────────────────────────────────────
    // FIX: antes el veto se aplicaba siempre que EMA20 > EMA50, lo que bloqueaba
    // SHORTs durante semanas enteras en bull markets y perdía los mejores puntos
    // de entrada bajista. Ahora solo se aplica cuando ADX > 30 (tendencia activa
    // y fuerte), que es cuando realmente el mercado tiene momentum unidireccional.
    if (adx >= 30 && isShortTermBullish && currentPrice > ema20) {
      sellScore = 0;
    }
    if (adx >= 30 && isShortTermBearish && currentPrice < ema20) {
      buyScore = 0;
    }

    let signal: 'STRONG_BUY' | 'BUY' | 'NEUTRAL' | 'SELL' | 'STRONG_SELL' = 'NEUTRAL';
    let summary = 'Mercado sin confluencia suficiente para operar.';

    if (buyScore >= 6.0 && isMacroBullish && canBuyRsi) {
      signal = 'STRONG_BUY';
      summary = `🚀 CONFLUENCIA ALCISTA FUERTE (score ${buyScore.toFixed(1)}, RSI ${rsi}, ADX ${adx}): EMAs alineadas, MACD ${macd.histogram > 0 ? 'positivo' : ''}${macdCross === 'BULLISH' ? ' con cruce reciente' : ''}${isHighVolume ? ', volumen institucional' : ''}.`;
    } else if (buyScore >= 4.5 && isMacroBullish && canBuyRsi && (macd.histogram > 0 || macdCross === 'BULLISH')) {
      signal = 'BUY';
      summary = `📈 Señal ALCISTA confirmada (score ${buyScore.toFixed(1)}, RSI ${rsi}): Precio sobre EMA macro $${macroEma.toFixed(0)}, MACD ${macd.histogram > 0 ? 'positivo' : 'cruzando al alza'}.`;
    } else if (sellScore >= 6.0 && isMacroBearish && canSellRsi) {
      signal = 'STRONG_SELL';
      summary = `💥 CONFLUENCIA BAJISTA FUERTE (score ${sellScore.toFixed(1)}, RSI ${rsi}, ADX ${adx}): EMAs alineadas, MACD ${macd.histogram < 0 ? 'negativo' : ''}${macdCross === 'BEARISH' ? ' con cruce reciente' : ''}${isHighVolume ? ', volumen institucional' : ''}.`;
    } else if (sellScore >= 4.5 && isMacroBearish && canSellRsi && (macd.histogram < 0 || macdCross === 'BEARISH')) {
      signal = 'SELL';
      summary = `📉 Señal BAJISTA confirmada (score ${sellScore.toFixed(1)}, RSI ${rsi}): Precio bajo EMA macro $${macroEma.toFixed(0)}, MACD ${macd.histogram < 0 ? 'negativo' : 'cruzando a la baja'}.`;
    } else {
      signal = 'NEUTRAL';
      if (buyScore >= 4.5 && !canBuyRsi) {
        summary = `⏸ Señal alcista bloqueada por RSI extendido (${rsi} fuera de rango 30-68). Esperar corrección.`;
      } else if (sellScore >= 4.5 && !canSellRsi) {
        summary = `⏸ Señal bajista bloqueada por RSI en suelo (${rsi} fuera de rango 32-70). Esperar rebote.`;
      } else if (adx < MIN_ADX) {
        summary = `⏸ ADX ${adx} < ${MIN_ADX} — Tendencia débil. Esperando dirección clara.`;
      }
    }

    return {
      symbol,
      currentPrice,
      rsi,
      ema20,
      ema50,
      ema200,
      macd,
      bollinger,
      atr,
      volumeSMA,
      adx,
      signal,
      summary,
    };
  }
}
