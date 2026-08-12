let currentSymbol = 'BTC-USDT';
let currentSide = 'LONG';
let currentAccountBalance = 10000;
let currentMarketPrice = 0;

document.addEventListener('DOMContentLoaded', () => {
  initChart();
  setupEventListeners();
  connectWebSocket();
  loadKlinesAndAnalysis();
  loadPositions();
  fetchTradeHistory();
  loadBotStatus();
});

function setupEventListeners() {
  // Selector de Par
  const symbolSelect = document.getElementById('symbol-select');
  if (symbolSelect) {
    symbolSelect.addEventListener('change', (e) => {
      currentSymbol = e.target.value;
      loadKlinesAndAnalysis();
    });
  }

  // Selector LONG / SHORT
  const btnLong = document.getElementById('btn-select-long');
  const btnShort = document.getElementById('btn-select-short');
  const btnSubmit = document.getElementById('btn-submit-order');

  btnLong.addEventListener('click', () => {
    currentSide = 'LONG';
    btnLong.classList.add('active');
    btnShort.classList.remove('active');
    btnSubmit.style.background = 'linear-gradient(135deg, var(--green-buy), #059669)';
    btnSubmit.style.boxShadow = '0 4px 14px var(--green-glow)';
    recalculateRisk();
  });

  btnShort.addEventListener('click', () => {
    currentSide = 'SHORT';
    btnShort.classList.add('active');
    btnLong.classList.remove('active');
    btnSubmit.style.background = 'linear-gradient(135deg, var(--red-sell), #dc2626)';
    btnSubmit.style.boxShadow = '0 4px 14px var(--red-glow)';
    recalculateRisk();
  });

  // Re-calcular riesgo dinámicamente al cambiar inputs
  ['input-risk-percent', 'input-leverage', 'input-entry-price', 'input-stop-loss', 'input-take-profit'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', recalculateRisk);
    }
  });

  // Ejecución de Orden
  btnSubmit.addEventListener('click', executeOrder);

  // Actualizar posiciones
  document.getElementById('btn-refresh-positions').addEventListener('click', loadPositions);

  // Switch de Bot
  document.getElementById('toggle-bot-active').addEventListener('change', updateBotStatus);
  document.getElementById('toggle-auto-trade').addEventListener('change', updateBotStatus);
}

