import axios from 'axios';

export interface AiValidationRequest {
  symbol: string;
  signal: 'BUY' | 'SELL';
  currentPrice: number;
  rsi: number;
  ema20: number;
  ema50: number;
  ema200: number;
  macd: { macdLine: number; signalLine: number; histogram: number };
  atrPercent: number;
  adx?: number;
  isWeekend: boolean;
  summary: string;
}

export interface AiValidationResponse {
  approved: boolean;
  confidence: number; // 0 - 100
  reason: string;
}

/**
 * AiRiskManager — Filtro de segundo nivel orientado a detectar lo que el código NO puede:
 *  1. Mercados en chop lateral disfrazado de tendencia (baja volatilidad + ADX engañoso)
 *  2. Horas de baja liquidez institucional (00:00–06:00 UTC)
 *  3. Condiciones de sobre-extensión RSI que el código permite pero la IA penaliza
 *
 * NOTA: NO duplica filtros del código (EMA200, score). Se centra en contexto de mercado.
 *
 * ⚠️ FIX: el prompt le pide a la IA "aprueba solo con confianza > 75%", pero el
 * código original en el caller (auto-bot.ts) sólo exigía `confidence < 70` para
 * vetar. Se expone aquí MIN_CONFIDENCE_TO_APPROVE como fuente única de verdad,
 * para que el caller la importe en vez de tener el número hardcodeado y
 * desalineado del prompt.
 */
export class AiRiskManager {
  private static API_URL = 'https://api.openai.com/v1/chat/completions';

  // Debe coincidir con el umbral indicado en el system prompt ("confianza > 75%").
  static readonly MIN_CONFIDENCE_TO_APPROVE = 75;

  static async validateTrade(request: AiValidationRequest): Promise<AiValidationResponse> {
    const apiKey = process.env.OPENAI_API_KEY?.trim();

    // Si la API key no está configurada, permitimos operar sin bloquear el bot
    if (!apiKey) {
      console.log(`[AiRiskManager] ℹ️ OPENAI_API_KEY no configurada. Bypass activado (Aprobado).`);
      return { approved: true, confidence: 80, reason: 'Bypass: OPENAI_API_KEY no configurada.' };
    }

    // Detectar hora UTC actual para contexto de liquidez
    const utcHour = new Date().getUTCHours();
    const isLowLiquidityHour = utcHour >= 0 && utcHour < 6; // 00:00–06:00 UTC = baja liquidez

    try {
      console.log(`[AiRiskManager] 🤖 Consultando GPT-4o-mini: ${request.signal} en ${request.symbol} (RSI ${request.rsi.toFixed(1)}, ADX ${request.adx?.toFixed(0) ?? 'N/A'})...`);

      const systemPrompt = `Eres el Chief Risk Officer (CRO) de un fondo cuantitativo de criptomonedas. Tu rol es EXCLUSIVAMENTE detectar condiciones de mercado peligrosas que los indicadores técnicos no capturan bien:

1. CHOP LATERAL DISFRAZADO: Mercados que parecen tener tendencia pero en realidad están en rango (movimientos erráticos sin dirección, whipsaws).
2. HORAS DE BAJA LIQUIDEZ: Entre las 00:00 y 06:00 UTC el volumen institucional es mínimo y las falsas rupturas son frecuentes.
3. SOBRE-EXTENSIÓN PELIGROSA: RSI > 72 para BUY o RSI < 28 para SELL en timeframe corto son extremos peligrosos.
4. VOLATILIDAD EXCESIVA: ATR% > 3% indica volatilidad extrema donde los Stop Loss pueden saltarse.

IMPORTANTE: Debes ser riguroso y conservador. Tu trabajo es proteger el capital y evitar entrar en operaciones mediocres, en contratendencia, o con riesgo de retroceso (whipsaw).

Responde SIEMPRE en JSON exacto:
{ "approved": boolean, "confidence": number (0-100), "reason": "Justificación máx 20 palabras en español" }`;

      const userPrompt = `Evalúa esta señal para ${request.symbol}:
- Tipo: ${request.signal}
- Precio: $${request.currentPrice}
- RSI (14): ${request.rsi.toFixed(2)}
- ADX: ${request.adx?.toFixed(1) ?? 'No disponible'}
- MACD Histograma: ${request.macd.histogram.toFixed(4)}
- ATR (% del precio): ${request.atrPercent.toFixed(2)}%
- Hora UTC actual: ${utcHour}:00 (${isLowLiquidityHour ? '⚠️ BAJA LIQUIDEZ' : 'liquidez normal'})
- Fin de semana UTC: ${request.isWeekend ? 'SÍ' : 'NO'}
- Resumen técnico del sistema: "${request.summary}"

Criterios de VETO ESTRICTOS (evalúa matemáticamente sin inventar datos):
1. Si ATR% < 0.10% → chop muerto sin volatilidad, VETA.
2. Si ADX < 20 → mercado lateral o sin fuerza institucional, VETA. (Si ADX >= 20, NO puedes aplicar este veto).
3. Si señal BUY con RSI > 74 → sobre-compra extrema y agotamiento de tendencia, VETA.
4. Si señal SELL con RSI < 26 → sobre-venta extrema y agotamiento de tendencia, VETA.
5. Si hora UTC entre 00-06 Y el ADX es menor a 22 → baja liquidez institucional en madrugada, VETA.
6. Si ATR% > 3.5% → volatilidad extrema, slippage peligroso, VETA.
7. Si notas cualquier incoherencia o falta de confluencia en el resumen técnico, VETA.

REGLA DE ORO: Si el ADX es >= 20 y el RSI está en zona saludable (entre 26 y 74), LA TENDENCIA ES VÁLIDA y debes APROBAR (approved: true) con confianza > 75% sin alucinar problemas inexistentes.`;

      const response = await axios.post(
        this.API_URL,
        {
          model: 'gpt-4o-mini',
          temperature: 0.1,
          response_format: { type: 'json_object' },
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: userPrompt }
          ]
        },
        {
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`
          },
          timeout: 7000
        }
      );

      const content = response.data?.choices?.[0]?.message?.content;
      if (!content) throw new Error('Respuesta vacía desde OpenAI.');

      const parsed = JSON.parse(content) as AiValidationResponse;
      const approved = Boolean(parsed.approved);
      const confidence = typeof parsed.confidence === 'number' ? Math.min(Math.max(parsed.confidence, 0), 100) : 75;
      const reason = parsed.reason || 'Análisis completado.';

      console.log(`[AiRiskManager] ${approved ? '🟢 APROBADO' : '🔴 VETADO'} ${request.symbol} (${confidence}%): "${reason}"`);

      return { approved, confidence, reason };

    } catch (error: any) {
      const errorMsg = error.response?.data?.error?.message || error.message || 'Error desconocido';
      console.warn(`[AiRiskManager] ⚠️ Error OpenAI (${errorMsg}). Aprobando por fallback.`);

      // Fallback: aprobar con confianza moderada para no bloquear el bot por errores de red.
      // NOTA DE RIESGO (no corregido automáticamente, decisión de producto): esto significa
      // que cualquier corte hacia OpenAI convierte al bot en "sin filtro de IA" sin aviso
      // por Telegram. Si prefieres fail-closed (vetar en vez de aprobar cuando OpenAI falla),
      // cambia `approved: true` por `approved: false` aquí — pero eso pausará el bot cada vez
      // que OpenAI tenga un hiccup, así que es un trade-off explícito a decidir por ti.
      return { approved: true, confidence: 70, reason: `Fallback por error API: ${errorMsg.substring(0, 40)}` };
    }
  }
}