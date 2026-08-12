import { bingxClient } from './src/services/bingx/bingx-client';

async function testConnection() {
  try {
    const btcTicker = await bingxClient.getTickerPrice('BTC-USDT');
    console.log("Success! BTC Price:", btcTicker);
  } catch (error: any) {
    console.error("Error:", error.message);
  }
}

testConnection();
