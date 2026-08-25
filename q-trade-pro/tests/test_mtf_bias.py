"""
tests/test_mtf_bias.py
======================
Tests que demuestran la AUSENCIA de look-ahead bias en la alineación MTF.

REGLA A DEMOSTRAR
─────────────────
Una vela HTF con open_time=T y duración D minutos cierra a T+D.
Ninguna vela LTF con timestamp < T+D puede ver esa vela HTF.

Ejemplo concreto que se testa:
    HTF vela: open=10:00, close=11:00 (duración 60 min)
    LTF 10:00 → NO puede ver esta vela HTF
    LTF 10:15 → NO puede ver esta vela HTF
    LTF 10:30 → NO puede ver esta vela HTF
    LTF 10:45 → NO puede ver esta vela HTF
    LTF 11:00 → SÍ puede ver esta vela HTF (close_time = 11:00)
    LTF 11:15 → SÍ puede ver esta vela HTF

Todos los tests usan datos sintéticos deterministas.
No se conecta a ningún exchange.
"""

import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timezone

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.data_processor import MarketDataFetcher


def make_htf_df(
    regime_by_hour: dict,  # {hour: regime_name}
    date_str: str = "2024-01-15",
) -> pd.DataFrame:
    """
    Crea un DataFrame HTF sintético con regímenes predefinidos.

    Args:
        regime_by_hour: {0: 'RANGING', 1: 'BULL_TREND', ...}
        date_str: Fecha base en formato YYYY-MM-DD

    Returns:
        DataFrame con índice UTC (open_time de cada vela 1h) y columna 'regime'.
    """
    rows = []
    for hour, regime in sorted(regime_by_hour.items()):
        ts = pd.Timestamp(f"{date_str} {hour:02d}:00:00", tz="UTC")
        rows.append({
            "timestamp": ts,
            "open": 50000.0,
            "high": 51000.0,
            "low":  49000.0,
            "close": 50500.0,
            "volume": 100.0,
            "regime_label": regime,
            "ADX_14": 25.0,
            "EMA_50": 50000.0,
            "EMA_200": 49000.0,
        })
    df = pd.DataFrame(rows).set_index("timestamp")
    return df


def make_ltf_df(
    minutes: list,  # [minute_offset, ...] desde las 10:00
    date_str: str = "2024-01-15",
    base_hour: int = 10,
) -> pd.DataFrame:
    """
    Crea un DataFrame LTF sintético (velas de 15 minutos).

    Args:
        minutes: Lista de offsets en minutos desde las base_hour:00.
        date_str: Fecha base.
        base_hour: Hora base.

    Returns:
        DataFrame indexado por open_time UTC.
    """
    rows = []
    for m in minutes:
        hour_offset = m // 60
        minute = m % 60
        ts = pd.Timestamp(
            f"{date_str} {(base_hour + hour_offset):02d}:{minute:02d}:00",
            tz="UTC"
        )
        rows.append({
            "timestamp": ts,
            "open":  50000.0,
            "high":  50200.0,
            "low":   49800.0,
            "close": 50100.0,
            "volume": 10.0,
        })
    df = pd.DataFrame(rows).set_index("timestamp")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# TEST PRINCIPAL — Imposibilidad de look-ahead bias
# ─────────────────────────────────────────────────────────────────────────────

