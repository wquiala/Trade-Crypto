import { bingxClient } from './src/services/bingx/bingx-client';
import * as dotenv from 'dotenv';
dotenv.config();

async function run() {
  try {
    const history = await bingxClient.getTradeHistory(30);
    console.log("Recent Trades:", JSON.stringify(history, null, 2));
  } catch(e) { console.error(e); }
}
run();
