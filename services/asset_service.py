import json
import logging
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from requests import RequestException


logger = logging.getLogger(__name__)

TWSE_COMPANY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TWSE_ETF_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
TPEX_ETF_URL = "https://info.tpex.org.tw/api/etfFilter"

TIMEOUT_SECONDS = 10
CACHE_TTL = timedelta(hours=24)
TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "asset_metadata.json"

SOURCE_NAMES = ("twse_company", "tpex_company", "twse_etf", "tpex_etf")
ETF_SOURCES = ("twse_etf", "tpex_etf")
COMPANY_SOURCES = ("twse_company", "tpex_company")
SOURCE_PAIRS = {
    "twse_company": "twse_etf",
    "twse_etf": "twse_company",
    "tpex_company": "tpex_etf",
    "tpex_etf": "tpex_company",
}


def asset_fallback() -> dict:
    return {"type": "unknown", "source": None, "confidence": "low"}


class AssetService:
    def __init__(self, cache_path=None, now_provider=None):
        self.cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
        self._now_provider = now_provider or (lambda: datetime.now(TAIPEI))

    def get_asset(self, stock_id: str) -> dict:
        symbol = self._normalize_symbol(stock_id)
        if not symbol:
            return asset_fallback()

        cache = self._load_cache()
        now = self._safe_now()
        if now is None:
            return self._asset_from_stale_cache(cache, symbol)

        if self._cache_is_fresh(cache, now):
            return self._asset_from_cache(cache, symbol)

        refreshed = self._refresh(cache, now)
        if refreshed is not None:
            return self._asset_from_cache(refreshed, symbol)
        return self._asset_from_stale_cache(cache, symbol)

    @staticmethod
    def _normalize_symbol(stock_id):
        if stock_id is None or isinstance(stock_id, bool):
            return None
        if not isinstance(stock_id, (str, int)):
            return None
        value = str(stock_id).strip()
        return value or None

    def _safe_now(self):
        try:
            value = self._now_provider()
            if not isinstance(value, datetime):
                return None
            if value.tzinfo is None:
                return value.replace(tzinfo=TAIPEI)
            return value.astimezone(TAIPEI)
        except Exception:
            return None

    def _load_cache(self):
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("assets"), dict):
            return None
        return payload

    @staticmethod
    def _parse_timestamp(value):
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(TAIPEI)

    def _cache_is_fresh(self, cache, now):
        if not isinstance(cache, dict):
            return False
        updated_at = self._parse_timestamp(cache.get("updated_at"))
        if updated_at is None:
            return False
        age = now - updated_at
        return timedelta(0) <= age < CACHE_TTL

    @staticmethod
    def _valid_asset_record(record):
        return (
            isinstance(record, dict)
            and record.get("type") in {"stock", "etf"}
            and record.get("source") in SOURCE_NAMES
            and record.get("confidence") in {"high", "medium"}
        )

    def _asset_from_cache(self, cache, symbol):
        if not isinstance(cache, dict):
            return asset_fallback()
        record = (cache.get("assets") or {}).get(symbol)
        if not self._valid_asset_record(record):
            return asset_fallback()
        return deepcopy(record)

    def _asset_from_stale_cache(self, cache, symbol):
        record = self._asset_from_cache(cache, symbol)
        if record["type"] == "unknown":
            return record
        return {
            "type": record["type"],
            "source": "official_cache",
            "confidence": "medium",
        }

    def _refresh(self, old_cache, now):
        results = {
            "twse_company": self._fetch_twse_companies(),
            "tpex_company": self._fetch_tpex_companies(),
            "twse_etf": self._fetch_twse_etfs(),
            "tpex_etf": self._fetch_tpex_etfs(),
        }
        successful = {name: values for name, values in results.items() if values is not None}
        if not successful:
            return None

        assets = self._build_assets(successful)
        if isinstance(old_cache, dict):
            failed_sources = set(SOURCE_NAMES) - set(successful)
            for symbol, record in (old_cache.get("assets") or {}).items():
                if (
                    symbol not in assets
                    and self._valid_asset_record(record)
                    and record.get("source") in failed_sources
                ):
                    assets[symbol] = {
                        "type": record["type"],
                        "source": record["source"],
                        "confidence": "medium",
                    }

        timestamp = now.isoformat()
        cache = {
            "updated_at": timestamp,
            "sources": {
                name: {
                    "updated_at": timestamp if results[name] is not None else None,
                    "status": "ok" if results[name] is not None else "failed",
                }
                for name in SOURCE_NAMES
            },
            "assets": assets,
        }
        self._write_cache(cache)
        return cache

    @staticmethod
    def _build_assets(source_sets):
        symbols = set().union(*(values for values in source_sets.values())) if source_sets else set()
        assets = {}
        for symbol in sorted(symbols):
            etf_hits = [name for name in ETF_SOURCES if symbol in source_sets.get(name, set())]
            company_hits = [name for name in COMPANY_SOURCES if symbol in source_sets.get(name, set())]
            if etf_hits and company_hits:
                continue
            if etf_hits:
                source = etf_hits[0]
                confidence = "high" if SOURCE_PAIRS[source] in source_sets else "medium"
                assets[symbol] = {"type": "etf", "source": source, "confidence": confidence}
            elif company_hits:
                source = company_hits[0]
                confidence = "high" if SOURCE_PAIRS[source] in source_sets else "medium"
                assets[symbol] = {"type": "stock", "source": source, "confidence": confidence}
        return assets

    def _write_cache(self, cache):
        temporary_path = None
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_path.parent,
                prefix=f".{self.cache_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(cache, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.cache_path)
        except OSError as error:
            logger.warning(
                "Asset cache write failed (error_type=%s)",
                type(error).__name__,
            )
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _request_json(method, url):
        try:
            response = requests.request(method, url, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, RequestException, ValueError, TypeError) as error:
            logger.warning(
                "Asset metadata source failed (error_type=%s)",
                type(error).__name__,
            )
            return None

    def _fetch_twse_companies(self):
        payload = self._request_json("GET", TWSE_COMPANY_URL)
        return self._parse_records(payload, "公司代號", "公司簡稱")

    def _fetch_tpex_companies(self):
        payload = self._request_json("GET", TPEX_COMPANY_URL)
        return self._parse_records(payload, "SecuritiesCompanyCode", "CompanyAbbreviation")

    def _fetch_twse_etfs(self):
        payload = self._request_json("GET", TWSE_ETF_URL)
        return self._parse_records(payload, "基金代號", "基金簡稱")

    def _fetch_tpex_etfs(self):
        payload = self._request_json("POST", TPEX_ETF_URL)
        if not isinstance(payload, dict) or payload.get("status") != "success":
            return None
        data = payload.get("data")
        if not isinstance(data, list):
            return None
        result = set()
        for record in data:
            if not isinstance(record, dict):
                continue
            symbol = record.get("stockNo")
            name = record.get("stockName")
            listing_date = record.get("listingDate")
            if not self._valid_required_strings(symbol, name):
                continue
            if not self._valid_yyyymmdd(listing_date):
                continue
            result.add(symbol.strip())
        return result or None

    @staticmethod
    def _parse_records(payload, symbol_key, name_key):
        if not isinstance(payload, list):
            return None
        result = set()
        for record in payload:
            if not isinstance(record, dict):
                continue
            symbol = record.get(symbol_key)
            name = record.get(name_key)
            if AssetService._valid_required_strings(symbol, name):
                result.add(symbol.strip())
        return result or None

    @staticmethod
    def _valid_required_strings(symbol, name):
        return (
            isinstance(symbol, str)
            and bool(symbol.strip())
            and isinstance(name, str)
            and bool(name.strip())
        )

    @staticmethod
    def _valid_yyyymmdd(value):
        if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
            return False
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError:
            return False
        return True