// Conectar a WebSockets del Servidor local
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}`;
  const ws = new WebSocket(wsUrl);

  const statusEl = document.getElementById('ws-status');

  ws.onopen = () => {
    if (statusEl) statusEl.innerHTML = '● Conectado';
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'MARKET_TICKER' && msg.data) {
        const { btc, eth, sol, avax, link, paxg, bnb, xrp, doge, sui, balance } = msg.data;

        if (btc && document.getElementById('header-btc-price')) {
          document.getElementById('header-btc-price').innerText = `$${btc.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
          if (currentSymbol === 'BTC-USDT') currentMarketPrice = btc.price;
        }

        if (eth && document.getElementById('header-eth-price')) {
          document.getElementById('header-eth-price').innerText = `$${eth.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
          if (currentSymbol === 'ETH-USDT') currentMarketPrice = eth.price;
        }

        if (sol && document.getElementById('header-sol-price')) {
          document.getElementById('header-sol-price').innerText = `$${sol.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
          if (currentSymbol === 'SOL-USDT') currentMarketPrice = sol.price;
        }

        if (avax && document.getElementById('header-avax-price')) {
          document.getElementById('header-avax-price').innerText = `$${avax.price.toLocaleString(undefined, { minimumFractionDigits: 3 })}`;
          if (currentSymbol === 'AVAX-USDT') currentMarketPrice = avax.price;
        }

        if (link && document.getElementById('header-link-price')) {
          document.getElementById('header-link-price').innerText = `$${link.price.toLocaleString(undefined, { minimumFractionDigits: 3 })}`;
          if (currentSymbol === 'LINK-USDT') currentMarketPrice = link.price;
        }

        if (paxg && document.getElementById('header-paxg-price')) {
          document.getElementById('header-paxg-price').innerText = `$${paxg.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
          if (currentSymbol === 'PAXG-USDT') currentMarketPrice = paxg.price;
        }

        if (bnb && document.getElementById('header-bnb-price')) {
          document.getElementById('header-bnb-price').innerText = `$${bnb.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
          if (currentSymbol === 'BNB-USDT') currentMarketPrice = bnb.price;
        }

        if (xrp && document.getElementById('header-xrp-price')) {
          document.getElementById('header-xrp-price').innerText = `$${xrp.price.toLocaleString(undefined, { minimumFractionDigits: 4 })}`;
          if (currentSymbol === 'XRP-USDT') currentMarketPrice = xrp.price;
        }

        if (doge && document.getElementById('header-doge-price')) {
          document.getElementById('header-doge-price').innerText = `$${doge.price.toLocaleString(undefined, { minimumFractionDigits: 5 })}`;
          if (currentSymbol === 'DOGE-USDT') currentMarketPrice = doge.price;
        }

        if (sui && document.getElementById('header-sui-price')) {
          document.getElementById('header-sui-price').innerText = `$${sui.price.toLocaleString(undefined, { minimumFractionDigits: 4 })}`;
          if (currentSymbol === 'SUI-USDT') currentMarketPrice = sui.price;
        }

        if (balance) {
          currentAccountBalance = typeof balance.available === 'number' ? balance.available : 0;
          document.getElementById('user-balance-display').innerText = `Saldo (${balance.asset}): $${currentAccountBalance.toFixed(2)}`;

          const badge = document.getElementById('account-mode-badge');
          if (badge) {
            if (balance.isRealAccount) {
              badge.innerText = `🟢 BINGX CONECTADO ${balance.shortUid ? '(UID: ' + balance.shortUid + ')' : ''}`;
              badge.style.background = 'rgba(16, 185, 129, 0.15)';
              badge.style.color = '#10b981';
              badge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
            } else {
              badge.innerText = 'MODO DEMO (VST)';
              badge.style.background = 'rgba(245, 158, 11, 0.15)';
              badge.style.color = '#f59e0b';
              badge.style.border = '1px solid rgba(245, 158, 11, 0.3)';
            }
          }

          const pnlTextEl = document.getElementById('daily-pnl-text');
          const pnlBoxEl = document.getElementById('header-daily-pnl');
          if (pnlTextEl && pnlBoxEl) {
            let pnlVal = 0;
            let displayStr = '';
            if (msg.data.realizedToday && typeof msg.data.realizedToday.realizedNetPnL === 'number') {
              pnlVal = msg.data.realizedToday.realizedNetPnL;
              const sign = pnlVal >= 0 ? '+' : '';
              const count = msg.data.realizedToday.closedOrdersCount || 0;
              displayStr = `${sign}$${pnlVal.toFixed(2)} USD (${count} op.)`;
            } else if (typeof msg.data.startOfDayEquity === 'number' && msg.data.startOfDayEquity > 0) {
              const startEq = msg.data.startOfDayEquity;
              const currentEq = typeof balance.equity === 'number' ? balance.equity : balance.available;
              pnlVal = currentEq - startEq;
              const sign = pnlVal >= 0 ? '+' : '';
              displayStr = `${sign}$${pnlVal.toFixed(2)} USD`;
            }

            if (displayStr) {
              pnlTextEl.innerText = displayStr;
              if (pnlVal >= 0) {
                pnlTextEl.style.color = '#10b981';
                pnlBoxEl.style.background = 'rgba(16, 185, 129, 0.1)';
                pnlBoxEl.style.borderColor = 'rgba(16, 185, 129, 0.35)';
              } else {
                pnlTextEl.style.color = '#ef4444';
                pnlBoxEl.style.background = 'rgba(239, 68, 68, 0.1)';
                pnlBoxEl.style.borderColor = 'rgba(239, 68, 68, 0.35)';
              }
            }
          }
        }

        if (msg.data.positions && Array.isArray(msg.data.positions)) {
          renderPositionsTable(msg.data.positions);
        }
      }
    } catch (err) {
      console.error('Error parsing WS message', err);
    }
  };

  ws.onclose = () => {
    if (statusEl) statusEl.innerHTML = '○ Desconectado (Reintentando...)';
    setTimeout(connectWebSocket, 3000);
  };
}

