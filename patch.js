const fs = require('fs');
const path = '/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade/src/services/ctrader/ctrader-client.ts';
let code = fs.readFileSync(path, 'utf8');

// Parchear el manejo del error 2142
code = code.replace(
  'console.log(`[cTrader] Mensaje no gestionado: payloadType=${payloadType}`);',
  'if (payloadType === 2142) console.error(`[cTrader] ERROR 2142 (ProtoMessageError):`, JSON.stringify(msg)); else console.log(`[cTrader] Mensaje no gestionado: payloadType=${payloadType}`);'
);

fs.writeFileSync(path, code);
