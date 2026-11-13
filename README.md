# Eliz Scalp Engine

Mesin analisis **scalping crypto** yang berjalan sepenuhnya di GitHub: scan tiap 15 menit lewat **GitHub Actions**, hasilnya dipublikasikan sebagai dashboard di **GitHub Pages**. Aturan strategi diturunkan dari materi Eliz (postingan X @eliz883 + video YouTube ElizCrypto). Indikator memakai **pandas-ta-classic**.

> Edukasi & riset, **bukan nasihat finansial**. Mesin ini tidak menjamin profit. Jalankan backtest pada data nyata dan uji di akun demo/ukuran kecil sebelum memakai uang sungguhan.

## Cara pasang (5 langkah)

1. Buat repo baru di GitHub (branch utama `main`), upload **seluruh isi folder ini** (termasuk folder `.github`).
2. **Settings → Actions → General → Workflow permissions** → pilih **Read and write permissions** → Save.
3. **Settings → Pages → Build and deployment → Source** → pilih **GitHub Actions**.
4. Tab **Actions** → workflow **Scan & Deploy** → **Run workflow**. Setelah hijau, alamat dashboard muncul di job `deploy` (biasanya `https://USERNAME.github.io/NAMA-REPO/`).
5. Jalankan workflow **Backtest** sekali (Run workflow) agar panel backtest terisi. Setelahnya otomatis tiap Senin.

Opsional: notifikasi sinyal ke Telegram/Discord. Tambah di **Settings → Secrets and variables → Actions**: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, dan/atau `DISCORD_WEBHOOK_URL`.

Catatan biaya/batas GitHub:
- Repo **publik**: Actions gratis tanpa batas menit, Pages gratis. Repo **privat**: Pages butuh paket berbayar, dan cron 15 menit (~100 run/hari) bisa melebihi kuota gratis 2.000 menit/bulan. Ubah cron di `scan-deploy.yml` menjadi `*/30` bila perlu.
- Cron GitHub bisa telat beberapa menit. Mesin sudah menangani ini (lihat "Anti-telat" di bawah).
- GitHub menonaktifkan cron pada repo tanpa aktivitas 60 hari; commit state oleh bot biasanya menjaganya tetap aktif. Bila berhenti, aktifkan lagi di tab Actions.

## Cara kerja

Data hanya satu: candle **15m** (diunduh dari Binance data-api → OKX → Bybit sebagai cadangan, tanpa API key). H1 dan H4 dibuat dengan resample dan hanya terlihat setelah candle-nya **closed** (tanpa look-ahead; ada tesnya).

| Materi Eliz | Implementasi |
|---|---|
| "Work on ranges in H1, focus on deviations of the range's highs and lows" | **Setup A – Deviasi Range**: range H1 valid (≥2 sentuhan tiap sisi, lebar 2–9 ATR, ADX ≤ 28); wick menembus tepi lalu candle 15m **close kembali ke dalam** |
| "Stop run = candle yang mengambil liquidity lalu recover", "liquidity sweep below Monday low" | **Setup B – Stop Run Level**: sweep + reclaim pada PDH/PDL, Monday High/Low, PWH/PWL |
| "Close di luar range, retest, posisi long/short di retest" | **Setup C – Breakout-Retest**: breakout close H1, retest level, bertahan |
| "Squeeze", "flip the EMA" | **Setup D – Squeeze Ekspansi**: squeeze Bollinger lalu close di luar band dengan volume ≥1,5x |
| "Scalp long in long season, short in short season", "TOTAL di atas box → bias long alt" | Bias **EMA20/50 di H4** dan bias **BTC**: searah +skor, melawan −skor |
| "Don't chase price", "tengah range = no man's land" | Tidak ada trigger di tengah range; panel Pantauan memberi rencana "tunggu sweep di …" |
| "Wait for trigger/confirmation" | Sinyal hanya dari candle **closed**, bentuk candle reclaim harus kuat |
| "Easy invalidation", "stop 2–3–4% maks", "risk reward harus layak" | SL di luar ekstrem sweep + buffer ATR, SL maks 1,5%, RR TP2 ≥ 2, TP1 parsial 50% lalu SL ke BE |
| "Volume rendah = melawan bot", "scalp BTC dengan stop sempit RR tidak layak" | Volume mati ditolak; **gerbang biaya**: fee+slippage maks 0,30R |

