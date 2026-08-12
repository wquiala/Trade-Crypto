import dotenv from 'dotenv';
dotenv.config();

const rawDemoMode = process.env.BINGX_DEMO_MODE?.toLowerCase();
const demoMode = rawDemoMode === 'true' || rawDemoMode === '1' ? true : false;

export const config = {
  port: parseInt(process.env.PORT || '3000', 10),
  bingx: {
    apiKey: process.env.BINGX_API_KEY?.trim() || '',
    secretKey: process.env.BINGX_SECRET_KEY?.trim() || '',
    demoMode,
    baseUrl: process.env.BINGX_API_URL || 'https://open-api.bingx.com',
  },
  telegram: {
    botToken: process.env.TELEGRAM_BOT_TOKEN?.trim() || '',
    chatId: process.env.TELEGRAM_CHAT_ID?.trim() || '',
  },
  ctrader: {
    clientId: process.env.CTRADER_CLIENT_ID?.trim() || '',
    clientSecret: process.env.CTRADER_CLIENT_SECRET?.trim() || '',
    accessToken: process.env.CTRADER_ACCESS_TOKEN?.trim() || '',
    refreshToken: process.env.CTRADER_REFRESH_TOKEN?.trim() || '',
    accountId: process.env.CTRADER_ACCOUNT_ID?.trim() || '',
    env: (process.env.CTRADER_ENV?.trim() as 'sandbox' | 'live') || 'sandbox',
  }
};

export const isBingxConfigured = Boolean(config.bingx.apiKey && config.bingx.secretKey);
