import { bingxClient } from './src/services/bingx/bingx-client';

async function analyzeTrades() {
  try {
    const history = await bingxClient.getTradeHistory(40, true);
    console.log("Recent Trades:");
    let totalPnL = 0;
    history.forEach((trade: any) => {
        console.log(`- ${new Date(trade.time).toISOString()} | ${trade.symbol} | ${trade.positionSide} | ${trade.side} | Qty: ${trade.quantity} | Price: ${trade.price} | PnL: $${trade.profit.toFixed(2)} | Net PnL: $${trade.netProfit.toFixed(2)}`);
        totalPnL += trade.netProfit;
    });
    console.log(`\nTotal Net PnL: $${totalPnL.toFixed(2)}`);
  } catch (e) {
    console.error("Error fetching trades:", e);
  }
}

analyzeTrades();
