const WebSocket = require('ws');
require('dotenv').config();

const clientId = process.env.CTRADER_CLIENT_ID;
const clientSecret = process.env.CTRADER_CLIENT_SECRET;
const accountId = process.env.CTRADER_ACCOUNT_ID;
const accessToken = process.env.CTRADER_ACCESS_TOKEN;

const ws = new WebSocket('wss://demo.ctraderapi.com:5036');

ws.on('open', () => {
    console.log('Connected');
    const msg = {
        payloadType: 2100, // APPLICATION_AUTH_REQ
        clientMsgId: 'req_1',
        payload: {
            clientId: clientId,
            clientSecret: clientSecret
        }
    };
    ws.send(JSON.stringify(msg));
});

ws.on('message', (data) => {
    console.log('Received:', data.toString());
    const res = JSON.parse(data.toString());
    
    if (res.payloadType === 2101) { // 2101 is APPLICATION_AUTH_RES
        console.log('App Authed, sending Account Auth...');
        const msg2 = {
            payloadType: 2102, // ACCOUNT_AUTH_REQ
            clientMsgId: 'req_2',
            payload: {
                ctidTraderAccountId: parseInt(accountId, 10),
                accessToken: accessToken
            }
        };
        ws.send(JSON.stringify(msg2));
    } else if (res.payloadType === 2132 || res.payloadType === 2142) {
        console.log('Error:', res);
    }
});
