import { bingxClient } from './src/services/bingx/bingx-client';
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

async function checkAvax() {
  (bingxClient as any).isDemoMode = false;
  try {
     const positions = await bingxClient.getActivePositions();
     console.log("Positions:", positions);
  } catch (e: any) {
     console.log("Error:", e);
  }
}

checkAvax();
