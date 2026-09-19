# Özekşi Backtest Motoru (Python)

`../pine/` dosyalarının birebir Python karşılığı. Aynı OTT çekirdeği, aynı
sinyal kuralları, aynı emir mantığı.

**Neden gerekli?** TradingView'in Strategy Tester'ı tek seferde tek parametre
seti dener ve sana "şu ayarla %214 kâr" der. Bu sayı neredeyse her zaman
yalandır — çünkü o ayarı zaten aynı veriye bakarak seçtin. Bu araç yüzlerce
kombinasyonu otomatik dener **ve** walk-forward ile o yalanı ölçer.

---

## Kurulum

```bash
pip install -r requirements.txt     # numpy + pandas, başka bağımlılık yok
```

## Hızlı başlangıç

```bash
# Veri dosyası olmadan hemen dene (sentetik OHLC üretir)
python ozeksi_backtest.py --demo

# Tüm modları karşılaştır
python ozeksi_backtest.py --demo --mode PMax
python ozeksi_backtest.py --demo --mode "HOTT/LOTT"

# Kendi verinle
python ozeksi_backtest.py --csv THYAO.csv --mode OTT --length 2 --percent 1.4

# Parametre taraması
python ozeksi_backtest.py --csv THYAO.csv --mode OTT --sweep --out sonuc.csv

# Walk-forward — dürüst sonuç budur
python ozeksi_backtest.py --csv THYAO.csv --mode OTT --walk-forward
```

### CSV formatı

```csv
date,open,high,low,close,volume
2023-01-02,45.10,45.90,44.80,45.60,1250000
2023-01-03,45.60,46.20,45.30,46.05,1380000
```

Tarih sütunu `date`, `time`, `datetime` veya `tarih` olabilir. Artan sıralı olmalı.
Veriyi TradingView'den (grafik → sağ tık → Export chart data), Investing.com'dan
veya `yfinance` ile (`yf.download("THYAO.IS")`) alabilirsin.

---

## Neden walk-forward?

Demo veride kendi ölçtüğüm sonuç, meselenin tamamını anlatıyor:

| Yöntem | Sharpe | Net kâr |
|---|---|---|
| Parametre taraması, en iyi satır | **0.99** | **+%214** |
| Aynı grid, walk-forward out-of-sample | **0.07** | **−%1.3** |

Tarama tablosundaki o parlak `+%214`, stratejinin kazanma gücü değil, **o veri
setinin gürültüsünü ezberlemiş** bir parametre setidir. Walk-forward şunu yapar:

```
|--- eğitim (%70) ---|- test (%30) -|          fold 1
                      ↑ en iyi parametre burada seçilir
                                      ↑ ve burada, hiç değiştirilmeden test edilir
```

Beş fold'un test kısımları birleştirilir. Çıkan eğri, stratejinin gerçekte ne
yapacağına dair elindeki en iyi tahmindir.

**Okuma kuralı:** `egitim_sharpe` ile `TEST_sharpe` arasındaki uçurum,
aşırı optimizasyonun doğrudan ölçüsüdür. Eğitimde 3.20, testte −1.84 ise orada
strateji yok, ezber var.

---

## Modlar

Pine dosyalarıyla aynı dokuz mod:

`OTT` · `TOTT` · `OTT Bands` · `MOST` · `PMax` · `BOOTS` · `HOTT/LOTT` · `OTTO` · `ROTT`

Her modun `DEFAULT_GRIDS` içinde makul bir başlangıç grid'i tanımlı.
Kendi grid'ini kullanmak istersen Python'dan:

```python
import ozeksi_backtest as oz

df = oz.load_csv("THYAO.csv")
tablo = oz.sweep(
    df,
    oz.Params(mode="OTT", ma="VAR"),
    {"length": [2, 3, 5, 8, 13], "percent": [0.5, 1.0, 1.4, 2.0, 3.0]},
    oz.Costs(commission_pct=0.05, slippage_pct=0.02),
)
print(tablo.head(10))
```

## Maliyet ayarı

```bash
--commission 0.05    # işlem başına %, tek yön
--slippage 0.02      # işlem başına %, tek yön
```

Varsayılanlar temkinli ama her aracı kurum farklı. **Sıfır maliyetle yapılan
backtest yalan söyler** — özellikle OTT gibi çok işlem üreten stratejilerde
komisyon tek başına kârı silebilir.

---

## Testler

```bash
python test_ozeksi.py
```

13 test, hepsi geçiyor. En kritik ikisi:

- **`trail_core_pine_ile_ayni`** — Pine kaynağından satır satır çevrilmiş naif bir
  referans uygulamayla, kullandığımız hızlı uygulamayı rastgele 8 seride
  karşılaştırır. Optimizasyon sırasında mantık bozulmuşsa burada yakalanır.
- **`gelecege_bakmiyor`** — veriyi sondan kırpınca geçmiş sinyaller değişiyor mu?
  Değişirse lookahead (geleceğe bakma) hatası var demektir. Değişmiyor.

Diğerleri: trailing stop'un geri gitmediği, OTT'nin MT'nin doğru tarafında
kaldığı, `shift2`'nin Pine'daki `nz(x[2], x)` ile aynı olduğu, maliyetin
düşüldüğü, dokuz modun ve dokuz MA tipinin çalıştığı, `--long-only` seçilince
short açılmadığı, Flat Zone'un piyasada kalma oranını azalttığı.

---

## Sınırlar — bunu bilerek kullan

- **Tek enstrüman, tek zaman dilimi.** Portföy, pozisyon boyutlandırma, kaldıraç yok.
- **Emirler bar kapanışında gerçekleşir** (Pine'daki `process_orders_on_close=true`).
  Gerçekte kapanışa tam basamak yakalayamazsın; `--slippage` bunu kabaca telafi eder.
- **Bar içi hareket yok.** Bar içinde stop'a değip dönen fiyat modellenmez.
- **Temettü, bölünme, borçlanma maliyeti, kısa satış ücreti yok.**
- **Sentetik demo verisi gerçek piyasa değildir.** `--demo` sonuçları aracın
  çalıştığını gösterir, stratejinin işe yaradığını değil.

## Uyarı

Eğitim ve araştırma amaçlıdır. **Yatırım tavsiyesi değildir.**
