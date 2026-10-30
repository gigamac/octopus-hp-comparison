# Octopus HP Comparison: Agile vs. Cosy Heat Pump Tariff Comparator

A toolkit for Octopus Energy customers who have installed a heat pump to compare **Agile Octopus** with **Cosy Octopus**, with or without home battery storage, using real smart meter readings.

---

## 4-Way Scenario Analysis
1. **Agile Octopus (Base)**: Your current half-hourly dynamic wholesale tariff.
2. **Cosy Octopus (Base)**: Octopus's heat pump tariff with 8 hours of cheap dip power (~14p/kWh) every day.
3. **Agile + Battery**: Smart price-arbitrage charging during cheapest daily slots.
4. **Cosy + Battery**: Pre-charging in the 13:00–16:00 dip (~14.1p) to eliminate the 16:00–19:00 peak (~43.2p).

---

## Key Features

1. **Persistent Local Disk Caching (`data_cache/`):**  
   Automatically caches smart meter intervals, gas readings, and tariff rates. Subsequent queries run in **under 2 seconds** instead of repeatedly hitting Octopus APIs.
2. **Gas-to-Heat-Pump Conversion (`gas_converter.py`):**  
   Converts historical winter gas consumption into equivalent heat pump electricity using Seasonal COP (SCOP) and boiler efficiency, letting you accurately model future winter bills before your first heating season.
3. **Octopus Outgoing Export Arbitrage:**  
   Models pairing a home battery with **Octopus Outgoing** (Agile dynamic wholesale export ~25–45p/kWh or Fixed 15p/kWh). Simulates exporting surplus battery capacity during the 16:00–19:00 peak to generate substantial bill credits.
4. **Non-Intrusive Smart Update Dialogue:**  
   On opening the dashboard, if cached data is older than today, a gentle dialogue prompts:  
   *"Last recorded smart meter date is YYYY-MM-DD. Would you like to fetch recent readings up to today?"*  
   Can be dismissed with one click or re-opened anytime via the subtle header link.
5. **Interactive Visual Dashboard (`tariff_comparison_report.html`):**  
   A self-contained dashboard with real-time browser sliders:
   - **Battery Size Slider** (0 to 15 kWh)
   - **Octopus Export Tariff Toggle** (Agile Outgoing vs Fixed 15p)
   - **Automation / Dip Shifting Slider** (0% to 90%)
   - **Heat Pump SCOP Slider** (2.5 to 4.5)
   - **Gas Heating Conversion Toggle** (ON/OFF)
   - **Date Presets** (Full Year, Post-Heat-Pump Only, Winter, Summer)

---

## Project Structure

```
octopus-hp-comparison/
├── octopus_client.py              # Kraken REST API client with local disk caching
├── tariff_comparator.py           # Fast indexed 4-way calculation engine
├── gas_converter.py               # Gas m3 -> Heat Pump electricity using SCOP
├── compare.py                     # CLI tool with simulation, real data, and HTML generation
├── server.py                      # Optional lightweight companion server for 1-click in-browser updates
├── data_cache/                    # Local persistent cache for electricity, gas & tariff rates
├── tariff_comparison_report.html  # Interactive real-time dashboard with sliders & dialogue
├── Octopus_Energy_Kraken_API.postman_collection.json # Preconfigured Postman collection
├── .env                           # Your Octopus API credentials (kept private)
└── README.md
```

---

## Quick Usage

### 1. Update & Regenerate Dashboard with Latest Data
```bash
python3 compare.py --battery 5 --html
```
- If run in the future, it automatically queries Octopus for newly recorded half-hour intervals up to the current date and appends them to your local cache.
- To bypass the cache and force a complete re-download:
```bash
python3 compare.py --refresh --battery 5 --html
```
- To run with 1-click in-browser updates enabled:
```bash
python3 server.py
# or
python3 compare.py --serve
```

### 2. Run Pure Post-Heat-Pump Period (15 Sep - Now)
```bash
python3 compare.py --from 2026-09-15 --to 2026-10-30 --battery 5 --html
```

### 3. Open the Interactive Visual Dashboard
Double-click or open [`tariff_comparison_report.html`](./tariff_comparison_report.html) in any browser (or visit [http://localhost:8050](http://localhost:8050) when running with `--serve`).

> [!NOTE]
> **How the Update Dialogue works:**
> When you open the HTML report, if the cached smart meter data is older than today, a subtle dialogue asks if you want to update.
> - If `python3 server.py` is running, clicking **"Yes, Update Now"** automatically fetches recent readings from Kraken and updates the graphs live.
> - If the server is offline, it provides a 1-click copyable terminal command to update the file directly.
