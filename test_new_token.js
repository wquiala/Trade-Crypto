const WebSocket = require('ws');

const clientId = "34193_MDnQ7azhrFBfEcyL7rFqUEhgaNbvDQRx15knPF591f4XHD2ubT";
const clientSecret = "1USHLdC8u7h3zHKyhHbHcJFp75mqHEIgb5eqfs2iMjQkhZgVBA";
const accessToken = "XAats-hNMK3pr9W-7BWUIsFm0GzsdiMMC0ppa_RrztQ";

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
                console.log(`Error en ${host}: ${JSON.stringify(res.payload || res)}`);
                ws.close();
                resolve();
            }
        });
        
        ws.on('error', () => resolve());
        setTimeout(() => { ws.close(); resolve(); }, 3000);
    });
}

async function run() {
    await getAccounts('live.ctraderapi.com');
    await getAccounts('demo.ctraderapi.com');
}

run();