// Cargar Klines y Análisis Técnico desde el backend
async function loadKlinesAndAnalysis() {
  try {
    const resKlines = await fetch(`/api/market/klines?symbol=${currentSymbol}&interval=15m&limit=100`);
    const dataKlines = await resKlines.json();

    if (dataKlines.success && Array.isArray(dataKlines.data)) {
      updateChartData(dataKlines.data);
    }

    const resAnalysis = await fetch(`/api/market/analysis?symbol=${currentSymbol}`);
    const dataAnalysis = await resAnalysis.json();

    if (dataAnalysis.success && dataAnalysis.data) {
      const a = dataAnalysis.data;
      document.getElementById('metric-rsi').innerText = a.rsi;
      const adxEl = document.getElementById('metric-adx');
      if (adxEl && a.adx !== undefined) {
        adxEl.innerText = Number(a.adx).toFixed(1);
        adxEl.style.color = a.adx >= 20 ? '#00C076' : '#999999';
      }
      document.getElementById('metric-ema20').innerText = `$${a.ema20}`;
      document.getElementById('metric-ema50').innerText = `$${a.ema50}`;
      document.getElementById('metric-macd').innerText = a.macd.histogram;

      const badge = document.getElementById('signal-badge-container');
      if (badge) {
        badge.innerText = a.signal.replace('_', ' ');
        badge.className = `signal-badge signal-${a.signal}`;
      }

      // Sugerir precios por defecto si los campos están vacíos
      if (!document.getElementById('input-entry-price').value) {
        document.getElementById('input-entry-price').value = a.currentPrice;
      }
      if (!document.getElementById('input-stop-loss').value) {
        const slSuggestion = currentSide === 'LONG' ? a.currentPrice * 0.985 : a.currentPrice * 1.015;
        document.getElementById('input-stop-loss').value = parseFloat(slSuggestion.toFixed(2));
      }
      if (!document.getElementById('input-take-profit').value) {
        const tpSuggestion = currentSide === 'LONG' ? a.currentPrice * 1.03 : a.currentPrice * 0.97;
        document.getElementById('input-take-profit').value = parseFloat(tpSuggestion.toFixed(2));
      }

      recalculateRisk();
    }
  } catch (err) {
    console.error('Error loading market data:', err);
  }
}

// Recalcular Riesgo usando la API del backend
async function recalculateRisk() {
  const riskPercent = document.getElementById('input-risk-percent').value || '0.5';
  const leverage = document.getElementById('input-leverage').value || '10';
  const entryPrice = document.getElementById('input-entry-price').value || currentMarketPrice;
  const stopLoss = document.getElementById('input-stop-loss').value;
  const takeProfit = document.getElementById('input-take-profit').value;

  if (!entryPrice || !stopLoss) return;

  try {
    const res = await fetch('/api/trade/calculate-risk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        riskPercentage: riskPercent,
        entryPrice,
        stopLossPrice: stopLoss,
        takeProfitPrice: takeProfit,
        leverage,
        positionSide: currentSide,
      }),
    });

    const result = await res.json();

    if (result.success && result.data) {
      const d = result.data;
      document.getElementById('calc-max-risk').innerText = `$${d.maxRiskAmountUSDT.toFixed(2)} (${riskPercent}%)`;
      document.getElementById('calc-position-coins').innerText = `${d.positionSizeCoins} ${currentSymbol.split('-')[0]}`;
      document.getElementById('calc-margin-needed').innerText = `$${d.marginRequiredUSDT.toFixed(2)}`;
      document.getElementById('calc-rr-ratio').innerText = d.riskRewardRatio > 0 ? `1 : ${d.riskRewardRatio}` : 'N/A';
    }
  } catch (err) {
    console.error('Error calculating risk:', err);
  }
}