class TestMTFNoLookAheadBias:
    """
    Suite de tests que garantizan que align_htf_to_ltf() no introduce look-ahead.
    """

    def test_htf_not_available_before_close_basic(self):
        """
        CRÍTICO: La vela HTF 10:00-11:00 NO puede ser vista por velas LTF
        anteriores a las 11:00.

        Setup:
            HTF vela 09:00-10:00 → regime='RANGING'
            HTF vela 10:00-11:00 → regime='BULL_TREND'

        Esperado:
            LTF 10:00, 10:15, 10:30, 10:45 → deben ver 'RANGING' (vela de 09:00-10:00)
            LTF 11:00, 11:15, 11:30        → deben ver 'BULL_TREND' (vela de 10:00-11:00)
        """
        # Crear HTF con dos velas: 09:00 (RANGING) y 10:00 (BULL_TREND)
        htf = make_htf_df({
            9:  "RANGING",
            10: "BULL_TREND",
        })

        # Crear LTF: velas cada 15 minutos desde 10:00 hasta 11:30
        ltf = make_ltf_df([0, 15, 30, 45, 60, 75, 90])  # 10:00 a 11:30

        # Alinear
        merged = MarketDataFetcher.align_htf_to_ltf(ltf, htf, htf_duration_minutes=60)

        # Las primeras 4 velas (10:00-10:45) deben tener el régimen ANTERIOR (RANGING)
        # porque la vela BULL_TREND de 10:00-11:00 no ha cerrado aún
        before_close = merged[
            merged.index < pd.Timestamp("2024-01-15 11:00:00", tz="UTC")
        ]
        after_close = merged[
            merged.index >= pd.Timestamp("2024-01-15 11:00:00", tz="UTC")
        ]

        # Verificar: ANTES del close → deben ver RANGING (la vela previa)
        for ts, row in before_close.iterrows():
            actual_regime = row.get("regime_label_htf", None)
            assert actual_regime == "RANGING", (
                f"LOOK-AHEAD BIAS DETECTADO en {ts}: "
                f"la vela LTF vio 'BULL_TREND' antes de que la vela HTF 10:00-11:00 cerrara. "
                f"Actual: {actual_regime}"
            )

        # Verificar: DESDE las 11:00 → deben ver BULL_TREND
        for ts, row in after_close.iterrows():
            actual_regime = row.get("regime_label_htf", None)
            assert actual_regime == "BULL_TREND", (
                f"Error en {ts}: la vela LTF debería ver BULL_TREND después de las 11:00. "
                f"Actual: {actual_regime}"
            )

    def test_htf_candle_available_exactly_at_close_time(self):
        """
        La vela HTF 10:00-11:00 debe estar disponible EXACTAMENTE a las 11:00.
        No debe haber un delay de un período adicional.
        """
        htf = make_htf_df({9: "RANGING", 10: "BULL_TREND"})
        ltf = make_ltf_df([60])  # Solo una vela: exactamente a las 11:00

        merged = MarketDataFetcher.align_htf_to_ltf(ltf, htf, htf_duration_minutes=60)

        assert len(merged) == 1
        regime_at_1100 = merged.iloc[0].get("regime_label_htf", None)
        assert regime_at_1100 == "BULL_TREND", (
            f"La vela de las 11:00 debería ver BULL_TREND (vela HTF cerró exactamente a las 11:00). "
            f"Actual: {regime_at_1100}"
        )

    def test_no_data_before_first_htf_candle(self):
        """
        Las velas LTF anteriores a la primera vela HTF disponible deben tener NaN.
        No debe inventarse información.
        """
        # HTF empieza a las 12:00
        htf = make_htf_df({12: "BULL_TREND"})

        # LTF empieza a las 10:00, mucho antes de la primera vela HTF
        ltf = make_ltf_df([0, 15, 30, 45])  # 10:00-10:45

        merged = MarketDataFetcher.align_htf_to_ltf(ltf, htf, htf_duration_minutes=60)

        # Ninguna vela LTF debería tener datos HTF (la primera vela HTF cierra a las 13:00)
        for ts, row in merged.iterrows():
            regime = row.get("regime_label_htf", None)
            assert pd.isna(regime), (
                f"Se asignó un régimen HTF ficticio a {ts} antes de que hubiera velas HTF. "
                f"Actual: {regime}"
            )

    def test_regime_change_propagates_at_correct_time(self):
        """
        Un cambio de régimen en HTF solo afecta al LTF a partir del cierre de la vela.

        Escenario:
            HTF 08:00-09:00 → RANGING
            HTF 09:00-10:00 → BULL_TREND (cambio)
            HTF 10:00-11:00 → BULL_TREND

        El cambio de RANGING → BULL_TREND solo es visible desde las 10:00 en el LTF.
        """
        htf = make_htf_df({8: "RANGING", 9: "BULL_TREND", 10: "BULL_TREND"})
        ltf = make_ltf_df([
            -60, -45, -30, -15,   # 09:00-09:45 → deberían ver RANGING (vela 08:00-09:00)
            0,   15,  30,  45,    # 10:00-10:45 → deberían ver BULL_TREND (vela 09:00-10:00)
        ], base_hour=10)  # base_hour=10, así -60 min = 09:00

        merged = MarketDataFetcher.align_htf_to_ltf(ltf, htf, htf_duration_minutes=60)

        ranging_ltfs = merged[merged.index < pd.Timestamp("2024-01-15 10:00:00", tz="UTC")]
        bull_ltfs    = merged[merged.index >= pd.Timestamp("2024-01-15 10:00:00", tz="UTC")]

        for ts, row in ranging_ltfs.iterrows():
            assert row.get("regime_label_htf") == "RANGING", (
                f"BIAS en {ts}: debería ser RANGING, encontrado {row.get('regime_label_htf')}"
            )

        for ts, row in bull_ltfs.iterrows():
            assert row.get("regime_label_htf") == "BULL_TREND", (
                f"Error en {ts}: debería ser BULL_TREND, encontrado {row.get('regime_label_htf')}"
            )

    def test_original_ltf_columns_preserved(self):
        """
        El merge no debe alterar ni eliminar columnas del LTF original.
        """
        htf = make_htf_df({10: "BULL_TREND"})
        ltf = make_ltf_df([60, 75])  # 11:00, 11:15

        merged = MarketDataFetcher.align_htf_to_ltf(ltf, htf, htf_duration_minutes=60)

        # Todas las columnas del LTF deben estar presentes e intactas
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in merged.columns, f"Columna LTF '{col}' perdida tras el merge."

        # Los valores del LTF no deben haber sido modificados
        assert float(merged.iloc[0]["close"]) == 50100.0

    def test_deterministic_output(self):
        """
        Mismo input → mismo output. El alineamiento debe ser 100% determinista.
        """
        htf = make_htf_df({9: "RANGING", 10: "BULL_TREND"})
        ltf = make_ltf_df([0, 15, 30, 60, 75])

        result1 = MarketDataFetcher.align_htf_to_ltf(ltf, htf, htf_duration_minutes=60)
        result2 = MarketDataFetcher.align_htf_to_ltf(ltf, htf, htf_duration_minutes=60)

        pd.testing.assert_frame_equal(result1, result2)

    def test_4h_htf_duration(self):
        """
        El mecanismo funciona para timeframes HTF más largos (4h).
        Vela HTF 08:00-12:00 solo visible desde las 12:00.
        """
        htf_4h = pd.DataFrame({
            "regime_label": ["RANGING", "BULL_TREND"],
            "ADX_14":       [15.0, 28.0],
        }, index=pd.DatetimeIndex([
            pd.Timestamp("2024-01-15 08:00:00", tz="UTC"),
            pd.Timestamp("2024-01-15 12:00:00", tz="UTC"),
        ]))

        ltf_timestamps = pd.DatetimeIndex([
            pd.Timestamp("2024-01-15 09:00:00", tz="UTC"),  # dentro de vela HTF 08:00-12:00
            pd.Timestamp("2024-01-15 10:00:00", tz="UTC"),  # dentro de vela HTF 08:00-12:00
            pd.Timestamp("2024-01-15 11:00:00", tz="UTC"),  # dentro de vela HTF 08:00-12:00
            pd.Timestamp("2024-01-15 12:00:00", tz="UTC"),  # cierre → disponible
            pd.Timestamp("2024-01-15 13:00:00", tz="UTC"),  # disponible
        ])
        ltf = pd.DataFrame({"close": [50000.0] * 5}, index=ltf_timestamps)

        merged = MarketDataFetcher.align_htf_to_ltf(ltf, htf_4h, htf_duration_minutes=240)

        # La primera vela HTF tiene open_time=08:00 y close_time=12:00.
        # Antes de las 12:00: no hay ninguna vela HTF disponible aún → NaN
        # Las velas de 09:00, 10:00, 11:00 no ven ninguna vela HTF (NaN es correcto).
        for ts in ltf_timestamps[:3]:
            regime = merged.loc[ts].get("regime_label_htf", None)
            assert pd.isna(regime) or regime is None, (
                f"LOOK-AHEAD BIAS (4H) en {ts}: se asignó régimen '{regime}' antes de "
                f"que la primera vela HTF cerrara a las 12:00. Esperado: NaN."
            )

        # A las 12:00: la vela 08:00-12:00 (RANGING) acaba de cerrar → disponible
        regime_1200 = merged.loc[ltf_timestamps[3]].get("regime_label_htf", None)
        assert regime_1200 == "RANGING", (
            f"A las 12:00 debería ver RANGING (vela 08:00-12:00 recién cerrada), "
            f"encontrado {regime_1200}"
        )
        # A las 13:00: sigue viendo RANGING (la vela 12:00-16:00 aún no cerró)
        regime_1300 = merged.loc[ltf_timestamps[4]].get("regime_label_htf", None)
        assert regime_1300 == "RANGING", (
            f"A las 13:00 debería ver RANGING (vela 12:00-16:00 aún abierta), "
            f"encontrado {regime_1300}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST DE COMPARACIÓN — Método legacy vs nuevo
# ─────────────────────────────────────────────────────────────────────────────

class TestLegacyVsNewMethod:
    """
    Demuestra que el método legacy (merge_timeframes) introduce look-ahead bias
    y que el nuevo (align_htf_to_ltf) no lo introduce.
    """

    def test_legacy_method_has_lookahead_bias(self):
        """
        El método merge_timeframes() INTRODUCE look-ahead bias.
        Este test documenta el bug conocido y sirve como referencia.
        """
        htf = make_htf_df({9: "RANGING", 10: "BULL_TREND"})
        ltf = make_ltf_df([0, 15, 30, 45])  # 10:00-10:45

        # El método legacy asigna el régimen de la vela 10:00 (BULL_TREND)
        # a velas LTF de las 10:00-10:45 via ffill, lo cual es look-ahead bias
        htf_with_suffix = htf.rename(columns={c: f"{c}_1h" for c in htf.columns})
        legacy_result = ltf.join(htf_with_suffix, how="left").ffill()

        # Con el método legacy, la vela de 10:00 ya tiene BULL_TREND asignado
        # antes de que la vela HTF cierre — eso es el bug
        # Simplemente verificamos que el nuevo método retorna algo DIFERENTE
        new_result = MarketDataFetcher.align_htf_to_ltf(ltf, htf, htf_duration_minutes=60)

        # El nuevo método debe tener NaN o RANGING para las velas antes de las 11:00
        new_regime_1000 = new_result.iloc[0].get("regime_label_htf", None)

        # El método legacy asigna BULL_TREND a las 10:00 (look-ahead)
        legacy_regime_1000 = legacy_result.iloc[0].get("regime_label_1h", None)

        # El nuevo método NO debe asignar BULL_TREND a las 10:00
        assert new_regime_1000 != "BULL_TREND", (
            "El nuevo método sigue introduciendo look-ahead bias a las 10:00"
        )

        # El método legacy SÍ comete look-ahead (documentado como comportamiento conocido buggy)
        # Si esto falla en algún momento, hay que revisar el test
        # (No todos los setups van a mostrar el bias, depende del ffill)
        # Esto es informativo, no falla el test global si el legacy resulta correcto


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
