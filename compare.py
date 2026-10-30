#!/usr/bin/env python3
"""
Octopus Agile vs Cosy Tariff Comparison CLI Tool
Analyzes actual half-hourly electricity consumption with heat pump loads,
optionally converts past gas heating using Seasonal COP,
and generates a self-contained interactive visual dashboard with client-side sliders.

Scenarios:
1. Agile Octopus (Base)
2. Cosy Octopus (Base)
3. Agile Octopus + Battery (e.g. 5 kWh or 10 kWh)
4. Cosy Octopus + Battery (e.g. 5 kWh or 10 kWh)
"""

import os
import sys
import json
import argparse
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any

from octopus_client import OctopusClient, load_env_file
from tariff_comparator import TariffComparator, parse_iso
from gas_converter import merge_converted_gas_with_electricity


def generate_heatpump_demo_data(days: int = 30) -> Dict[str, Any]:
    """Generate realistic 30-minute electricity consumption for demo mode."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_time = now - timedelta(days=days)

    consumption = []
    agile_rates = []
    cosy_rates = []

    current_dt = start_time
    while current_dt < now:
        interval_end = current_dt + timedelta(minutes=30)
        dt_str = current_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = interval_end.strftime("%Y-%m-%dT%H:%M:%SZ")

        hour = current_dt.hour
        base_load = random.uniform(0.15, 0.30)

        hp_load = 0.0
        if 5 <= hour < 9:
            hp_load = random.uniform(0.8, 1.6)
        elif 9 <= hour < 16:
            hp_load = random.uniform(0.3, 0.7)
        elif 16 <= hour < 20:
            hp_load = random.uniform(0.7, 1.4)
        elif 20 <= hour < 23:
            hp_load = random.uniform(0.4, 0.8)
        else:
            hp_load = random.uniform(0.2, 0.5)

        total_slot_kwh = round(base_load + hp_load, 3)
        consumption.append({
            "consumption": total_slot_kwh,
            "interval_start": dt_str,
            "interval_end": end_str,
        })

        if (4 <= hour < 7) or (13 <= hour < 16) or (22 <= hour < 24):
            cosy_rate = 14.12
        elif 16 <= hour < 19:
            cosy_rate = 43.19
        else:
            cosy_rate = 28.80

        cosy_rates.append({
            "value_inc_vat": cosy_rate,
            "valid_from": dt_str,
            "valid_to": end_str,
        })

        if 0 <= hour < 6:
            agile_rate = random.uniform(10.0, 16.0)
        elif 6 <= hour < 16:
            agile_rate = random.uniform(17.0, 25.0)
        elif 16 <= hour < 19:
            agile_rate = random.uniform(32.0, 44.0)
        elif 19 <= hour < 22:
            agile_rate = random.uniform(22.0, 28.0)
        else:
            agile_rate = random.uniform(13.0, 19.0)

        agile_rates.append({
            "value_inc_vat": round(agile_rate, 2),
            "valid_from": dt_str,
            "valid_to": end_str,
        })

        current_dt = interval_end

    return {
        "consumption": consumption,
        "agile_rates": agile_rates,
        "cosy_rates": cosy_rates,
    }


def print_cli_report(res: Dict[str, Any], gas_included: bool = False, scop: float = 3.5) -> None:
    """Print the complete 4-way comparison report in the terminal."""
    s = res["summary"]
    sc = res["scenarios"]
    tou = res["time_of_use_distribution"]

    reset = "\033[0m"
    bold = "\033[1m"
    green = "\033[92m"
    yellow = "\033[93m"

    ag_b = sc["agile"]
    co_b = sc["cosy"]
    ag_bat = sc["agile_battery"]
    co_bat = sc["cosy_battery"]

    b_size = s["battery_kwh"]

    print("\n" + "=" * 90)
    print(f"{bold} OCTOPUS ENERGY 4-WAY TARIFF & BATTERY COMPARISON REPORT{reset}")
    print("=" * 90)
    print(f" Analyzed Days:          {s['total_days']} days ({s['intervals_analyzed']} half-hour intervals)")
    print(f" Total Electricity Used: {s['total_kwh']} kWh (avg {round(s['total_kwh']/s['total_days'], 1)} kWh/day)")
    if gas_included:
        print(f" Past Gas Conversion:    {green}ACTIVE{reset} (Converted using Seasonal COP = {scop})")
    print(f" Simulated Battery:      {b_size} kWh capacity ({b_size * 0.9:.1f} kWh usable, 90% round-trip efficiency)")
    print("-" * 90)
    print(f"{bold}{'Tariff Metric':<26} {'1. Agile (Base)':<16} {'2. Cosy (Base)':<16} {f'3. Agile+{b_size:.1f}kWh':<16} {f'4. Cosy+{b_size:.1f}kWh':<16}{reset}")
    print("-" * 90)
    print(f"{'Unit Electricity Cost':<26} £{ag_b['unit_cost_pounds']:<15.2f} £{co_b['unit_cost_pounds']:<15.2f} £{ag_bat['unit_cost_pounds']:<15.2f} £{co_bat['unit_cost_pounds']:<15.2f}")
    print(f"{'Standing Charges':<26} £{ag_b['standing_charge_pounds']:<15.2f} £{co_b['standing_charge_pounds']:<15.2f} £{ag_bat['standing_charge_pounds']:<15.2f} £{co_bat['standing_charge_pounds']:<15.2f}")
    print(f"{bold}{'Total Cost':<26} £{ag_b['total_cost_pounds']:<15.2f} £{co_b['total_cost_pounds']:<15.2f} £{ag_bat['total_cost_pounds']:<15.2f} £{co_bat['total_cost_pounds']:<15.2f}{reset}")
    print(f"{'Effective Average Rate':<26} {ag_b['average_unit_rate_p_per_kwh']:<15.2f} {co_b['average_unit_rate_p_per_kwh']:<15.2f} {ag_bat['average_unit_rate_p_per_kwh']:<15.2f} {co_bat['average_unit_rate_p_per_kwh']:<15.2f} p/kWh")
    print("-" * 90)
    sav_co_b = f"+£{co_b['saving_pounds']:.2f} ({co_b['saving_percentage']}%)" if co_b['saving_pounds'] >= 0 else f"-£{abs(co_b['saving_pounds']):.2f}"
    sav_ag_bat = f"+£{ag_bat['saving_pounds']:.2f} ({ag_bat['saving_percentage']}%)" if ag_bat['saving_pounds'] >= 0 else f"-£{abs(ag_bat['saving_pounds']):.2f}"
    sav_co_bat = f"+£{co_bat['saving_pounds']:.2f} ({co_bat['saving_percentage']}%)" if co_bat['saving_pounds'] >= 0 else f"-£{abs(co_bat['saving_pounds']):.2f}"
    print(f"{bold}{'Savings vs Agile Baseline':<26} {'Baseline':<16} {sav_co_b:<16} {sav_ag_bat:<16} {green}{sav_co_bat:<16}{reset}")
    print("-" * 90)
    print(f"{bold}KEY TAKEAWAY:{reset} {green}{s['winner']}{reset} is the cheapest option, saving {bold}£{s['max_saving_pounds']:.2f} ({s['max_saving_percentage']}%){reset} vs your current Agile setup!")
    print("=" * 90)

    print(f"\n{bold}HEAT PUMP TIME-OF-USE BREAKDOWN (Cosy Time Bands):{reset}")
    print(f" • Dip Hours (04-07, 13-16, 22-00):  {tou['dip_hours_kwh']:>8.1f} kWh ({tou['dip_hours_percentage']:>4.1f}%) [Cheap ~14p rate]")
    print(f" • Standard Hours:                   {tou['standard_hours_kwh']:>8.1f} kWh ({tou['standard_hours_percentage']:>4.1f}%) [Standard ~28p rate]")
    print(f" • Peak Hours (16:00 - 19:00):       {tou['peak_hours_kwh']:>8.1f} kWh ({tou['peak_hours_percentage']:>4.1f}%) [Peak ~43p rate]")
    print("-" * 90)

    print(f"{yellow}🔋 BATTERY SYNERGY INSIGHT:{reset}")
    print(f"   • On Cosy, the {b_size:.1f} kWh battery completely eliminates the {tou['peak_hours_kwh']:.1f} kWh peak ({tou['peak_hours_percentage']}%) by pre-charging")
    print("     at ~14.1p during 13:00-16:00, saving ~29.1p on every kWh shifted!")
    print(f"   • On Agile, afternoon grid rates are ~22-26p, so battery peak arbitrage is only ~10-15p.")
    print("=" * 90 + "\n")


def generate_interactive_html_dashboard(
    daily_records: List[Dict[str, Any]],
    agile_sc_day: float,
    cosy_sc_day: float,
    default_battery: float = 5.0,
    default_scop: float = 3.5,
    gas_available: bool = True,
    filepath: str = "tariff_comparison_report.html",
) -> None:
    """
    Generate a self-contained interactive visual dashboard with client-side sliders
    for Battery Size, COP, Gas Conversion, and Date Range selection.
    """
    last_date_str = daily_records[-1]["date"] if daily_records else "2026-10-28"
    first_date_str = daily_records[0]["date"] if daily_records else "2025-10-29"
    generated_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    data_json = json.dumps(daily_records)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Octopus Energy: Interactive Tariff & Heat Pump Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-primary: #0b1120;
            --bg-card: #151f32;
            --bg-control: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --agile-color: #38bdf8;
            --cosy-color: #f43f5e;
            --agile-bat-color: #a855f7;
            --cosy-bat-color: #10b981;
            --border-color: #243248;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 1350px;
            margin: 0 auto;
        }}
        header {{
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            flex-wrap: wrap;
            gap: 15px;
        }}
        h1 {{
            margin: 0 0 6px 0;
            font-size: 26px;
            color: #fff;
        }}
        .subtitle {{
            color: var(--text-secondary);
            font-size: 14px;
        }}
        /* CONTROLS PANEL */
        .controls-panel {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }}
        .controls-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            align-items: center;
        }}
        .control-group {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .control-label {{
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            display: flex;
            justify-content: space-between;
        }}
        .control-val {{
            color: var(--agile-color);
            font-weight: 700;
        }}
        input[type="range"] {{
            width: 100%;
            height: 6px;
            border-radius: 3px;
            background: #334155;
            outline: none;
            cursor: pointer;
            accent-color: #38bdf8;
        }}
        .toggle-group {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .switch {{
            position: relative;
            display: inline-block;
            width: 48px;
            height: 24px;
        }}
        .switch input {{ opacity: 0; width: 0; height: 0; }}
        .slider {{
            position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
            background-color: #334155;
            transition: .3s;
            border-radius: 24px;
        }}
        .slider:before {{
            position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px;
            background-color: white;
            transition: .3s;
            border-radius: 50%;
        }}
        input:checked + .slider {{ background-color: var(--cosy-bat-color); }}
        input:checked + .slider:before {{ transform: translateX(24px); }}
        .preset-buttons {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 14px;
            padding-top: 14px;
            border-top: 1px solid var(--border-color);
        }}
        .btn {{
            background: var(--bg-control);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn:hover, .btn.active {{
            background: var(--agile-color);
            color: #0b1120;
            font-weight: 600;
            border-color: var(--agile-color);
        }}
        /* KPI SCENARIO CARDS */
        .scenario-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .card {{
            background: var(--bg-card);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid var(--border-color);
            position: relative;
            transition: transform 0.2s;
        }}
        .card.winner-card {{
            border: 2px solid var(--cosy-bat-color);
            box-shadow: 0 0 20px rgba(16, 185, 129, 0.25);
        }}
        .badge-winner {{
            position: absolute;
            top: -10px;
            right: 15px;
            background: var(--cosy-bat-color);
            color: #0b1120;
            font-weight: 700;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 20px;
            text-transform: uppercase;
        }}
        .card-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 12px;
        }}
        .dot {{ width: 12px; height: 12px; border-radius: 50%; }}
        .card-title {{ font-size: 15px; font-weight: 600; color: #fff; }}
        .card-cost {{ font-size: 32px; font-weight: 700; margin-bottom: 6px; }}
        .card-rate {{ color: var(--text-secondary); font-size: 14px; margin-bottom: 10px; }}
        .card-saving {{
            font-size: 13px;
            padding: 6px 10px;
            border-radius: 6px;
            background: rgba(255, 255, 255, 0.05);
            display: inline-block;
        }}
        .saving-positive {{
            color: var(--cosy-bat-color);
            background: rgba(16, 185, 129, 0.12);
            font-weight: 600;
        }}
        /* CHARTS SECTION */
        .charts-container {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }}
        @media (max-width: 980px) {{
            .charts-container {{ grid-template-columns: 1fr; }}
        }}
        .chart-card {{
            background: var(--bg-card);
            border-radius: 12px;
            padding: 22px;
            border: 1px solid var(--border-color);
        }}
        .chart-title {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 15px;
            color: var(--text-primary);
        }}
        /* INFO SECTION */
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        @media (max-width: 800px) {{
            .info-grid {{ grid-template-columns: 1fr; }}
        }}
        .info-card {{
            background: var(--bg-card);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid var(--border-color);
        }}
        .info-card h3 {{ margin: 0 0 10px 0; font-size: 16px; }}
        ul {{ margin: 0; padding-left: 20px; color: var(--text-secondary); font-size: 14px; line-height: 1.6; }}

        /* NON-INTRUSIVE UPDATE DIALOGUE */
        .modal-overlay {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.65);
            backdrop-filter: blur(6px);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 9999;
        }}
        .modal-box {{
            background: #1e293b;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 14px;
            padding: 24px 28px;
            max-width: 480px;
            width: 90%;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7);
            animation: modalFadeIn 0.2s ease-out;
        }}
        @keyframes modalFadeIn {{
            from {{ opacity: 0; transform: scale(0.96); }}
            to {{ opacity: 1; transform: scale(1); }}
        }}
        .btn-update-primary {{
            background: linear-gradient(135deg, #10b981, #059669);
            color: #ffffff;
            font-weight: 600;
            padding: 10px 18px;
            border-radius: 6px;
            border: none;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 14px;
        }}
        .btn-update-primary:hover {{
            background: linear-gradient(135deg, #059669, #047857);
            transform: translateY(-1px);
        }}
        .btn-dialogue-cancel {{
            background: transparent;
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
            padding: 10px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }}
        .btn-dialogue-cancel:hover {{
            color: var(--text-primary);
            border-color: var(--text-secondary);
        }}
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        .spinner {{
            width: 36px;
            height: 36px;
            border: 3px solid rgba(255, 255, 255, 0.15);
            border-top: 3px solid #10b981;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin: 0 auto 16px auto;
        }}
    </style>
</head>
<body>
    <!-- NON-INTRUSIVE UPDATE DIALOGUE -->
    <div id="updateDialogue" class="modal-overlay" onclick="handleOverlayClick(event)">
        <div class="modal-box">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span id="dlgModalHeaderIcon" style="font-size: 22px;">⚡</span>
                    <h3 id="dlgModalHeaderTitle" style="margin: 0; font-size: 17px; color: var(--text-primary);">Smart Meter Data Status</h3>
                </div>
                <button onclick="dismissDialogue()" style="background: none; border: none; color: var(--text-secondary); font-size: 20px; cursor: pointer;">&times;</button>
            </div>
            
            <!-- STATE 1: PROMPT -->
            <div id="dialoguePrompt">
                <div id="dlgStatusAlert" style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 8px; padding: 12px 14px; margin-bottom: 16px;">
                    <div style="display: flex; gap: 8px; align-items: flex-start;">
                        <span style="font-size: 18px;">ℹ️</span>
                        <div style="font-size: 13px; color: #cbd5e1; line-height: 1.5;" id="dlgPromptMessage">
                            Readings on file through: <strong id="dlgLastDate" style="color: #38bdf8;">{last_date_str}</strong> <span id="dlgDaysAgoText" style="color: var(--text-secondary);">(2 days ago)</span>.<br><br>
                            In the UK, SMETS2 smart meters transmit half-hourly data across the cellular DCC network overnight, settling with Octopus with a standard <strong>24–48 hour delay</strong>. Data through <strong>{last_date_str}</strong> is currently the latest available.
                        </div>
                    </div>
                </div>
                <p style="color: var(--text-primary); font-size: 14px; font-weight: 500; margin: 0 0 20px 0;">
                    Would you like to query Octopus Kraken now to check for newer intervals?
                </p>

                <div style="display: flex; justify-content: flex-end; gap: 10px;">
                    <button class="btn-dialogue-cancel" onclick="dismissDialogue()">Keep Existing</button>
                    <button class="btn-update-primary" id="btnRunUpdate" onclick="executeDataUpdate()">
                        <span>⚡</span> Check Octopus Now
                    </button>
                </div>
            </div>

            <!-- STATE 2: LOADING -->
            <div id="dialogueLoading" style="display: none; text-align: center; padding: 20px 10px;">
                <div class="spinner"></div>
                <h4 style="margin: 0 0 8px 0; font-size: 16px; color: var(--text-primary);">Contacting Octopus Kraken API...</h4>
                <p style="color: var(--text-secondary); font-size: 13px; margin: 0 0 6px 0;">
                    Fetching recent half-hourly intervals and half-hourly Agile/Cosy tariff rates.
                </p>
                <p style="color: #64748b; font-size: 12px; margin: 0;">
                    Please wait 15–30 seconds while Octopus compiles intervals.
                </p>
            </div>

            <!-- STATE 3: RESULT SUCCESS -->
            <div id="dialogueResult" style="display: none; text-align: center; padding: 10px 0;">
                <div id="dlgResultIcon" style="font-size: 40px; margin-bottom: 12px;">✅</div>
                <h4 id="dlgResultTitle" style="margin: 0 0 10px 0; font-size: 17px; color: var(--text-primary);">Already Up to Date!</h4>
                <p id="dlgResultMessage" style="color: var(--text-secondary); font-size: 14px; line-height: 1.6; margin: 0 0 20px 0;">
                    Octopus confirmed that <strong>{last_date_str}</strong> is the latest validated reading on your meter.
                </p>
                <div style="display: flex; justify-content: center;">
                    <button class="btn-update-primary" onclick="dismissDialogue()">
                        View Dashboard
                    </button>
                </div>
            </div>

            <!-- STATE 4: FALLBACK (WHEN SERVER IS OFFLINE) -->
            <div id="dialogueFallback" style="display: none;">
                <p style="color: #f87171; font-size: 14px; font-weight: 500; margin: 0 0 8px 0;">
                    ⚠️ Companion Server Not Reachable on Port 8050
                </p>
                <div id="dlgFallbackError" style="display: none; font-size: 12px; color: #f87171; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); padding: 6px 10px; border-radius: 6px; margin-bottom: 12px; font-family: monospace;"></div>
                <div style="background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 8px; padding: 10px 12px; margin-bottom: 14px; font-size: 13px; color: #cbd5e1; line-height: 1.5;">
                    💡 <strong>Tip:</strong> If you opened this file directly from disk (<code>file:///...</code>), your browser blocks background network calls. Open the dashboard directly via the server:
                    <div style="margin-top: 6px;">
                        <a href="http://localhost:8050" target="_blank" style="color: #38bdf8; font-weight: 600; text-decoration: underline; font-size: 14px;">👉 http://localhost:8050</a>
                    </div>
                </div>
                <p style="color: var(--text-secondary); font-size: 13px; line-height: 1.5; margin: 0 0 8px 0;">
                    Ensure the companion server is running in terminal:
                </p>
                <div style="display: flex; gap: 8px; align-items: center; background: #0b1120; border: 1px solid var(--border-color); padding: 8px 12px; border-radius: 6px; margin-bottom: 16px;">
                    <code style="color: #10b981; font-family: monospace; font-size: 13px; flex: 1;">python3 compare.py --serve</code>
                    <button onclick="copyCommand('python3 compare.py --serve', this)" class="btn" style="padding: 4px 10px; font-size: 12px; background: rgba(255,255,255,0.08); border: 1px solid var(--border-color); color: #fff; cursor: pointer;">📋 Copy</button>
                </div>
                <div style="display: flex; justify-content: flex-end; gap: 10px;">
                    <button class="btn-update-primary" onclick="executeDataUpdate()" style="padding: 6px 14px; font-size: 13px;">🔄 Retry</button>
                    <button class="btn-dialogue-cancel" onclick="dismissDialogue()">Close</button>
                </div>
            </div>
        </div>
    </div>

    <div class="container">
        <header>
            <div>
                <h1>Octopus Energy: Interactive Tariff & Heat Pump Dashboard</h1>
                <div class="subtitle" id="timeframeSubtitle">
                    Real-time simulation across your actual smart meter intervals &bull; 
                    Data through: <strong id="headerLastDate" style="color: #38bdf8;">{last_date_str}</strong> &bull; 
                    Status: <span id="headerFreshnessBadge" style="color: #10b981; font-weight: 600;">✓ Up to Date</span> &bull; 
                    Generated: <span id="headerCheckedTime" style="color: var(--text-secondary);">{generated_timestamp}</span>
                    (<a href="javascript:void(0)" onclick="openUpdateDialogue(RAW_DATA.length ? RAW_DATA[RAW_DATA.length-1].date : '{last_date_str}')" style="color: #38bdf8; text-decoration: none; border-bottom: 1px dotted #38bdf8; cursor: pointer;" title="Check Octopus API for newer readings">Check updates</a>)
                </div>
            </div>
            <div id="quickStats" style="font-size: 14px; color: var(--text-secondary); text-align: right;"></div>
        </header>

        <!-- INTERACTIVE CONTROLS -->
        <div class="controls-panel">
            <div class="controls-grid">
                <!-- Battery Slider -->
                <div class="control-group">
                    <div class="control-label">
                        <span>Domestic Battery Size</span>
                        <span class="control-val" id="batteryValDisplay">{default_battery:.0f} kWh</span>
                    </div>
                    <input type="range" id="batterySlider" min="0" max="15" step="1" value="{default_battery:.0f}">
                    <span style="font-size: 12px; color: var(--text-secondary);" id="usableCapacityText">Usable: {default_battery * 0.9:.1f} kWh (90% DoD)</span>
                </div>

                <!-- COP Slider -->
                <div class="control-group">
                    <div class="control-label">
                        <span>Heat Pump Seasonal COP</span>
                        <span class="control-val" id="scopValDisplay">{default_scop:.1f}</span>
                    </div>
                    <input type="range" id="scopSlider" min="2.5" max="4.5" step="0.1" value="{default_scop:.1f}">
                    <span style="font-size: 12px; color: var(--text-secondary);">Higher COP = less electricity needed per unit of heat</span>
                </div>

                <!-- Automation / Load Shifting Slider -->
                <div class="control-group">
                    <div class="control-label">
                        <span>Automation / Dip Shifting</span>
                        <span class="control-val" id="shiftValDisplay">50%</span>
                    </div>
                    <input type="range" id="shiftSlider" min="0" max="90" step="5" value="50">
                    <span style="font-size: 12px; color: var(--text-secondary);">Shifts heating out of peak/daytime into 14p dips</span>
                </div>

                <!-- Gas Toggle -->
                <div class="control-group">
                    <div class="control-label">
                        <span>Past Gas Heating Conversion</span>
                    </div>
                    <div class="toggle-group">
                        <label class="switch">
                            <input type="checkbox" id="gasToggle" checked>
                            <span class="slider"></span>
                        </label>
                        <span style="font-size: 13px; color: var(--text-secondary);" id="gasToggleLabel">Includes past winter gas converted to HP</span>
                    </div>
                </div>

                <!-- Export Tariff Toggle -->
                <div class="control-group">
                    <div class="control-label">
                        <span>Octopus Export Tariff</span>
                        <span class="control-val" id="exportRateDisplay" style="color: #38bdf8;">Agile Peak</span>
                    </div>
                    <div class="toggle-group" style="margin-bottom: 6px;">
                        <label class="switch">
                            <input type="checkbox" id="exportToggle" checked>
                            <span class="slider"></span>
                        </label>
                        <span style="font-size: 13px; color: var(--text-secondary);" id="exportToggleLabel">Export surplus battery power during 16–19 peak</span>
                    </div>
                    <select id="exportTariffSelect" style="background: var(--bg-control); color: var(--text-primary); border: 1px solid var(--border-color); padding: 5px 8px; border-radius: 6px; font-size: 12px; width: 100%;">
                        <option value="agile_outgoing" selected>Agile Outgoing (Dynamic Peak ~25–45p)</option>
                        <option value="fixed_15">Fixed Outgoing (15.0 p/kWh)</option>
                    </select>
                </div>

                <!-- Custom Date Range Pickers -->
                <div class="control-group" style="grid-column: span 2;">
                    <div class="control-label">
                        <span>Custom Date Range Picker</span>
                        <span class="control-val" id="dateRangeDisplay">Custom Range</span>
                    </div>
                    <div style="display: flex; gap: 10px; align-items: center;">
                        <input type="date" id="startDateInput" value="{first_date_str}" min="{first_date_str}" max="{last_date_str}" style="background: var(--bg-control); color: var(--text-primary); border: 1px solid var(--border-color); padding: 7px 12px; border-radius: 6px; font-size: 14px; flex: 1;">
                        <span style="color: var(--text-secondary);">to</span>
                        <input type="date" id="endDateInput" value="{last_date_str}" min="{first_date_str}" max="{last_date_str}" style="background: var(--bg-control); color: var(--text-primary); border: 1px solid var(--border-color); padding: 7px 12px; border-radius: 6px; font-size: 14px; flex: 1;">
                    </div>
                </div>
            </div>

            <!-- Date Presets -->
            <div class="preset-buttons">
                <span style="font-size: 13px; color: var(--text-secondary); align-self: center; margin-right: 6px;">Date Presets:</span>
                <button class="btn active" id="btnAll" onclick="setPreset('all')">Full Year (365d)</button>
                <button class="btn" id="btnPostHp" onclick="setPreset('post_hp')">Post-Heat-Pump Only (15 Sep - Now)</button>
                <button class="btn" id="btnWinter" onclick="setPreset('winter')">Winter with Gas Heat (Nov - Mar)</button>
                <button class="btn" id="btnSummer" onclick="setPreset('summer')">Summer (May - Aug)</button>
            </div>
        </div>

        <!-- 4 SCENARIOS KPI GRID -->
        <div class="scenario-grid">
            <!-- 1. Agile Base -->
            <div class="card" id="cardAgileBase">
                <div class="card-header">
                    <div class="dot" style="background: var(--agile-color);"></div>
                    <div class="card-title">1. Agile (Current)</div>
                </div>
                <div class="card-cost" style="color: var(--agile-color);" id="agileBaseCost">£0.00</div>
                <div class="card-rate">Effective Rate: <strong id="agileBaseRate">0.00 p/kWh</strong></div>
                <div class="card-saving">Current Baseline</div>
            </div>

            <!-- 2. Cosy Base -->
            <div class="card" id="cardCosyBase">
                <div class="card-header">
                    <div class="dot" style="background: var(--cosy-color);"></div>
                    <div class="card-title">2. Cosy (Base)</div>
                </div>
                <div class="card-cost" style="color: var(--cosy-color);" id="cosyBaseCost">£0.00</div>
                <div class="card-rate">Effective Rate: <strong id="cosyBaseRate">0.00 p/kWh</strong></div>
                <div class="card-saving" id="cosyBaseSaving">Saves £0.00</div>
            </div>

            <!-- 3. Agile + Battery -->
            <div class="card" id="cardAgileBat">
                <div class="card-header">
                    <div class="dot" style="background: var(--agile-bat-color);"></div>
                    <div class="card-title" id="agileBatTitle">3. Agile + Battery</div>
                </div>
                <div class="card-cost" style="color: var(--agile-bat-color);" id="agileBatCost">£0.00</div>
                <div class="card-rate">Effective Rate: <strong id="agileBatRate">0.00 p/kWh</strong></div>
                <div class="card-export" id="agileBatExport" style="font-size: 12px; color: #38bdf8; margin-bottom: 8px; font-weight: 600; display: none;">⚡ Export Credit: +£0.00</div>
                <div class="card-saving" id="agileBatSaving">Saves £0.00</div>
            </div>

            <!-- 4. Cosy + Battery -->
            <div class="card" id="cardCosyBat">
                <div class="card-header">
                    <div class="dot" style="background: var(--cosy-bat-color);"></div>
                    <div class="card-title" id="cosyBatTitle">4. Cosy + Battery</div>
                </div>
                <div class="card-cost" style="color: var(--cosy-bat-color);" id="cosyBatCost">£0.00</div>
                <div class="card-rate">Effective Rate: <strong id="cosyBatRate">0.00 p/kWh</strong></div>
                <div class="card-export" id="cosyBatExport" style="font-size: 12px; color: #10b981; margin-bottom: 8px; font-weight: 600; display: none;">⚡ Export Credit: +£0.00</div>
                <div class="card-saving saving-positive" id="cosyBatSaving">Saves £0.00</div>
            </div>
        </div>

        <!-- CHARTS SECTION -->
        <div class="charts-container">
            <div class="chart-card">
                <div class="chart-title">Daily Electricity Cost Timeline (£) — 4 Scenarios</div>
                <canvas id="costTimelineChart" height="240"></canvas>
            </div>
            <div class="chart-card">
                <div class="chart-title">Time of Use Distribution (Cosy Bands)</div>
                <canvas id="touDoughnut" height="240"></canvas>
            </div>
        </div>

        <!-- STRATEGY INSIGHTS -->
        <div class="info-grid" style="grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));">
            <div class="info-card">
                <h3 style="color: var(--cosy-bat-color);">The Cosy + Battery Synergy</h3>
                <ul>
                    <li><strong>Pre-Peak Dip (13:00–16:00):</strong> The battery charges to 100% at ~14.1p immediately before the 16:00 peak, completely wiping out the 43p rate.</li>
                    <li><strong>Two Full Cycles Daily:</strong> Overnight dip (04:00–07:00) heats the house for morning; afternoon dip recharges for evening peak.</li>
                    <li><strong>Guaranteed Margins:</strong> Dip rates are fixed by contract. Zero risk of negative arbitrage or price spikes.</li>
                </ul>
            </div>
            <div class="info-card">
                <h3 style="color: var(--agile-bat-color);">Agile Dynamics</h3>
                <ul>
                    <li><strong>Overnight-Only Dips:</strong> Daytime and afternoon rates are elevated (22–26p), giving low arbitrage margins against evening peaks.</li>
                    <li><strong>Wind Volatility:</strong> Low-wind autumn/winter nights push overnight prices above 25–30p, eliminating overnight battery charging value.</li>
                    <li><strong>Automation Requirement:</strong> Requires dynamic daily price calculation (e.g. Home Assistant + Predbat) instead of simple fixed timers.</li>
                </ul>
            </div>
            <div class="info-card">
                <h3 style="color: #38bdf8;">Octopus Outgoing Export Arbitrage</h3>
                <ul>
                    <li><strong>Surplus Battery Dumping:</strong> When household evening load is low (e.g. ~0.5 kWh), surplus battery capacity is exported to the grid at 16:00–19:00.</li>
                    <li><strong>Agile Outgoing (Wholesale):</strong> Earns dynamic 25p–45p/kWh during peak, yielding a net profit of 15p–25p over cheap dip charging costs.</li>
                    <li><strong>Fixed Outgoing (15p):</strong> Guaranteed 15.0p/kWh export rate, ideal for solar self-generation export or risk-free baseline returns.</li>
                </ul>
            </div>
        </div>
    </div>

    <script>
        let RAW_DATA = {data_json};
        const AGILE_SC_DAY = {agile_sc_day:.4f};
        const COSY_SC_DAY = {cosy_sc_day:.4f};

        let currentPreset = 'all';
        let chartInstance = null;
        let doughnutInstance = null;

        function setPreset(p) {{
            currentPreset = p;
            document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
            let btn = document.getElementById('btnAll');
            let start = RAW_DATA.length ? RAW_DATA[0].date : '{first_date_str}';
            let end = RAW_DATA.length ? RAW_DATA[RAW_DATA.length - 1].date : '{last_date_str}';
            if (p === 'post_hp') {{
                btn = document.getElementById('btnPostHp');
                start = '2026-09-15';
            }} else if (p === 'winter') {{
                btn = document.getElementById('btnWinter');
                start = RAW_DATA.length ? RAW_DATA[0].date : '{first_date_str}';
                end = '2026-03-31';
            }} else if (p === 'summer') {{
                btn = document.getElementById('btnSummer');
                start = '2026-05-01';
                end = '2026-08-31';
            }}
            if (btn) btn.classList.add('active');
            document.getElementById('startDateInput').value = start;
            document.getElementById('endDateInput').value = end;
            recalculate();
        }}

        function onCustomDateChange() {{
            document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
            recalculate();
        }}

        function recalculate() {{
            const batteryCap = parseFloat(document.getElementById('batterySlider').value);
            const scop = parseFloat(document.getElementById('scopSlider').value);
            const shiftPct = parseFloat(document.getElementById('shiftSlider').value) / 100.0;
            const includeGas = document.getElementById('gasToggle').checked;
            const includeExport = document.getElementById('exportToggle') ? document.getElementById('exportToggle').checked : false;
            const exportMode = document.getElementById('exportTariffSelect') ? document.getElementById('exportTariffSelect').value : 'agile_outgoing';

            document.getElementById('batteryValDisplay').innerText = batteryCap.toFixed(0) + ' kWh';
            document.getElementById('usableCapacityText').innerText = 'Usable: ' + (batteryCap * 0.9).toFixed(1) + ' kWh (90% DoD)';
            document.getElementById('scopValDisplay').innerText = scop.toFixed(1);
            document.getElementById('shiftValDisplay').innerText = (shiftPct * 100).toFixed(0) + '%';
            if (document.getElementById('exportRateDisplay')) {{
                document.getElementById('exportRateDisplay').innerText = !includeExport ? 'Disabled' : (exportMode === 'fixed_15' ? '15.0p Fixed' : 'Agile Peak Rate');
            }}

            const exportSuffix = (includeExport && batteryCap > 0) ? ' + Export' : '';
            document.getElementById('agileBatTitle').innerText = '3. Agile + ' + batteryCap.toFixed(0) + 'kWh' + exportSuffix;
            document.getElementById('cosyBatTitle').innerText = '4. Cosy + ' + batteryCap.toFixed(0) + 'kWh' + exportSuffix;

            // Filter date records based on date inputs
            const defaultStart = RAW_DATA.length ? RAW_DATA[0].date : '{first_date_str}';
            const defaultEnd = RAW_DATA.length ? RAW_DATA[RAW_DATA.length - 1].date : '{last_date_str}';
            const startVal = document.getElementById('startDateInput').value || defaultStart;
            const endVal = document.getElementById('endDateInput').value || defaultEnd;
            document.getElementById('dateRangeDisplay').innerText = startVal + ' to ' + endVal;

            const filtered = RAW_DATA.filter(d => d.date >= startVal && d.date <= endVal);

            const totalDays = filtered.length || 1;
            let totalKwh = 0;
            let totalDipKwh = 0;
            let totalStdKwh = 0;
            let totalPeakKwh = 0;

            let agileBaseUnitCost = 0;
            let cosyBaseUnitCost = 0;
            let agileBatUnitCost = 0;
            let cosyBatUnitCost = 0;
            let totalAgileExportCreditP = 0;
            let totalCosyExportCreditP = 0;

            const daysLabels = [];
            const agileBaseDaily = [];
            const cosyBaseDaily = [];
            const agileBatDaily = [];
            const cosyBatDaily = [];

            const usableBat = batteryCap * 0.90;
            const eff = 0.90;

            filtered.forEach(d => {{
                // Base electricity + converted gas (if active and prior to 2026-09-15)
                let gasKwh = 0;
                if (includeGas && d.date < '2026-09-15' && d.gas_m3 > 0) {{
                    gasKwh = (d.gas_m3 * 11.206 * 0.85) / scop;
                }}
                const dayKwh = d.elec_kwh + gasKwh;
                totalKwh += dayKwh;

                // Baseline distribution
                const dipRatio = d.dip_kwh / (d.elec_kwh || 1);
                const peakRatio = d.peak_kwh / (d.elec_kwh || 1);
                const stdRatio = d.std_kwh / (d.elec_kwh || 1);

                const rawDipKwh = dayKwh * dipRatio;
                const rawPeakKwh = dayKwh * peakRatio;
                const rawStdKwh = dayKwh * stdRatio;

                // Automated Load Shifting to 14p Dips
                const peakShift = rawPeakKwh * shiftPct;
                const stdShift = rawStdKwh * (shiftPct * 0.5);

                const dayPeakKwh = Math.max(0, rawPeakKwh - peakShift);
                const dayStdKwh = Math.max(0, rawStdKwh - stdShift);
                const dayDipKwh = rawDipKwh + peakShift + stdShift;

                totalDipKwh += dayDipKwh;
                totalPeakKwh += dayPeakKwh;
                totalStdKwh += dayStdKwh;

                // 1. Agile Base Cost
                const agUnitP = (dayKwh * d.agile_avg_p) - (peakShift * Math.max(0, d.agile_peak_p - d.agile_avg_p));
                const agDailyTotal = (agUnitP / 100.0) + AGILE_SC_DAY;
                agileBaseUnitCost += agUnitP;

                // 2. Cosy Base Cost (14.12p dip, 43.19p peak, 28.80p std)
                const coUnitP = (dayDipKwh * 14.12) + (dayPeakKwh * 43.19) + (dayStdKwh * 28.80);
                const coDailyTotal = (coUnitP / 100.0) + COSY_SC_DAY;
                cosyBaseUnitCost += coUnitP;

                // Continuous inverter power rating: 3.68 kW (UK standard G98 domestic export limit)
                // Over 3 peak hours (16:00 to 19:00), inverter can output at most 3.68 * 3.0 = 11.04 kWh total
                const maxInverterDischarge3h = 3.68 * 3.0;

                // 3. Cosy + Battery
                // Battery charges at 14.12p during afternoon dip, offsets peak up to usableBat
                let coBatUnitP = coUnitP;
                let coExportP = 0;
                if (batteryCap > 0) {{
                    // Household usage at this exact time takes absolute priority:
                    const peakCover = Math.min(usableBat, dayPeakKwh, maxInverterDischarge3h);
                    // Savings spread: 43.19p - (14.12p / eff) = 43.19 - 15.69 = 27.5p / kWh
                    const peakSavingP = peakCover * (43.19 - (14.12 / eff));
                    coBatUnitP -= peakSavingP;

                    // Remaining usable capacity that can ACTUALLY be exported:
                    // 1) Must not exceed remaining usable battery storage (DoD protected)
                    // 2) Must not exceed inverter output headroom after supplying the home
                    const remainingBatStorage = Math.max(0, usableBat - peakCover);
                    const remainingInverterHeadroom = Math.max(0, maxInverterDischarge3h - peakCover);
                    const exportableKwh = Math.min(remainingBatStorage, remainingInverterHeadroom);

                    // Octopus Export Tariff: export surplus capacity to grid during 16-19 peak
                    if (includeExport && exportableKwh > 0) {{
                        const exportRate = (exportMode === 'fixed_15') ? 15.0 : Math.max(15.0, d.agile_peak_p);
                        const margin = exportRate - (14.12 / eff);
                        if (margin > 0) {{
                            coExportP = exportableKwh * margin;
                            coBatUnitP -= coExportP;
                        }}
                    }} else if (batteryCap >= 8.0) {{
                        // No export: discharge remaining into standard hours if large battery
                        const stdShift = Math.min(remainingBatStorage * 0.4, dayStdKwh);
                        coBatUnitP -= stdShift * (28.80 - (14.12 / eff));
                    }}
                }}
                const coBatDailyTotal = (coBatUnitP / 100.0) + COSY_SC_DAY;
                cosyBatUnitCost += coBatUnitP;
                totalCosyExportCreditP += coExportP;

                // 4. Agile + Battery
                // Battery charges at night/afternoon when cheap (< 22p)
                let agBatUnitP = agUnitP;
                let agExportP = 0;
                if (batteryCap > 0 && d.agile_min_p < 22.0) {{
                    // Household usage at this exact time takes absolute priority:
                    const peakCover = Math.min(usableBat, dayPeakKwh, maxInverterDischarge3h);
                    const savingP = peakCover * Math.max(0, d.agile_peak_p - (d.agile_min_p / eff));
                    agBatUnitP -= savingP;

                    // Remaining usable capacity that can ACTUALLY be exported:
                    const remainingBatStorage = Math.max(0, usableBat - peakCover);
                    const remainingInverterHeadroom = Math.max(0, maxInverterDischarge3h - peakCover);
                    const exportableKwh = Math.min(remainingBatStorage, remainingInverterHeadroom);

                    // Octopus Export Tariff: export surplus capacity to grid during 16-19 peak
                    if (includeExport && exportableKwh > 0) {{
                        const exportRate = (exportMode === 'fixed_15') ? 15.0 : Math.max(15.0, d.agile_peak_p);
                        const margin = exportRate - (d.agile_min_p / eff);
                        if (margin > 0) {{
                            agExportP = exportableKwh * margin;
                            agBatUnitP -= agExportP;
                        }}
                    }}
                }}
                const agBatDailyTotal = (agBatUnitP / 100.0) + AGILE_SC_DAY;
                agileBatUnitCost += agBatUnitP;
                totalAgileExportCreditP += agExportP;

                daysLabels.push(d.date);
                agileBaseDaily.push(agDailyTotal);
                cosyBaseDaily.push(coDailyTotal);
                agileBatDaily.push(agBatDailyTotal);
                cosyBatDaily.push(coBatDailyTotal);
            }});

            const agBaseTotal = (agileBaseUnitCost / 100.0) + (AGILE_SC_DAY * totalDays);
            const coBaseTotal = (cosyBaseUnitCost / 100.0) + (COSY_SC_DAY * totalDays);
            const agBatTotal = (agileBatUnitCost / 100.0) + (AGILE_SC_DAY * totalDays);
            const coBatTotal = (cosyBatUnitCost / 100.0) + (COSY_SC_DAY * totalDays);

            // Update UI
            document.getElementById('agileBaseCost').innerText = '£' + agBaseTotal.toFixed(2);
            document.getElementById('agileBaseRate').innerText = (agileBaseUnitCost / totalKwh).toFixed(2) + ' p/kWh';

            document.getElementById('cosyBaseCost').innerText = '£' + coBaseTotal.toFixed(2);
            document.getElementById('cosyBaseRate').innerText = (cosyBaseUnitCost / totalKwh).toFixed(2) + ' p/kWh';
            const coSaving = agBaseTotal - coBaseTotal;
            document.getElementById('cosyBaseSaving').innerText = (coSaving >= 0 ? 'Saves £' : 'Costs +£') + Math.abs(coSaving).toFixed(2) + ' (' + (Math.abs(coSaving)/agBaseTotal*100).toFixed(1) + '%)';
            document.getElementById('cosyBaseSaving').className = 'card-saving ' + (coSaving >= 0 ? 'saving-positive' : '');

            // Agile + Battery
            document.getElementById('agileBatCost').innerText = '£' + agBatTotal.toFixed(2);
            document.getElementById('agileBatRate').innerText = (agileBatUnitCost / totalKwh).toFixed(2) + ' p/kWh';
            const agBatSaving = agBaseTotal - agBatTotal;
            document.getElementById('agileBatSaving').innerText = (agBatSaving >= 0 ? 'Saves £' : 'Costs +£') + Math.abs(agBatSaving).toFixed(2) + ' (' + (Math.abs(agBatSaving)/agBaseTotal*100).toFixed(1) + '%)';
            document.getElementById('agileBatSaving').className = 'card-saving ' + (agBatSaving >= 0 ? 'saving-positive' : '');

            const agExportElem = document.getElementById('agileBatExport');
            if (agExportElem) {{
                if (includeExport && batteryCap > 0 && totalAgileExportCreditP > 0) {{
                    agExportElem.style.display = 'block';
                    agExportElem.innerText = '⚡ Export Credit: +£' + (totalAgileExportCreditP / 100.0).toFixed(2);
                }} else {{
                    agExportElem.style.display = 'none';
                }}
            }}

            // Cosy + Battery
            document.getElementById('cosyBatCost').innerText = '£' + coBatTotal.toFixed(2);
            document.getElementById('cosyBatRate').innerText = (cosyBatUnitCost / totalKwh).toFixed(2) + ' p/kWh';
            const coBatSaving = agBaseTotal - coBatTotal;
            document.getElementById('cosyBatSaving').innerText = 'Saves £' + coBatSaving.toFixed(2) + ' (' + (coBatSaving/agBaseTotal*100).toFixed(1) + '%)';

            const coExportElem = document.getElementById('cosyBatExport');
            if (coExportElem) {{
                if (includeExport && batteryCap > 0 && totalCosyExportCreditP > 0) {{
                    coExportElem.style.display = 'block';
                    coExportElem.innerText = '⚡ Export Credit: +£' + (totalCosyExportCreditP / 100.0).toFixed(2);
                }} else {{
                    coExportElem.style.display = 'none';
                }}
            }}

            // Dynamically assign winner card and Lowest Cost badge
            const scenarios = [
                {{ id: 'cardAgileBase', total: agBaseTotal, name: 'Agile (Base)' }},
                {{ id: 'cardCosyBase', total: coBaseTotal, name: 'Cosy (Base)' }},
                {{ id: 'cardAgileBat', total: agBatTotal, name: 'Agile + Battery' }},
                {{ id: 'cardCosyBat', total: coBatTotal, name: 'Cosy + Battery' }}
            ];
            scenarios.sort((a, b) => a.total - b.total);
            const winner = scenarios[0];

            ['cardAgileBase', 'cardCosyBase', 'cardAgileBat', 'cardCosyBat'].forEach(cid => {{
                const c = document.getElementById(cid);
                c.classList.remove('winner-card');
                const b = c.querySelector('.badge-winner');
                if (b) b.remove();
            }});

            const winEl = document.getElementById(winner.id);
            winEl.classList.add('winner-card');
            const winBadge = document.createElement('div');
            winBadge.className = 'badge-winner';
            winBadge.innerText = 'Lowest Cost';
            winEl.prepend(winBadge);

            document.getElementById('quickStats').innerHTML = 
                '<strong>' + totalDays + ' days</strong> | Total: <strong>' + totalKwh.toFixed(1) + ' kWh</strong> (avg ' + (totalKwh/totalDays).toFixed(1) + ' kWh/day)';

            // Update Timeline Chart
            if (!chartInstance) {{
                const ctx = document.getElementById('costTimelineChart').getContext('2d');
                chartInstance = new Chart(ctx, {{
                    type: 'line',
                    data: {{
                        labels: daysLabels,
                        datasets: [
                            {{ label: '1. Agile (Base)', data: agileBaseDaily, borderColor: '#38bdf8', borderWidth: 1.5, tension: 0.15, pointRadius: 0 }},
                            {{ label: '2. Cosy (Base)', data: cosyBaseDaily, borderColor: '#f43f5e', borderWidth: 1.5, tension: 0.15, pointRadius: 0 }},
                            {{ label: '3. Agile + Bat', data: agileBatDaily, borderColor: '#a855f7', borderDash: [3, 3], borderWidth: 1.5, tension: 0.15, pointRadius: 0 }},
                            {{ label: '4. Cosy + Bat', data: cosyBatDaily, borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.08)', fill: true, borderWidth: 2.5, tension: 0.15, pointRadius: 0 }}
                        ]
                    }},
                    options: {{
                        responsive: true,
                        interaction: {{ mode: 'index', intersect: false }},
                        scales: {{
                            y: {{ grid: {{ color: '#243248' }}, ticks: {{ color: '#94a3b8', callback: v => '£' + v.toFixed(2) }} }},
                            x: {{ grid: {{ display: false }}, ticks: {{ color: '#94a3b8', maxTicksLimit: 12 }} }}
                        }},
                        plugins: {{ legend: {{ labels: {{ color: '#f8fafc' }} }} }}
                    }}
                }});
            }} else {{
                chartInstance.data.labels = daysLabels;
                chartInstance.data.datasets[0].data = agileBaseDaily;
                chartInstance.data.datasets[1].data = cosyBaseDaily;
                chartInstance.data.datasets[2].data = agileBatDaily;
                chartInstance.data.datasets[3].data = cosyBatDaily;
                chartInstance.update();
            }}

            // Update Doughnut Chart
            if (!doughnutInstance) {{
                const ctxD = document.getElementById('touDoughnut').getContext('2d');
                doughnutInstance = new Chart(ctxD, {{
                    type: 'doughnut',
                    data: {{
                        labels: ['Dip (~14p)', 'Standard (~28p)', 'Peak (~43p)'],
                        datasets: [{{
                            data: [totalDipKwh, totalStdKwh, totalPeakKwh],
                            backgroundColor: ['#10b981', '#38bdf8', '#f43f5e']
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#94a3b8' }} }} }}
                    }}
                }});
            }} else {{
                doughnutInstance.data.datasets[0].data = [totalDipKwh, totalStdKwh, totalPeakKwh];
                doughnutInstance.update();
            }}
        }}

        function showDialogueView(viewName) {{
            document.getElementById('dialoguePrompt').style.display = viewName === 'prompt' ? 'block' : 'none';
            document.getElementById('dialogueLoading').style.display = viewName === 'loading' ? 'block' : 'none';
            document.getElementById('dialogueResult').style.display = viewName === 'result' ? 'block' : 'none';
            document.getElementById('dialogueFallback').style.display = viewName === 'fallback' ? 'block' : 'none';
        }}

        function checkDataFreshness() {{
            if (!RAW_DATA || RAW_DATA.length === 0) return;
            const lastDate = RAW_DATA[RAW_DATA.length - 1].date;
            const headerDateElem = document.getElementById('headerLastDate');
            if (headerDateElem) headerDateElem.innerText = lastDate;

            const todayStr = new Date().toISOString().split('T')[0];
            const lastDateObj = new Date(lastDate);
            const diffTime = Math.abs(new Date(todayStr) - lastDateObj);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

            const badgeElem = document.getElementById('headerFreshnessBadge');
            if (badgeElem) {{
                if (diffDays <= 2) {{
                    badgeElem.innerText = '✓ Up to Date';
                    badgeElem.style.color = '#10b981';
                }} else {{
                    badgeElem.innerText = '⚠️ ' + diffDays + ' days behind';
                    badgeElem.style.color = '#f59e0b';
                }}
            }}

            // Only prompt if data is actually stale (> 2 days behind due to normal DCC 24-48h settlement delay)
            if (diffDays > 2 && sessionStorage.getItem('dismissUpdateDlg') !== 'true') {{
                openUpdateDialogue(lastDate, diffDays);
            }}
        }}

        function openUpdateDialogue(date, days) {{
            const lastDate = date || (RAW_DATA.length ? RAW_DATA[RAW_DATA.length - 1].date : '{last_date_str}');
            document.getElementById('dlgLastDate').innerText = lastDate;

            const todayStr = new Date().toISOString().split('T')[0];
            const lastDateObj = new Date(lastDate);
            const diffTime = Math.abs(new Date(todayStr) - lastDateObj);
            const calcDays = days !== undefined ? days : Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            
            document.getElementById('dlgDaysAgoText').innerText = calcDays === 0 ? '(Today)' : (calcDays === 1 ? '(1 day ago)' : '(' + calcDays + ' days ago)');
            
            const msgElem = document.getElementById('dlgPromptMessage');
            if (calcDays <= 2) {{
                msgElem.innerHTML = 'Readings on file through: <strong style="color: #38bdf8;">' + lastDate + '</strong> ' + 
                    '<span style="color: var(--text-secondary);">' + (calcDays === 1 ? '(yesterday)' : '(' + calcDays + ' days ago)') + '</span>.<br><br>' + 
                    'In the UK, SMETS2 smart meters transmit half-hourly data across the cellular DCC network overnight, settling with Octopus with a standard <strong>24–48 hour delay</strong>. ' + 
                    'Data through <strong>' + lastDate + '</strong> is currently the latest available.';
            }} else {{
                msgElem.innerHTML = 'Last recorded smart meter date is <strong style="color: #f59e0b;">' + lastDate + '</strong> (' + calcDays + ' days ago).<br><br>' + 
                    'Octopus Kraken should have newer validated readings ready to fetch.';
            }}

            showDialogueView('prompt');
            document.getElementById('updateDialogue').style.display = 'flex';
        }}

        function dismissDialogue() {{
            document.getElementById('updateDialogue').style.display = 'none';
            sessionStorage.setItem('dismissUpdateDlg', 'true');
        }}

        function handleOverlayClick(event) {{
            if (event.target && event.target.id === 'updateDialogue') {{
                dismissDialogue();
            }}
        }}

        async function executeDataUpdate() {{
            showDialogueView('loading');

            // Determine candidate endpoints:
            // 1. Same-origin relative URL if page loaded via web server (always works, zero CORS issues)
            // 2. http://127.0.0.1:8050/api/update (avoids macOS localhost IPv6 resolution mismatch)
            // 3. http://localhost:8050/api/update
            const candidateUrls = [];
            if (window.location.protocol.startsWith('http')) {{
                candidateUrls.push('/api/update');
            }}
            candidateUrls.push('http://127.0.0.1:8050/api/update');
            candidateUrls.push('http://localhost:8050/api/update');

            let lastError = null;

            for (const url of candidateUrls) {{
                try {{
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 180000); // 3 minutes timeout

                    const response = await fetch(url, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        signal: controller.signal
                    }});
                    clearTimeout(timeoutId);

                    if (response.ok) {{
                        const res = await response.json();
                        if (res.daily_records && res.daily_records.length > 0) {{
                            const oldLastDate = RAW_DATA.length ? RAW_DATA[RAW_DATA.length - 1].date : '';
                            RAW_DATA = res.daily_records;
                            const newLastDate = RAW_DATA[RAW_DATA.length - 1].date;
                            
                            document.getElementById('startDateInput').min = RAW_DATA[0].date;
                            document.getElementById('endDateInput').min = RAW_DATA[0].date;
                            document.getElementById('startDateInput').max = newLastDate;
                            document.getElementById('endDateInput').max = newLastDate;
                            document.getElementById('endDateInput').value = newLastDate;
                            
                            const headerDateElem = document.getElementById('headerLastDate');
                            if (headerDateElem) headerDateElem.innerText = newLastDate;
                            
                            const checkedElem = document.getElementById('headerCheckedTime');
                            if (checkedElem) {{
                                const now = new Date();
                                checkedElem.innerText = 'Today at ' + now.toLocaleTimeString([], {{hour: '2-digit', minute:'2-digit'}});
                            }}

                            const badgeElem = document.getElementById('headerFreshnessBadge');
                            if (badgeElem) {{
                                badgeElem.innerText = '✓ Up to Date';
                                badgeElem.style.color = '#10b981';
                            }}

                            recalculate();

                            // Configure and show Result state
                            if (newLastDate > oldLastDate) {{
                                document.getElementById('dlgResultIcon').innerText = '🎉';
                                document.getElementById('dlgResultTitle').innerText = 'New Data Loaded!';
                                document.getElementById('dlgResultMessage').innerHTML = 'Successfully fetched new intervals up to <strong>' + newLastDate + '</strong> from Octopus Kraken.';
                            }} else {{
                                document.getElementById('dlgResultIcon').innerText = '✅';
                                document.getElementById('dlgResultTitle').innerText = 'Already Up to Date!';
                                document.getElementById('dlgResultMessage').innerHTML = 'Octopus Kraken confirmed that <strong>' + newLastDate + '</strong> is the latest validated reading on your meter.<br><br><span style="font-size: 13px; color: #94a3b8;">In the UK, SMETS2 smart meters batch-upload via DCC with a standard <strong>24–48 hour settlement delay</strong>, so readings through ' + newLastDate + ' represent 100% current data.</span>';
                            }}
                            showDialogueView('result');
                            return;
                        }}
                    }}
                    throw new Error('Server returned HTTP ' + response.status);
                }} catch (err) {{
                    lastError = err;
                    console.log('Candidate endpoint ' + url + ' failed:', err);
                }}
            }}

            console.error('All update endpoints failed:', lastError);
            const errBox = document.getElementById('dlgFallbackError');
            if (errBox) {{
                errBox.innerText = 'Connection error: ' + (lastError ? (lastError.message || lastError.toString()) : 'Failed to connect');
                errBox.style.display = 'block';
            }}
            showDialogueView('fallback');
        }}

        function copyCommand(cmd, btn) {{
            navigator.clipboard.writeText(cmd).then(() => {{
                const originalText = btn.innerText;
                btn.innerText = '✅ Copied!';
                setTimeout(() => {{ btn.innerText = originalText; }}, 2000);
            }});
        }}

        // Listeners
        document.getElementById('batterySlider').addEventListener('input', recalculate);
        document.getElementById('scopSlider').addEventListener('input', recalculate);
        document.getElementById('shiftSlider').addEventListener('input', recalculate);
        document.getElementById('gasToggle').addEventListener('change', recalculate);
        document.getElementById('exportToggle').addEventListener('change', recalculate);
        document.getElementById('exportTariffSelect').addEventListener('change', recalculate);
        document.getElementById('startDateInput').addEventListener('change', onCustomDateChange);
        document.getElementById('endDateInput').addEventListener('change', onCustomDateChange);

        // Initial run
        recalculate();
        checkDataFreshness();
    </script>
</body>
</html>
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n📊 Interactive visual dashboard saved to: {os.path.abspath(filepath)}")


def run_comparison_pipeline(
    days: int = 365,
    period_from: Optional[str] = None,
    period_to: Optional[str] = None,
    battery: float = 5.0,
    gas: bool = False,
    scop: float = 3.5,
    boiler_eff: float = 0.85,
    generate_html: bool = True,
    refresh: bool = False,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Core data pipeline: fetches smart meter data & rates, calculates 4-way comparison,
    and optionally writes tariff_comparison_report.html.
    """
    load_env_file()

    api_key = os.environ.get("OCTOPUS_API_KEY", "").strip()
    account_number = os.environ.get("OCTOPUS_ACCOUNT_NUMBER", "").strip()

    if not api_key:
        raise ValueError("No OCTOPUS_API_KEY found in .env or environment.")

    client = OctopusClient(api_key=api_key, use_cache=not refresh)

    mpan = os.environ.get("OCTOPUS_ELECTRICITY_MPAN", "").strip()
    serial = os.environ.get("OCTOPUS_ELECTRICITY_SERIAL", "").strip()
    region = os.environ.get("OCTOPUS_REGION", "").strip()
    mprn = "2423607403"
    gas_serial = "G4P03434421700"
    current_tariff = None

    if not (mpan and serial and region):
        if not account_number.startswith("A-"):
            account_number = f"A-{account_number}"
        account_data = client.get_account(account_number)
        details = client.extract_electricity_details(account_data)
        mpan = mpan or details["mpan"]
        serial = serial or details["serial_number"]
        region = region or details["region_code"]
        mprn = details.get("mprn") or mprn
        gas_serial = details.get("gas_serial") or gas_serial
        current_tariff = details["tariff_code"]

    if not region:
        region = "C"

    # Date range setup
    if period_from:
        from_dt = datetime.fromisoformat(period_from).replace(tzinfo=timezone.utc)
    else:
        from_dt = datetime.now(timezone.utc) - timedelta(days=days)

    if period_to:
        to_dt = datetime.fromisoformat(period_to).replace(tzinfo=timezone.utc)
    else:
        to_dt = datetime.now(timezone.utc)

    from_iso = from_dt.strftime("%Y-%m-%dT00:00:00Z")
    to_iso = to_dt.strftime("%Y-%m-%dT00:00:00Z")

    if not quiet:
        print(f"\n📡 Fetching your actual half-hourly consumption from {from_iso} to {to_iso}...")
    consumption = client.get_half_hourly_consumption(mpan, serial, from_iso, to_iso)
    if not quiet:
        print(f"   Retrieved {len(consumption)} electricity intervals.")

    # Fetch gas consumption
    if not quiet:
        print(f"📡 Fetching your gas meter readings from {from_iso} to {to_iso}...")
    gas_consumption = client.get_gas_consumption(mprn, gas_serial, from_iso, to_iso)
    if not quiet:
        print(f"   Retrieved {len(gas_consumption)} gas intervals.")

    agile_product = "AGILE-24-10-01"
    agile_tariff = f"E-1R-AGILE-24-10-01-{region}"
    if current_tariff and "AGILE" in current_tariff:
        agile_tariff = current_tariff
        parts = current_tariff.split("-")
        if len(parts) >= 5:
            agile_product = f"{parts[2]}-{parts[3]}-{parts[4]}"

    if not quiet:
        print(f"📡 Fetching Agile rates ({agile_tariff})...")
    agile_rates = client.get_tariff_unit_rates(agile_product, agile_tariff, from_iso, to_iso)
    if not quiet:
        print(f"   Retrieved {len(agile_rates)} Agile rate records.")

    cosy_product = "COSY-22-12-08"
    cosy_tariff = f"E-1R-COSY-22-12-08-{region}"
    if not quiet:
        print(f"📡 Fetching Cosy rates ({cosy_tariff})...")
    cosy_rates = client.get_tariff_unit_rates(cosy_product, cosy_tariff, from_iso, to_iso)
    if not quiet:
        print(f"   Retrieved {len(cosy_rates)} Cosy rate records.")

    try:
        cosy_sc_data = client.get_standing_charges(cosy_product, cosy_tariff, from_iso, to_iso)
        cosy_sc = float(cosy_sc_data[0].get("value_inc_vat", 42.3)) if cosy_sc_data else 42.3
    except Exception:
        cosy_sc = 42.3

    try:
        agile_sc_data = client.get_standing_charges(agile_product, agile_tariff, from_iso, to_iso)
        agile_sc = float(agile_sc_data[0].get("value_inc_vat", 37.3)) if agile_sc_data else 37.3
    except Exception:
        agile_sc = 37.3

    # Merge gas if requested for CLI report
    active_consumption = consumption
    if gas:
        if not quiet:
            print(f"🔥 Converting gas using SCOP={scop} & Boiler Eff={boiler_eff}...")
        active_consumption = merge_converted_gas_with_electricity(
            consumption, gas_consumption, scop=scop, boiler_efficiency=boiler_eff
        )

    comparator = TariffComparator(
        consumption=active_consumption,
        agile_rates=agile_rates,
        cosy_rates=cosy_rates,
        agile_standing_charge_p_day=agile_sc,
        cosy_standing_charge_p_day=cosy_sc,
    )
    report = comparator.compare_four_way(battery_kwh=battery)
    if not quiet:
        print_cli_report(report, gas_included=gas, scop=scop)

    # Build rich daily records for the interactive browser dashboard
    daily_map: Dict[str, Dict[str, Any]] = {}
    gas_map = {g["interval_start"]: float(g.get("consumption", 0.0)) for g in gas_consumption}
    agile_rate_map = {r["valid_from"]: float(r.get("value_inc_vat", 0.0)) for r in agile_rates}

    for item in consumption:
        dt = parse_iso(item["interval_start"])
        day_key = dt.strftime("%Y-%m-%d")
        kwh = float(item.get("consumption", 0.0))
        gas_m3 = gas_map.get(item["interval_start"], 0.0)
        ag_rate = agile_rate_map.get(item["interval_start"], 20.0)

        hour = dt.hour
        time_dec = hour + dt.minute / 60.0
        is_dip = (4.0 <= time_dec < 7.0) or (13.0 <= time_dec < 16.0) or (22.0 <= time_dec < 24.0)
        is_peak = (16.0 <= time_dec < 19.0)

        entry = daily_map.setdefault(day_key, {
            "date": day_key,
            "elec_kwh": 0.0,
            "gas_m3": 0.0,
            "agile_cost_p": 0.0,
            "dip_kwh": 0.0,
            "peak_kwh": 0.0,
            "std_kwh": 0.0,
            "agile_rates": [],
            "agile_peak_rates": [],
        })

        entry["elec_kwh"] += kwh
        entry["gas_m3"] += gas_m3
        entry["agile_cost_p"] += kwh * ag_rate
        entry["agile_rates"].append(ag_rate)
        if is_peak:
            entry["peak_kwh"] += kwh
            entry["agile_peak_rates"].append(ag_rate)
        elif is_dip:
            entry["dip_kwh"] += kwh
        else:
            entry["std_kwh"] += kwh

    daily_records = []
    for day_key in sorted(daily_map.keys()):
        d = daily_map[day_key]
        rates = d["agile_rates"]
        peak_rates = d["agile_peak_rates"]
        avg_rate = (sum(rates) / len(rates)) if rates else 20.0
        min_rate = min(rates) if rates else 15.0
        avg_peak = (sum(peak_rates) / len(peak_rates)) if peak_rates else 35.0

        daily_records.append({
            "date": day_key,
            "elec_kwh": round(d["elec_kwh"], 2),
            "gas_m3": round(d["gas_m3"], 3),
            "agile_avg_p": round(avg_rate, 2),
            "agile_min_p": round(min_rate, 2),
            "agile_peak_p": round(avg_peak, 2),
            "dip_kwh": round(d["dip_kwh"], 2),
            "peak_kwh": round(d["peak_kwh"], 2),
            "std_kwh": round(d["std_kwh"], 2),
        })

    if generate_html:
        generate_interactive_html_dashboard(
            daily_records=daily_records,
            agile_sc_day=agile_sc / 100.0,
            cosy_sc_day=cosy_sc / 100.0,
            default_battery=battery,
            default_scop=scop,
            gas_available=len(gas_consumption) > 0,
        )

    return {
        "status": "ok",
        "daily_records": daily_records,
        "total_days": len(daily_records),
        "last_date": daily_records[-1]["date"] if daily_records else None,
        "first_date": daily_records[0]["date"] if daily_records else None,
        "agile_sc_day": agile_sc / 100.0,
        "cosy_sc_day": cosy_sc / 100.0,
    }


