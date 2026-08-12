import http from 'http';
import path from 'path';
import express from 'express';
import cors from 'cors';
import { WebSocketServer, WebSocket } from 'ws';
import marketRoutes from './routes/market.routes';
import tradeRoutes from './routes/trade.routes';
import botRoutes, { botConfig } from './routes/bot.routes';
import { bingxClient } from '../services/bingx/bingx-client';
import { config } from '../config/environment';

export function createApp() {
  const app = express();
  const server = http.createServer(app);
  const wss = new WebSocketServer({ server });

  // Middleware
  app.use(cors());
  app.use(express.json());
  app.use(express.urlencoded({ extended: true }));

  // Archivos Estáticos del Dashboard Frontend
  app.use(express.static(path.join(__dirname, '../../public')));

  // Rutas API REST
  app.use('/api/market', marketRoutes);
  app.use('/api/trade', tradeRoutes);
  app.use('/api/bot', botRoutes);


  // WebSocket Server para datos en vivo en el Dashboard Frontend
  const activeSockets = new Set<WebSocket>();

  wss.on('connection', (ws) => {
    activeSockets.add(ws);
    console.log('[WebSocket] Cliente conectado al Dashboard.');

    ws.on('close', () => {
      activeSockets.delete(ws);
    });
  });

  let cachedRealizedToday = { closedOrdersCount: 0, realizedPnL: 0, realizedNetPnL: 0 };
  let lastRealizedFetchTime = 0;

  // Emisión periódica de precios y ticker a los clientes web conectados (cada 3 segundos)
  setInterval(async () => {
    if (activeSockets.size === 0) return;

    try {
      const [btcTicker, ethTicker, solTicker, avaxTicker, linkTicker, paxgTicker, bnbTicker, xrpTicker, dogeTicker, suiTicker, balance, positions] = await Promise.all([
        bingxClient.getTickerPrice('BTC-USDT'),
        bingxClient.getTickerPrice('ETH-USDT'),
        bingxClient.getTickerPrice('SOL-USDT'),
        bingxClient.getTickerPrice('AVAX-USDT'),
        bingxClient.getTickerPrice('LINK-USDT'),
        bingxClient.getTickerPrice('PAXG-USDT'),
        bingxClient.getTickerPrice('BNB-USDT'),
        bingxClient.getTickerPrice('XRP-USDT'),
        bingxClient.getTickerPrice('DOGE-USDT'),
        bingxClient.getTickerPrice('SUI-USDT'),
        bingxClient.getAccountBalance(),
        bingxClient.getActivePositions(),
      ]);

      const now = Date.now();
      if (now - lastRealizedFetchTime > 20000) {
        lastRealizedFetchTime = now;
        cachedRealizedToday = await bingxClient.getTodayRealizedPnL();
      }

      const payload = JSON.stringify({
        type: 'MARKET_TICKER',
        data: {
          btc: btcTicker,
          eth: ethTicker,
          sol: solTicker,
          avax: avaxTicker,
          link: linkTicker,
          paxg: paxgTicker,
          bnb: bnbTicker,
          xrp: xrpTicker,
          doge: dogeTicker,
          sui: suiTicker,
          balance,
          positions,
          demoMode: config.bingx.demoMode,
          startOfDayEquity: botConfig.startOfDayEquity,
          realizedToday: cachedRealizedToday,
          timestamp: Date.now(),
        }
      });

      for (const client of activeSockets) {
        if (client.readyState === WebSocket.OPEN) {
          client.send(payload);
        }
      }
    } catch (err) {
      // Ignorar errores de transmisión periódica
    }
  }, 4500); // 4.5 segundos para evitar error 100410 (límite de frecuencia en BingX API)

  return { app, server };
}
