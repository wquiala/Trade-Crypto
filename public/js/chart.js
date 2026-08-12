let chart = null;
let candleSeries = null;

function initChart() {
  const container = document.getElementById('trading-chart');
  if (!container) return;

  if (typeof LightweightCharts === 'undefined') {
    console.warn('[Chart] LightweightCharts no cargó desde CDN, reintentando...');
    container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#9ca3af;">⏳ Cargando motor de gráficos...</div>';
    setTimeout(initChart, 500);
    return;
  }

  container.innerHTML = ''; // Limpiar contenedor

  const width = container.clientWidth || 750;

  chart = LightweightCharts.createChart(container, {
    width: width,
    height: 380,
    layout: {
      background: { type: 'solid', color: '#111827' },
      textColor: '#9ca3af',
    },
    grid: {
      vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
      horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: 'rgba(255, 255, 255, 0.1)',
    },
    timeScale: {
      borderColor: 'rgba(255, 255, 255, 0.1)',
      timeVisible: true,
      secondsVisible: false,
    },
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: '#10b981',
    downColor: '#ef4444',
    borderDownColor: '#ef4444',
    borderUpColor: '#10b981',
    wickDownColor: '#ef4444',
    wickUpColor: '#10b981',
  });

  window.addEventListener('resize', () => {
    if (chart && container) {
      chart.applyOptions({ width: container.clientWidth || 750 });
    }
  });
}

function updateChartData(klines) {
  if (!candleSeries) {
    setTimeout(() => updateChartData(klines), 300);
    return;
  }
  if (!Array.isArray(klines) || klines.length === 0) return;
  const sorted = [...klines].sort((a, b) => a.time - b.time);
  candleSeries.setData(sorted);
  if (chart) chart.timeScale().fitContent();
}

function updateLastCandle(candle) {
  if (!candleSeries) return;
  candleSeries.update(candle);
}
