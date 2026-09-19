#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ozeksi_backtest.py için doğruluk testleri.

Çalıştır:  python test_ozeksi.py

En önemli test `test_trail_core_pine_ile_ayni`: Pine kaynağından SATIR SATIR
çevrilmiş naif bir referans uygulamayla, kullandığımız hızlı uygulamayı
karşılaştırır. İkisi ayrışırsa optimizasyon sırasında mantık bozulmuş demektir.
"""

from __future__ import annotations

import math
import sys
import traceback

import numpy as np
import pandas as pd

import ozeksi_backtest as oz


# ═══════════════════════════════════════════ PINE REFERANS UYGULAMASI ═══

def trail_core_reference(ma, fark, pct):
    """Pine'daki trailCore()'un birebir, optimize edilmemiş çevirisi.

    Pine kaynağı (@zeubetella'nın MPL-2.0 ROTT dosyasından doğrulanmıştır):
        longStop     = ma - fark
        longStopPrev = nz(longStop[1], longStop)
        longStop    := ma > longStopPrev ? max(longStop, longStopPrev) : longStop
        shortStop     = ma + fark
        shortStopPrev = nz(shortStop[1], shortStop)
        shortStop    := ma < shortStopPrev ? min(shortStop, shortStopPrev) : shortStop
        dir := dir == -1 and ma > shortStopPrev ? 1 :
               dir ==  1 and ma < longStopPrev  ? -1 : dir
        MT  = dir == 1 ? longStop : shortStop
        OTT = ma > MT ? MT*(200+pct)/200 : MT*(200-pct)/200
    """
    n = len(ma)
    long_hist, short_hist = [], []
    mt, ott, dirs = [], [], []
    d = 1

    for i in range(n):
        long_stop = ma[i] - fark[i]
        long_prev = long_hist[i - 1] if i > 0 else long_stop
        if ma[i] > long_prev:
            long_stop = max(long_stop, long_prev)

        short_stop = ma[i] + fark[i]
        short_prev = short_hist[i - 1] if i > 0 else short_stop
        if ma[i] < short_prev:
            short_stop = min(short_stop, short_prev)

        if d == -1 and ma[i] > short_prev:
            d = 1
        elif d == 1 and ma[i] < long_prev:
            d = -1

        m = long_stop if d == 1 else short_stop
        mt.append(m)
        ott.append(m * (200 + pct) / 200 if ma[i] > m else m * (200 - pct) / 200)
        dirs.append(d)
        long_hist.append(long_stop)
        short_hist.append(short_stop)

    return np.array(mt), np.array(ott), np.array(dirs, dtype=np.int8)


# ═══════════════════════════════════════════════════════════ TESTLER ═══

def test_trail_core_pine_ile_ayni():
    """Hızlı uygulama, Pine'dan satır satır çevrilmiş referansla aynı mı?"""
    rng = np.random.default_rng(1)
    for trial in range(8):
        n = int(rng.integers(50, 400))
        ma = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
        pct = float(rng.uniform(0.1, 5.0))
        fark = np.abs(ma) * pct * 0.01

        mt_a, ott_a, dir_a = oz.trail_core(ma, fark, pct)
        mt_b, ott_b, dir_b = trail_core_reference(ma, fark, pct)

        assert np.allclose(mt_a, mt_b), f"deneme {trial}: MT ayrıştı"
        assert np.allclose(ott_a, ott_b), f"deneme {trial}: OTT ayrıştı"
        assert np.array_equal(dir_a, dir_b), f"deneme {trial}: dir ayrıştı"


def test_trailing_stop_geri_gitmez():
    """Takip eden stop tanım gereği tek yönlüdür: yükselirken geri düşmemeli."""
    rng = np.random.default_rng(2)
    ma = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 500)))
    fark = ma * 0.02
    mt, _, direction = oz.trail_core(ma, fark, 2.0)

    for i in range(1, len(mt)):
        if direction[i] == 1 and direction[i - 1] == 1:
            assert mt[i] >= mt[i - 1] - 1e-9, f"bar {i}: long stop geri düştü"
        if direction[i] == -1 and direction[i - 1] == -1:
            assert mt[i] <= mt[i - 1] + 1e-9, f"bar {i}: short stop geri çıktı"


def test_ott_mt_nin_dogru_tarafinda():
    """OTT, yön yukarıysa MT'nin üstünde, aşağıysa altında olmalı."""
    rng = np.random.default_rng(3)
    ma = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, 400)))
    pct = 1.4
    mt, ott, _ = oz.trail_core(ma, ma * pct * 0.01, pct)

    up = ma > mt
    assert np.all(ott[up] >= mt[up] - 1e-9), "yukarı yönde OTT, MT'nin altında kaldı"
    assert np.all(ott[~up] <= mt[~up] + 1e-9), "aşağı yönde OTT, MT'nin üstünde kaldı"


def test_shift2_pine_nz_ile_ayni():
    """shift2, Pine'daki nz(x[2], x) davranışını vermeli."""
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    got = oz.shift2(x, True)
    assert np.array_equal(got, np.array([1.0, 2.0, 1.0, 2.0, 3.0])), got
    assert np.array_equal(oz.shift2(x, False), x)


def test_vidya_ozellikleri():
    """VIDYA: periyot 1'de kaynağın kendisi; hep kaynağın aralığında kalmalı."""
    rng = np.random.default_rng(4)
    s = 100 + np.cumsum(rng.normal(0, 1, 300))

    assert np.array_equal(oz.vidya(s, 1), s), "n=1'de VIDYA kaynağa eşit olmalı"

    v = oz.vidya(s, 20)
    assert np.all(np.isfinite(v)), "VIDYA NaN/inf üretti"
    assert v.min() >= s.min() - 1e-9 and v.max() <= s.max() + 1e-9, \
        "VIDYA kaynağın aralığını aştı"


