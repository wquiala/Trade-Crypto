const WebSocket = require('ws');
require('dotenv').config();

const ws = new WebSocket(`wss://demo.ctraderapi.com:5036`);

ws.on('open', () => {
    console.log('Connected');
    ws.send(JSON.stringify({
        payloadType: 2100, // APP AUTH
        clientMsgId: 'test_1',
        payload: { 
            clientId: process.env.CTRADER_CLIENT_ID, 
            clientSecret: process.env.CTRADER_CLIENT_SECRET 
        }
    }));
});

ws.on('message', (data) => {
    console.log('Received:', data.toString());
    ws.close();
});

ws.on('error', (err) => {
    console.log('Error:', err.message);
});

setTimeout(() => {
    console.log('Timeout');
    ws.close();
}, 5000);
