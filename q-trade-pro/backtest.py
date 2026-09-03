"""
Backtest vectorizado Q-Trade Pro.
Genera señales en batch (sin look-ahead) y simula trades con pandas.
Tarda ~30-60 segundos en total.
"""
import asyncio, sys
import pandas as pd
import numpy as np
from dotenv import load_dotenv
load_dotenv()

from core.data_processor import MarketDataFetcher
from core.feature_engine import FeatureEngine
import ccxt.async_support as ccxt

SYMBOLS = [
    'BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT',
    'XRP/USDT','ADA/USDT','DOGE/USDT','AVAX/USDT','LINK/USDT'
]
INITIAL_CAPITAL = 55_000.0
RISK_PCT        = 0.01
SL_MULT         = 1.5
TP_MULT         = 3.0
MONTHS          = 6
PAGE_LIMIT      = 1440

# ─── Descarga ─────────────────────────────────────────────────────────────────
async def fetch_all(exchange, symbol, tf, months):
    since = int((pd.Timestamp.now(tz='UTC') - pd.DateOffset(months=months)).timestamp()*1000)
    out = []
    while True:
        batch = await exchange.fetch_ohlcv(symbol, tf, since=since, limit=PAGE_LIMIT)
        if not batch: break
        out.extend(batch)
        if len(batch) < PAGE_LIMIT: break
        since = batch[-1][0] + 1
        await asyncio.sleep(0.2)
    return out

async def download():
    print("📥 Descargando datos históricos de Binance...")
    exc = ccxt.binance({'enableRateLimit': True})
    data = {}
    for sym in SYMBOLS:
        try:
            print(f"   {sym}...", end=' ', flush=True)
            r15 = await fetch_all(exc, sym, '15m', MONTHS)
            r1h = await fetch_all(exc, sym, '1h',  MONTHS)
            data[sym] = {'15m': r15, '1h': r1h}
            print(f"✓ {len(r15)} velas")
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"✗ {e}")
    await exc.close()
    return data

