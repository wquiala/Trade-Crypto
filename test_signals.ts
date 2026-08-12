import { bingxClient } from './src/services/bingx/bingx-client';
import { TechnicalAnalysis } from './src/services/analytics/indicators';

async function run() {
  const symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'ADA-USDT'];
  for (const sym of symbols) {
    const klines = await bingxClient.getKlines(sym, '5m', 250);
    const closedKlines = klines.slice(0, -1);
    const analysis = TechnicalAnalysis.analyze(sym, closedKlines);
    console.log(`${sym}: ${analysis.signal} (Price: ${analysis.currentPrice})`);
  }
}
run();
