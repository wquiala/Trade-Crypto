const WebSocket = require('ws');
require('dotenv').config();

const clientId = process.env.CTRADER_CLIENT_ID;
const clientSecret = process.env.CTRADER_CLIENT_SECRET;
const accessToken = process.env.CTRADER_ACCESS_TOKEN;

function getAccounts(host) {
    return new Promise((resolve) => {
        const ws = new WebSocket(`wss://${host}:5036`);
        ws.on('open', () => {
            ws.send(JSON.stringify({
                payloadType: 2100, // APP AUTH
                clientMsgId: 'auth',
                payload: { clientId, clientSecret }
            }));
        });
        
        ws.on('message', (data) => {
            const res = JSON.parse(data.toString());
            if (res.payloadType === 2101) {
                // App authed, request account list
                ws.send(JSON.stringify({
                    payloadType: 2149, // ACCOUNT_LIST_BY_ACCESS_TOKEN_REQ
                    clientMsgId: 'list',
                    payload: { accessToken }
                }));
            } else if (res.payloadType === 2150) { // ACCOUNT_LIST_BY_ACCESS_TOKEN_RES
                console.log(`\n=== Cuentas autorizadas en ${host} ===`);
                if (res.payload && res.payload.ctidTraderAccount) {
                    const accounts = res.payload.ctidTraderAccount;
                    accounts.forEach(acc => {
                        console.log(`- Account ID: ${acc.ctidTraderAccountId} | Broker: ${acc.brokerName} | Live: ${acc.isLive}`);
                    });
                } else {
                    console.log('No hay cuentas autorizadas para este token.');
                }
                ws.close();
                resolve();
            } else if (res.payloadType === 2132 || res.payloadType === 2142) {
                // console.log(`Error: ${JSON.stringify(res)}`);
                ws.close();
                resolve();
            }
        });
        setTimeout(() => { ws.close(); resolve(); }, 3000);
    });
}

async function run() {
    await getAccounts('live.ctraderapi.com');
    await getAccounts('demo.ctraderapi.com');
}

run();
