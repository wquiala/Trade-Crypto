import pandas as pd

class RegimeDetector:
    """
    Identifica el régimen de mercado actual utilizando la temporalidad superior (ej. 1h o 4h).
    """
    
    @staticmethod
    def detect(df_higher: pd.DataFrame) -> str:
        """
        Clasifica el estado del mercado evaluando la última vela cerradaAA.
        
        Regímenes posibles:
        - BULL_TREND: Precio sobre EMAs, ADX fuerte, EMA corta > EMA larga.
        - BEAR_TREND: Precio bajo EMAs, ADX fuerte, EMA corta < EMA larga.
        - RANGING: ADX débil, precio oscilando.
        - EXTREME_VOLATILITY: ATR/Volatilidad por encima del percentil crítico.
        """
        if df_higher.empty:
            return 'UNKNOWN'
            
        # Usar la última vela CERRADA (iloc[-2]) para no operar con velas incompletas en formación
        last_row = df_higher.iloc[-2] if len(df_higher) >= 2 else df_higher.iloc[-1]
        
        adx = last_row.get('ADX_14', 0)
        ema50 = last_row.get('EMA_50', 0)
        ema200 = last_row.get('EMA_200', 0)
        close = last_row.get('close', 0)
        
        # 1. Filtro de Alta Volatilidad (Chop o Extremo)
        # Podría implementarse con percentiles históricos de ATR
        
        # 2. Ranging (Mercado Lateral)
        if adx < 13:
            return 'RANGING'
            
        # 3. Tendencias (ADX >= 25 para asegurar fuerza real)
        if adx >= 25:
            if close > ema50 and ema50 > ema200:
                return 'BULL_TREND'
            elif close < ema50 and ema50 < ema200:
                return 'BEAR_TREND'
                
        # Si no entra en reglas estrictas, es transición
        return 'TRANSITION'