# ─── Generación vectorizada de señales ───────────────────────────────────────
def compute_signals(df15: pd.DataFrame, df1h: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica la misma lógica del ScoringEngine pero de forma vectorizada.
    Devuelve un DataFrame con columnas: signal, score, sl_dist, atr
    """
    # Indicadores 15m (ya calculados por FeatureEngine)
    d = df15.copy()

    # Régimen en 1h: asignar a cada vela 15m el régimen de la última vela 1h anterior
    # usando merge_asof (no hay look-ahead porque usamos la última vela 1h CERRADA)
    regime_map = []
    for ts, row in df1h.iterrows():
        adx   = row.get('ADX_14', 0)
        ema50 = row.get('EMA_50', 0)
        ema200= row.get('EMA_200', 0)
        close = row.get('close', 0)
        if adx < 13:
            reg = 'RANGING'
        elif adx >= 25 and close > ema50 and ema50 > ema200:
            reg = 'BULL_TREND'
        elif adx >= 25 and close < ema50 and ema50 < ema200:
            reg = 'BEAR_TREND'
        else:
            reg = 'TRANSITION'
        regime_map.append({'timestamp': ts, 'regime': reg})

    df_reg = pd.DataFrame(regime_map).set_index('timestamp').sort_index()
    # Asignar régimen a cada vela 15m via merge_asof
    d = d.sort_index()
    d['regime'] = pd.merge_asof(
        d[[]],
        df_reg,
        left_index=True,
        right_index=True,
        direction='backward'
    )['regime'].fillna('TRANSITION')

    # Indicadores
    rsi        = d['RSI_14']
    macd_h     = d['MACDh_12_26_9']
    macd_h_prev= macd_h.shift(1)
    close      = d['close']
    ema20      = d['EMA_20']
    ema50      = d['EMA_50']
    adx        = d['ADX_14']
    atr        = d['ATRr_14']
    bbu        = d['BBU_20_2.0']
    bbl        = d['BBL_20_2.0']
    regime     = d['regime']

    # ── BULL_TREND: LONG ──────────────────────────────────────────────────────
    bull = regime == 'BULL_TREND'
    bull_adx_ok   = adx >= 20
    bull_structure = (close > ema20) & (ema20 > ema50)
    bull_rsi_ideal = (rsi >= 35) & (rsi <= 55)
    bull_rsi_ok    = (rsi > 55)  & (rsi <= 65)
    bull_rsi_bad   = rsi > 70
    bull_macd_best = (macd_h > 0) & (macd_h > macd_h_prev)
    bull_macd_ok   = (macd_h > 0) & ~bull_macd_best
    bull_macd_turn = (macd_h <= 0) & (macd_h > macd_h_prev)

    bull_score = pd.Series(0.0, index=d.index)
    bull_score[bull & (adx >= 25)]         += 20
    bull_score[bull & (adx >= 20) & (adx < 25)] += 10
    bull_score[bull & bull_structure]      += 20
    bull_score[bull & (close > ema20) & ~bull_structure] += 10
    bull_score[bull & bull_rsi_ideal]      += 25
    bull_score[bull & bull_rsi_ok]         += 10
    bull_score[bull & bull_rsi_bad]        -= 30
    bull_score[bull & (rsi < 30)]          -= 20
    bull_score[bull & bull_macd_best]      += 25
    bull_score[bull & bull_macd_ok]        += 15
    bull_score[bull & bull_macd_turn]      += 5
    bull_score[bull & ~bull_adx_ok]        = 0

    # ── BEAR_TREND: SHORT ─────────────────────────────────────────────────────
    bear = regime == 'BEAR_TREND'
    bear_adx_ok    = adx >= 20
    bear_structure = (close < ema20) & (ema20 < ema50)
    bear_rsi_ideal = (rsi >= 45) & (rsi <= 65)
    bear_rsi_ok    = (rsi >= 35) & (rsi < 45)
    bear_rsi_bad   = rsi < 30
    bear_macd_best = (macd_h < 0) & (macd_h < macd_h_prev)
    bear_macd_ok   = (macd_h < 0) & ~bear_macd_best
    bear_macd_turn = (macd_h >= 0) & (macd_h < macd_h_prev)

    bear_score = pd.Series(0.0, index=d.index)
    bear_score[bear & (adx >= 25)]         += 20
    bear_score[bear & (adx >= 20) & (adx < 25)] += 10
    bear_score[bear & bear_structure]      += 20
    bear_score[bear & (close < ema20) & ~bear_structure] += 10
    bear_score[bear & bear_rsi_ideal]      += 25
    bear_score[bear & bear_rsi_ok]         += 10
    bear_score[bear & bear_rsi_bad]        -= 30
    bear_score[bear & (rsi > 70)]          -= 20
    bear_score[bear & bear_macd_best]      += 25
    bear_score[bear & bear_macd_ok]        += 15
    bear_score[bear & bear_macd_turn]      += 5
    bear_score[bear & ~bear_adx_ok]        = 0

    # ── RANGING ───────────────────────────────────────────────────────────────
    rang = regime == 'RANGING'
    rang_long_score  = pd.Series(0.0, index=d.index)
    rang_short_score = pd.Series(0.0, index=d.index)
    at_lower = rang & (close <= bbl)
    at_upper = rang & (close >= bbu)
    rang_long_score[at_lower]                    += 50
    rang_long_score[at_lower & (rsi < 35)]       += 30
    rang_long_score[at_lower & (rsi >= 35) & (rsi < 45)] += 15
    rang_long_score[at_lower & (macd_h > macd_h_prev)]   += 10
    rang_short_score[at_upper]                   += 50
    rang_short_score[at_upper & (rsi > 65)]      += 30
    rang_short_score[at_upper & (rsi > 55) & (rsi <= 65)] += 15
    rang_short_score[at_upper & (macd_h < macd_h_prev)]  += 10

    # ── Señal final ───────────────────────────────────────────────────────────
    signal = pd.Series('NEUTRAL', index=d.index)
    score  = pd.Series(0.0, index=d.index)

    long_mask  = (bull & (bull_score  >= 80)) | (rang & (rang_long_score  >= 80))
    short_mask = (bear & (bear_score  >= 80)) | (rang & (rang_short_score >= 80))
    # Transición → score 0
    signal[long_mask]  = 'LONG'
    signal[short_mask] = 'SHORT'
    score[bull] = bull_score[bull].clip(0, 100)
    score[bear] = bear_score[bear].clip(0, 100)
    score[rang & at_lower] = rang_long_score[rang & at_lower].clip(0, 100)
    score[rang & at_upper] = rang_short_score[rang & at_upper].clip(0, 100)

    out = pd.DataFrame({'signal': signal, 'score': score, 'atr': atr, 'close': close, 'regime': regime})
    return out

# ─── Simulación de trades ─────────────────────────────────────────────────────
def simulate(all_signals: dict, all_15m: dict) -> dict:
    print("\n⚙️  Simulando trades...")
    capital  = INITIAL_CAPITAL
    trades   = []
    equity   = [capital]

    # Construir tabla de eventos: para cada señal en cada símbolo, generar un trade
    all_trade_events = []
    for sym, sig_df in all_signals.items():
        df15 = all_15m[sym]
        entries = sig_df[sig_df['signal'] != 'NEUTRAL'].copy()
        if entries.empty:
            continue

        # Filtrar entradas consecutivas del mismo símbolo (cooldown de 4 velas = 1h)
        valid = []
        last_bar = -999
        for i, (ts, row) in enumerate(entries.iterrows()):
            bar_idx = df15.index.get_loc(ts) if ts in df15.index else -1
            if bar_idx < 0: continue
            if bar_idx - last_bar < 4: continue
            valid.append({'ts': ts, 'bar': bar_idx, 'signal': row['signal'],
                          'atr': row['atr'], 'close': row['close'], 'symbol': sym,
                          'regime': row['regime']})
            last_bar = bar_idx

        all_trade_events.extend(valid)

    # Ordenar todos los eventos por tiempo
    all_trade_events.sort(key=lambda x: x['ts'])

    open_pos = {}  # sym → {entry, sl, tp, size, signal, bar}

    def check_closes(current_bar, df15_map):
        nonlocal capital
        for sym in list(open_pos.keys()):
            pos = open_pos[sym]
            df  = df15_map[sym]
            if current_bar >= len(df): continue
            high  = float(df.iloc[current_bar]['high'])
            low   = float(df.iloc[current_bar]['low'])
            hit_sl = hit_tp = False
            exit_p = 0.0

            if pos['signal'] == 'LONG':
                if low  <= pos['sl']: hit_sl, exit_p = True, pos['sl']
                elif high >= pos['tp']: hit_tp, exit_p = True, pos['tp']
                pnl_dir = 1
            else:
                if high >= pos['sl']: hit_sl, exit_p = True, pos['sl']
                elif low  <= pos['tp']: hit_tp, exit_p = True, pos['tp']
                pnl_dir = -1

            if hit_sl or hit_tp:
                pnl = (exit_p - pos['entry']) * pos['size'] * pnl_dir
                capital += pnl
                trades.append({
                    'symbol': sym, 'signal': pos['signal'],
                    'entry': pos['entry'], 'exit': exit_p, 'pnl': pnl,
                    'result': 'TP' if hit_tp else 'SL',
                    'duration_h': (current_bar - pos['bar']) * 15 / 60,
                    'regime': pos['regime']
                })
                del open_pos[sym]
                equity.append(capital)

    df15_by_sym = {sym: df for sym, df in all_15m.items()}

    for ev in all_trade_events:
        sym = ev['symbol']
        bar = ev['bar']

        # Comprobar cierres en todas las posiciones abiertas hasta este bar
        max_bar = max((p['bar'] for p in open_pos.values()), default=bar)
        for b in range(max_bar, bar + 1):
            check_closes(b, df15_by_sym)

        if sym in open_pos: continue
        if len(open_pos) >= 5: continue
        same_dir = sum(1 for p in open_pos.values() if p['signal'] == ev['signal'])
        if same_dir >= 3: continue

        entry = ev['close']
        atr   = ev['atr']
        if atr <= 0: continue
        sl_d  = atr * SL_MULT
        tp_d  = atr * TP_MULT
        size  = (capital * RISK_PCT) / sl_d if sl_d > 0 else 0
        if size <= 0: continue

        sl = entry - sl_d if ev['signal'] == 'LONG' else entry + sl_d
        tp = entry + tp_d if ev['signal'] == 'LONG' else entry - tp_d

        open_pos[sym] = {'entry': entry, 'sl': sl, 'tp': tp, 'size': size,
                         'signal': ev['signal'], 'bar': bar, 'regime': ev['regime']}

    # Forzar cierre de posiciones abiertas al final
    for sym, pos in open_pos.items():
        df  = df15_by_sym.get(sym)
        if df is None: continue
        last = float(df.iloc[-1]['close'])
        pnl  = (last - pos['entry']) * pos['size'] if pos['signal'] == 'LONG' \
               else (pos['entry'] - last) * pos['size']
        capital += pnl
        trades.append({'symbol': sym, 'signal': pos['signal'], 'entry': pos['entry'],
                       'exit': last, 'pnl': pnl, 'result': 'OPEN',
                       'duration_h': 0, 'regime': pos['regime']})
    equity.append(capital)
    return {'trades': trades, 'equity': equity, 'final_capital': capital}

def print_stats(result):
    df    = pd.DataFrame(result['trades'])
    final = result['final_capital']
    if df.empty:
        print("⚠️  Sin operaciones."); return

    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    wr     = len(wins)/len(df)*100
    avg_w  = wins['pnl'].mean()   if len(wins)   > 0 else 0
    avg_l  = losses['pnl'].mean() if len(losses) > 0 else 0
    rr     = abs(avg_w/avg_l)     if avg_l != 0 else 0
    pf     = wins['pnl'].sum()/abs(losses['pnl'].sum()) if losses['pnl'].sum() != 0 else 0
    eq     = pd.Series(result['equity'])
    max_dd = ((eq - eq.cummax())/eq.cummax()*100).min()

    print("\n" + "═"*62)
    print("        RESULTADOS DEL BACKTEST — Q-Trade Pro")
    print("═"*62)
    print(f"  Capital inicial:       ${INITIAL_CAPITAL:>12,.2f}")
    print(f"  Capital final:         ${final:>12,.2f}   ({(final/INITIAL_CAPITAL-1)*100:+.2f}%)")
    print(f"  PnL neto:              ${df['pnl'].sum():>+12,.2f}")
    print("─"*62)
    print(f"  Total operaciones:     {len(df):>12}")
    print(f"  Ganadoras:             {len(wins):>9} ({wr:.1f}%)")
    print(f"  Perdedoras:            {len(losses):>9} ({100-wr:.1f}%)")
    print(f"  Ganancia media:        ${avg_w:>+12,.2f}")
    print(f"  Pérdida media:         ${avg_l:>+12,.2f}")
    print(f"  Ratio R:B real:        {rr:>12.2f}x")
    print(f"  Factor de beneficio:   {pf:>12.2f}x  (>1.0 = rentable)")
    print(f"  Drawdown máximo:       {max_dd:>11.2f}%")
    print("─"*62)
    by_sym = df.groupby('symbol')['pnl'].sum().sort_values(ascending=False)
    print("  PnL por símbolo:")
    for s,p in by_sym.items():
        print(f"    {s:15} ${p:>+10,.2f}  {'🟢' if p>0 else '🔴'}")
    print("─"*62)
    by_reg = df.groupby('regime')[['pnl']].agg(['sum','count'])
    by_reg.columns = ['pnl','n']
    print("  PnL por régimen:")
    for reg,row in by_reg.iterrows():
        print(f"    {reg:20} ${row['pnl']:>+10,.2f}  ({int(row['n'])} trades)")
    print("═"*62)
    v = "✅ CON EDGE" if pf>1.2 and wr>35 else "🟡 MARGINAL" if pf>1.0 else "🔴 SIN EDGE — ajustar estrategia"
    print(f"  VEREDICTO: {v}")
    print("═"*62+"\n")

async def main():
    print("="*62)
    print("   BACKTEST — Q-Trade Pro | 6 meses  (vectorizado)")
    print("="*62)
    data = await download()
    if not data:
        print("❌ Sin datos."); return

    print("\n⚙️  Calculando indicadores (puede tardar 30s)...")
    all_signals, all_15m = {}, {}
    for sym_bot, raw in data.items():
        sym_short = sym_bot.replace('/USDT','').replace(':USDT','')
        sym_key   = sym_bot
        df15 = FeatureEngine.compute(MarketDataFetcher.normalize_klines(raw['15m']))
        df1h = FeatureEngine.compute(MarketDataFetcher.normalize_klines(raw['1h']))
        sigs = compute_signals(df15, df1h)
        all_signals[sym_bot] = sigs
        all_15m[sym_bot]     = df15
        n_signals = (sigs['signal'] != 'NEUTRAL').sum()
        print(f"   {sym_bot:20} {n_signals} señales detectadas")

    result = simulate(all_signals, all_15m)
    print_stats(result)

if __name__ == '__main__':
    asyncio.run(main())
