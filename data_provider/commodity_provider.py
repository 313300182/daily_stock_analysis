# -*- coding: utf-8 -*-
"""
Commodity context provider (fail-open).

Provides related commodity futures/spot price context for resource-related
stocks. Uses AkShare ``futures_spot_price`` to fetch spot prices and basis
data for all major commodity categories in a single call, then filters by
the stock-commodity mapping.

This module never raises to caller; missing data is allowed.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Commodity symbol -> Chinese display name
# ---------------------------------------------------------------------------
COMMODITY_NAMES: Dict[str, str] = {
    "AU": "黄金",
    "AG": "白银",
    "CU": "铜",
    "AL": "铝",
    "ZN": "锌",
    "PB": "铅",
    "NI": "镍",
    "SN": "锡",
    "I": "铁矿石",
    "RB": "螺纹钢",
    "HC": "热轧卷板",
    "J": "焦炭",
    "JM": "焦煤",
    "SC": "原油",
    "FU": "燃料油",
    "SS": "不锈钢",
    "SI": "工业硅",
    "LC": "碳酸锂",
    "AO": "氧化铝",
}

# ---------------------------------------------------------------------------
# Stock code -> related commodity symbols (precise mapping, highest priority)
# ---------------------------------------------------------------------------
STOCK_COMMODITY_MAP: Dict[str, List[str]] = {
    # A股
    "601899": ["AU", "AG", "CU"],       # 紫金矿业
    "600489": ["AU"],                    # 中金黄金
    "002155": ["AU", "AG"],              # 湖南黄金
    "600547": ["AU"],                    # 山东黄金
    "600988": ["AU"],                    # 赤峰黄金
    "002237": ["AU"],                    # 恒邦股份
    "000630": ["CU", "AL"],             # 铜陵有色
    "603993": ["CU"],                    # 洛阳钼业（铜钴）
    "601168": ["AL"],                    # 西部矿业
    "600362": ["AL"],                    # 江西铜业
    "600219": ["ZN", "PB"],             # 南山铝业
    "000060": ["ZN", "PB"],             # 中金岭南
    "600497": ["ZN"],                    # 驰宏锌锗
    "000878": ["AL"],                    # 云南铜业
    "600111": ["NI", "CU"],             # 北方稀土（稀土+镍）
    "002460": ["NI"],                    # 赣锋锂业（锂）
    "600516": ["AU"],                    # 方大炭素（关联焦炭）
    "000709": ["I", "RB"],              # 河钢股份
    "600019": ["I", "RB"],              # 宝钢股份
    "600010": ["I", "RB"],              # 包钢股份
    "000898": ["I", "RB", "HC"],        # 鞍钢股份
    "000825": ["I", "RB"],              # 太钢不锈
    "601003": ["J", "JM"],              # 柳钢股份
    "601225": ["J", "JM"],              # 陕西煤业
    "601088": ["J", "JM"],              # 中国神华
    "600188": ["J", "JM"],              # 兖矿能源
    "601898": ["J", "JM"],              # 中煤能源
    "600028": ["SC", "FU"],             # 中国石化
    "601857": ["SC", "FU"],             # 中国石油
    "600346": ["SC"],                    # 恒力石化
    "600803": ["LC"],                    # 新奥股份（碳酸锂关联）
    # 港股
    "hk03993": ["CU", "ZN"],            # 洛阳钼业 H
    "hk02899": ["AU", "CU"],            # 紫金矿业 H
    "hk01088": ["J", "JM"],             # 中国神华 H
    "hk00386": ["SC", "FU"],            # 中国石化 H
    "hk00857": ["SC", "FU"],            # 中国石油 H
}

# ---------------------------------------------------------------------------
# Name keyword -> related commodity symbols (fuzzy fallback)
#
# Keywords are chosen to be precise enough to avoid false positives
# (e.g. "黄金" not "金", "铜业" not "铜").
# ---------------------------------------------------------------------------
NAME_COMMODITY_KEYWORDS: Dict[str, List[str]] = {
    "黄金": ["AU", "AG"],
    "白银": ["AG"],
    "铜业": ["CU"],
    "铜矿": ["CU"],
    "铝业": ["AL"],
    "铝材": ["AL"],
    "锌业": ["ZN"],
    "镍业": ["NI"],
    "锡业": ["SN"],
    "钢铁": ["I", "RB", "HC"],
    "钢股": ["I", "RB"],
    "炼钢": ["I", "RB"],
    "特钢": ["I", "RB"],
    "不锈钢": ["SS"],
    "矿业": ["AU", "CU", "I"],
    "有色": ["CU", "AL", "ZN", "NI"],
    "煤炭": ["J", "JM"],
    "煤业": ["J", "JM"],
    "焦煤": ["JM"],
    "焦炭": ["J"],
    "石油": ["SC", "FU"],
    "石化": ["SC"],
    "油气": ["SC"],
    "稀土": ["NI"],
    "碳酸锂": ["LC"],
    "锂业": ["LC"],
    "铁矿": ["I"],
}


def _resolve_commodities(stock_code: str, stock_name: str) -> List[str]:
    """Return related commodity symbols for *stock_code* / *stock_name*.

    Returns an empty list when the stock is not resource-related.
    """
    clean_code = stock_code.lstrip("0").lstrip("sh").lstrip("sz")
    if stock_code in STOCK_COMMODITY_MAP:
        return STOCK_COMMODITY_MAP[stock_code]
    if clean_code in STOCK_COMMODITY_MAP:
        return STOCK_COMMODITY_MAP[clean_code]

    matched: Set[str] = set()
    for keyword, symbols in NAME_COMMODITY_KEYWORDS.items():
        if keyword in stock_name:
            matched.update(symbols)
    return list(matched)


class CommodityContextProvider:
    """Provides commodity price context for resource-related stocks.

    Design principles:
    - fail-open: never raises, returns ``None`` on any error
    - cached: ``futures_spot_price`` result is cached for ``cache_ttl_seconds``
      so that a batch run analysing multiple resource stocks only issues one API call
    - zero-cost for non-resource stocks: ``_resolve_commodities`` returns empty → skip
    """

    def __init__(self, cache_ttl_seconds: float = 600.0):
        self._cache_ttl = cache_ttl_seconds
        self._spot_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._spot_cache_ts: float = 0.0
        self._cache_lock = RLock()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def get_commodity_context(
        self, stock_code: str, stock_name: str
    ) -> Optional[Dict[str, Any]]:
        """Return commodity context dict or ``None`` (non-resource stock / error)."""
        related = _resolve_commodities(stock_code, stock_name)
        if not related:
            return None

        try:
            spot_map = self._get_spot_data()
        except Exception as exc:
            logger.debug("CommodityContextProvider: spot data fetch failed: %s", exc)
            return None

        if not spot_map:
            return None

        commodities = []
        for sym in related:
            item = spot_map.get(sym.upper())
            if item is not None:
                commodities.append(item)

        if not commodities:
            return None

        return {
            "status": "ok",
            "related_commodities": commodities,
            "source": "akshare/futures_spot_price",
        }

    # ------------------------------------------------------------------
    # Internal: spot data with caching
    # ------------------------------------------------------------------

    def _get_spot_data(self) -> Optional[Dict[str, Dict[str, Any]]]:
        with self._cache_lock:
            now = time.monotonic()
            if self._spot_cache is not None and (now - self._spot_cache_ts) < self._cache_ttl:
                return self._spot_cache

        fresh = self._fetch_spot_data()
        if fresh is not None:
            with self._cache_lock:
                self._spot_cache = fresh
                self._spot_cache_ts = time.monotonic()
        return fresh

    def _fetch_spot_data(self) -> Optional[Dict[str, Dict[str, Any]]]:
        try:
            import akshare as ak
        except ImportError:
            logger.warning("CommodityContextProvider: akshare not installed")
            return None

        today_str = datetime.now().strftime("%Y%m%d")
        df = None
        for attempt_date in self._recent_trade_dates(today_str, lookback=5):
            try:
                df = ak.futures_spot_price(attempt_date)
                if df is not None and not df.empty:
                    break
            except Exception:
                continue

        if df is None or df.empty:
            logger.debug("CommodityContextProvider: no spot data available")
            return None

        result: Dict[str, Dict[str, Any]] = {}
        for _, row in df.iterrows():
            sym = str(row.get("symbol", "")).strip().upper()
            if not sym:
                continue
            display_name = COMMODITY_NAMES.get(sym, sym)
            result[sym] = {
                "name": display_name,
                "symbol": sym,
                "spot_price": _safe_number(row.get("spot_price")),
                "dom_contract": str(row.get("dom_contract", "")),
                "dom_price": _safe_number(row.get("dom_contract_price")),
                "dom_basis_rate": _safe_number(row.get("dom_basis_rate")),
            }
        return result

    @staticmethod
    def _recent_trade_dates(today_str: str, lookback: int = 5) -> List[str]:
        """Return *today_str* and the previous *lookback-1* calendar days as YYYYMMDD."""
        base = datetime.strptime(today_str, "%Y%m%d")
        return [(base - timedelta(days=i)).strftime("%Y%m%d") for i in range(lookback)]


def _safe_number(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None
