import { bingxClient } from './services/bingx/bingx-client';
import { config } from './config/environment';

// Bypass TLS en entorno corporativo/VPN
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

async function analyzeWeekendTrades() {
  try {
    console.log('🔍 Consultando el historial de operaciones de BingX (últimas 50 cerradas)...');
    
    // Forzar modo real para usar API Keys
    (bingxClient as any).isDemoMode = false;
    
    const history = await bingxClient.getTradeHistory(50);

    if (!history || history.length === 0) {
      console.log('⚠️ No se encontraron operaciones cerradas en el historial reciente o no se pudo conectar con BingX.');
      return;
    }

    // Filtrar operaciones del fin de semana (viernes noche a domingo actual)
    // El timestamp en history.time está en milisegundos
    const now = Date.now();
    const threeDaysAgo = now - (3 * 24 * 60 * 60 * 1000);
    
    const weekendTrades = history.filter(t => t.time >= threeDaysAgo);

    console.log(`\n======================================================`);
    console.log(`📊 REPORTE DE OPERACIONES (ÚLTIMOS 3 DÍAS)`);
    console.log(`======================================================`);
    console.log(`Total de operaciones analizadas: ${weekendTrades.length}`);

    let totalWins = 0;
    let totalLosses = 0;
    let totalNetPnl = 0;
    let totalCommissions = 0;
    const symbolStats: Record<string, { count: number; wins: number; losses: number; netPnl: number }> = {};

    for (const trade of weekendTrades) {
      const isWin = trade.netProfit > 0;
      if (isWin) totalWins++;
      else totalLosses++;

      totalNetPnl += trade.netProfit;
      totalCommissions += trade.commission;

      if (!symbolStats[trade.symbol]) {
        symbolStats[trade.symbol] = { count: 0, wins: 0, losses: 0, netPnl: 0 };
      }
      symbolStats[trade.symbol].count++;
      if (isWin) symbolStats[trade.symbol].wins++;
      else symbolStats[trade.symbol].losses++;
      symbolStats[trade.symbol].netPnl += trade.netProfit;
    }

    const winRate = weekendTrades.length > 0 ? ((totalWins / weekendTrades.length) * 100).toFixed(1) : '0';

    console.log(`\n📈 RESUMEN GLOBAL:`);
    console.log(`• Ganadoras:        ${totalWins} (${winRate}%)`);
    console.log(`• Perdedoras:       ${totalLosses}`);
    console.log(`• PnL Neto Total:   $${totalNetPnl.toFixed(2)} USD`);
    console.log(`• Comisiones aprox: $${totalCommissions.toFixed(2)} USD`);

    console.log(`\n📌 DESGLOSE POR MONEDA:`);
    for (const [symbol, stats] of Object.entries(symbolStats)) {
      console.log(`• ${symbol} -> Operaciones: ${stats.count} | Ganadoras: ${stats.wins} | Perdedoras: ${stats.losses} | PnL: $${stats.netPnl.toFixed(2)} USD`);
    }

    console.log(`\n📋 ÚLTIMAS 15 OPERACIONES DETALLADAS:`);
    const recent = weekendTrades.slice(0, 15);
    for (const trade of recent) {
      const dateStr = new Date(trade.time).toLocaleString('es-ES');
      const icon = trade.netProfit > 0 ? '🟢 WIN ' : '🔴 LOSS';
      console.log(`${icon} | ${dateStr} | ${trade.symbol} (${trade.positionSide}) | Precio: $${trade.price} | PnL Neto: $${trade.netProfit.toFixed(2)}`);
    }

    console.log(`\n💡 DIAGNÓSTICO DEL COMPORTAMIENTO:`);
    if (totalLosses > totalWins) {
      console.log(`1. MERCADO LATERAL DE FIN DE SEMANA: El criptomercado suele perder liquidez institucional los sábados y domingos.`);
      console.log(`2. WHIPSAWS (FALSAS RUPTURAS): En rangos laterales, los indicadores de tendencia (EMA 200/50, MACD) dan entradas que luego revierten rápidamente, tocando los Stop Loss ceñidos.`);
      console.log(`3. RECOMENDACIÓN INSTITUCIONAL: Se recomienda pausar el bot o usar un filtro de horario para no operar de viernes por la noche a domingo, o endurecer el filtro ADX (exigir ADX > 30 en fin de semana).`);
    }

  } catch (err: any) {
    console.error('Error durante el análisis:', err.message || err);
  }
}

analyzeWeekendTrades();
