import { config } from 'dotenv';
config();
import { BingXClient } from './src/services/bingx/bingx-client';

async function test() {
  const client = new BingXClient();
  const positions = await client.getActivePositions();
  for (const p of positions) {
    console.log(`${p.symbol} ${p.positionSide} | Entry: $${p.entryPrice} | Amount: ${p.amount} | PnL: $${p.unrealizedProfit} | Margin: $${p.margin} | Leverage: ${p.leverage}x`);
    console.log(`  -> SL: ${p.stopLoss} | TP: ${p.takeProfit}`);
  }
}
test().catch(console.error);
