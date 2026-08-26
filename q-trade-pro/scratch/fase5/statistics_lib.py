import numpy as np
import scipy.stats as stats
import pandas as pd

def calculate_correlations(df, pred_col, target_col):
    """Calcula Pearson y Spearman entre una feature y el forward return"""
    valid = df[[pred_col, target_col]].dropna()
    if len(valid) < 30:
        return {"pearson": 0, "p_pearson": 1, "spearman": 0, "p_spearman": 1, "n": len(valid)}
        
    p_corr, p_pval = stats.pearsonr(valid[pred_col], valid[target_col])
    s_corr, s_pval = stats.spearmanr(valid[pred_col], valid[target_col])
    
    return {
        "pearson": p_corr,
        "p_pearson": p_pval,
        "spearman": s_corr,
        "p_spearman": s_pval,
        "n": len(valid)
    }

def calculate_bucket_stats(df, target_col):
    """Calcula estadísticas para un bucket específico de datos"""
    ret = df[target_col].dropna()
    n = len(ret)
    if n < 30:
        return {"n": n, "mean": 0, "std": 0, "win_prob": 0, "ci_lower": 0, "ci_upper": 0, "significance": "INCONCLUSIVE"}
        
    mean = ret.mean()
    std = ret.std()
    win_prob = (ret > 0).mean()
    
    se = std / np.sqrt(n)
    ci = stats.t.interval(0.95, n-1, loc=mean, scale=se)
    
    # Test contra media 0
    t_stat, p_val = stats.ttest_1samp(ret, 0)
    
    if p_val < 0.05 and mean > 0:
        sig = "POSITIVE"
    elif p_val < 0.05 and mean < 0:
        sig = "NEGATIVE"
    else:
        sig = "NULL"
        
    # Asignar niveles de muestra
    if n < 100: sig += " (Débil)"
    elif n > 300: sig += " (Fuerte)"
    
    return {
        "n": n,
        "mean": mean * 100, # en porcentaje
        "std": std * 100,
        "win_prob": win_prob * 100,
        "ci_lower": ci[0] * 100,
        "ci_upper": ci[1] * 100,
        "p_value": p_val,
        "significance": sig
    }
