# 🤖 Trading Journal Bot + WebApp

Bot Telegram untuk mencatat & menganalisis trading **Forex** dengan **Telegram Mini App (WebApp)** — di-deploy langsung ke **Railway**.

---

## ✨ Fitur Utama

- 📱 **Telegram Mini App (WebApp)** — form sentuh interaktif, preview P&L & pips real-time
- 🎛️ **Touch Panel** (`/panel`) — navigasi tombol sentuh tanpa mengetik command
- 📝 **Input Fleksibel** — WebApp form, `/trade` inline satu baris, atau `/add` wizard 7 langkah
- 📊 **Statistik & Analisis** — win rate, profit factor, net P&L, pips, R-multiple, breakdown per-pair & per-direction
- 📈 **Visual Chart** — kurva ekuitas P&L via `/chart`
- 🛡️ **Risk Management** — kalkulator lot `/size`, peringatan batas max-loss harian
- 📄 **Ekspor CSV** — download data trade via `/export`
- ⚙️ **Dynamic Settings** — ubah balance, risk %, kurs langsung dari bot (`/settings`)
- 🗄️ **PostgreSQL** — database cloud untuk data persisten

---

## 🚀 Deploy ke Railway

### Langkah 1: Buat Database PostgreSQL di Aiven

1. Buka [aiven.io](https://aiven.io) → Login
2. Klik **Create service** → pilih **PostgreSQL**
3. Pilih plan **Free** (atau yang sesuai)
4. Copy connection string (format: `postgres://user:pass@host:port/dbname?sslmode=require`)

### Langkah 2: Push ke GitHub

```bash
git init
git add .
git commit -m "feat: Trading journal bot & webapp"
git branch -M main
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```

### Langkah 3: Deploy di Railway

1. Buka [railway.app](https://railway.app) → Login
2. Klik **+ New** → **Deploy from GitHub repo** → pilih repository ini
3. Di tab **Variables**, tambahkan:

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | Token dari [@BotFather](https://t.me/BotFather) |
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string |
| `TIMEZONE` | — | `Asia/Jakarta` | Zona waktu untuk tampilan |
| `DEFAULT_BALANCE` | — | `1000` | Saldo akun default |
| `DEFAULT_RISK_PERCENT` | — | `1` | Risiko per trade (%) |
| `USDJPY_RATE` | — | `150` | Kurs USD/JPY |
| `CURRENCY` | — | `USD` | Simbol mata uang |
| `ALLOWED_USER_IDS` | — | — | Batasi user (ID Telegram, koma) |

### Langkah 4: Generate Domain

1. Di Railway Dashboard → tab **Settings** → **Networking** → **Generate Domain**
2. Railway otomatis set `RAILWAY_PUBLIC_DOMAIN` → bot mendeteksi & mengaktifkan WebApp button

---

## 💻 Jalankan Lokal

```bash
pip install -r requirements.txt
cp .env.example .env
nano .env  # isi BOT_TOKEN dan DATABASE_URL
python main.py
```

Server aktif di `http://0.0.0.0:8080`, Telegram Bot langsung polling.

---

## 📖 Perintah Bot

| Perintah | Deskripsi |
|---|---|
| `/panel` | 🎛️ Panel kontrol tombol sentuh & WebApp |
| `/start` | 👋 Panel utama |
| `/help` | 📚 Panduan lengkap |
| `/trade PAIR DIR entry=.. exit=.. lot=.. [sl=..]` | ⚡ Catat trade cepat |
| `/add` | 📝 Wizard 7 langkah |
| `/list [today\|week\|month\|PAIR]` | 📒 Riwayat trade |
| `/detail <id>` | 🔍 Detail trade |
| `/edit <id>` | ✏️ Edit trade |
| `/delete <id>` | 🗑️ Hapus trade |
| `/stats [today\|week\|month\|all]` | 📊 Statistik performa |
| `/report [week\|month]` | 🗓️ Laporan berkala |
| `/chart` | 📈 Kurva ekuitas (PNG) |
| `/export` | 📤 Download CSV |
| `/size PAIR entry stop` | 📏 Kalkulator lot aman |
| `/settings` | ⚙️ Pengaturan akun |

---

## 🗂️ Struktur Proyek

```
.
├── main.py              # Entry point — wiring Telegram bot + aiohttp server
├── config.py            # Settings dari .env / environment variables
├── db.py                # PostgreSQL: skema, connection pool, CRUD
├── calc.py              # Rumus forex: P&L, R-multiple, pip, statistik
├── formatters.py        # Renderer teks Telegram (Bahasa Indonesia)
├── charts.py            # Kurva ekuitas PNG (matplotlib, opsional)
├── handlers/
│   ├── __init__.py      # Pengumpul semua handler
│   ├── common.py        # Helper bersama: otorisasi, build_settings
│   ├── trade.py         # /trade, /add, /list, /detail, /edit, /delete
│   ├── stats.py         # /stats
│   ├── report.py        # /export, /report, /chart
│   ├── risk.py          # /settings, /size
│   ├── panel.py         # /panel + callback tombol
│   └── webapp.py        # Telegram Mini App data handler
├── webapp/              # Frontend: HTML + Tailwind CSS + JS
│   ├── index.html
│   ├── style.css
│   └── app.js
├── scripts/
│   └── gen_stats.py     # Generator snapshot JSON untuk webapp
├── Procfile             # Railway start command
├── railway.toml         # Railway deployment config
├── requirements.txt     # Python dependencies
├── .env.example         # Template konfigurasi
└── .gitignore
```

---

## 🔧 Konfigurasi

Semua pengaturan bisa diubah tanpa restart bot:

```
/settings set balance 2000
/settings set risk_percent 2.0
/settings set usdjpy_rate 152.5
```

Values disimpan di database PostgreSQL dan di-override dari `.env` / env vars Railway.

---

## 📝 License

Personal use. Modified for individual trading journal.
