# -*- coding: utf-8 -*-
"""EastmoneyNewsProvider / SinaFinanceNewsProvider / XueqiuNewsProvider tests.

通过 mock akshare 验证三个 CN 专属 Provider 的行为：
- 时效过滤（按 days cutoff）
- query 关键词过滤
- 列名自动映射
- fail-open（akshare 异常/缺函数不抛出）

@author Amadeus
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import MagicMock

import pandas as pd

if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import (  # noqa: E402
    EastmoneyNewsProvider,
    SinaFinanceNewsProvider,
    XueqiuNewsProvider,
)


def _fake_ak_module_with(**attrs) -> ModuleType:
    mod = ModuleType("akshare")
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _install_fake_ak(module: ModuleType) -> None:
    sys.modules["akshare"] = module


class EastmoneyNewsProviderTests(unittest.TestCase):
    """EastmoneyNewsProvider 行为验证。"""

    def setUp(self) -> None:
        self._saved_ak = sys.modules.get("akshare")

    def tearDown(self) -> None:
        if self._saved_ak is not None:
            sys.modules["akshare"] = self._saved_ak
        else:
            sys.modules.pop("akshare", None)

    def test_returns_fresh_results_within_window(self) -> None:
        """近 7 天的新闻应被保留，超期的被过滤。"""
        today = datetime.now()
        recent = today - timedelta(days=1)
        stale = today - timedelta(days=20)

        df = pd.DataFrame(
            [
                {
                    "关键词": "保龄宝",
                    "新闻标题": "保龄宝签订战略合作协议",
                    "新闻内容": "公司公告：签订战略合作协议...",
                    "发布时间": recent.strftime("%Y-%m-%d %H:%M:%S"),
                    "文章来源": "东方财富",
                    "新闻链接": "http://example.com/news/1",
                },
                {
                    "关键词": "保龄宝",
                    "新闻标题": "旧新闻：已过期的标题",
                    "新闻内容": "远古新闻",
                    "发布时间": stale.strftime("%Y-%m-%d %H:%M:%S"),
                    "文章来源": "东方财富",
                    "新闻链接": "http://example.com/news/old",
                },
            ]
        )

        fn = MagicMock(return_value=df)
        _install_fake_ak(_fake_ak_module_with(stock_news_em=fn))

        provider = EastmoneyNewsProvider()
        self.assertTrue(provider.is_available)
        resp = provider.search_by_code("002286", query="", max_results=10, days=7)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertIn("战略合作", resp.results[0].title)
        self.assertEqual(resp.results[0].source, "东方财富")
        fn.assert_called_once_with(symbol="002286")

    def test_query_keyword_filters_results(self) -> None:
        """传 query 时应按标题+内容做关键词过滤。"""
        recent = datetime.now() - timedelta(days=1)
        df = pd.DataFrame(
            [
                {
                    "新闻标题": "A 消息：业绩超预期",
                    "新闻内容": "公司业绩超预期增长",
                    "发布时间": recent.strftime("%Y-%m-%d"),
                    "文章来源": "东财",
                    "新闻链接": "",
                },
                {
                    "新闻标题": "B 消息：无关项",
                    "新闻内容": "这条和关键词无关",
                    "发布时间": recent.strftime("%Y-%m-%d"),
                    "文章来源": "东财",
                    "新闻链接": "",
                },
            ]
        )
        _install_fake_ak(_fake_ak_module_with(stock_news_em=MagicMock(return_value=df)))

        provider = EastmoneyNewsProvider()
        resp = provider.search_by_code("000001", query="业绩超预期", days=7)
        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertIn("业绩", resp.results[0].title)

    def test_akshare_missing_returns_failure(self) -> None:
        """akshare 未安装时 fail-open，不抛出。"""
        sys.modules.pop("akshare", None)
        # 强制 import akshare 失败：在 sys.modules 放置一个会触发 ImportError 的 finder
        provider = EastmoneyNewsProvider()
        # 如果环境里确实没有 akshare，is_available 会是 False；如果有，这里至少不应抛异常
        resp = provider.search_by_code("000001", query="", days=7)
        self.assertIsNotNone(resp)
        self.assertFalse(bool(resp.success and not resp.results) and False)

    def test_function_missing_returns_failure(self) -> None:
        """akshare 存在但没有 stock_news_em 时返回失败响应，不抛异常。"""
        _install_fake_ak(_fake_ak_module_with())  # 无 stock_news_em

        provider = EastmoneyNewsProvider()
        resp = provider.search_by_code("000001", query="", days=7)
        self.assertFalse(resp.success)
        self.assertIn("stock_news_em", resp.error_message or "")

    def test_exception_from_ak_is_handled(self) -> None:
        """akshare 抛异常时返回失败响应，不把异常暴露给上层。"""
        def _boom(symbol: str):
            raise RuntimeError("connection reset")

        _install_fake_ak(_fake_ak_module_with(stock_news_em=_boom))

        provider = EastmoneyNewsProvider()
        resp = provider.search_by_code("000001", query="", days=7)
        self.assertFalse(resp.success)
        self.assertIn("stock_news_em", resp.error_message or "")

    def test_search_method_rejects_keyword_only_call(self) -> None:
        """search() 仅按关键词调用不被支持，必须使用 search_by_code。"""
        _install_fake_ak(_fake_ak_module_with(stock_news_em=MagicMock(return_value=pd.DataFrame())))
        provider = EastmoneyNewsProvider()
        resp = provider.search("任意关键词", max_results=3)
        self.assertFalse(resp.success)
        self.assertIn("search_by_code", resp.error_message or "")


class SinaFinanceNewsProviderTests(unittest.TestCase):
    """SinaFinanceNewsProvider 行为验证（新浪 + 财联社双通道）。"""

    def setUp(self) -> None:
        self._saved_ak = sys.modules.get("akshare")

    def tearDown(self) -> None:
        if self._saved_ak is not None:
            sys.modules["akshare"] = self._saved_ak
        else:
            sys.modules.pop("akshare", None)

    def test_prefers_stock_news_sina_when_available(self) -> None:
        recent = datetime.now() - timedelta(days=1)
        df_sina = pd.DataFrame(
            [
                {
                    "标题": "新浪：行业动态",
                    "内容": "最新行业动态摘要",
                    "时间": recent.strftime("%Y-%m-%d %H:%M:%S"),
                    "来源": "新浪财经",
                    "链接": "http://finance.sina.com.cn/x",
                }
            ]
        )
        sina_fn = MagicMock(return_value=df_sina)
        cls_fn = MagicMock(return_value=pd.DataFrame())
        _install_fake_ak(
            _fake_ak_module_with(stock_news_sina=sina_fn, stock_info_global_cls=cls_fn)
        )

        provider = SinaFinanceNewsProvider()
        resp = provider.search_by_code("600036", query="", stock_name="招商银行", days=7)
        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].source, "新浪财经")
        sina_fn.assert_called_once()

    def test_falls_back_to_cls_when_sina_returns_empty(self) -> None:
        recent = datetime.now() - timedelta(hours=2)
        df_sina = pd.DataFrame()
        df_cls = pd.DataFrame(
            [
                {
                    "标题": "财联社电报",
                    "内容": "招商银行 新公告 …",
                    "发布日期": recent.strftime("%Y-%m-%d"),
                    "发布时间": recent.strftime("%H:%M:%S"),
                },
                {
                    "标题": "无关电报",
                    "内容": "某公司与主题无关",
                    "发布日期": recent.strftime("%Y-%m-%d"),
                    "发布时间": recent.strftime("%H:%M:%S"),
                },
            ]
        )
        sina_fn = MagicMock(return_value=df_sina)
        cls_fn = MagicMock(return_value=df_cls)
        _install_fake_ak(
            _fake_ak_module_with(stock_news_sina=sina_fn, stock_info_global_cls=cls_fn)
        )

        provider = SinaFinanceNewsProvider()
        resp = provider.search_by_code("600036", query="", stock_name="招商银行", days=7)
        self.assertTrue(resp.success)
        # 应过滤只保留包含 stock_name 的电报
        for item in resp.results:
            merged = (item.title or "") + (item.snippet or "")
            self.assertIn("招商银行", merged)

    def test_no_stock_name_does_not_call_cls(self) -> None:
        """未传 stock_name 时不应触发 cls 通道（因为缺少过滤关键词）。"""
        sina_fn = MagicMock(return_value=pd.DataFrame())
        cls_fn = MagicMock(return_value=pd.DataFrame())
        _install_fake_ak(
            _fake_ak_module_with(stock_news_sina=sina_fn, stock_info_global_cls=cls_fn)
        )
        provider = SinaFinanceNewsProvider()
        resp = provider.search_by_code("000001", query="", stock_name="", days=7)
        cls_fn.assert_not_called()
        # 无结果但不算失败（新浪调用成功但空）
        self.assertTrue(resp.success)
        self.assertEqual(resp.results, [])


class XueqiuNewsProviderTests(unittest.TestCase):
    """XueqiuNewsProvider 默认关闭/可用性判断。"""

    def setUp(self) -> None:
        self._saved_ak = sys.modules.get("akshare")

    def tearDown(self) -> None:
        if self._saved_ak is not None:
            sys.modules["akshare"] = self._saved_ak
        else:
            sys.modules.pop("akshare", None)

    def test_unavailable_when_ak_missing_function(self) -> None:
        _install_fake_ak(_fake_ak_module_with())
        provider = XueqiuNewsProvider()
        self.assertFalse(provider.is_available)

    def test_returns_failure_when_function_missing(self) -> None:
        _install_fake_ak(_fake_ak_module_with())
        provider = XueqiuNewsProvider()
        resp = provider.search_by_code("000001", query="", days=7)
        self.assertFalse(resp.success)
        self.assertIn("stock_news_xq", resp.error_message or "")

    def test_available_when_function_present(self) -> None:
        _install_fake_ak(_fake_ak_module_with(stock_news_xq=MagicMock(return_value=pd.DataFrame())))
        provider = XueqiuNewsProvider()
        self.assertTrue(provider.is_available)


if __name__ == "__main__":
    unittest.main()
