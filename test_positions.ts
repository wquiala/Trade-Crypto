import { bingxClient } from './src/services/bingx/bingx-client';

async function run() {
  try {
    const positions = await bingxClient.getActivePositions();
    console.log(JSON.stringify(positions, null, 2));
  } catch (e) {
    console.error(e);
  }
}
run();
