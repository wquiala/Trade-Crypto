import { bingxClient } from './src/services/bingx/bingx-client';
import { TechnicalAnalysis } from './src/services/analytics/indicators';

const symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'ADA-USDT'];

async function run() {
  for (const sym of symbols) {
    try {
      const klines = await bingxClient.getKlines(sym, '1h', 250);
      const closed = klines.slice(0, -1);
      const analysis = TechnicalAnalysis.analyze(sym, closed);
      console.log(`${sym} - Price: ${analysis.currentPrice}, ATR: ${analysis.atr}`);
    } catch (e) {
      console.error(e);
    }
  }
}
run();
