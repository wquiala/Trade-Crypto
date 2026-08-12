import { bingxClient } from './src/services/bingx/bingx-client';
import { TechnicalAnalysis } from './src/services/analytics/indicators';

process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

async function run() {
  const klines = await bingxClient.getKlines('LINK-USDT', '15m', 250);
  const closedKlines = klines.slice(0, -1);
  const analysis = TechnicalAnalysis.analyze('LINK-USDT', closedKlines);
  console.log(JSON.stringify(analysis, null, 2));
}
run();
