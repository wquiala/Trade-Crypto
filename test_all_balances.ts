import crypto from 'crypto';
import axios from 'axios';
import dotenv from 'dotenv';

dotenv.config();

const apiKey = process.env.BINGX_API_KEY || '';
const secretKey = process.env.BINGX_SECRET_KEY || '';
const baseUrl = process.env.BINGX_API_URL || 'https://open-api.bingx.com';

function sign(queryString: string): string {
  return crypto
    .createHmac('sha256', secretKey)
    .update(queryString)
    .digest('hex');
}

function getSignedParams(params: Record<string, any> = {}): string {
  const timestamp = Date.now();
  const allParams: Record<string, any> = { ...params, timestamp };
  const sortedKeys = Object.keys(allParams).sort();
  const queryString = sortedKeys
    .map((key) => `${key}=${encodeURIComponent(allParams[key])}`)
    .join('&');

  const signature = sign(queryString);
  return `${queryString}&signature=${signature}`;
}

async function testAllBalances() {
  console.log('Inspeccionando todos los monederos de BingX (Spot, Futuros Perpetuos, Futuros Estándar, Fondos)...');

  // 1. Swap V2 Balance (Perpetual Futures)
  try {
    const query = getSignedParams();
    const res = await axios.get(`${baseUrl}/openApi/swap/v2/user/balance?${query}`, {
      headers: { 'X-BX-APIKEY': apiKey }
    });
    console.log('\n--- 1. Futuros Perpetuos (Swap v2) ---');
    console.log(JSON.stringify(res.data, null, 2));
  } catch (err: any) {
    console.error('Swap V2 Error:', err?.response?.data || err.message);
  }

  // 2. Spot V1 Account Assets / Balance
  try {
    const query = getSignedParams();
    const res = await axios.get(`${baseUrl}/openApi/spot/v1/account/balance?${query}`, {
      headers: { 'X-BX-APIKEY': apiKey }
    });
    console.log('\n--- 2. Cuenta Spot (v1) ---');
    console.log(JSON.stringify(res.data, null, 2));
  } catch (err: any) {
    console.error('Spot V1 Error:', err?.response?.data || err.message);
  }

  // 3. Standard Futures Balance (Std Futures)
  try {
    const query = getSignedParams();
    const res = await axios.get(`${baseUrl}/openApi/contract/v1/user/balance?${query}`, {
      headers: { 'X-BX-APIKEY': apiKey }
    });
    console.log('\n--- 3. Futuros Estándar (Contract v1) ---');
    console.log(JSON.stringify(res.data, null, 2));
  } catch (err: any) {
    console.error('Std Futures Error:', err?.response?.data || err.message);
  }

  // 4. Asset Transfer / Capital Fund assets
  try {
    const query = getSignedParams();
    const res = await axios.get(`${baseUrl}/openApi/wallets/v1/capital/config/getall?${query}`, {
      headers: { 'X-BX-APIKEY': apiKey }
    });
    console.log('\n--- 4. Wallets Config / Capital ---');
    console.log(JSON.stringify(res.data, null, 2));
  } catch (err: any) {
    console.error('Wallets Error:', err?.response?.data || err.message);
  }
}

testAllBalances();
