import { Router } from 'express';
import { bingxClient } from '../../services/bingx/bingx-client';
import { RiskCalculator } from '../../services/analytics/risk-calculator';
import { telegramBot } from '../../services/telegram/telegram-bot';

const router = Router();

// GET /api/trade/balance
router.get('/balance', async (req, res) => {
  try {
    const balance = await bingxClient.getAccountBalance();
    res.json({ success: true, data: balance });
  } catch (error: any) {
    res.status(500).json({ success: false, message: error.message });
  }
});

// GET /api/trade/positions
router.get('/positions', async (req, res) => {
  try {
    const positions = await bingxClient.getActivePositions();
    res.json({ success: true, data: positions });
  } catch (error: any) {
    res.status(500).json({ success: false, message: error.message });
  }
});

// POST /api/trade/calculate-risk
router.post('/calculate-risk', async (req, res) => {
  try {
    const {
      riskPercentage,
      entryPrice,
      stopLossPrice,
      takeProfitPrice,
      leverage,
      positionSide,
    } = req.body;

    const balanceData = await bingxClient.getAccountBalance();

    const calculation = RiskCalculator.calculate({
      accountBalance: balanceData.available || 10000,
      riskPercentage: parseFloat(riskPercentage || 1),
      entryPrice: parseFloat(entryPrice),
      stopLossPrice: parseFloat(stopLossPrice),
      takeProfitPrice: takeProfitPrice ? parseFloat(takeProfitPrice) : undefined,
      leverage: parseInt(leverage || 10, 10),
      positionSide: positionSide || 'LONG',
    });

    res.json({ success: true, data: calculation });
  } catch (error: any) {
    res.status(500).json({ success: false, message: error.message });
  }
});

// POST /api/trade/order
router.post('/order', async (req, res) => {
  try {
    const { symbol, side, positionSide, type, quantity, price, stopLoss, takeProfit, leverage } = req.body;

    if (!symbol || !side || !quantity) {
      return res.status(400).json({ success: false, message: 'Faltan campos obligatorios (symbol, side, quantity)' });
    }

    const result = await bingxClient.placeOrder({
      symbol,
      side,
      positionSide: positionSide || (side === 'BUY' ? 'LONG' : 'SHORT'),
      type: type || 'MARKET',
      quantity: parseFloat(quantity),
      price: price ? parseFloat(price) : undefined,
      stopLoss: stopLoss ? parseFloat(stopLoss) : undefined,
      takeProfit: takeProfit ? parseFloat(takeProfit) : undefined,
      leverage: leverage ? parseInt(leverage, 10) : 10,
    });

    if (result.success) {
      telegramBot.sendMessage(`⚡ *EJECUCIÓN DE ORDEN BINGX*\n\n• Par: ${symbol}\n• Tipo: ${positionSide || side}\n• Cantidad: ${quantity}\n• Mensaje: ${result.message}`);
    }

    res.json(result);
  } catch (error: any) {
    res.status(500).json({ success: false, message: error.message });
  }
});

// POST /api/trade/close-position
router.post('/close-position', async (req, res) => {
  try {
    const { symbol, positionSide } = req.body;
    if (!symbol || !positionSide) {
      return res.status(400).json({ success: false, message: 'Se requiere symbol y positionSide (LONG/SHORT)' });
    }

    const result = await bingxClient.closePosition(symbol, positionSide);
    if (result.success) {
      telegramBot.sendMessage(`🔒 *POSICIÓN CERRADA*\n\n• Par: ${symbol}\n• Lado: ${positionSide}\n• Resumen: ${result.message}`);
    }
    res.json(result);
  } catch (error: any) {
    res.status(500).json({ success: false, message: error.message });
  }
});

// GET /api/trade/history
router.get('/history', async (req, res) => {
  try {
    const limit = parseInt((req.query.limit as string) || '20', 10);
    const history = await bingxClient.getTradeHistory(limit);
    res.json({ success: true, data: history });
  } catch (error: any) {
    res.status(500).json({ success: false, message: error.message });
  }
});

export default router;
