const WebSocket = require('ws');
const accessToken = "Z2Dn6FUiGrTTg12vMDWcayc5ZRl8NMzpji2ZKU2Di14";
const accountId = 48083214;
const ws = new WebSocket(`wss://demo.ctraderapi.com:5036`);

ws.on('open', () => {
    ws.send(JSON.stringify({
        payloadType: 2100,
        clientMsgId: 'auth_app',
        payload: { clientId: "34193_MDnQ7azhrFBfEcyL7rFqUEhgaNbvDQRx15knPF591f4XHD2ubT", clientSecret: "1USHLdC8u7h3zHKyhHbHcJFp75mqHEIgb5eqfs2iMjQkhZgVBA" }
    }));
});
ws.on('message', (data) => {
    const res = JSON.parse(data.toString());
    if (res.payloadType === 2101) {
        ws.send(JSON.stringify({
            payloadType: 2102,
            clientMsgId: 'auth_acc',
            payload: { ctidTraderAccountId: accountId, accessToken }
        }));
    } else if (res.payloadType === 2103) {
        ws.send(JSON.stringify({
            payloadType: 2121, // TRADER REQ
            clientMsgId: 'bal_req_2121',
            payload: { ctidTraderAccountId: accountId }
        }));
    } else if (res.payloadType === 2122) {
        console.log('Trader REQ (2121) Response:', JSON.stringify(res, null, 2));
        ws.close();
    } else if (res.clientMsgId === 'bal_req_2121') {
        console.log('Unexpected response for 2121:', JSON.stringify(res));
    }
});
