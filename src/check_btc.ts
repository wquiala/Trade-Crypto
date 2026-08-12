import { bingxClient } from './services/bingx/bingx-client';
import { TechnicalAnalysis } from './services/analytics/indicators';
import { config } from './config/environment';

async function checkBTC() {
  try {
    console.log('🔄 Fetching Klines for BTC-USDT (5m interval)...');
    
    // Forzamos a no ser Demo Mode para que traiga precios reales
    (bingxClient as any).isDemoMode = false;

    const klines = await bingxClient.getKlines('BTC-USDT', '5m', 250);
    
    if (klines.length < 35) {
       console.log('❌ Error: No se recibieron suficientes velas o la API falló (Network).');
       return;
    }
    
    const closedKlines = klines.slice(0, -1);
    const analysis = TechnicalAnalysis.analyze('BTC-USDT', closedKlines);
    
    console.log('\n📊 === DIAGNÓSTICO DE BITCOIN (BTC) ===');
    console.log(`Precio Actual: $${analysis.currentPrice}`);
    console.log(`Señal Final:   ${analysis.signal}`);
    
    console.log('\n🔍 === DESGLOSE DE INDICADORES ===');
    console.log(`RSI (Fuerza):                 ${analysis.rsi.toFixed(2)}`);
    console.log(`MACD Histograma:              ${analysis.macd.histogram.toFixed(2)}`);
    console.log(`EMA 50:                       ${analysis.ema50.toFixed(2)}`);
    console.log(`EMA 200:                      ${analysis.ema200.toFixed(2)}`);
    console.log(`ATR (Volatilidad):            ${analysis.atr.toFixed(2)}`);

    console.log('\n💡 === ¿POR QUÉ NO OPERA? ===');
    console.log('-> RESUMEN DEL BOT: ' + analysis.summary);
    if (analysis.signal === 'NEUTRAL') {
      const isBullish = analysis.ema50 > analysis.ema200;
      console.log(`-> Tendencia actual: ${isBullish ? 'ALCISTA' : 'BAJISTA'} pero falta confluencia (RSI o MACD no apoyan).`);
      console.log('-> El bot espera el momento perfecto (Sniper).');
    } else {
      console.log('-> ¡La señal es válida! Si no se abre operación, revisa el Límite de Drawdown (Emergency Break) o el Cooldown de 30 mins.');
    }
    
  } catch (err) {
    console.error('Error durante chequeo:', err);
  }
}

checkBTC();
