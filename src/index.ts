import { createApp } from './server/app';
import { config } from './config/environment';

const { server } = createApp();

server.listen(config.port, () => {
  console.log(`
  ================================================================
  🚀 BINGX TRADING ASSISTANT & BOT INICIADO
  ================================================================
  🌐 Dashboard Web: http://localhost:${config.port}
  🔒 Modo BingX:    ${config.bingx.demoMode ? 'DEMO / VST (Simulado / Cuenta Demo)' : 'PROD / REAL'}
  🤖 Bot Telegram:  ${config.telegram.botToken ? 'Conectado 🟢' : 'Desactivado (Falta Token en .env)'}
  ================================================================
  `);
});
