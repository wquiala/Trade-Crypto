import asyncio
import pandas as pd
from datetime import datetime, timedelta
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from backtest.backtester import Backtester
from config.config import BacktestConfig
from models.trade import TradeRecord

class Phase4Runner:
    def __init__(self, strategies):
        self.strategies = strategies
        # Para descargar datos reutilizamos la config base (6 meses)
        self.bt_cfg = BacktestConfig(backtest_months=6, entry_on="next_open", intrabar_policy="conservative")
        self.base_bt = Backtester(backtest_cfg=self.bt_cfg)
        
    async def load_data(self):
        print("📥 Descargando datos (6 meses)...")
        self.raw_data = await self.base_bt.download()
        self.aligned_data = {}
        for sym, raw in self.raw_data.items():
            df_15m, df_1h = self.base_bt._prepare_symbol_data(raw)
            if df_15m is not None and df_1h is not None:
                # Aprovechamos el alineador del backtester base
                df_aligned = self.base_bt._align_htf(df_15m, df_1h)
                self.aligned_data[sym] = {
                    "15m": df_15m,
                    "1h": df_1h,
                    "aligned": df_aligned
                }
        print(f"Datos preparados para {len(self.aligned_data)} símbolos.")
        
    def run(self):
        # 1. Split date
        dates = []
        for sym, d in self.aligned_data.items():
            dates.extend(d["15m"].index.tolist())
        start_date = min(dates)
        cutoff_date = start_date + timedelta(days=120) # 4 meses TRAIN
        
        results = {}
        
        for strategy in self.strategies:
            print(f"\n🚀 Ejecutando {strategy.name}...")
            all_trades = []
            
            for sym, d in self.aligned_data.items():
                df_15m = d["15m"]
                df_aligned = d["aligned"]
                
                signals = strategy.generate_signals(df_aligned, d["1h"])
                sym_trades = self._simulate_executions(sym, df_15m, signals)
                all_trades.extend(sym_trades)
                
            train_trades = [t for t in all_trades if t.entry_time < cutoff_date]
            val_trades = [t for t in all_trades if t.entry_time >= cutoff_date]
            
            results[strategy.name] = {
                "train": train_trades,
                "val": val_trades
            }
            
        return results

    def _simulate_executions(self, symbol, df_15m, signals):
        trades = []
        in_position = False
        trade_id_counter = 1
        
        fee_rate = 0.0005 # 0.05% taker
        slippage_pct = 0.0005 # 0.05% slippage
        sl_mult = 1.5
        tp_mult = 3.0
        
        capital = 1000.0
        
        # Necesitamos simular el trade barra a barra para detectar SL o TP
        for sig in signals:
            if in_position:
                continue # No abrir si ya estamos dentro
                
            entry_time = sig["time"]
            # La entrada real es a la apertura de la SIGUIENTE vela, que es sig["entry_price"]
            idx = df_15m.index.get_indexer([entry_time])[0]
            if idx == -1 or idx >= len(df_15m) - 1:
                continue
                
            entry_idx = idx + 1
            entry_bar = df_15m.iloc[entry_idx]
            entry_price_raw = sig["entry_price"]
            direction = sig["signal"]
            atr = sig["atr"]
            
            if atr == 0:
                continue
                
            # Calcular precios con fees
            if direction == "LONG":
                eff_entry = entry_price_raw * (1 + slippage_pct)
                sl = entry_price_raw - (atr * sl_mult)
                tp = entry_price_raw + (atr * tp_mult)
            else:
                eff_entry = entry_price_raw * (1 - slippage_pct)
                sl = entry_price_raw + (atr * sl_mult)
                tp = entry_price_raw - (atr * tp_mult)
                
            # Position sizing (1% riesgo)
            risk_amt = capital * 0.01
            risk_per_unit = abs(eff_entry - sl)
            if risk_per_unit == 0: continue
            size = risk_amt / risk_per_unit
            
            entry_fee_usd = (size * eff_entry) * fee_rate
            
            # Simular evolución del trade
            mfe_price = eff_entry
            mae_price = eff_entry
            exit_price = 0
            exit_time = None
            closed = False
            
            for j in range(entry_idx, len(df_15m)):
                bar = df_15m.iloc[j]
                high = bar["high"]
                low = bar["low"]
                
                # Actualizar MFE / MAE
                if direction == "LONG":
                    if high > mfe_price: mfe_price = high
                    if low < mae_price: mae_price = low
                else:
                    if low < mfe_price: mfe_price = low
                    if high > mae_price: mae_price = high
                    
                # Chequeo Conservative: si toca ambos, asumimos SL primero
                hit_sl = (low <= sl) if direction == "LONG" else (high >= sl)
                hit_tp = (high >= tp) if direction == "LONG" else (low <= tp)
                
                if hit_sl:
                    exit_price = sl
                    exit_time = bar.name
                    closed = True
                    break
                elif hit_tp:
                    exit_price = tp
                    exit_time = bar.name
                    closed = True
                    break
                    
            if not closed:
                exit_price = df_15m.iloc[-1]["close"]
                exit_time = df_15m.index[-1]
                
            # Calcular PnL
            if direction == "LONG":
                gross = (exit_price - eff_entry) * size
                exit_slip = exit_price * slippage_pct
            else:
                gross = (eff_entry - exit_price) * size
                exit_slip = exit_price * slippage_pct
                
            exit_fee = (size * exit_price) * fee_rate
            net = gross - entry_fee_usd - exit_fee - (size * exit_slip)
            
            # R multiples
            r_mult = net / risk_amt
            
            # MFE/MAE en R
            if direction == "LONG":
                mfe_r = (mfe_price - eff_entry) / risk_per_unit
                mae_r = (eff_entry - mae_price) / risk_per_unit
            else:
                mfe_r = (eff_entry - mfe_price) / risk_per_unit
                mae_r = (mae_price - eff_entry) / risk_per_unit
                
            trades.append(TradeRecord(
                trade_id=f"{symbol}_{trade_id_counter}",
                symbol=symbol,
                signal=direction,
                regime="UNKNOWN",
                score=100,
                signal_time=sig["time"],
                entry_time=entry_bar.name,
                exit_time=exit_time,
                entry_price=eff_entry,
                exit_price=exit_price,
                stop_loss=sl,
                take_profit=tp,
                size=size,
                risk_amount_usd=risk_amt,
                entry_fee_usd=entry_fee_usd,
                exit_fee_usd=exit_fee,
                entry_slippage_usd=(eff_entry - entry_price_raw) * size if direction == "LONG" else (entry_price_raw - eff_entry) * size,
                exit_slippage_usd=size * exit_slip,
                gross_pnl=gross,
                net_pnl=net,
                mfe=mfe_r,
                mae=mae_r,
                duration_bars=int((exit_time - entry_bar.name).total_seconds() / 900),
                entry_features=sig.get("features", {})
            ))
            trade_id_counter += 1
            capital += net
            
        return trades
