"""
Octopus Energy / Kraken REST API Client with Persistent Disk Caching
Provides fast, cached access to Octopus account details, electricity & gas consumption,
and tariff rates (Agile, Cosy, etc.).
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
import requests
from requests.auth import HTTPBasicAuth


def load_env_file(filepath: str = ".env") -> None:
    """Simple parser to load .env file into os.environ if it exists."""
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


class DiskCache:
    """Simple JSON-based persistent disk cache for consumption and tariff rates."""

    def __init__(self, cache_dir: str = "data_cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _get_path(self, key: str) -> str:
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return os.path.join(self.cache_dir, f"{safe_key}.json")

    def load(self, key: str) -> Dict[str, Any]:
        path = self._get_path(key)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self, key: str, data: Dict[str, Any]) -> None:
        path = self._get_path(key)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Warning: Failed to save cache for {key}: {e}", file=sys.stderr)


class OctopusClient:
    BASE_URL = "https://api.octopus.energy/v1"

    def __init__(self, api_key: Optional[str] = None, use_cache: bool = True):
        self.api_key = api_key or os.environ.get("OCTOPUS_API_KEY", "").strip()
        self.session = requests.Session()
        if self.api_key:
            self.session.auth = HTTPBasicAuth(self.api_key, "")
        self.use_cache = use_cache
        self.cache = DiskCache() if use_cache else None

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, paginate: bool = False) -> Any:
        url = endpoint if endpoint.startswith("http") else f"{self.BASE_URL}{endpoint}"
        all_results = []

        while url:
            resp = self.session.get(url, params=params)
            params = None

            if resp.status_code != 200:
                raise RuntimeError(
                    f"Octopus API request failed ({resp.status_code}): {resp.text}\nURL: {url}"
                )

            data = resp.json()
            if not paginate or "results" not in data:
                return data

            all_results.extend(data["results"])
            url = data.get("next")

        return all_results

    def get_account(self, account_number: str) -> Dict[str, Any]:
        """Fetch account details, including properties, meters, and active tariffs."""
        if not self.api_key:
            raise ValueError("OCTOPUS_API_KEY is required to access the account endpoint.")
        return self._get(f"/accounts/{account_number}/")

    def extract_electricity_details(self, account_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract primary MPAN, meter serial, active tariff code, and region code from account response."""
        properties = account_data.get("properties", [])
        if not properties:
            raise ValueError("No properties found in account.")

        prop = properties[0]
        meter_points = prop.get("electricity_meter_points", [])
        if not meter_points:
            raise ValueError("No electricity meter points found for this property.")

        import_meters = [m for m in meter_points if not m.get("is_export", False)]
        target_meter_point = import_meters[0] if import_meters else meter_points[0]

        mpan = target_meter_point.get("mpan")
        meters = target_meter_point.get("meters", [])
        serial = meters[0].get("serial_number") if meters else None

        agreements = target_meter_point.get("agreements", [])
        tariff_code = None
        region_code = None
        if agreements:
            sorted_agreements = sorted(agreements, key=lambda a: a.get("valid_from") or "")
            tariff_code = sorted_agreements[-1].get("tariff_code")
            if tariff_code and tariff_code.rfind("-") != -1:
                region_code = tariff_code.split("-")[-1]

        # Also extract gas details if present
        gas_points = prop.get("gas_meter_points", [])
        mprn = gas_points[0].get("mprn") if gas_points else None
        gas_serial = gas_points[0].get("meters", [{}])[0].get("serial_number") if gas_points else None

        return {
            "mpan": mpan,
            "serial_number": serial,
            "tariff_code": tariff_code,
            "region_code": region_code,
            "mprn": mprn,
            "gas_serial": gas_serial,
            "address": f"{prop.get('address_line_1', '')}, {prop.get('postcode', '')}".strip(", "),
        }

    def get_half_hourly_consumption(
        self,
        mpan: str,
        serial_number: str,
        period_from: str,
        period_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch half-hourly electricity consumption intervals with disk caching.
        Returns sorted list of intervals.
        """
        cache_key = f"elec_{mpan}_{serial_number}"
        cached_dict = self.cache.load(cache_key) if self.use_cache else {}

        # Check what we already have
        # If cache covers period_from and period_to, we can return directly
        params = {
            "period_from": period_from,
            "order_by": "period",
            "page_size": 25000,
        }
        if period_to:
            params["period_to"] = period_to

        # Filter cached records within requested range
        needed_fetch = True
        if cached_dict:
            # Check coverage
            records_in_range = [
                r for r in cached_dict.values()
                if r["interval_start"] >= period_from and (period_to is None or r["interval_start"] < period_to)
            ]
            if len(records_in_range) > 40:
                earliest = min(r["interval_start"] for r in records_in_range)
                latest = max(r["interval_end"] for r in records_in_range)
                if earliest <= period_from and (period_to is None or latest >= period_to):
                    # Cache completely covers requested range!
                    return sorted(records_in_range, key=lambda x: x["interval_start"])

        # Fetch from API
        endpoint = f"/electricity-meter-points/{mpan}/meters/{serial_number}/consumption/"
        results = self._get(endpoint, params=params, paginate=True)

        if self.use_cache and results:
            for r in results:
                cached_dict[r["interval_start"]] = r
            self.cache.save(cache_key, cached_dict)

        # Merge with cached
        all_matching = [
            r for r in (cached_dict.values() if cached_dict else results)
            if r["interval_start"] >= period_from and (period_to is None or r["interval_start"] < period_to)
        ]
        return sorted(all_matching, key=lambda x: x["interval_start"])

    def get_gas_consumption(
        self,
        mprn: str,
        serial_number: str,
        period_from: str,
        period_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch half-hourly gas consumption intervals (in m3) with disk caching.
        """
        cache_key = f"gas_{mprn}_{serial_number}"
        cached_dict = self.cache.load(cache_key) if self.use_cache else {}

        params = {
            "period_from": period_from,
            "order_by": "period",
            "page_size": 25000,
        }
        if period_to:
            params["period_to"] = period_to

        if cached_dict:
            records_in_range = [
                r for r in cached_dict.values()
                if r["interval_start"] >= period_from and (period_to is None or r["interval_start"] < period_to)
            ]
            if len(records_in_range) > 40:
                earliest = min(r["interval_start"] for r in records_in_range)
                latest = max(r["interval_end"] for r in records_in_range)
                if earliest <= period_from and (period_to is None or latest >= period_to):
                    return sorted(records_in_range, key=lambda x: x["interval_start"])

        endpoint = f"/gas-meter-points/{mprn}/meters/{serial_number}/consumption/"
        try:
            results = self._get(endpoint, params=params, paginate=True)
        except Exception as e:
            print(f"Note: Gas endpoint returned: {e}")
            results = []

        if self.use_cache and results:
            for r in results:
                cached_dict[r["interval_start"]] = r
            self.cache.save(cache_key, cached_dict)

        all_matching = [
            r for r in (cached_dict.values() if cached_dict else results)
            if r["interval_start"] >= period_from and (period_to is None or r["interval_start"] < period_to)
        ]
        return sorted(all_matching, key=lambda x: x["interval_start"])

    def get_tariff_unit_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: Optional[str] = None,
        period_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch half-hourly standard unit rates with disk caching."""
        cache_key = f"rates_{product_code}_{tariff_code}"
        cached_dict = self.cache.load(cache_key) if self.use_cache else {}

        if period_from and cached_dict:
            records_in_range = [
                r for r in cached_dict.values()
                if r["valid_from"] >= period_from and (period_to is None or r["valid_from"] < period_to)
            ]
            if len(records_in_range) > 40:
                earliest = min(r["valid_from"] for r in records_in_range)
                latest = max(r["valid_to"] for r in records_in_range if r.get("valid_to"))
                if earliest <= period_from and (period_to is None or latest >= period_to):
                    return sorted(records_in_range, key=lambda x: x["valid_from"])

        params = {"page_size": 25000}
        if period_from:
            params["period_from"] = period_from
        if period_to:
            params["period_to"] = period_to

        endpoint = f"/products/{product_code}/electricity-tariffs/{tariff_code}/standard-unit-rates/"
        results = self._get(endpoint, params=params, paginate=True)

        if self.use_cache and results:
            for r in results:
                cached_dict[r["valid_from"]] = r
            self.cache.save(cache_key, cached_dict)

        if period_from:
            all_matching = [
                r for r in (cached_dict.values() if cached_dict else results)
                if r["valid_from"] >= period_from and (period_to is None or r["valid_from"] < period_to)
            ]
            return sorted(all_matching, key=lambda x: x["valid_from"])

        return results

    def get_standing_charges(
        self,
        product_code: str,
        tariff_code: str,
        period_from: Optional[str] = None,
        period_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch standing charges for a given product and tariff with caching."""
        cache_key = f"sc_{product_code}_{tariff_code}"
        cached = self.cache.load(cache_key) if self.use_cache else {}
        if cached and "results" in cached:
            return cached["results"]

        params = {}
        if period_from:
            params["period_from"] = period_from
        if period_to:
            params["period_to"] = period_to

        endpoint = f"/products/{product_code}/electricity-tariffs/{tariff_code}/standing-charges/"
        results = self._get(endpoint, params=params, paginate=True)

        if self.use_cache and results:
            self.cache.save(cache_key, {"results": results})

        return results
