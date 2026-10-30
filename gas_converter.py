"""
Gas to Heat Pump Converter
Converts historical gas consumption (m3) into equivalent heat pump electricity consumption (kWh)
using Boiler Efficiency and Seasonal Coefficient of Performance (SCOP).
"""

from typing import Dict, List, Any


def convert_gas_to_heatpump_kwh(
    gas_m3: float,
    scop: float = 3.5,
    boiler_efficiency: float = 0.85,
    calorific_value: float = 39.5,
    volume_correction: float = 1.02264,
) -> float:
    """
    Convert gas cubic meters (m3) into equivalent heat pump electricity (kWh).
    
    Formula:
    1. Gas kWh = m3 * volume_correction * calorific_value / 3.6
    2. Heat Delivered = Gas kWh * boiler_efficiency
    3. HP Electricity kWh = Heat Delivered / SCOP
    """
    if gas_m3 <= 0:
        return 0.0
    gas_kwh = (gas_m3 * volume_correction * calorific_value) / 3.6
    heat_delivered_kwh = gas_kwh * boiler_efficiency
    hp_electricity_kwh = heat_delivered_kwh / scop
    return round(hp_electricity_kwh, 4)


def merge_converted_gas_with_electricity(
    electricity_intervals: List[Dict[str, Any]],
    gas_intervals: List[Dict[str, Any]],
    heatpump_install_date: str = "2026-09-15T00:00:00Z",
    scop: float = 3.5,
    boiler_efficiency: float = 0.85,
) -> List[Dict[str, Any]]:
    """
    Merge converted gas heat pump load into historical electricity consumption intervals
    for dates prior to heatpump_install_date.
    """
    # Map gas intervals by start time
    gas_map = {g["interval_start"]: float(g.get("consumption", 0.0)) for g in gas_intervals}

    merged = []
    for item in electricity_intervals:
        start_ts = item["interval_start"]
        base_elec_kwh = float(item.get("consumption", 0.0))

        hp_extra_kwh = 0.0
        # Only add converted gas for dates PRIOR to heat pump commissioning
        if start_ts < heatpump_install_date and start_ts in gas_map:
            gas_m3 = gas_map[start_ts]
            hp_extra_kwh = convert_gas_to_heatpump_kwh(gas_m3, scop=scop, boiler_efficiency=boiler_efficiency)

        total_kwh = round(base_elec_kwh + hp_extra_kwh, 4)
        merged.append({
            "consumption": total_kwh,
            "base_electricity_kwh": base_elec_kwh,
            "hp_converted_gas_kwh": hp_extra_kwh,
            "interval_start": start_ts,
            "interval_end": item["interval_end"],
        })

    return merged