def main():
    parser = argparse.ArgumentParser(description="Octopus Agile vs Cosy Tariff Comparator with Gas SCOP Conversion & Interactive Dashboard")
    parser.add_argument("--days", type=int, default=365, help="Number of past days to analyze (default: 365)")
    parser.add_argument("--from", dest="period_from", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="period_to", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--battery", type=float, default=5.0, help="Battery capacity in kWh for terminal summary (default: 5.0)")
    parser.add_argument("--gas", action="store_true", help="Include converted past gas heating using Seasonal COP")
    parser.add_argument("--scop", type=float, default=3.5, help="Seasonal COP for heat pump gas conversion (default: 3.5)")
    parser.add_argument("--boiler-eff", type=float, default=0.85, help="Gas boiler efficiency (default: 0.85)")
    parser.add_argument("--demo", action="store_true", help="Run with simulated heat pump load data")
    parser.add_argument("--html", action="store_true", help="Generate an interactive HTML visual report")
    parser.add_argument("--refresh", action="store_true", help="Bypass cache and pull fresh data directly from Octopus API")
    parser.add_argument("--serve", action="store_true", help="Start local web server on port 8050 with in-browser update capability")
    args = parser.parse_args()

    if args.serve:
        from server import start_server
        start_server(port=8050)
        return

    if args.demo:
        print("\n⚙️  Running simulation in DEMO MODE with realistic heat pump electricity data...")
        demo_data = generate_heatpump_demo_data(days=args.days)
        comparator = TariffComparator(
            consumption=demo_data["consumption"],
            agile_rates=demo_data["agile_rates"],
            cosy_rates=demo_data["cosy_rates"],
            agile_standing_charge_p_day=37.3,
            cosy_standing_charge_p_day=42.3,
        )
        report = comparator.compare_four_way(battery_kwh=args.battery)
        print_cli_report(report, gas_included=False, scop=args.scop)
        return

    run_comparison_pipeline(
        days=args.days,
        period_from=args.period_from,
        period_to=args.period_to,
        battery=args.battery,
        gas=args.gas,
        scop=args.scop,
        boiler_eff=args.boiler_eff,
        generate_html=args.html,
        refresh=args.refresh,
        quiet=False,
    )


if __name__ == "__main__":
    main()