Skor konfluensi 0–100 (bias, volume sweep, kekuatan candle, RSI ekstrem, RR, sentuhan range, dll.); sinyal dipublikasi bila ≥ `signal.min_score` (60).

### Anti-EXPIRED / anti-INVALID
- Data dibersihkan sebelum analisis (NaN, harga ≤ 0, high<low, duplikat, candle belum closed, data basi → simbol dilewati dan tampil di Diagnostik).
- Sinyal yang **sudah telat** (harga lari > 0,35 ATR dari entry, sudah mundur > 0,5R, atau sudah kena SL/TP) **tidak dipublikasikan**.
- Status tiap sinyal dihitung ulang dari candle (stateless), jadi tidak ada status menggantung. Satu sinyal terbuka per simbol, cooldown per arah, batas total sinyal terbuka.

### Aturan simulasi hasil (live & backtest identik)
Entry di close candle trigger; biaya fee+slippage dihitung; bila SL dan TP tersentuh di candle yang sama → **SL dianggap lebih dulu**; setelah TP1, SL sisa di BE; timeout 48 candle (12 jam). Hasil dalam satuan **R**.

## Perintah lokal

```bash
pip install -r requirements-dev.txt
python -m pytest -q                       # 36 tes
python -m scalp demo                      # scan + backtest + dashboard dengan data sintetis -> folder public/
python -m scalp scan                      # scan live (butuh internet)
python -m scalp backtest --days 45        # backtest data nyata
python -m scalp build-site --out public   # rakit dashboard dari state/
```
Mode `--demo` memakai data acak buatan; hasilnya **tidak ada artinya** untuk trading dan hanya untuk menguji alur.

## Mengatur strategi

Semua parameter ada di `config.yaml` (daftar koin, lookback range, kedalaman sweep, SL/TP, skor minimum, biaya, setup on/off). Commit perubahan, workflow berikutnya otomatis memakainya. Cara mengevaluasi: jalankan Backtest, lihat tabel per **arah** dan per **setup**, lalu matikan setup yang rugi atau naikkan `min_score`. Hati-hati overfitting: jangan menyetel ulang berkali-kali pada periode data yang sama.

Tentang biaya: dengan SL ±0,5%, fee taker + slippage pulang-pergi (16 bps) sudah memakan ~0,3R per trade. Karena itu `max_cost_r` menolak setup dengan SL terlalu rapat. Memakai order limit (fee maker) memperbaiki ini; sesuaikan `costs.fee_bps` dengan tier akunmu.

## Keterbatasan (jujur)

- **Heatmap likuidasi / order book** (Coinglass, Bookmap) yang sering dipakai Eliz tidak tersedia gratis lewat API publik. Sebagai pengganti dipakai *proxy* likuiditas: sweep PDH/PDL, Monday, PWH/PWL, dan tepi range. Tidak ada Fibonacci 0,75 atau pola Wolfe otomatis.
- Penilaian "bias" dan "range" bersifat aturan mekanis; Eliz menggambar level secara diskresioner, jadi hasil mesin tidak akan identik dengan chart-nya.
- Data 15m hanya ±15 hari tiap scan live (cukup untuk level mingguan sebelumnya dan EMA H4); backtest mengunduh sejarah lebih panjang.
- Backtest tidak memodelkan likuiditas/depth, funding, atau penolakan order. Hasil live bisa berbeda.

## Struktur

```
config.yaml              parameter strategi
scalp/data.py            unduh & validasi candle (Binance data-api, OKX, Bybit)
scalp/ind.py             indikator via pandas-ta-classic (fallback pandas murni)
scalp/features.py        range H1, bias H4, level harian/mingguan (tanpa look-ahead)
scalp/setups.py          4 setup + skor + SL/TP + ukuran posisi
scalp/trade.py           simulasi hasil trade (dipakai live & backtest)
scalp/tracker.py         dedup, cooldown, validasi kesegaran sinyal, pembaruan status
scalp/backtest.py        backtest walk-forward
scalp/pipeline.py        orkestrasi scan/backtest/situs
site/                    dashboard statis (HTML/CSS/JS tanpa dependensi)
state/                   signals.json, market.json, backtest.json (di-commit oleh bot)
.github/workflows/       ci.yml, scan-deploy.yml, backtest.yml
tests/                   36 tes (pytest)
```
