import pandas as pd
from typing import List, Dict

class MarketDataFetcher:
    """
    Simula la obtención y procesamiento de datos de mercado.
    En producción, esto se conectaría a ExchangeClient (ccxt).
    """
    
    @staticmethod
    def normalize_klines(raw_data: List[List]) -> pd.DataFrame:
        """
        Convierte la respuesta cruda OHLCV de ccxt a un DataFrame de pandas.
        
        Args:
            raw_data: Lista de listas [timestamp, open, high, low, close, volume]
        """
        df = pd.DataFrame(raw_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # Convertir a float
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
            
        return df

    @staticmethod
    def merge_timeframes(df_lower: pd.DataFrame, df_higher: pd.DataFrame, higher_tf: str = '1h') -> pd.DataFrame:
        """
        Fusiona indicadores de una temporalidad superior al DataFrame de temporalidad inferior,
        haciendo forward-fill (ffill) para evitar look-ahead bias.
        """
        # Asegurar que ambos índices son datetime
        # Renombrar columnas del TF superior para evitar conflictos
        df_higher_renamed = df_higher.add_suffix(f'_{higher_tf}')
        
        # Combinar usando asof merge o ffill
        df_merged = df_lower.join(df_higher_renamed, how='left').ffill()
        return df_merged
