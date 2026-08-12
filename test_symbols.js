const WebSocket = require('ws');
require('dotenv').config();

const clientId = "34193_MDnQ7azhrFBfEcyL7rFqUEhgaNbvDQRx15knPF591f4XHD2ubT";
const clientSecret = "1USHLdC8u7h3zHKyhHbHcJFp75mqHEIgb5eqfs2iMjQkhZgVBA";
const accessToken = "Z2Dn6FUiGrTTg12vMDWcayc5ZRl8NMzpji2ZKU2Di14";
const accountId = 48083214;

const ws = new WebSocket(`wss://demo.ctraderapi.com:5036`);

ws.on('open', () => {
    ws.send(JSON.stringify({
        payloadType: 2100, // APP AUTH
        clientMsgId: 'auth_app',
        payload: { clientId, clientSecret }
    }));
});

ws.on('message', (data) => {
    const res = JSON.parse(data.toString());
    console.log('Received:', res.payloadType, res.clientMsgId);
    if (res.payloadType === 2101) {
        ws.send(JSON.stringify({
            payloadType: 2102, // ACCOUNT AUTH
            clientMsgId: 'auth_acc',
            payload: { ctidTraderAccountId: accountId, accessToken }
        }));
    } else if (res.payloadType === 2103) {
        ws.send(JSON.stringify({
            payloadType: 2114, // SYMBOLS LIST
            clientMsgId: 'sym_req',
            payload: { ctidTraderAccountId: accountId, includeDailyBar: false }
        }));
    } else if (res.payloadType === 2115) {
        console.log('Symbols count:', res.payload.symbol ? res.payload.symbol.length : 'none');
        if (res.payload.symbol) {
             console.log('Sample:', res.payload.symbol[0]);
        }
        ws.close();
    } else if (res.payloadType === 2142) {
        console.log('Error 2142 Payload:', JSON.stringify(res));
    }
});