// Enviar Orden
async function executeOrder() {
  const feedback = document.getElementById('order-feedback');
  feedback.innerHTML = '⏳ Procesando orden...';
  feedback.style.color = 'var(--text-muted)';

  const riskPercent = document.getElementById('input-risk-percent').value || '0.5';
  const leverage = document.getElementById('input-leverage').value || '10';
  const entryPrice = document.getElementById('input-entry-price').value || currentMarketPrice;
  const stopLoss = document.getElementById('input-stop-loss').value;
  const takeProfit = document.getElementById('input-take-profit').value;

  // Primero obtener la cantidad recomendada según la calculadora de riesgo
  const calcRes = await fetch('/api/trade/calculate-risk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      riskPercentage: riskPercent,
      entryPrice,
      stopLossPrice: stopLoss,
      takeProfitPrice: takeProfit,
      leverage,
      positionSide: currentSide,
    }),
  });

  const calcData = await calcRes.json();
  if (!calcData.success || !calcData.data) {
    feedback.innerHTML = '❌ Error al calcular tamaño de orden';
    feedback.style.color = 'var(--red-sell)';
    return;
  }

  const quantity = calcData.data.positionSizeCoins;

  try {
    const orderRes = await fetch('/api/trade/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: currentSymbol,
        side: currentSide === 'LONG' ? 'BUY' : 'SELL',
        positionSide: currentSide,
        type: 'MARKET',
        quantity,
        stopLoss,
        takeProfit,
        leverage,
      }),
    });

    const orderData = await orderRes.json();

    if (orderData.success) {
      feedback.innerHTML = `✅ ${orderData.message}`;
      feedback.style.color = 'var(--green-buy)';
      loadPositions();
    } else {
      feedback.innerHTML = `❌ ${orderData.message}`;
      feedback.style.color = 'var(--red-sell)';
    }
  } catch (err) {
    feedback.innerHTML = `❌ Error al conectar con el servidor`;
    feedback.style.color = 'var(--red-sell)';
  }
}

function renderPositionsTable(positions) {
  const tbody = document.getElementById('positions-table-body');
  if (!tbody) return;

  if (Array.isArray(positions) && positions.length > 0) {
    tbody.innerHTML = positions.map((p) => {
      const pnlColor = p.unrealizedProfit >= 0 ? 'var(--green-buy)' : 'var(--red-sell)';
      const pnlSign = p.unrealizedProfit >= 0 ? '+' : '';
      return `
        <tr>
          <td><strong>${p.symbol}</strong></td>
          <td><span style="color: ${p.positionSide === 'LONG' ? 'var(--green-buy)' : 'var(--red-sell)'}">${p.positionSide} ${p.leverage}x</span></td>
          <td>$${p.entryPrice}</td>
          <td>$${p.markPrice}</td>
          <td>${p.amount}</td>
          <td>$${p.margin}</td>
          <td style="color: ${pnlColor}; font-weight: 700;">${pnlSign}$${p.unrealizedProfit}</td>
          <td style="font-size: 11px;">
            <div style="color: var(--green-buy);">TP: ${p.takeProfit ? '$'+p.takeProfit : '--'}</div>
            <div style="color: var(--red-sell);">SL: ${p.stopLoss ? '$'+p.stopLoss : '--'}</div>
          </td>
          <td><button class="btn-close-pos" onclick="closePosition('${p.symbol}', '${p.positionSide}')">Cerrar</button></td>
        </tr>
      `;
    }).join('');
  } else {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 20px;">Sin posiciones abiertas</td></tr>`;
  }
}

