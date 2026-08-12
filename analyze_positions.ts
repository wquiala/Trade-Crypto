import { bingxClient } from './src/services/bingx/bingx-client';

async function analyzeActivePositions() {
  try {
    const positions = await bingxClient.getActivePositions();
    if (positions.length === 0) {
      console.log("No active positions.");
      return;
    }
    console.log(`Active Positions (${positions.length}):`);
    let totalUnrealizedPnL = 0;
    
    positions.forEach((p) => {
        const pnl = p.unrealizedProfit;
        totalUnrealizedPnL += pnl;
        const pnlPct = (pnl / p.margin) * 100;
        console.log(`- ${p.symbol} | ${p.positionSide} | Entry: $${p.entryPrice} | Mark: $${p.markPrice} | Qty: ${p.amount} | Margin: $${p.margin.toFixed(2)} | PnL: $${pnl.toFixed(2)} (${pnlPct.toFixed(2)}%) | SL: ${p.stopLoss || 'N/A'} | TP: ${p.takeProfit || 'N/A'}`);
    });
    
    console.log(`\nTotal Unrealized PnL: $${totalUnrealizedPnL.toFixed(2)}`);
  } catch (e) {
    console.error("Error fetching positions:", e);
  }
}

analyzeActivePositions();
