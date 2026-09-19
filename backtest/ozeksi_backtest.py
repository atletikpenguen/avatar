#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anıl Özekşi trend göstergeleri — Python backtest ve parametre tarama motoru.

Pine dosyalarının (../pine/) birebir Python karşılığıdır: aynı OTT çekirdeği,
aynı sinyal kuralları, aynı emir mantığı. Amaç TradingView'de elle 5 kombinasyon
denemek yerine yüzlercesini otomatik test etmek ve — asıl önemlisi —
walk-forward ile aşırı optimizasyonu (overfitting) ayıklamaktır.

Orijinal gösterge fikirleri : Anıl Özekşi (Matriks Trader)
Pine uyarlamaları          : Kıvanç Özbilgiç, @zeubetella (MPL-2.0)

Eğitim ve araştırma amaçlıdır. Yatırım tavsiyesi değildir.

Kullanım
--------
    # Hemen dene (sentetik veri üretir, dosya gerekmez)
    python ozeksi_backtest.py --demo

    # Kendi CSV'nle tek backtest
    python ozeksi_backtest.py --csv THYAO.csv --mode OTT --length 2 --percent 1.4

    # Parametre taraması
    python ozeksi_backtest.py --csv THYAO.csv --mode OTT --sweep

    # Walk-forward (dürüst sonuç budur)
    python ozeksi_backtest.py --csv THYAO.csv --mode OTT --walk-forward