// Cargar Posiciones Activas
async function loadPositions() {
  try {
    const res = await fetch('/api/trade/positions');
    const data = await res.json();
    if (data.success && Array.isArray(data.data)) {
      renderPositionsTable(data.data);
    }
  } catch (err) {
    console.error('Error loading positions:', err);
  }
}

// Cerrar Posición
async function closePosition(symbol, positionSide) {
  try {
    const res = await fetch('/api/trade/close-position', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, positionSide }),
    });

    const data = await res.json();
    if (data.success) {
      alert(`✅ ${data.message}`);
      loadPositions();
    } else {
      alert(`❌ ${data.message}`);
    }
  } catch (err) {
    alert('Error al cerrar posición');
  }
}

// Cargar Estado del Bot
async function loadBotStatus() {
  try {
    const res = await fetch('/api/bot/status');
    const data = await res.json();
    if (data.success && data.data) {
      document.getElementById('toggle-bot-active').checked = data.data.isAutoBotActive;
      document.getElementById('toggle-auto-trade').checked = data.data.autoTradeEnabled;
    }
  } catch (err) {}
}

// Actualizar Estado del Bot
async function updateBotStatus() {
  const active = document.getElementById('toggle-bot-active').checked;
  const autoTrade = document.getElementById('toggle-auto-trade').checked;

  try {
    await fetch('/api/bot/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        active,
        autoTrade,
        symbol: currentSymbol,
      }),
    });
  } catch (err) {}
}

// Cargar Historial de Operaciones
async function fetchTradeHistory() {
  const tbody = document.getElementById('history-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">Cargando historial...</td></tr>`;

  try {
    const res = await fetch('/api/trade/history?limit=20');
    const data = await res.json();

    if (data.success && Array.isArray(data.data) && data.data.length > 0) {
      let totalPnl = 0;
      
      tbody.innerHTML = data.data.map(t => {
        const netPnl = parseFloat(t.netProfit || 0);
        totalPnl += netPnl;
        
        const pnlColor = netPnl > 0 ? 'var(--green-buy)' : (netPnl < 0 ? 'var(--red-sell)' : 'var(--text-main)');
        const pnlSign = netPnl > 0 ? '+' : '';
        const sideColor = t.positionSide === 'LONG' ? 'var(--green-buy)' : 'var(--red-sell)';
        
        // Formatear Fecha
        const dateObj = new Date(t.time);
        const dateStr = dateObj.toLocaleDateString() + ' ' + dateObj.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});

        return `
          <tr>
            <td style="color: var(--text-muted); font-size: 12px;">${dateStr}</td>
            <td style="font-weight: 500;">${t.symbol}</td>
            <td style="color: ${sideColor}; font-weight: bold;">${t.positionSide}</td>
            <td>$${t.price.toFixed(4)}</td>
            <td>${t.quantity}</td>
            <td style="color: var(--red-sell); font-size: 12px;">$${t.commission.toFixed(4)}</td>
            <td style="text-align: right; color: ${pnlColor}; font-weight: 700;">${pnlSign}$${netPnl.toFixed(4)}</td>
          </tr>
        `;
      }).join('');
      
      const pnlDisplay = document.getElementById('history-total-pnl');
      if (pnlDisplay) {
        pnlDisplay.textContent = `${totalPnl > 0 ? '+' : ''}$${totalPnl.toFixed(2)}`;
        pnlDisplay.style.color = totalPnl > 0 ? 'var(--green-buy)' : (totalPnl < 0 ? 'var(--red-sell)' : 'var(--text-main)');
      }
      
    } else {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">No hay operaciones cerradas recientes.</td></tr>`;
      const pnlDisplay = document.getElementById('history-total-pnl');
      if (pnlDisplay) {
         pnlDisplay.textContent = '$0.00';
         pnlDisplay.style.color = 'var(--text-main)';
      }
    }
  } catch (err) {
    console.error('Error fetching trade history:', err);
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--red-sell); padding: 20px;">Error al cargar historial</td></tr>`;
  }
}
