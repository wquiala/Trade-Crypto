import { bingxClient } from './src/services/bingx/bingx-client';

async function analyzeAvax() {
  try {
    const time = new Date(1786422749707);
    console.log(`AVAX Trade Open Time: ${time.toISOString()}`);

    const positions = await bingxClient.getActivePositions('AVAX-USDT');
    console.log('\nActive AVAX Positions:', JSON.stringify(positions, null, 2));

    const klines = await bingxClient.getKlines('AVAX-USDT', '15m', 10);
    console.log('\nRecent 15m Candles for AVAX:');
    klines.forEach(k => {
      console.log(`- ${new Date(k.time * 1000).toISOString()} | O: ${k.open} H: ${k.high} L: ${k.low} C: ${k.close}`);
    });
  } catch (e) {
    console.error(e);
  }
}

analyzeAvax();
