import axios from 'axios';
import { config } from '../../config/environment';
import { bingxClient } from '../bingx/bingx-client';
import { TechnicalAnalysis } from '../analytics/indicators';
import { botConfig } from '../../server/routes/bot.routes';

/** Escapa caracteres especiales de HTML para evitar errores en el parse de Telegram */
export function escHtml(text: string | number): string {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export class TelegramBotService {
  private token: string;
  private chatId: string;
  private isEnabled: boolean;
  private pollInterval: NodeJS.Timeout | null = null;
  private lastUpdateId: number = 0;

  constructor() {
    this.token = config.telegram.botToken;
    this.chatId = config.telegram.chatId;
    this.isEnabled = Boolean(this.token);

    if (this.isEnabled) {
      console.log('[TelegramBot] Inicializando Bot de Telegram...');
      this.startPolling();
    } else {
      console.log('[TelegramBot] Token no configurado. Notificaciones de Telegram desactivadas. (Configúralo en .env)');
    }
  }

  /**
   * Enviar mensaje simple a Telegram
   */
  async sendMessage(text: string): Promise<boolean> {
    if (!this.isEnabled || !this.chatId) return false;

    try {
      await axios.post(`https://api.telegram.org/bot${this.token}/sendMessage`, {
        chat_id: this.chatId,
        text,
        parse_mode: 'HTML',
      });
      return true;
    } catch (error: any) {
      console.error('[TelegramBot] Error al enviar mensaje:', error?.response?.data || error.message);
      return false;
    }
  }

  /**
   * Polling ligero de comandos de Telegram
   */
  private startPolling() {
    this.pollInterval = setInterval(async () => {
      try {
        const response = await axios.get(`https://api.telegram.org/bot${this.token}/getUpdates`, {
          params: { offset: this.lastUpdateId + 1, timeout: 2 }
        });

        if (response.data && response.data.ok && Array.isArray(response.data.result)) {
          for (const update of response.data.result) {
            this.lastUpdateId = update.update_id;
            if (update.message && update.message.text) {
              await this.handleCommand(update.message.chat.id, update.message.text);
            }
          }
        }
      } catch (error) {
        // Ignorar errores temporales de conexión
      }
    }, 3000);
  }

  /**
   * Manejador de Comandos interactivos de Telegram
   */
  private async handleCommand(chatId: number, text: string) {
    const command = text.trim().toLowerCase();

    if (command === '/start' || command === '/help') {
      const helpMsg = `🤖 *Asistente de Trading BingX* 🚀\n\n` +
        `Comandos disponibles:\n` +
        `💰 \`/balance\` - Consultar saldo y rendimiento diario\n` +
        `📅 \`/daily\` - Ver ganancia / pérdida del día de hoy\n` +
        `📊 \`/positions\` - Ver posiciones activas y PnL\n` +
        `📈 \`/signals\` - Ver señal técnica actual y ADX de BTC\n` +
        `⚡ \`/adx\` - Ver fuerza de tendencia (ADX 15m) en todas las monedas\n` +
        `🖥 \`/status\` - Estado de la conexión a BingX`;
      await this.sendMessageToChat(chatId, helpMsg);
    } 
    else if (command === '/balance' || command === '/daily' || command === '/hoy' || command === '/pnl') {
      const balance = await bingxClient.getAccountBalance();
      const realized = await bingxClient.getTodayRealizedPnL();
      const emojiRealized = realized.realizedNetPnL >= 0 ? '🟢' : '🔴';
      const signRealized = realized.realizedNetPnL >= 0 ? '+' : '';

      const startEquity = botConfig.startOfDayEquity > 0 ? botConfig.startOfDayEquity : balance.equity;
      const floatingPnL = balance.equity - startEquity;
      const signFloat = floatingPnL >= 0 ? '+' : '';

      const msg = `💰 *Rendimiento y Balance Diario (${balance.asset})*\n\n` +
        `• *Ganancia Realizada Hoy (Cerradas):* ${emojiRealized} *${signRealized}$${realized.realizedNetPnL.toFixed(2)} USD* (${realized.closedOrdersCount} operac.)\n` +
        `• *Ganancia Bruta (Sin comisiones):* ${signRealized}$${realized.realizedPnL.toFixed(2)} USD\n` +
        `• *Patrimonio Actual (Equity):* $${balance.equity.toFixed(2)}\n` +
        `• *Saldo Inicial del Día:* $${startEquity.toFixed(2)}\n` +
        `• *Flotante Actual (Total):* ${signFloat}$${floatingPnL.toFixed(2)} USD\n` +
        `• *Máximo del Día (Peak):* $${(botConfig.highestEquityToday || balance.equity).toFixed(2)}\n` +
        `• *Disponible (Billetera):* $${balance.available.toFixed(2)}`;
      await this.sendMessageToChat(chatId, msg);
    } 
    else if (command === '/positions') {
      const positions = await bingxClient.getActivePositions();
      if (positions.length === 0) {
        await this.sendMessageToChat(chatId, '📭 No tienes posiciones abiertas en este momento.');
        return;
      }

      let msg = `📊 *Posiciones Activas (${positions.length})*\n\n`;
      for (const p of positions) {
        const emoji = p.unrealizedProfit >= 0 ? '🟢' : '🔴';
        msg += `${emoji} *${p.symbol}* (${p.positionSide} ${p.leverage}x)\n` +
          `• Entrada: $${p.entryPrice} | Marca: $${p.markPrice}\n` +
          `• Cantidad: ${p.amount} | Margen: $${p.margin}\n` +
          `• *PnL no realizado:* $${p.unrealizedProfit}\n\n`;
      }
      await this.sendMessageToChat(chatId, msg);
    } 
    else if (command === '/signals') {
      const klines = await bingxClient.getKlines('BTC-USDT', '15m', 750); // Mismo límite que el loop del bot para consistencia
      const analysis = TechnicalAnalysis.analyze('BTC-USDT', klines);

      const emojiMap = {
        STRONG_BUY: '🚀 COMPRA FUERTE',
        BUY: '🟢 COMPRA',
        NEUTRAL: '⚪ NEUTRAL',
        SELL: '🔴 VENTA',
        STRONG_SELL: '💥 VENTA FUERTE',
      };

      const isWeekend = [0, 6].includes(new Date().getUTCDay());
      const minAdxReq = isWeekend ? 18 : 15;

      const adxVal = analysis.adx ? analysis.adx.toFixed(1) : 'N/A';
      const adxEmoji = (analysis.adx || 0) >= minAdxReq ? '📈' : '⚪';

      const msg = `📈 *Análisis Técnico BTC-USDT (15m)*\n\n` +
        `• *Precio Actual:* $${analysis.currentPrice}\n` +
        `• *ADX (14):* ${adxEmoji} ${adxVal} (${(analysis.adx || 0) >= minAdxReq ? 'Tendencia Activa' : 'En Rango'}) [Mín: ${minAdxReq}]\n` +
        `• *RSI (14):* ${analysis.rsi}\n` +
        `• *EMA 20:* $${analysis.ema20} | *EMA 50:* $${analysis.ema50}\n` +
        `• *MACD:* ${analysis.macd.histogram}\n` +
        `• *Señal:* *${emojiMap[analysis.signal]}*\n\n` +
        `ℹ️ _${analysis.summary}_`;
      await this.sendMessageToChat(chatId, msg);
    }
    else if (command === '/adx') {
      const symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'LINK-USDT', 'AVAX-USDT'];
      const isWeekend = [0, 6].includes(new Date().getUTCDay());
      const minAdxReq = isWeekend ? 18 : 15;

      let msg = `⚡ *Fuerza de Tendencia ADX (15m)* ${isWeekend ? '(🛡️ Fin de Semana)' : ''}\n\n`;
      for (const sym of symbols) {
        try {
          const k = await bingxClient.getKlines(sym, '15m', 750); // 750 velas para EMA200 confiable
          const a = TechnicalAnalysis.analyze(sym, k);
          const adx = a.adx ? a.adx.toFixed(1) : '0';
          const icon = (a.adx || 0) >= minAdxReq ? '🟢' : '⚪';
          const status = (a.adx || 0) >= minAdxReq ? '*Tendencia Activa*' : 'Rango Plano';
          msg += `${icon} *${sym.replace('-USDT', '')}:* ADX ${adx} -> ${status}\n`;
        } catch (e) {
          msg += `⚪ *${sym}:* No disponible\n`;
        }
      }
      msg += `\nℹ️ _ADX >= ${minAdxReq} activa la búsqueda de entradas del Bot (${isWeekend ? 'filtro elevado por fin de semana' : 'estándar entre semana'})._`;
      await this.sendMessageToChat(chatId, msg);
    }
    else if (command === '/status') {
      const realized = await bingxClient.getTodayRealizedPnL();
      const emojiRealized = realized.realizedNetPnL >= 0 ? '🟢' : '🔴';
      const signRealized = realized.realizedNetPnL >= 0 ? '+' : '';
      await this.sendMessageToChat(chatId, `✅ Servidor backend activo y conectado a BingX (Modo Demo: ${config.bingx.demoMode ? 'Activado' : 'Desactivado'}).\n\n• *Ganancia Cerrada Hoy:* ${emojiRealized} *${signRealized}$${realized.realizedNetPnL.toFixed(2)} USD* (${realized.closedOrdersCount} operac.)\n• *Auto-Trade:* ${botConfig.autoTradeEnabled ? '🟢 ACTIVADO' : '🔴 DESACTIVADO'}`);
    }
  }

  private async sendMessageToChat(chatId: number, text: string) {
    try {
      await axios.post(`https://api.telegram.org/bot${this.token}/sendMessage`, {
        chat_id: chatId,
        text,
        parse_mode: 'HTML',
      });
    } catch (error) {
      console.error('[TelegramBot] Error sending to chat:', error);
    }
  }

  /**
   * Notificación broadcast para alertas del sistema o ejecuciones
   */
  async notifySignal(analysis: any) {
    const cleanSignal = String(analysis.signal || '').replace(/_/g, ' ');
    const text = `🚨 *NUEVA SEÑAL DETECTADA: ${analysis.symbol}*\n\n` +
      `• *Señal:* ${cleanSignal}\n` +
      `• *Precio:* $${analysis.currentPrice}\n` +
      `• *RSI:* ${analysis.rsi}\n` +
      `• *Resumen:* ${analysis.summary}`;
    await this.sendMessage(text);
  }
}

export const telegramBot = new TelegramBotService();
