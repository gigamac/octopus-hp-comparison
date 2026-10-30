"""
Tariff Comparison Engine with Realistic Battery Arbitrage Simulation
Compares historical electricity consumption across 4 key scenarios:
1. Agile Octopus (Base)
2. Cosy Octopus (Base)
3. Agile Octopus + Battery (e.g. 5 kWh or 10 kWh)
4. Cosy Octopus + Battery (e.g. 5 kWh or 10 kWh)
"""

from datetime import datetime
from typing import Dict, List, Any, Optional, Set


def parse_iso(dt_str: str) -> datetime:
    """Parse ISO datetime string to timezone-aware datetime using standard library."""
    clean_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(clean_str)


class TariffComparator:
    def __init__(
        self,
        consumption: List[Dict[str, Any]],
        agile_rates: List[Dict[str, Any]],
        cosy_rates: List[Dict[str, Any]],
        agile_standing_charge_p_day: float = 37.3,
        cosy_standing_charge_p_day: float = 42.3,
    ):
        self.consumption = sorted(consumption, key=lambda x: x["interval_start"])
        self.agile_rates = sorted(agile_rates, key=lambda x: x["valid_from"])
        self.cosy_rates = sorted(cosy_rates, key=lambda x: x["valid_from"])
        self.agile_sc = agile_standing_charge_p_day
        self.cosy_sc = cosy_standing_charge_p_day

        # Fast O(1) and O(log N) indexing
        self.agile_map = {r["valid_from"]: float(r.get("value_inc_vat", 0.0)) for r in self.agile_rates}
        self.cosy_times = [parse_iso(r["valid_from"]).timestamp() for r in self.cosy_rates]
        self.cosy_values = [float(r.get("value_inc_vat", 0.0)) for r in self.cosy_rates]

    def _find_agile_rate(self, iso_str: str) -> float:
        return self.agile_map.get(iso_str, 20.0)

    def _find_cosy_rate(self, dt: datetime) -> float:
        import bisect
        if not self.cosy_times:
            return 28.8
        ts = dt.timestamp()
        idx = bisect.bisect_right(self.cosy_times, ts) - 1
        if 0 <= idx < len(self.cosy_values):
            return self.cosy_values[idx]
        return 28.8

    def _determine_smart_agile_charge_slots(self, usable_battery: float, efficiency: float) -> Set[str]:
        """
        Real batteries on Agile don't charge on dumb timers; they use price-aware
        arbitrage (e.g. Predbat / Wonderwatt).
        For each 24h day, determine the lowest-priced slots that actually yield positive
        arbitrage after round-trip efficiency losses.
        """
        daily_slots: Dict[str, List[Dict[str, Any]]] = {}
        for r in self.agile_rates:
            start_dt = parse_iso(r["valid_from"])
            day_key = start_dt.strftime("%Y-%m-%d")
            daily_slots.setdefault(day_key, []).append({
                "rate": float(r.get("value_inc_vat", 0.0)),
                "dt": start_dt,
                "iso": r["valid_from"],
            })

        charge_slots: Set[str] = set()

        for day_key, slots in daily_slots.items():
            peak_rates = [s["rate"] for s in slots if 16 <= s["dt"].hour < 19]
            avg_peak = sum(peak_rates) / len(peak_rates) if peak_rates else 35.0

            # Only charge during overnight or afternoon slots (not peak)
            non_peak_slots = [s for s in slots if not (16 <= s["dt"].hour < 19)]
            sorted_non_peak = sorted(non_peak_slots, key=lambda x: x["rate"])

            # Maximum slots to charge based on battery capacity (1.3 kWh per 30 mins)
            slots_needed = int(round(usable_battery / 1.3)) + 1

            for s in sorted_non_peak[:slots_needed]:
                # Viable arbitrage condition:
                # Cost to store 1 kWh = s['rate'] / efficiency
                # Must be at least 3.0p cheaper than the evening peak
                if (s["rate"] / efficiency) < (avg_peak - 3.0) and s["rate"] < 22.0:
                    charge_slots.add(s["iso"])

        return charge_slots

    def compare_single(self, battery_kwh: float = 0.0) -> Dict[str, Any]:
        """Perform interval-by-interval cost calculation for a specific battery size."""
        usable_battery = battery_kwh * 0.90  # 90% usable depth of discharge
        efficiency = 0.90  # 90% round trip efficiency
        max_rate_per_half_hour = 1.3  # ~2.6 kW inverter limit per 30 mins

        total_kwh = 0.0
        agile_unit_cost_p = 0.0
        cosy_unit_cost_p = 0.0

        cosy_dip_kwh = 0.0
        cosy_peak_kwh = 0.0
        cosy_standard_kwh = 0.0

        daily_kwh: Dict[str, float] = {}
        daily_agile_cost: Dict[str, float] = {}
        daily_cosy_cost: Dict[str, float] = {}

        matched_intervals = 0
        cosy_soc = 0.0
        agile_soc = 0.0

        agile_smart_charge_slots = self._determine_smart_agile_charge_slots(usable_battery, efficiency) if battery_kwh > 0 else set()

        for item in self.consumption:
            raw_kwh = float(item.get("consumption", 0.0))
            start_dt = parse_iso(item["interval_start"])
            day_key = start_dt.strftime("%Y-%m-%d")

            total_kwh += raw_kwh
            daily_kwh[day_key] = daily_kwh.get(day_key, 0.0) + raw_kwh

            agile_rate = self._find_agile_rate(item["interval_start"])
            cosy_rate = self._find_cosy_rate(start_dt)

            hour = start_dt.hour
            minute = start_dt.minute
            time_dec = hour + minute / 60.0

            is_cosy_dip = (4.0 <= time_dec < 7.0) or (13.0 <= time_dec < 16.0) or (22.0 <= time_dec < 24.0)
            is_cosy_peak = (16.0 <= time_dec < 19.0)

            if is_cosy_dip:
                cosy_dip_kwh += raw_kwh
            elif is_cosy_peak:
                cosy_peak_kwh += raw_kwh
            else:
                cosy_standard_kwh += raw_kwh

            # --- Battery Logic for Cosy ---
            effective_cosy_kwh = raw_kwh
            if battery_kwh > 0:
                if is_cosy_dip:
                    # Charge during dip (especially 13:00-16:00 pre-peak)
                    charge_needed = usable_battery - cosy_soc
                    charge_amount = min(charge_needed, max_rate_per_half_hour)
                    cosy_soc += charge_amount
                    effective_cosy_kwh = raw_kwh + (charge_amount / efficiency)
                elif is_cosy_peak:
                    # Discharge during peak to eliminate expensive 43p rate
                    discharge = min(cosy_soc, raw_kwh, max_rate_per_half_hour)
                    cosy_soc -= discharge
                    effective_cosy_kwh = raw_kwh - discharge
                else:
                    # Discharge during daytime standard hours if we have surplus charge
                    if cosy_soc > (usable_battery * 0.4) and (7.0 <= time_dec < 13.0):
                        discharge = min(cosy_soc - (usable_battery * 0.4), raw_kwh, max_rate_per_half_hour)
                        cosy_soc -= discharge
                        effective_cosy_kwh = raw_kwh - discharge

            # --- Smart Battery Logic for Agile ---
            effective_agile_kwh = raw_kwh
            if battery_kwh > 0:
                # Check if this slot was selected as an economical charging slot
                if item["interval_start"] in agile_smart_charge_slots:
                    charge_needed = usable_battery - agile_soc
                    charge_amount = min(charge_needed, max_rate_per_half_hour)
                    agile_soc += charge_amount
                    effective_agile_kwh = raw_kwh + (charge_amount / efficiency)
                elif 16.0 <= time_dec < 19.0:
                    # Discharge during expensive evening peak
                    discharge = min(agile_soc, raw_kwh, max_rate_per_half_hour)
                    agile_soc -= discharge
                    effective_agile_kwh = raw_kwh - discharge
                elif agile_soc > 0 and agile_rate > 24.0:
                    # Discharge during daytime when rates exceed 24p
                    discharge = min(agile_soc, raw_kwh, max_rate_per_half_hour)
                    agile_soc -= discharge
                    effective_agile_kwh = raw_kwh - discharge

            agile_cost_slot = effective_agile_kwh * agile_rate
            cosy_cost_slot = effective_cosy_kwh * cosy_rate

            agile_unit_cost_p += agile_cost_slot
            cosy_unit_cost_p += cosy_cost_slot

            daily_agile_cost[day_key] = daily_agile_cost.get(day_key, 0.0) + (agile_cost_slot / 100.0)
            daily_cosy_cost[day_key] = daily_cosy_cost.get(day_key, 0.0) + (cosy_cost_slot / 100.0)

            matched_intervals += 1

        total_days = len(daily_kwh) or 1
        agile_standing_total_pounds = (self.agile_sc * total_days) / 100.0
        cosy_standing_total_pounds = (self.cosy_sc * total_days) / 100.0

        agile_unit_pounds = agile_unit_cost_p / 100.0
        cosy_unit_pounds = cosy_unit_cost_p / 100.0

        agile_total_pounds = agile_unit_pounds + agile_standing_total_pounds
        cosy_total_pounds = cosy_unit_pounds + cosy_standing_total_pounds

        avg_agile_rate = (agile_unit_cost_p / total_kwh) if total_kwh > 0 else 0.0
        avg_cosy_rate = (cosy_unit_cost_p / total_kwh) if total_kwh > 0 else 0.0

        return {
            "total_kwh": round(total_kwh, 2),
            "total_days": total_days,
            "intervals_analyzed": matched_intervals,
            "battery_kwh": battery_kwh,
            "agile": {
                "unit_cost_pounds": round(agile_unit_pounds, 2),
                "standing_charge_pounds": round(agile_standing_total_pounds, 2),
                "total_cost_pounds": round(agile_total_pounds, 2),
                "average_unit_rate_p_per_kwh": round(avg_agile_rate, 2),
            },
            "cosy": {
                "unit_cost_pounds": round(cosy_unit_pounds, 2),
                "standing_charge_pounds": round(cosy_standing_total_pounds, 2),
                "total_cost_pounds": round(cosy_total_pounds, 2),
                "average_unit_rate_p_per_kwh": round(avg_cosy_rate, 2),
            },
            "time_of_use_distribution": {
                "dip_hours_kwh": round(cosy_dip_kwh, 2),
                "dip_hours_percentage": round((cosy_dip_kwh / (total_kwh or 1)) * 100, 1),
                "peak_hours_kwh": round(cosy_peak_kwh, 2),
                "peak_hours_percentage": round((cosy_peak_kwh / (total_kwh or 1)) * 100, 1),
                "standard_hours_kwh": round(cosy_standard_kwh, 2),
                "standard_hours_percentage": round((cosy_standard_kwh / (total_kwh or 1)) * 100, 1),
            },
            "daily_kwh": daily_kwh,
            "daily_agile_cost": daily_agile_cost,
            "daily_cosy_cost": daily_cosy_cost,
        }

    def compare_four_way(self, battery_kwh: float = 5.0) -> Dict[str, Any]:
        """
        Run both base (no battery) and battery scenario (e.g. 5 kWh or 10 kWh)
        to return all 4 indicators:
        - Agile (Base)
        - Cosy (Base)
        - Agile + Battery
        - Cosy + Battery
        """
        base = self.compare_single(battery_kwh=0.0)
        battery = self.compare_single(battery_kwh=battery_kwh)

        total_days = base["total_days"]
        ag_sc_day = self.agile_sc / 100.0
        co_sc_day = self.cosy_sc / 100.0

        all_days = sorted(base["daily_kwh"].keys())
        daily_breakdown = {}
        for d in all_days:
            daily_breakdown[d] = {
                "kwh": round(base["daily_kwh"][d], 2),
                "agile": round(base["daily_agile_cost"][d] + ag_sc_day, 2),
                "cosy": round(base["daily_cosy_cost"][d] + co_sc_day, 2),
                "agile_battery": round(battery["daily_agile_cost"][d] + ag_sc_day, 2),
                "cosy_battery": round(battery["daily_cosy_cost"][d] + co_sc_day, 2),
            }

        agile_base_total = base["agile"]["total_cost_pounds"]

        def calc_saving(scenario_total: float) -> Dict[str, Any]:
            diff = agile_base_total - scenario_total
            pct = (diff / agile_base_total * 100.0) if agile_base_total > 0 else 0.0
            return {
                "saving_pounds": round(diff, 2),
                "saving_percentage": round(pct, 1),
            }

        scenarios = {
            "agile": {
                "name": "Agile Octopus",
                "badge": "Agile (Current)",
                **base["agile"],
                **calc_saving(base["agile"]["total_cost_pounds"]),
            },
            "cosy": {
                "name": "Cosy Octopus",
                "badge": "Cosy",
                **base["cosy"],
                **calc_saving(base["cosy"]["total_cost_pounds"]),
            },
            "agile_battery": {
                "name": f"Agile + {battery_kwh:.1f}kWh Battery",
                "badge": f"Agile + {battery_kwh:.1f}kWh",
                **battery["agile"],
                **calc_saving(battery["agile"]["total_cost_pounds"]),
            },
            "cosy_battery": {
                "name": f"Cosy + {battery_kwh:.1f}kWh Battery",
                "badge": f"Cosy + {battery_kwh:.1f}kWh",
                **battery["cosy"],
                **calc_saving(battery["cosy"]["total_cost_pounds"]),
            },
        }

        ranked = sorted(scenarios.items(), key=lambda item: item[1]["total_cost_pounds"])

        return {
            "summary": {
                "total_kwh": base["total_kwh"],
                "total_days": base["total_days"],
                "intervals_analyzed": base["intervals_analyzed"],
                "battery_kwh": battery_kwh,
                "winner": ranked[0][1]["name"],
                "max_saving_pounds": ranked[0][1]["saving_pounds"],
                "max_saving_percentage": ranked[0][1]["saving_percentage"],
            },
            "scenarios": scenarios,
            "ranked_scenarios": [r[0] for r in ranked],
            "time_of_use_distribution": base["time_of_use_distribution"],
            "daily_breakdown": daily_breakdown,
        }

    def compare(self, battery_kwh: float = 0.0) -> Dict[str, Any]:
        return self.compare_single(battery_kwh=battery_kwh)
