import asyncio
import pandas as pd
import numpy as np
import sys

sys.path.append("/Users/iwilfredo/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Trading y bolsa/Trade-Crypto/q-trade-pro")

from scratch.fase5.dataset import Fase5Dataset

def calculate_benchmarks(dataset: Fase5Dataset):
    print("--- BENCHMARKS FASE 5 ---")
    
    horizons = [1, 2, 4, 8, 16, 32, 48]
    all_data = pd.concat(dataset.data.values(), ignore_index=True)
    
    # Buy and Hold (Media de todos los retornos)
    print("\n[A] Buy & Hold (Distribución incondicional)")
    for h in horizons:
        col = f'fwd_ret_{h}'
        ret = all_data[col].dropna()
        if not ret.empty:
            mean = ret.mean() * 100
            median = ret.median() * 100
            std = ret.std() * 100
            win_prob = (ret > 0).mean() * 100
            print(f"Horizonte +{h} velas:")
            print(f"  Media: {mean:.4f}% | Mediana: {median:.4f}% | Std: {std:.4f}% | Win Prob: {win_prob:.2f}%")
            
    # Random con y sin costes
    print("\n[B] Random Entry (Con y Sin Costes)")
    taker_fee = 0.0005 # 0.05%
    slippage = 0.0005  # 0.05%
    friccion_total = (taker_fee + slippage) * 2 # Entrada y Salida = 0.20% total
    
    for h in horizons:
        col = f'fwd_ret_{h}'
        ret = all_data[col].dropna()
        if not ret.empty:
            # En random, la mitad son LONG y la mitad SHORT. 
            # El retorno esperado bruto de un LONG random es la media del mercado.
            # El retorno esperado bruto de un SHORT random es la inversa de la media del mercado.
            # Promedio de ambos = 0.
            
            # Simulamos 100,000 entradas aleatorias
            np.random.seed(42)
            n_samples = min(100000, len(ret))
            samples = np.random.choice(ret, size=n_samples, replace=False)
            directions = np.random.choice([1, -1], size=n_samples) # 1=LONG, -1=SHORT
            
            # Retorno bruto
            gross_returns = samples * directions
            mean_gross = gross_returns.mean() * 100
            
            # Retorno neto
            net_returns = gross_returns - friccion_total
            mean_net = net_returns.mean() * 100
            
            print(f"Horizonte +{h} velas:")
            print(f"  Random RAW (sin costes): {mean_gross:.4f}%")
            print(f"  Random NET (con costes): {mean_net:.4f}%")
            
    print("\n--- FIN BENCHMARKS ---")

async def main():
    dataset = Fase5Dataset()
    await dataset.load_and_prepare()
    calculate_benchmarks(dataset)

if __name__ == "__main__":
    asyncio.run(main())