CSV formatı: date,open,high,low,close[,volume] başlıklı, artan tarih sıralı.
"""

from __future__ import annotations

import argparse
import itertools
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd

MODES = ["OTT", "TOTT", "OTT Bands", "MOST", "PMax", "BOOTS", "HOTT/LOTT", "OTTO", "ROTT"]
MA_TYPES = ["SMA", "EMA", "WMA", "TMA", "VAR", "WWMA", "ZLEMA", "TSF", "HULL"]
TWO_LINE_MODES = {"TOTT", "OTT Bands", "BOOTS", "HOTT/LOTT"}


# ══════════════════════════════════════════════ HAREKETLİ ORTALAMALAR ═══

def sma(s: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(s).rolling(n, min_periods=1).mean().to_numpy()


def ema(s: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(s).ewm(span=n, adjust=False).mean().to_numpy()


def wma(s: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    w = np.arange(1, n + 1, dtype=float)
    return (
        pd.Series(s)
        .rolling(n, min_periods=1)
        .apply(lambda x: np.dot(x, w[-len(x):]) / w[-len(x):].sum(), raw=True)
        .to_numpy()
    )


def tma(s: np.ndarray, n: int) -> np.ndarray:
    return sma(sma(s, math.ceil(n / 2)), math.floor(n / 2) + 1)


def vidya(s: np.ndarray, n: int) -> np.ndarray:
    """VAR / VIDYA — CMO(9) ile modüle edilen uyarlanabilir ortalama.

    Pine karşılığı (@zeubetella'nın ROTT kaynağıyla doğrulanmış):
        alpha = 2 / (n + 1)
        vidya = |CMO(9)| * alpha * (fiyat - vidya[1]) + vidya[1]
    """
    s = np.asarray(s, dtype=float)
    if n == 1:
        return s.copy()

    d = np.diff(s, prepend=s[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    sum_up = pd.Series(up).rolling(9, min_periods=1).sum().to_numpy()
    sum_dn = pd.Series(dn).rolling(9, min_periods=1).sum().to_numpy()
    denom = sum_up + sum_dn
    cmo = np.divide(sum_up - sum_dn, denom, out=np.zeros_like(denom), where=denom != 0)

    alpha = 2.0 / (n + 1)
    k = np.abs(cmo) * alpha
    seed = sma(s, n)

    out = np.empty_like(s)
    prev = np.nan
    for i in range(s.size):
        if np.isnan(prev):
            out[i] = seed[i]
        else:
            out[i] = k[i] * (s[i] - prev) + prev
        prev = out[i]
    return out


def wwma(s: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(s).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def zlema(s: np.ndarray, n: int) -> np.ndarray:
    lag = n // 2 if n % 2 == 0 else (n - 1) // 2
    shifted = np.concatenate([np.full(lag, s[0]), s[:-lag]]) if lag else s
    return ema(s + (s - shifted), n)


def tsf(s: np.ndarray, n: int) -> np.ndarray:
    def linreg(arr: np.ndarray, length: int, offset: int) -> np.ndarray:
        ser = pd.Series(arr)
        x = np.arange(length, dtype=float)

        def _f(win: np.ndarray) -> float:
            if len(win) < 2:
                return float(win[-1])
            xx = x[-len(win):]
            b, a = np.polyfit(xx, win, 1)
            return float(a + b * (xx[-1] - offset))

        return ser.rolling(length, min_periods=1).apply(_f, raw=True).to_numpy()

    lrc = linreg(s, n, 0)
    lrc1 = linreg(s, n, 1)
    return lrc + (lrc - lrc1)


def hull(s: np.ndarray, n: int) -> np.ndarray:
    h1 = max(1, round(n / 2))
    h2 = max(1, round(math.sqrt(n)))
    return wma(2 * wma(s, h1) - wma(s, n), h2)


_MA_FUNCS: dict[str, Callable[[np.ndarray, int], np.ndarray]] = {
    "SMA": sma, "EMA": ema, "WMA": wma, "TMA": tma, "VAR": vidya,
    "WWMA": wwma, "ZLEMA": zlema, "TSF": tsf, "HULL": hull,
}


def get_ma(s: np.ndarray, n: int, kind: str) -> np.ndarray:
    try:
        return _MA_FUNCS[kind](np.asarray(s, dtype=float), int(n))
    except KeyError:
        raise ValueError(f"Bilinmeyen MA tipi: {kind}. Seçenekler: {MA_TYPES}") from None


# ═════════════════════════════════════════════════════ OTT ÇEKİRDEĞİ ═══

def trail_core(ma: np.ndarray, fark: np.ndarray, pct: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """İki taraflı takip eden stop. Pine'daki trailCore() ile birebir aynı.

    Dönüş: (MT = MOST çizgisi, OTT çizgisi, dir = yön +1/-1)
    """
    n = ma.size
    mt = np.empty(n)
    ott = np.empty(n)
    direction = np.empty(n, dtype=np.int8)

    long_prev = np.nan
    short_prev = np.nan
    d = 1

    for i in range(n):
        ls = ma[i] - fark[i]
        ss = ma[i] + fark[i]
        lp = ls if np.isnan(long_prev) else long_prev
        sp = ss if np.isnan(short_prev) else short_prev

        ls = max(ls, lp) if ma[i] > lp else ls
        ss = min(ss, sp) if ma[i] < sp else ss

        if d == -1 and ma[i] > sp:
            d = 1
        elif d == 1 and ma[i] < lp:
            d = -1

        m = ls if d == 1 else ss
        mt[i] = m
        ott[i] = m * (200 + pct) / 200 if ma[i] > m else m * (200 - pct) / 200
        direction[i] = d
        long_prev, short_prev = ls, ss

    return mt, ott, direction


def ott_of(s: np.ndarray, n: int, pct: float, ma_kind: str) -> np.ndarray:
    """Bir kaynaktan doğrudan OTT çizgisi üretir (BOOTS, HOTT/LOTT için)."""
    ma = get_ma(s, n, ma_kind)
    _, ott, _ = trail_core(ma, np.abs(ma) * pct * 0.01, pct)
    return ott


def shift2(x: np.ndarray, enabled: bool = True) -> np.ndarray:
    """Pine'daki nz(x[2], x) — orijinal OTT'nin 2 bar kaydırması."""
    if not enabled:
        return x
    out = np.empty_like(x)
    out[:2] = x[:2]
    out[2:] = x[:-2]
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    prev_close = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    return wwma(tr, n)


# ════════════════════════════════════════════════════════ AYARLAR ═══

@dataclass
class Params:
    mode: str = "OTT"
    length: int = 2
    percent: float = 1.4
    ma: str = "VAR"
    use_shift: bool = True
    # TOTT / OTT Bands
    tott_coeff: float = 0.006
    band_up: float = 0.010
    band_dn: float = 0.010
    # PMax
    atr_period: int = 10
    atr_mult: float = 3.0
    # BOOTS
    bb_length: int = 2
    bb_mult: float = 2.0
    # HOTT/LOTT
    hl_length: int = 2
    # OTTO
    otto_fast: int = 10
    otto_slow: int = 25
    otto_cc: float = 100_000.0
    # ROTT
    rott_var_len: int = 1000
    # İşlem kuralları
    allow_long: bool = True
    allow_short: bool = True
    flat_zone: bool = False

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Costs:
    commission_pct: float = 0.05   # işlem başına, tek yön
    slippage_pct: float = 0.02     # işlem başına, tek yön
    bars_per_year: float = 252.0


# ═══════════════════════════════════════════════════════ SİNYALLER ═══

def build_lines(df: pd.DataFrame, p: Params) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Aktif mod için (sinyal kaynağı, long tetik çizgisi, short tetik çizgisi)."""
    close = df["close"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)

    if p.mode == "OTTO":
        fast = vidya(close, p.otto_fast)
        slow = vidya(close, p.otto_slow)
        raw = np.divide(fast, slow, out=np.ones_like(slow), where=slow != 0) * p.otto_cc
        support = vidya(raw, p.length)
        _, ott, _ = trail_core(support, np.abs(support) * p.percent * 0.01, p.percent)
        trig = shift2(ott, True)
        return support, trig, trig

    if p.mode == "ROTT":
        base = 2.0 * vidya(close, p.rott_var_len)
        support = vidya(base, p.length)
        _, ott, _ = trail_core(support, np.abs(support) * p.percent * 0.01, p.percent)
        trig = shift2(ott, True)
        return support, trig, trig

    ma = get_ma(close, p.length, p.ma)

    if p.mode == "MOST":
        mt, _, _ = trail_core(ma, np.abs(ma) * p.percent * 0.01, p.percent)
        return ma, mt, mt

    if p.mode == "PMax":
        fark = atr(high, low, close, p.atr_period) * p.atr_mult
        mt, _, _ = trail_core(ma, fark, p.percent)
        return ma, mt, mt

    if p.mode == "BOOTS":
        basis = sma(close, p.bb_length)
        dev = p.bb_mult * pd.Series(close).rolling(p.bb_length, min_periods=1).std(ddof=0).to_numpy()
        up = shift2(ott_of(basis + dev, p.length, p.percent, p.ma), p.use_shift)
        dn = shift2(ott_of(basis - dev, p.length, p.percent, p.ma), p.use_shift)
        return close, up, dn

    if p.mode == "HOTT/LOTT":
        hh = pd.Series(high).rolling(p.hl_length, min_periods=1).max().to_numpy()
        ll = pd.Series(low).rolling(p.hl_length, min_periods=1).min().to_numpy()
        up = shift2(ott_of(hh, p.length, p.percent, p.ma), p.use_shift)
        dn = shift2(ott_of(ll, p.length, p.percent, p.ma), p.use_shift)
        return close, up, dn

    _, ott, _ = trail_core(ma, np.abs(ma) * p.percent * 0.01, p.percent)
    ott_s = shift2(ott, p.use_shift)

    if p.mode == "TOTT":
        return ma, ott_s * (1 + p.tott_coeff), ott_s * (1 - p.tott_coeff)
    if p.mode == "OTT Bands":
        return ma, ott_s * (1 + p.band_up), ott_s * (1 - p.band_dn)
    if p.mode == "OTT":
        return ma, ott_s, ott_s

    raise ValueError(f"Bilinmeyen mod: {p.mode}. Seçenekler: {MODES}")


def _crossover(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    prev_a = np.concatenate([[a[0]], a[:-1]])
    prev_b = np.concatenate([[b[0]], b[:-1]])
    out = (a > b) & (prev_a <= prev_b)
    out[0] = False
    return out


def positions(df: pd.DataFrame, p: Params) -> np.ndarray:
    """Her barın KAPANIŞINDAN sonraki pozisyon (+1 long / 0 nakit / -1 short).

    Pine'daki process_orders_on_close=true ile aynı: sinyal barının kapanışında
    işleme girilir, getiri bir sonraki bardan itibaren işler.
    """
    sig, up, dn = build_lines(df, p)
    long_entry = _crossover(sig, up)
    long_exit = _crossover(up, sig)
    short_entry = _crossover(dn, sig)
    short_exit = _crossover(sig, dn)

    two_line = p.mode in TWO_LINE_MODES
    pos = np.zeros(len(df), dtype=np.int8)
    cur = 0

    for i in range(len(df)):
        nxt = cur
        if long_entry[i] and p.allow_long:
            nxt = 1
        if short_entry[i] and p.allow_short:
            nxt = -1
        if p.flat_zone and two_line:
            if long_exit[i] and nxt == 1:
                nxt = 0
            if short_exit[i] and nxt == -1:
                nxt = 0
        if short_entry[i] and not p.allow_short and nxt == 1:
            nxt = 0
        if long_entry[i] and not p.allow_long and nxt == -1:
            nxt = 0
        cur = nxt
        pos[i] = cur

    return pos


# ════════════════════════════════════════════════════════ BACKTEST ═══

@dataclass
class Result:
    metrics: dict = field(default_factory=dict)
    equity: pd.Series | None = None
    position: pd.Series | None = None

    def __repr__(self) -> str:
        return "Result(" + ", ".join(f"{k}={v}" for k, v in self.metrics.items()) + ")"


def backtest(df: pd.DataFrame, p: Params, costs: Costs = Costs()) -> Result:
    close = df["close"].to_numpy(float)
    pos = positions(df, p)

    # Bar i kapanışındaki pozisyon, i -> i+1 getirisini kazanır.
    ret = np.zeros(len(df))
    ret[1:] = close[1:] / close[:-1] - 1.0
    strat_ret = np.concatenate([[0.0], pos[:-1]]) * ret

    # Maliyet: pozisyon değişiminin mutlak büyüklüğü kadar devir hacmi.
    turnover = np.abs(np.diff(pos, prepend=0)).astype(float)
    cost_rate = (costs.commission_pct + costs.slippage_pct) / 100.0
    strat_ret = strat_ret - turnover * cost_rate

    equity = np.cumprod(1.0 + strat_ret)
    eq = pd.Series(equity, index=df.index, name="equity")

    return Result(metrics=_metrics(eq, strat_ret, pos, close, costs),
                  equity=eq,
                  position=pd.Series(pos, index=df.index, name="position"))


def _metrics(eq: pd.Series, rets: np.ndarray, pos: np.ndarray,
             close: np.ndarray, costs: Costs) -> dict:
    n = len(eq)
    total = eq.iloc[-1] - 1.0
    years = max(n / costs.bars_per_year, 1e-9)
    cagr = eq.iloc[-1] ** (1 / years) - 1.0 if eq.iloc[-1] > 0 else -1.0

    peak = np.maximum.accumulate(eq.to_numpy())
    dd = eq.to_numpy() / peak - 1.0
    max_dd = dd.min()

    sd = rets.std(ddof=0)
    sharpe = (rets.mean() / sd * math.sqrt(costs.bars_per_year)) if sd > 0 else 0.0
    downside = rets[rets < 0]
    dsd = downside.std(ddof=0) if downside.size else 0.0
    sortino = (rets.mean() / dsd * math.sqrt(costs.bars_per_year)) if dsd > 0 else 0.0

    # İşlem bazlı istatistikler: pozisyonun sıfırdan farklı olduğu her kesintisiz blok
    trades: list[float] = []
    i = 0
    while i < n:
        if pos[i] == 0:
            i += 1
            continue
        j = i
        while j + 1 < n and pos[j + 1] == pos[i]:
            j += 1
        entry_idx, exit_idx = i, min(j + 1, n - 1)
        if exit_idx > entry_idx:
            gross = (close[exit_idx] / close[entry_idx] - 1.0) * pos[i]
            trades.append(gross - 2 * (costs.commission_pct + costs.slippage_pct) / 100.0)
        i = j + 1

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "net_kar_%": round(total * 100, 2),
        "al_tut_%": round((close[-1] / close[0] - 1.0) * 100, 2),
        "CAGR_%": round(cagr * 100, 2),
        "max_dusus_%": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "kar_faktoru": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "kazanma_%": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "islem_sayisi": len(trades),
        "ort_islem_%": round(100 * float(np.mean(trades)), 3) if trades else 0.0,
        "piyasada_%": round(100 * float(np.mean(pos != 0)), 1),
    }


# ══════════════════════════════════════════════════ PARAMETRE TARAMA ═══

def sweep(df: pd.DataFrame, base: Params, grid: dict[str, Sequence],
          costs: Costs = Costs(), sort_by: str = "sharpe",
          progress: bool = True) -> pd.DataFrame:
    """Grid üzerindeki her kombinasyonu test eder, metrik tablosu döndürür."""
    keys = list(grid)
    combos = list(itertools.product(*(grid[k] for k in keys)))
    rows = []

    for idx, combo in enumerate(combos, 1):
        p = Params(**base.as_dict())
        for k, v in zip(keys, combo):
            setattr(p, k, v)
        try:
            m = backtest(df, p, costs).metrics
        except Exception as exc:  # tek kombinasyon patlarsa tarama sürsün
            print(f"  ! {dict(zip(keys, combo))} atlandı: {exc}", file=sys.stderr)
            continue
        rows.append({**dict(zip(keys, combo)), **m})
        if progress and (idx % 25 == 0 or idx == len(combos)):
            print(f"  ... {idx}/{len(combos)}", end="\r", file=sys.stderr, flush=True)

    if progress:
        print(" " * 40, file=sys.stderr)
    out = pd.DataFrame(rows)
    if not out.empty and sort_by in out.columns:
        out = out.sort_values(sort_by, ascending=False).reset_index(drop=True)
    return out


def walk_forward(df: pd.DataFrame, base: Params, grid: dict[str, Sequence],
                 folds: int = 5, train_ratio: float = 0.7,
                 costs: Costs = Costs(), sort_by: str = "sharpe") -> tuple[pd.DataFrame, Result]:
    """Walk-forward analizi — aşırı optimizasyona karşı tek dürüst savunma.

    Veri `folds` parçaya bölünür. Her parçada ilk %`train_ratio` üzerinde en iyi
    parametre aranır, kalan kısımda O PARAMETRE HİÇ DEĞİŞTİRİLMEDEN test edilir.
    Birleştirilen out-of-sample eğrisi, stratejinin gerçekte ne yapacağına dair
    elimizdeki en iyi tahmindir. Tarama tablosundaki parlak sayılar değil.
    """
    n = len(df)
    fold_size = n // folds
    if fold_size < 30:
        raise ValueError(f"Fold başına {fold_size} bar çok az. Daha az fold veya daha çok veri kullan.")

    rows, oos_parts = [], []

    for f in range(folds):
        start = f * fold_size
        stop = n if f == folds - 1 else (f + 1) * fold_size
        split = start + int((stop - start) * train_ratio)
        train, test = df.iloc[start:split], df.iloc[split:stop]
        if len(train) < 20 or len(test) < 5:
            continue

        tbl = sweep(train, base, grid, costs, sort_by, progress=False)
        if tbl.empty:
            continue
        best = tbl.iloc[0]
        chosen = {k: best[k] for k in grid}

        p = Params(**base.as_dict())
        for k, v in chosen.items():
            setattr(p, k, type(getattr(base, k))(v) if getattr(base, k) is not None else v)

        oos = backtest(test, p, costs)
        oos_parts.append(oos.equity / oos.equity.iloc[0])
        rows.append({
            "fold": f + 1,
            "egitim": f"{train.index[0].date()} → {train.index[-1].date()}",
            "test": f"{test.index[0].date()} → {test.index[-1].date()}",
            **{f"secilen_{k}": v for k, v in chosen.items()},
            "egitim_sharpe": best["sharpe"],
            "egitim_net_%": best["net_kar_%"],
            "TEST_sharpe": oos.metrics["sharpe"],
            "TEST_net_%": oos.metrics["net_kar_%"],
            "TEST_max_dusus_%": oos.metrics["max_dusus_%"],
            "TEST_islem": oos.metrics["islem_sayisi"],
        })

    if not oos_parts:
        raise ValueError("Hiçbir fold değerlendirilemedi.")

    stitched, level = [], 1.0
    for part in oos_parts:
        stitched.append(part * level)
        level = stitched[-1].iloc[-1]
    eq = pd.concat(stitched)
    rets = eq.pct_change().fillna(0.0).to_numpy()
    closes = df["close"].reindex(eq.index).to_numpy(float)
    pos_dummy = np.ones(len(eq), dtype=np.int8)

    combined = Result(metrics=_metrics(eq, rets, pos_dummy, closes, costs), equity=eq)
    combined.metrics.pop("kazanma_%", None)
    combined.metrics.pop("islem_sayisi", None)
    combined.metrics.pop("ort_islem_%", None)
    combined.metrics.pop("kar_faktoru", None)
    combined.metrics.pop("piyasada_%", None)
    return pd.DataFrame(rows), combined


# ═════════════════════════════════════════════════════ VERİ YÜKLEME ═══

def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    date_col = next((c for c in ("date", "time", "datetime", "tarih") if c in df.columns), None)
    if date_col is None:
        raise ValueError("CSV'de tarih sütunu yok (date / time / datetime / tarih bekleniyor).")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", format="mixed")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()

    missing = [c for c in ("open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise ValueError(f"CSV'de eksik sütun(lar): {missing}")
    return df[["open", "high", "low", "close"] + (["volume"] if "volume" in df.columns else [])]


def demo_data(n: int = 1500, seed: int = 7) -> pd.DataFrame:
    """Sentetik OHLC — araç veri dosyası olmadan denenebilsin diye.

    Trend rejimleri ile yatay rejimleri dönüşümlü üretir, çünkü trend takip
    göstergelerini yalnızca trendli veride test etmek yanıltıcı olur.
    """
    rng = np.random.default_rng(seed)
    drift = np.zeros(n)
    i = 0
    while i < n:
        block = rng.integers(60, 200)
        regime = rng.choice([0.0008, -0.0006, 0.0])
        drift[i:i + block] = regime
        i += block
    steps = drift + rng.normal(0, 0.014, n)
    close = 100 * np.exp(np.cumsum(steps))
    noise = np.abs(rng.normal(0, 0.006, n)) * close
    high = close + noise
    low = close - noise
    open_ = np.concatenate([[close[0]], close[:-1]])
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


# ═════════════════════════════════════════════════════════════ CLI ═══

DEFAULT_GRIDS: dict[str, dict[str, Sequence]] = {
    "OTT":        {"length": [2, 3, 4, 5, 8], "percent": [0.4, 0.7, 1.0, 1.4, 2.0, 3.0]},
    "TOTT":       {"length": [2, 3, 4, 5], "percent": [0.7, 1.0, 1.4, 2.0], "tott_coeff": [0.002, 0.006, 0.01]},
    "OTT Bands":  {"length": [2, 3, 5], "percent": [0.7, 1.4, 2.0], "band_up": [0.005, 0.01, 0.02]},
    "MOST":       {"length": [2, 3, 5, 8], "percent": [0.7, 1.0, 1.4, 2.0, 3.0]},
    "PMax":       {"length": [5, 10, 14], "atr_period": [7, 10, 14], "atr_mult": [1.5, 2.0, 3.0, 4.0]},
    "BOOTS":      {"length": [2, 3], "percent": [0.7, 1.4, 2.0], "bb_length": [2, 5, 10], "bb_mult": [1.5, 2.0]},
    "HOTT/LOTT":  {"length": [2, 3, 5], "percent": [0.7, 1.4, 2.0], "hl_length": [2, 5, 10]},
    "OTTO":       {"length": [2, 3], "percent": [0.7, 1.4, 2.0], "otto_fast": [5, 10], "otto_slow": [20, 25, 40]},
    "ROTT":       {"length": [20, 30, 40], "percent": [5.0, 7.0, 10.0]},
}


def _fmt(d: dict) -> str:
    return "\n".join(f"  {k:>16s} : {v}" for k, v in d.items())


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Anıl Özekşi trend göstergeleri — backtest ve parametre tarama",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="OHLC veri dosyası (date,open,high,low,close)")
    src.add_argument("--demo", action="store_true", help="Sentetik veri üret (dosya gerekmez)")

    ap.add_argument("--mode", default="OTT", choices=MODES)
    ap.add_argument("--ma", default="VAR", choices=MA_TYPES)
    ap.add_argument("--length", type=int, default=2)
    ap.add_argument("--percent", type=float, default=1.4)
    ap.add_argument("--no-shift", action="store_true", help="2 bar kaydırmayı kapat")
    ap.add_argument("--long-only", action="store_true")
    ap.add_argument("--short-only", action="store_true")
    ap.add_argument("--flat-zone", action="store_true", help="Çift çizgili modlarda kararsız bölgede pozisyonsuz bekle")

    ap.add_argument("--commission", type=float, default=0.05, help="işlem başına %% (tek yön)")
    ap.add_argument("--slippage", type=float, default=0.02, help="işlem başına %% (tek yön)")
    ap.add_argument("--bars-per-year", type=float, default=252.0)

    ap.add_argument("--sweep", action="store_true", help="Parametre taraması yap")
    ap.add_argument("--walk-forward", action="store_true", help="Walk-forward analizi yap")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--train-ratio", type=float, default=0.7)
    ap.add_argument("--sort-by", default="sharpe")
    ap.add_argument("--top", type=int, default=15, help="Tabloda gösterilecek satır sayısı")
    ap.add_argument("--out", help="Sonuç tablosunu bu CSV'ye yaz")

    a = ap.parse_args(argv)

    df = demo_data() if a.demo else load_csv(a.csv)
    print(f"\nVeri : {len(df)} bar   {df.index[0].date()} → {df.index[-1].date()}")
    print(f"Mod  : {a.mode}   (MA: {a.ma})")
    print(f"Maliyet: %{a.commission} komisyon + %{a.slippage} kayma (tek yön)\n")

    base = Params(
        mode=a.mode, ma=a.ma, length=a.length, percent=a.percent,
        use_shift=not a.no_shift,
        allow_long=not a.short_only, allow_short=not a.long_only,
        flat_zone=a.flat_zone,
    )
    costs = Costs(a.commission, a.slippage, a.bars_per_year)
    table: pd.DataFrame | None = None

    if a.walk_forward:
        grid = DEFAULT_GRIDS[a.mode]
        print(f"Walk-forward: {a.folds} fold, eğitim payı %{int(a.train_ratio * 100)}")
        print(f"Grid: {grid}\n")
        table, combined = walk_forward(df, base, grid, a.folds, a.train_ratio, costs, a.sort_by)
        with pd.option_context("display.width", 200, "display.max_columns", 50):
            print(table.to_string(index=False))
        print("\n— BİRLEŞTİRİLMİŞ OUT-OF-SAMPLE (dürüst sonuç) —")
        print(_fmt(combined.metrics))
        print("\nEğitim sharpe'ı ile TEST sharpe'ı arasındaki uçurum, aşırı")
        print("optimizasyonun ölçüsüdür. Eğitimde 3.0, testte 0.2 ise strateji yok.")

    elif a.sweep:
        grid = DEFAULT_GRIDS[a.mode]
        total = int(np.prod([len(v) for v in grid.values()]))
        print(f"Tarama: {total} kombinasyon   grid={grid}\n")
        table = sweep(df, base, grid, costs, a.sort_by)
        with pd.option_context("display.width", 200, "display.max_columns", 50):
            print(table.head(a.top).to_string(index=False))
        print(f"\nAl-tut getirisi: %{table.iloc[0]['al_tut_%']}")
        print("\nUYARI: Bu tablonun en üst satırı bir keşif değil, bir hipotezdir.")
        print("Doğrulamak için --walk-forward ile tekrar çalıştır.")

    else:
        res = backtest(df, base, costs)
        print(_fmt(res.metrics))

    if a.out and table is not None:
        table.to_csv(a.out, index=False)
        print(f"\nTablo yazıldı: {a.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
