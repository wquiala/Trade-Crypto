import { BingXClient } from './src/services/bingx/bingx-client';
import { TechnicalAnalysis } from './src/services/analytics/indicators';
import dotenv from 'dotenv';
dotenv.config();

const symbols = ["BTC-USDT", "ETH-USDT", "AVAX-USDT", "LINK-USDT", "SOL-USDT", "PAXG-USDT", "BNB-USDT", "XRP-USDT", "DOGE-USDT", "SUI-USDT"];

async function main() {
  const client = new BingXClient();
  
  console.log("Analizando estado actual en tiempo real...\n");
  for (const symbol of symbols) {
    try {
      const klines = await client.getKlines(symbol, '15m', 250);
      if (!klines || klines.length < 200) continue;
      
      const result = TechnicalAnalysis.analyze(symbol, klines);
      console.log(`--- ${symbol} ---`);
      console.log(`Precio: $${result.currentPrice}`);
      console.log(`RSI: ${result.rsi.toFixed(2)} | ADX: ${result.adx.toFixed(2)}`);
      console.log(`MACD Hist: ${result.macd.histogram.toFixed(4)}`);
      console.log(`EMA50: $${result.ema50.toFixed(2)} | EMA200: $${result.ema200.toFixed(2)}`);
      console.log(`Señal: ${result.signal}`);
      console.log(`Motivo: ${result.summary}\n`);
    } catch (e: any) {
      console.error(`Error en ${symbol}:`, e.message);
    }
  }
}
main();
