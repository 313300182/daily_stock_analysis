# -*- coding: utf-8 -*-
"""验证 Tavily 在 A 股场景下自动启用中文域名白名单 include_domains。

也覆盖 TavilySearchProvider.search 直接调用 include_domains 的分支。

@author Amadeus
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import MagicMock, patch

if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import SearchService, TavilySearchProvider  # noqa: E402


class _FakeTavilyClient:
    response_payload: dict = {"results": []}
    search_calls: list = []

    def __init__(self, api_key=None, **_kwargs):
        pass

    def search(self, **kwargs):
        type(self).search_calls.append(kwargs)
        return type(self).response_payload

    @classmethod
    def reset(cls) -> None:
        cls.response_payload = {"results": []}
        cls.search_calls = []


def _fake_tavily_module() -> ModuleType:
    module = ModuleType("tavily")
    module.TavilyClient = _FakeTavilyClient
    return module


class TavilyIncludeDomainsTests(unittest.TestCase):
    """TavilySearchProvider.search 的 include_domains 支持。"""

    def _patch_tavily(self, payload):
        _FakeTavilyClient.reset()
        _FakeTavilyClient.response_payload = payload
        return patch.dict(sys.modules, {"tavily": _fake_tavily_module()})

    def test_search_passes_include_domains_to_client(self) -> None:
        provider = TavilySearchProvider(["dummy_key"])
        whitelist = ["eastmoney.com", "finance.sina.com.cn", "cls.cn"]

        with self._patch_tavily(
            {
                "results": [
                    {
                        "title": "中文财经新闻",
                        "url": "https://eastmoney.com/a/1",
                        "content": "保龄宝公告...",
                        "published_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                ]
            }
        ):
            resp = provider.search(
                "保龄宝 最新新闻",
                max_results=3,
                days=3,
                topic="news",
                include_domains=whitelist,
            )

        self.assertTrue(resp.success)
        self.assertEqual(len(_FakeTavilyClient.search_calls), 1)
        call = _FakeTavilyClient.search_calls[0]
        self.assertEqual(call.get("topic"), "news")
        self.assertEqual(call.get("include_domains"), whitelist)

    def test_search_without_include_domains_does_not_add_param(self) -> None:
        provider = TavilySearchProvider(["dummy_key"])
        with self._patch_tavily({"results": []}):
            provider.search("AAPL latest news", max_results=3, days=3, topic="news")
        call = _FakeTavilyClient.search_calls[0]
        self.assertNotIn("include_domains", call)

    def test_include_domains_alone_still_triggers_direct_path(self) -> None:
        """未指定 topic 但提供 include_domains 也应走直接调用路径（带上 include_domains）。"""
        provider = TavilySearchProvider(["dummy_key"])
        with self._patch_tavily({"results": []}):
            provider.search(
                "保龄宝",
                max_results=3,
                days=3,
                include_domains=["eastmoney.com"],
            )
        self.assertEqual(len(_FakeTavilyClient.search_calls), 1)
        call = _FakeTavilyClient.search_calls[0]
        self.assertEqual(call.get("include_domains"), ["eastmoney.com"])
        self.assertNotIn("topic", call)


class SearchServiceAShareTavilyWhitelistTests(unittest.TestCase):
    """SearchService 在 A 股场景调用 Tavily 时自动附加 include_domains。"""

    def _patch_tavily(self, payload):
        _FakeTavilyClient.reset()
        _FakeTavilyClient.response_payload = payload
        return patch.dict(sys.modules, {"tavily": _fake_tavily_module()})

    def test_a_share_comprehensive_intel_adds_cn_whitelist_for_tavily(self) -> None:
        published_text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "results": [
                {
                    "title": "保龄宝：最新公告",
                    "url": "https://eastmoney.com/a/1",
                    "content": "公司公告内容...",
                    "published_date": published_text,
                }
            ]
        }

        with self._patch_tavily(payload):
            service = SearchService(
                tavily_keys=["dummy_key"],
                searxng_public_instances_enabled=False,
                news_max_age_days=3,
                news_strategy_profile="short",
            )
            service._cn_providers = []  # 禁用 CN 专属 Provider，强制走通用 Tavily 分支
            intel = service.search_comprehensive_intel("002286", "保龄宝", max_searches=2)

        self.assertIn("latest_news", intel)
        self.assertGreaterEqual(len(_FakeTavilyClient.search_calls), 1)
        first_call = _FakeTavilyClient.search_calls[0]
        self.assertEqual(first_call.get("topic"), "news")
        include_domains = first_call.get("include_domains")
        self.assertIsNotNone(include_domains, "A 股场景应自动附加 include_domains 白名单")
        self.assertIn("eastmoney.com", include_domains)
        self.assertIn("xueqiu.com", include_domains)
        # 用 sina.com.cn 作为新浪的域名代表
        self.assertTrue(
            any("sina.com.cn" in d for d in include_domains),
            msg=f"include_domains 应包含新浪域名，实际: {include_domains}",
        )

    def test_us_stock_does_not_add_cn_whitelist(self) -> None:
        payload = {
            "results": [
                {
                    "title": "Apple news",
                    "url": "https://example.com/apple",
                    "content": "Apple latest",
                    "published_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            ]
        }

        with self._patch_tavily(payload):
            service = SearchService(
                tavily_keys=["dummy_key"],
                searxng_public_instances_enabled=False,
                news_max_age_days=3,
                news_strategy_profile="short",
            )
            service._cn_providers = []
            service.search_comprehensive_intel("AAPL", "Apple Inc.", max_searches=2)

        self.assertGreaterEqual(len(_FakeTavilyClient.search_calls), 1)
        first_call = _FakeTavilyClient.search_calls[0]
        self.assertNotIn("include_domains", first_call)


if __name__ == "__main__":
    unittest.main()
