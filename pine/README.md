# Anıl Özekşi Trend Göstergeleri — Pine Script Backtest Seti

Anıl Özekşi'nin geliştirdiği trend takip göstergelerinin (**OTT** ve türevleri)
TradingView'de **strateji olarak backtest edilebilir** hâli.

---

## Köken ve emeğin sahibi

Bunu netleştirmek önemli, çünkü sık karıştırılıyor:

| Kim | Ne yaptı |
|---|---|
| **Anıl Özekşi** | Göstergelerin matematiğini tasarladı. Orijinal kodlar **Matriks Trader / İdeal Veri** formül dilinde. |
| **Kıvanç Özbilgiç** ([@KivancOzbilgic](https://www.tradingview.com/u/KivancOzbilgic/)) | OTT, MOST, PMax, TOTT, OTTO, OTT Bands, BOOTS, HOTT/LOTT'u TradingView'e **açık kaynak** Pine Script olarak uyarladı. |
| **[@zeubetella](https://github.com/zentoliyan)** | ROTT (Relative OTT) uyarlaması, MPL-2.0 lisanslı, [@dg_factor](https://www.tradingview.com/u/dg_factor/) katkısıyla. |
| Bu repo | Yukarıdaki mantıkları tek dosyada toplayıp `strategy()` hâline getirir — yani Strategy Tester'da backtest edilebilir. |

Orijinal göstergeleri kullanmak istersen TradingView'de doğrudan yayıncının
scriptini ekle. Bu dosyalar onların yerine geçmez; backtest için bir araçtır.

---

## Dosyalar

### `ozeksi_trend_suite.pine` — fiyat grafiği üstünde (overlay)

Tek script, 7 mod:

| Mod | Ne yapar |
|---|---|
| **OTT** | Asıl gösterge. VIDYA + gürültüsüz trailing stop, 2 bar kaydırmalı. |
| **TOTT** | OTT etrafında tek katsayılı ikiz bant. Yatay piyasada testere sinyalini keser. |
| **OTT Bands** | TOTT gibi ama üst/alt katsayılar **ayrı ayrı** ayarlanır (destek/direnç için). |
| **MOST** | OTT'nin atası. Kaydırma ve ek yüzde yok, ham trailing stop çizgisi. |
| **PMax** | MOST + SuperTrend melezi. Stop mesafesi yüzde yerine **ATR** ile ölçülür. |
| **BOOTS** | OTT, kapanış yerine **Bollinger üst ve alt bandına** uygulanır. İki çizgi arası flat zone. |
| **HOTT/LOTT** | OTT, **en yüksek** ve **en düşük** fiyatlara uygulanır. İki çizgi arası flat zone. |

### `ozeksi_oscillators.pine` — ayrı panelde (non-overlay)

| Mod | Ne yapar |
|---|---|
| **OTTO** | OTT'nin osilatör versiyonu. Hızlı/yavaş VIDYA oranı üzerine OTT. Fiyata daha duyarlı. |
| **ROTT** | Çok uzun periyotlu (varsayılan 1000) VIDYA üzerine OTT. Az sinyal, görece yüksek isabet. |

---

## Ortak matematik — bir kez anla, hepsini anla

Sekiz göstergenin **çekirdeği aynı**. Aradaki tek fark, hangi veriye
uygulandığı ve stop mesafesinin nasıl ölçüldüğü.

**1 — Gürültüyü temizle.** Fiyat yerine hareketli ortalama kullan. Varsayılan
`VAR` (VIDYA): Chande Momentum Oscillator'a göre hızlanıp yavaşlayan
uyarlanabilir bir ortalama. Piyasa hareketliyken fiyatı yakından takip eder,
sakinken yavaşlar.

```
alpha = 2 / (periyot + 1)
VIDYA = |CMO(9)| × alpha × (fiyat − VIDYA[1]) + VIDYA[1]
```

**2 — İki taraflı takip eden stop kur.**

```
longStop  = MA − sapma     // yukarı giderken asla geri düşmez
shortStop = MA + sapma     // aşağı giderken asla geri çıkmaz
```

`sapma` tek ayrım noktası:
- OTT / TOTT / MOST / BOOTS / HOTT-LOTT → `MA × yüzde` (oransal)
- **PMax** → `ATR × çarpan` (volatiliteye göre nefes alır) ← SuperTrend'den gelen kısım

**3 — Yön çevir.** Fiyat karşı stopu delerse `dir` +1 / −1 arası döner; aktif
çizgi değişir. Bu çizgi **MOST**'tur.

**4 — OTT'nin farkı.** MOST'u bir kez daha yüzde kadar iter
(`× (200 ± yüzde) / 200`) ve **2 bar ileriye kaydırarak** çizer. Yatay
piyasadaki testere sinyallerini kesen numara budur.

**5 — Çift çizgili türevler.** TOTT / OTT Bands / BOOTS / HOTT-LOTT aynı OTT'yi
iki farklı veriye (ya da iki katsayıya) uygulayıp aradaki boşluğu **flat zone**
ilan eder: o bölgede yeni pozisyon açılmaz.

> ⚠️ **Kaydırma repaint değildir.** OTT çizgisi grafikte 2 bar ileri uzanır,
> "geleceği biliyormuş" gibi görünür. Sinyal mantığı `OTT[2]` kullandığı için
> hesap doğrudur; kapanmış barlar sonradan değişmez.

---

## TradingView'de nasıl backtest edersin

1. Grafik aç → alt panelde **Pine Editor** sekmesi
2. `.pine` dosyasının içeriğini yapıştır → **Add to chart**
3. Alt panelde **Strategy Tester** açılır
4. Script ayarları (dişli) → **Gösterge** kutusundan modu değiştir, modları karşılaştır
5. **Properties** sekmesinden komisyon ve slippage'ı kendi aracı kurumuna göre düzelt

Kodda varsayılan olarak **%0.05 komisyon + 1 tick slippage** var. Bu değerler
stratejinin kaderini belirler — sıfır komisyonla yaptığın backtest yalan söyler.

### Başlangıç parametreleri

| Mod | Periyot | Yüzde | Not |
|---|---|---|---|
| OTT | 2 | 1.4 | Kıvanç'ın varsayılanı, günlük grafik için |
| TOTT | 2 | 1.4 | Katsayı 0.006 |
| BOOTS | 2 | 1.4 | BB periyodu 2, std sapma 2 |
| ROTT | 30 | 7.0 | VAR periyodu 1000 |
| OTTO | 2 | 1.4 | Hızlı 10 / Yavaş 25, sabit 100000 |

BIST hisselerinde günlükte genelde periyot 2–5 / yüzde 0.5–2 aralığı denenir;
kriptoda yüzde biraz daha yüksek tutulur.

---

## Doğrulama durumu — neyin ne kadar güvenilir olduğu

Dürüst olmak gerekirse hepsi aynı kesinlikte değil:

| Bölüm | Durum |
|---|---|
| OTT çekirdeği (trailing stop + `dir` + `(200±%)/200` + 2 bar kaydırma) | ✅ [@zeubetella'nın yayınlanmış MPL-2.0 ROTT kaynağıyla](https://github.com/zentoliyan/Pinescript-Indicator-ROTT-RelativeOTT) birebir doğrulandı |
| ROTT | ✅ Aynı kaynaktan birebir |
| VAR / VIDYA | ✅ Aynı kaynaktan birebir |
| MOST, PMax, TOTT | ✅ Yayınlanmış tanımlarla uyumlu |
| BOOTS, HOTT/LOTT, OTT Bands | ⚠️ Yayınlanmış **açıklamalardan** kuruldu (OTT'nin hangi veriye uygulandığı net, sinyal konvansiyonu flat-zone olarak alındı) |
| **OTTO** | ⚠️ Yalnızca açıklamadan **yeniden kurgulandı**. Hızlı/yavaş VIDYA oranının düzeltme sabitiyle ölçeklenmesi bir çıkarımdır; orijinal kodla birebir aynı olmayabilir |

Sayısal olarak referans almadan önce, ⚠️ işaretli modları TradingView'deki
orijinal scriptle aynı grafikte üst üste bindirip karşılaştır.

---

## Orijinal scriptler (TradingView)

- [Optimized Trend Tracker — OTT](https://www.tradingview.com/script/zVhoDQME/)
- [MOST by Anıl ÖZEKŞİ](https://www.tradingview.com/script/28ZcW4nv/)
- [Profit Maximizer — PMax](https://www.tradingview.com/script/sU9molfV/)
- [Twin Optimized Trend Tracker — TOTT](https://www.tradingview.com/script/eENf7NpJ/)
- [OTT Oscillator — OTTO](https://www.tradingview.com/script/W3BqP7Nq-Optimized-Trend-Tracker-Oscillator-OTTO/)
- [Optimized Trend Tracker Bands](https://www.tradingview.com/script/jD7ioJ1Y-Optimized-Trend-Tracker-Bands/)
- [Bollinger OTT Spread — BOOTS](https://www.tradingview.com/script/hynBgzIQ/)
- [HIGH and LOW OTT — HOTT/LOTT](https://www.tradingview.com/script/5qkKOlVg-HIGH-and-LOW-Optimized-Trend-Tracker-HOTT-LOTT/)
- [Multiple OTT](https://www.tradingview.com/script/UXwYKQ5u/)
- [OTT Strategy & Screener](https://www.tradingview.com/script/HPbRZvsV/)
- [Tüm "anilozeksi" etiketli scriptler](https://www.tradingview.com/scripts/anilozeksi/)

Python tarafı: [freqtrade/technical #97](https://github.com/freqtrade/technical/issues/97)

---

## Uyarılar

- **Aşırı optimizasyon (overfitting).** Strategy Tester'da yüzdeyi 1.4'ten
  1.37'ye çekip net kârı ikiye katlarsan, bulduğun şey strateji değil o veri
  setinin gürültüsüdür. Parametreyi bir dönemde seç, **başka bir dönemde**
  test et (walk-forward).
- **Bunlar trend takip göstergesidir.** Yatay piyasada kaybeder; bu bir hata
  değil, tasarım gereğidir. Kazanma oranı %40'larda olup yine de kârlı olabilir.
- **Eğitim ve araştırma amaçlıdır. Yatırım tavsiyesi değildir.**

## Lisans

OTT çekirdeği [Mozilla Public License 2.0](https://mozilla.org/MPL/2.0/)
altındaki [@zeubetella / ROTT](https://github.com/zentoliyan/Pinescript-Indicator-ROTT-RelativeOTT)
kaynağından türetilmiştir; bu dizin de aynı lisansla kullanılabilir.