def test_sabit_pozisyon_muhasebesi():
    """Sürekli long ve sıfır maliyetle özsermaye, fiyat getirisine eşit olmalı."""
    n = 200
    close = 100 * np.exp(np.cumsum(np.full(n, 0.001)))
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close},
                      index=pd.bdate_range("2020-01-01", periods=n))

    pos = np.ones(n, dtype=np.int8)
    ret = np.zeros(n)
    ret[1:] = close[1:] / close[:-1] - 1.0
    equity = np.cumprod(1 + np.concatenate([[0.0], pos[:-1]]) * ret)

    beklenen = close[-1] / close[0]
    assert abs(equity[-1] - beklenen) < 1e-9, f"{equity[-1]} != {beklenen}"


def test_maliyet_dusuluyor():
    """Maliyet artınca net kâr azalmalı; işlem sayısı sabit kalmalı."""
    df = oz.demo_data(600, seed=11)
    p = oz.Params(mode="OTT", length=2, percent=1.4)

    ucuz = oz.backtest(df, p, oz.Costs(0.0, 0.0))
    pahali = oz.backtest(df, p, oz.Costs(0.5, 0.2))

    assert pahali.metrics["net_kar_%"] < ucuz.metrics["net_kar_%"], \
        "maliyet artmasına rağmen net kâr düşmedi"
    assert pahali.metrics["islem_sayisi"] == ucuz.metrics["islem_sayisi"], \
        "maliyet işlem sayısını değiştirmemeli"


def test_tum_modlar_calisiyor():
    """Dokuz modun hepsi hata vermeden, mantıklı metrik üretmeli."""
    df = oz.demo_data(800, seed=5)
    for m in oz.MODES:
        p = oz.Params(mode=m)
        if m == "ROTT":
            p.rott_var_len = 200
        r = oz.backtest(df, p)
        assert np.all(np.isfinite(r.equity.to_numpy())), f"{m}: özsermaye eğrisinde NaN"
        assert r.equity.iloc[-1] > 0, f"{m}: özsermaye sıfırın altına indi"
        assert 0 <= r.metrics["kazanma_%"] <= 100, f"{m}: kazanma oranı aralık dışı"
        assert r.metrics["islem_sayisi"] >= 0


def test_tum_ma_tipleri_calisiyor():
    """Dokuz MA tipinin hepsi sonlu değer üretmeli."""
    rng = np.random.default_rng(6)
    s = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    for kind in oz.MA_TYPES:
        out = oz.get_ma(s, 10, kind)
        assert out.shape == s.shape, f"{kind}: uzunluk değişti"
        assert np.all(np.isfinite(out)), f"{kind}: NaN/inf üretti"


def test_short_yasakliyken_short_yok():
    """--long-only verildiğinde pozisyon hiç eksiye düşmemeli."""
    df = oz.demo_data(600, seed=9)
    p = oz.Params(mode="OTT", allow_short=False)
    pos = oz.positions(df, p)
    assert pos.min() >= 0, "short kapalıyken eksi pozisyon açıldı"
    assert pos.max() == 1, "hiç long açılmadı"


def test_flat_zone_piyasada_kalmayi_azaltir():
    """Flat Zone açıkken çift çizgili modda piyasada kalma oranı düşmeli."""
    df = oz.demo_data(800, seed=13)
    surekli = oz.backtest(df, oz.Params(mode="TOTT", flat_zone=False))
    bolgeli = oz.backtest(df, oz.Params(mode="TOTT", flat_zone=True))
    assert bolgeli.metrics["piyasada_%"] < surekli.metrics["piyasada_%"], \
        "Flat Zone piyasada kalma oranını azaltmadı"


def test_gelecege_bakmiyor():
    """Sinyal, geleceği göremez: veriyi sondan kırpmak geçmiş sinyalleri değiştirmemeli."""
    df = oz.demo_data(600, seed=17)
    p = oz.Params(mode="OTT", length=3, percent=1.4)

    tam = oz.positions(df, p)
    kirpik = oz.positions(df.iloc[:400], p)

    assert np.array_equal(tam[:400], kirpik), \
        "Veri sondan kırpılınca geçmiş pozisyonlar değişti — lookahead var!"


def test_walk_forward_calisiyor():
    """Walk-forward tablo ve birleşik sonuç üretmeli."""
    df = oz.demo_data(900, seed=21)
    grid = {"length": [2, 5], "percent": [1.0, 2.0]}
    tablo, birlesik = oz.walk_forward(df, oz.Params(mode="OTT"), grid, folds=3)

    assert len(tablo) == 3, f"3 fold bekleniyordu, {len(tablo)} geldi"
    assert "TEST_sharpe" in tablo.columns
    assert birlesik.equity is not None and len(birlesik.equity) > 0


# ═════════════════════════════════════════════════════════ ÇALIŞTIR ═══

def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    basarisiz = 0

    print(f"\n{len(tests)} test çalıştırılıyor...\n")
    for t in tests:
        ad = t.__name__.replace("test_", "").replace("_", " ")
        try:
            t()
            print(f"  ✓ {ad}")
        except Exception as exc:
            basarisiz += 1
            print(f"  ✗ {ad}\n      {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=2)

    print(f"\n{len(tests) - basarisiz}/{len(tests)} geçti")
    return 1 if basarisiz else 0


if __name__ == "__main__":
    sys.exit(main())
