import { config } from 'dotenv';
config();
import { BingXClient } from './src/services/bingx/bingx-client';
import { TechnicalAnalysis } from './src/services/analytics/indicators';

async function test() {
  const client = new BingXClient();
  for (const symbol of ['SOL-USDT', 'BNB-USDT']) {
    console.log(`\nAnalyzing ${symbol}...`);
    const klines = await client.getKlines(symbol, '5m', 200);
    const analysis = TechnicalAnalysis.analyze(symbol, klines);
    console.log(`Signal for ${symbol}: ${analysis.signal}`);
    console.log(`Summary: ${analysis.summary}`);
  }
}
test().catch(console.error);
