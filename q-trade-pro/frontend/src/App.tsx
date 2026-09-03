import { useEffect, useState } from 'react';
import axios from 'axios';
import { Activity, Wallet, ShieldAlert, Zap, TrendingUp, TrendingDown } from 'lucide-react';

// Usamos una ruta relativa para que Apache envíe las peticiones al puerto 8000 por detrás
const API_BASE = '/api';

function App() {
  const [status, setStatus] = useState<any>(null);
  const [scores, setScores] = useState<any>({});
  const [positions, setPositions] = useState<any>({});
  const [prices, setPrices] = useState<any>({});

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statusRes, scoresRes, posRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/market-scores`),
          axios.get(`${API_BASE}/positions`)
        ]);
        setStatus(statusRes.data);
        setScores(scoresRes.data.scores);
        setPrices(scoresRes.data.prices || {});
        setPositions(posRes.data.positions);
      } catch (error) {
        console.error("Error fetching data", error);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 2000); // Polling cada 2 segundos
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-background text-white p-6 flex flex-col gap-6">
      
      {/* HEADER */}
      <header className="flex items-center justify-between bg-panel backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-2xl">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-blue-500/20 rounded-xl">
            <Activity className="text-blue-400 w-8 h-8" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Q-Trade Pro</h1>
            <div className="flex items-center gap-2 mt-1">
              <span className="relative flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-neonGreen opacity-75"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-neonGreen"></span>
              </span>
              <span className="text-sm text-textMuted font-medium">Engine Running • Paper Trading</span>
            </div>
          </div>
        </div>

        <div className="flex gap-4">
          {status?.kill_switch_active && (
            <div className="flex items-center gap-2 px-4 py-2 bg-neonRed/20 border border-neonRed rounded-xl text-neonRed font-semibold animate-pulse">
              <ShieldAlert className="w-5 h-5" />
              KILL SWITCH ACTIVE
            </div>
          )}
          <div className="flex flex-col items-end px-6 py-2 bg-black/40 rounded-xl border border-white/5">
            <span className="text-sm text-textMuted font-medium flex items-center gap-2">
              <Wallet className="w-4 h-4" /> Capital
            </span>
            <span className="text-2xl font-mono font-bold text-white">
              ${status?.capital?.toFixed(2) || '0.00'}
            </span>
          </div>
          <div className="flex flex-col items-end px-6 py-2 bg-black/40 rounded-xl border border-white/5">
            <span className="text-sm text-textMuted font-medium flex items-center gap-2">
              <Activity className="w-4 h-4" /> PnL Diario
            </span>
            <span className={`text-2xl font-mono font-bold ${status?.daily_pnl >= 0 ? 'text-neonGreen' : 'text-neonRed'}`}>
              {status?.daily_pnl >= 0 ? '+' : ''}{status?.daily_pnl?.toFixed(2) || '0.00'} USDT
            </span>
          </div>
        </div>
      </header>

      {/* MAIN CONTENT */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1">
        
        {/* SCORES PANEL */}
        <div className="lg:col-span-1 bg-panel backdrop-blur-md border border-white/10 rounded-2xl p-6 flex flex-col gap-4">
          <h2 className="text-lg font-semibold flex items-center gap-2 border-b border-white/10 pb-4">
            <Zap className="w-5 h-5 text-yellow-400" />
            Market Scores
          </h2>
          <div className="flex flex-col gap-3">
            {Object.keys(scores).length === 0 ? (
              <div className="text-center text-textMuted py-8">Waiting for engine data...</div>
            ) : (
              Object.entries(scores).map(([symbol, data]: any) => (
                <div key={symbol} className="bg-black/40 rounded-xl p-4 border border-white/5 flex justify-between items-center transition-all hover:bg-black/60 cursor-default">
                  <div>
                    <h3 className="font-bold text-lg">{symbol.replace(':USDT', '')}</h3>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-textMuted font-mono uppercase bg-white/10 px-2 py-1 rounded-md inline-block">
                        {data.regime}
                      </span>
                      <span className="text-sm font-mono text-white/80">
                        ${prices[symbol]?.toFixed(4) || '---'}
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-col items-end">
                    <span className={`text-2xl font-black font-mono ${data.score >= 80 ? 'text-neonGreen' : 'text-white'}`}>
                      {data.score}
                    </span>
                    <span className="text-xs text-textMuted">Score</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* POSITIONS TABLE */}
        <div className="lg:col-span-2 bg-panel backdrop-blur-md border border-white/10 rounded-2xl p-6 flex flex-col gap-4">
          <h2 className="text-lg font-semibold border-b border-white/10 pb-4">
            Active Positions
          </h2>
          {Object.keys(positions).length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-textMuted flex-col gap-2">
              <Activity className="w-12 h-12 opacity-20" />
              <p>No active positions. Scanning market...</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="text-textMuted text-sm border-b border-white/10">
                    <th className="pb-3 font-medium">Symbol</th>
                    <th className="pb-3 font-medium">Side</th>
                    <th className="pb-3 font-medium">Entry</th>
                    <th className="pb-3 font-medium">Stop Loss</th>
                    <th className="pb-3 font-medium">Size</th>
                    <th className="pb-3 font-medium text-right">PnL</th>
                    <th className="pb-3 font-medium text-right">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(positions).map(([symbol, pos]: any) => (
                    <tr key={symbol} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                      <td className="py-4 font-bold">{symbol}</td>
                      <td className="py-4">
                        <span className={`flex items-center gap-1 font-bold ${pos.signal === 'LONG' ? 'text-neonGreen' : 'text-neonRed'}`}>
                          {pos.signal === 'LONG' ? <TrendingUp className="w-4 h-4"/> : <TrendingDown className="w-4 h-4"/>}
                          {pos.signal}
                        </span>
                      </td>
                      <td className="py-4 font-mono">${pos.entry_price.toFixed(4)}</td>
                      <td className="py-4 font-mono text-neonRed">${pos.stop_loss.toFixed(4)}</td>
                      <td className="py-4 font-mono">{pos.size.toFixed(4)}</td>
                      <td className="py-4 font-mono text-right font-bold">
                        <span className={pos.unrealized_pnl >= 0 ? 'text-neonGreen' : 'text-neonRed'}>
                          {pos.unrealized_pnl >= 0 ? '+' : ''}{pos.unrealized_pnl?.toFixed(2) || '0.00'} USDT
                        </span>
                        <div className={`text-xs ${pos.pnl_pct >= 0 ? 'text-neonGreen/70' : 'text-neonRed/70'}`}>
                          {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct?.toFixed(2) || '0.00'}%
                        </div>
                      </td>
                      <td className="py-4 text-right">
                        <div className="flex justify-end gap-2">
                          {pos.breakeven_triggered && (
                            <span className="bg-blue-500/20 text-blue-400 text-xs px-2 py-1 rounded-md font-medium border border-blue-500/30">
                              Breakeven
                            </span>
                          )}
                          {pos.partial_taken && (
                            <span className="bg-purple-500/20 text-purple-400 text-xs px-2 py-1 rounded-md font-medium border border-purple-500/30">
                              Partial Taken
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

      </div>

      {/* TRADE HISTORY ROW */}
      <div className="bg-panel backdrop-blur-md border border-white/10 rounded-2xl p-6 flex flex-col gap-4 mt-2">
        <h2 className="text-lg font-semibold border-b border-white/10 pb-4 flex items-center gap-2">
          <Activity className="w-5 h-5 text-purple-400" />
          Historial de Operaciones (Últimas 20)
        </h2>
        
        {(!status?.trade_history || status.trade_history.length === 0) ? (
          <div className="text-center text-textMuted py-8">No hay operaciones registradas aún.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="text-textMuted text-sm border-b border-white/10">
                  <th className="pb-3 font-medium">Fecha</th>
                  <th className="pb-3 font-medium">Par</th>
                  <th className="pb-3 font-medium">Dirección</th>
                  <th className="pb-3 font-medium text-right">Cantidad</th>
                  <th className="pb-3 font-medium text-right">Precio</th>
                  <th className="pb-3 font-medium text-right">Costo (USDT)</th>
                  <th className="pb-3 font-medium text-right">PnL Cerrado</th>
                </tr>
              </thead>
              <tbody>
                {status.trade_history.map((trade: any, idx: number) => {
                  const date = new Date(trade.timestamp).toLocaleString();
                  const isBuy = trade.side.toLowerCase() === 'buy';
                  const pnl = trade.realized_pnl || 0;
                  
                  return (
                    <tr key={idx} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                      <td className="py-4 text-sm text-textMuted">{date}</td>
                      <td className="py-4 font-bold">{trade.symbol}</td>
                      <td className="py-4">
                        <span className={`px-2 py-1 rounded-md text-xs font-bold ${isBuy ? 'bg-neonGreen/20 text-neonGreen' : 'bg-neonRed/20 text-neonRed'}`}>
                          {trade.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="py-4 font-mono text-right">{trade.amount}</td>
                      <td className="py-4 font-mono text-right">${trade.price?.toFixed(4) || '0.0000'}</td>
                      <td className="py-4 font-mono text-right">${trade.cost?.toFixed(2) || '0.00'}</td>
                      <td className={`py-4 font-mono text-right font-bold ${pnl >= 0 ? 'text-neonGreen' : 'text-neonRed'}`}>
                        {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} USDT
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
}

export default App;
