const WebSocket = require('ws');
require('dotenv').config();

const clientId = process.env.CTRADER_CLIENT_ID;
const clientSecret = process.env.CTRADER_CLIENT_SECRET;
const accountId = process.env.CTRADER_ACCOUNT_ID;
const accessToken = process.env.CTRADER_ACCESS_TOKEN;

function testEnv(envName, host) {
    return new Promise((resolve) => {
        console.log(`\n--- TESTING ENVIRONMENT: ${envName} (${host}) ---`);
        const ws = new WebSocket(`wss://${host}:5036`);

        ws.on('open', () => {
            console.log(`[${envName}] Connected to WebSocket`);
            ws.send(JSON.stringify({
                payloadType: 2100,
                clientMsgId: 'req_auth',
                payload: { clientId, clientSecret }
            }));
        });

        ws.on('message', (data) => {
            const res = JSON.parse(data.toString());
            console.log(`[${envName}] Received:`, JSON.stringify(res));

            if (res.payloadType === 2101) {
                console.log(`[${envName}] App Auth SUCCESS. Sending Account Auth for account ${accountId}...`);
                ws.send(JSON.stringify({
                    payloadType: 2102,
                    clientMsgId: 'req_acc',
                    payload: { ctidTraderAccountId: parseInt(accountId, 10), accessToken }
                }));
            } else if (res.payloadType === 2103) {
                console.log(`[${envName}] Account Auth SUCCESS!`);
                ws.close();
                resolve(true);
            } else if (res.payloadType === 2142 || res.payloadType === 2132) {
                console.log(`[${envName}] ERROR:`, res.payload ? res.payload : res);
                ws.close();
                resolve(false);
            }
        });

        ws.on('error', (err) => {
            console.log(`[${envName}] Socket Error:`, err.message);
            resolve(false);
        });
        
        setTimeout(() => {
            console.log(`[${envName}] Timeout`);
            ws.close();
            resolve(false);
        }, 5000);
    });
}

async function run() {
    console.log(`Testing cTrader Auth for Account: ${accountId}`);
    const liveRes = await testEnv('LIVE', 'live.ctraderapi.com');
    if (!liveRes) {
        await testEnv('SANDBOX', 'demo.ctraderapi.com');
    }
}

run();
