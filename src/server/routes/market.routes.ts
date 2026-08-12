import { Router } from 'express';
import { bingxClient } from '../../services/bingx/bingx-client';
import { TechnicalAnalysis } from '../../services/analytics/indicators';

const router = Router();

// GET /api/market/ticker?symbol=BTC-USDT
router.get('/ticker', async (req, res) => {
  try {
    const symbol = (req.query.symbol as string) || 'BTC-USDT';
    const ticker = await bingxClient.getTickerPrice(symbol);
    res.json({ success: true, data: ticker });
  } catch (error: any) {
    res.status(500).json({ success: false, message: error.message });
  }
});

// GET /api/market/klines?symbol=BTC-USDT&interval=1m&limit=100
router.get('/klines', async (req, res) => {
  try {
    const symbol = (req.query.symbol as string) || 'BTC-USDT';
    const interval = (req.query.interval as string) || '1m';
    const limit = parseInt((req.query.limit as string) || '100', 10);

    const klines = await bingxClient.getKlines(symbol, interval, limit);
    res.json({ success: true, data: klines });
  } catch (error: any) {
    res.status(500).json({ success: false, message: error.message });
  }
});

// GET /api/market/analysis?symbol=BTC-USDT
router.get('/analysis', async (req, res) => {
  try {
    const symbol = (req.query.symbol as string) || 'BTC-USDT';
    // Usar velas de 15m y 250 de límite (igual que el cerebro del bot)
    const klines = await bingxClient.getKlines(symbol, '15m', 250);
    // Ignorar la vela actual en vivo para analizar solo velas cerradas
    const closedKlines = klines.slice(0, -1);
    const analysis = TechnicalAnalysis.analyze(symbol, closedKlines);
    res.json({ success: true, data: analysis });
  } catch (error: any) {
    res.status(500).json({ success: false, message: error.message });
  }
});

export default router;
