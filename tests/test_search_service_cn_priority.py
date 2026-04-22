# -*- coding: utf-8 -*-
"""SearchService CN 专属 Provider 优先级验证。

验证：
- _select_providers_for_stock：A 股/港股把 Bocha/Anspire 提前，美股保持原序
- search_comprehensive_intel：A 股命中 CN 专属 Provider（Eastmoney/Sina）时，
  latest_news/announcements 维度的响应使用 CN Provider 结果，而非通用 Provider
- _filter_news_response 的 require_chinese 过滤纯英文结果

@author Amadeus
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import MagicMock, patch

if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import (  # noqa: E402
    BaseSearchProvider,
    EastmoneyNewsProvider,
    SearchResponse,
    SearchResult,
    SearchService,
    SinaFinanceNewsProvider,
)


class _StubProvider(BaseSearchProvider):
    """A minimal provider that records calls and returns predetermined responses."""

    def __init__(self, name: str, results: list | None = None, success: bool = True) -> None:
        super().__init__(api_keys=["fake-key"], name=name)
        self._results = results or []
        self._success = success
        self.search_calls: list[dict] = []

    @property
    def is_available(self) -> bool:
        return True

    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        return SearchResponse(
            query=query,
            results=list(self._results),
            provider=self._name,
            success=self._success,
            error_message=None if self._success else "stub fail",
        )

    def search(self, query: str, max_results: int = 5, days: int = 7, **kwargs) -> SearchResponse:
        self.search_calls.append({"query": query, "max_results": max_results, "days": days, **kwargs})
        return SearchResponse(
            query=query,
            results=list(self._results)[:max_results],
            provider=self._name,
            success=self._success,
            error_message=None if self._success else "stub fail",
        )


def _make_empty_service() -> SearchService:
    """构造一个不依赖真实 API Key 的 SearchService 实例。"""
    return SearchService(
        bocha_keys=None,
        tavily_keys=None,
        anspire_keys=None,
        brave_keys=None,
        serpapi_keys=None,
        minimax_keys=None,
        searxng_base_urls=None,
        searxng_public_instances_enabled=False,
    )


class SelectProvidersForStockTests(unittest.TestCase):
    """_select_providers_for_stock 排序策略。"""

    def setUp(self) -> None:
        self.service = _make_empty_service()
        # 注入 3 个 stub 通用 provider：Bocha / Tavily / Brave
        self.bocha = _StubProvider("Bocha")
        self.tavily = _StubProvider("Tavily")
        self.brave = _StubProvider("Brave")
        self.service._providers = [self.tavily, self.brave, self.bocha]

    def test_a_share_reorders_bocha_first(self) -> None:
        """A 股：6 位数字代码 → Bocha 排在最前。"""
        ordered = self.service._select_providers_for_stock("002286", "保龄宝")
        names = [p.name for p in ordered]
        self.assertEqual(names[0], "Bocha")
        self.assertIn("Tavily", names)
        self.assertIn("Brave", names)

    def test_hk_stock_reorders_bocha_first(self) -> None:
        """港股：hk 前缀 → Bocha 优先。"""
        ordered = self.service._select_providers_for_stock("HK00700", "腾讯控股")
        names = [p.name for p in ordered]
        self.assertEqual(names[0], "Bocha")

    def test_us_stock_keeps_original_order(self) -> None:
        """美股：保持原序，不重排。"""
        ordered = self.service._select_providers_for_stock("AAPL", "Apple Inc.")
        names = [p.name for p in ordered]
        self.assertEqual(names, ["Tavily", "Brave", "Bocha"])

    def test_anspire_always_first(self) -> None:
        """Anspire 存在时 A 股场景下最优先，Bocha 次之。"""
        anspire = _StubProvider("Anspire")
        self.service._providers.insert(0, anspire)
        ordered = self.service._select_providers_for_stock("002286", "保龄宝")
        names = [p.name for p in ordered]
        self.assertEqual(names[0], "Anspire")
        self.assertEqual(names[1], "Bocha")

    def test_is_a_share_classifier(self) -> None:
        self.assertTrue(SearchService._is_a_share("002286"))
        self.assertTrue(SearchService._is_a_share("600000"))
        self.assertFalse(SearchService._is_a_share("HK00700"))
        self.assertFalse(SearchService._is_a_share("AAPL"))
        self.assertFalse(SearchService._is_a_share("01234"))  # 5 位


class ComprehensiveIntelCNIntegrationTests(unittest.TestCase):
    """A 股场景下 CN 专属 Provider 是否被优先调用。"""

    def setUp(self) -> None:
        self.service = _make_empty_service()

        # 通用 Provider：一个通用 stub，用来检查是否被调用（理想情况下，
        # CN 命中后 latest_news/announcements 维度不会再走通用 Provider）
        self.general = _StubProvider(
            "GeneralStub",
            results=[
                SearchResult(
                    title="通用源兜底新闻",
                    snippet="",
                    url="http://x",
                    source="GeneralStub",
                    published_date=datetime.now().strftime("%Y-%m-%d"),
                )
            ],
        )
        self.service._providers = [self.general]

        recent = datetime.now() - timedelta(days=1)
        self.cn_result = SearchResult(
            title="东方财富独家：公司季报预告",
            snippet="公司预计同比增长 20%",
            url="http://eastmoney.com/x",
            source="东方财富",
            published_date=recent.isoformat(),
        )

    def test_a_share_uses_cn_provider_for_latest_news(self) -> None:
        """A 股 + CN Provider 命中 → latest_news 维度命中 Eastmoney 响应。"""
        fake_cn_resp = SearchResponse(
            query="保龄宝",
            results=[self.cn_result],
            provider="Eastmoney",
            success=True,
        )
        em_provider = EastmoneyNewsProvider()
        em_provider.search_by_code = MagicMock(return_value=fake_cn_resp)  # type: ignore[assignment]
        # 强制 is_available 返回 True（避免依赖 akshare 环境）
        type(em_provider).is_available = property(lambda self: True)  # type: ignore[assignment]
        self.service._cn_providers = [em_provider]

        intel = self.service.search_comprehensive_intel(
            stock_code="002286",
            stock_name="保龄宝",
            max_searches=5,
        )

        self.assertIn("latest_news", intel)
        latest = intel["latest_news"]
        self.assertTrue(latest.success)
        self.assertEqual(latest.provider, "Eastmoney")
        self.assertTrue(any("东方财富" in (r.source or "") for r in latest.results))
        # CN 命中后，latest_news 维度不应再走通用 stub
        general_queries = [c["query"] for c in self.general.search_calls]
        self.assertFalse(
            any("最新" in q and "保龄宝" in q for q in general_queries),
            msg=f"通用 Provider 不应再被 latest_news 维度调用，实际 calls={general_queries}",
        )

    def test_us_stock_does_not_invoke_cn_provider(self) -> None:
        """美股：CN Provider 即使注册也不会被调度。"""
        em_provider = EastmoneyNewsProvider()
        em_provider.search_by_code = MagicMock()  # type: ignore[assignment]
        type(em_provider).is_available = property(lambda self: True)  # type: ignore[assignment]
        self.service._cn_providers = [em_provider]

        self.service.search_comprehensive_intel(
            stock_code="AAPL",
            stock_name="Apple Inc.",
            max_searches=2,
        )
        em_provider.search_by_code.assert_not_called()

    def test_cn_provider_empty_falls_back_to_general(self) -> None:
        """CN Provider 无结果 → 回退到通用 Provider。"""
        empty_cn = EastmoneyNewsProvider()
        empty_cn.search_by_code = MagicMock(  # type: ignore[assignment]
            return_value=SearchResponse(
                query="",
                results=[],
                provider="Eastmoney",
                success=True,
            )
        )
        type(empty_cn).is_available = property(lambda self: True)  # type: ignore[assignment]
        self.service._cn_providers = [empty_cn]

        intel = self.service.search_comprehensive_intel(
            stock_code="002286",
            stock_name="保龄宝",
            max_searches=3,
        )
        # 应回退到通用 Provider，latest_news 维度会获得 GeneralStub 的响应
        self.assertIn("latest_news", intel)


class FilterNewsResponseRequireChineseTests(unittest.TestCase):
    """_filter_news_response 的 require_chinese 参数。"""

    def setUp(self) -> None:
        self.service = _make_empty_service()

    def test_require_chinese_filters_out_english_only_results(self) -> None:
        today = datetime.now().date()
        recent = today - timedelta(days=1)
        response = SearchResponse(
            query="保龄宝",
            results=[
                SearchResult(
                    title="Baolingbao signed strategic partnership",
                    snippet="The company announced a partnership...",
                    url="http://example.com/en",
                    source="example.com",
                    published_date=recent.isoformat(),
                ),
                SearchResult(
                    title="保龄宝签订战略合作协议",
                    snippet="公司公告内容",
                    url="http://example.com/cn",
                    source="eastmoney.com",
                    published_date=recent.isoformat(),
                ),
            ],
            provider="StubNet",
            success=True,
        )

        filtered = self.service._filter_news_response(
            response,
            search_days=7,
            max_results=5,
            log_scope="test",
            require_chinese=True,
        )
        self.assertEqual(len(filtered.results), 1)
        self.assertIn("保龄宝", filtered.results[0].title)

    def test_default_does_not_filter_language(self) -> None:
        today = datetime.now().date()
        recent = today - timedelta(days=1)
        response = SearchResponse(
            query="AAPL",
            results=[
                SearchResult(
                    title="Apple announces new iPhone",
                    snippet="Apple Inc. launched ...",
                    url="http://example.com/en",
                    source="example.com",
                    published_date=recent.isoformat(),
                ),
            ],
            provider="StubNet",
            success=True,
        )
        filtered = self.service._filter_news_response(
            response,
            search_days=7,
            max_results=5,
            log_scope="test",
        )
        self.assertEqual(len(filtered.results), 1)


if __name__ == "__main__":
    unittest.main()
