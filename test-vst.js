const crypto = require('crypto');
const axios = require('axios');
const API_KEY = '305eAx6anAs9PDKH8TYPGxl5J64YdowYZMfxqztNZ1wsfeIRGFqoZUbOd9gfc08j2qp2nO59lyyvjg4nVOA';
const SECRET = 'G0vdnvJuDeyhHRnbXB9Ztn98vCyWsWNSvBt2ZUsIcWdNpM7WHwqBteoW2xasu1CFPorBs213ttJDAq3Gfg';
const baseUrl = 'https://open-api-vst.bingx.com';

const params = { timestamp: Date.now() };
const sortedKeys = Object.keys(params).sort();
const rawQueryString = sortedKeys.map(k => `${k}=${params[k]}`).join('&');
const signature = crypto.createHmac('sha256', SECRET).update(rawQueryString).digest('hex');
const encodedQueryString = sortedKeys.map(k => `${k}=${encodeURIComponent(params[k])}`).join('&');
const query = `${encodedQueryString}&signature=${signature}`;

axios.get(`${baseUrl}/openApi/swap/v2/user/balance?${query}`, { headers: { 'X-BX-APIKEY': API_KEY } })
  .then(res => console.log('VST Balance:', res.data))
  .catch(err => console.error('Error:', err.response ? err.response.data : err.message));
