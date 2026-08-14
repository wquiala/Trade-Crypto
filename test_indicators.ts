import { config } from 'dotenv';
config();
import { BingXClient } from './src/services/bingx/bingx-client';
import { TechnicalAnalysis } from './src/services/analytics/indicators';

async function test() {
  const client = new BingXClient();
  const symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'LINK-USDT', 'AVAX-USDT'];
  for (const symbol of symbols) {
    const klines = await client.getKlines(symbol, '5m', 200);
    const analysis = TechnicalAnalysis.analyze(symbol, klines);
    const inverted = analysis.signal.includes('BUY') ? 'SHORT (SELL)' : (analysis.signal.includes('SELL') ? 'LONG (BUY)' : 'NEUTRAL');
    console.log(`[${symbol}] Señal Técnica: ${analysis.signal} -> Ejecutaría Inverso: ${inverted}`);
  }
}
test().catch(console.error);
