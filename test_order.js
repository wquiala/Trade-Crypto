const WebSocket = require('ws');
require('dotenv').config();

const clientId = process.env.CTRADER_CLIENT_ID;
const clientSecret = process.env.CTRADER_CLIENT_SECRET;
const accessToken = process.env.CTRADER_ACCESS_TOKEN;
const accountId = parseInt(process.env.CTRADER_ACCOUNT_ID, 10);

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
    if (res.payloadType === 2101) {
        ws.send(JSON.stringify({
            payloadType: 2102, // ACCOUNT AUTH
            clientMsgId: 'auth_acc',
            payload: { ctidTraderAccountId: accountId, accessToken }
        }));
    } else if (res.payloadType === 2103) {
        // Send a new order req
        ws.send(JSON.stringify({
            payloadType: 2106, // NEW_ORDER_REQ
            clientMsgId: 'order_test',
            payload: {
                ctidTraderAccountId: accountId,
                symbolId: 1, // EURUSD
                orderType: 'MARKET',
                tradeSide: 'BUY',
                volume: 1000 // 0.01 lots
            }
        }));
    } else if (res.clientMsgId === 'order_test') {
        console.log('Order Response:', JSON.stringify(res, null, 2));
        ws.close();
    }
});
