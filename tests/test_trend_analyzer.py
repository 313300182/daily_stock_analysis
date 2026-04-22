# -*- coding: utf-8 -*-
"""
Tests for stock_analyzer 的 MACD/RSI 分类，验证 BEARISH 不会混入 signal_reasons。

@author Amadeus
"""
import unittest
from unittest.mock import patch, MagicMock

from src.stock_analyzer import (
    StockTrendAnalyzer,
    TrendAnalysisResult,
    TrendStatus,
    VolumeStatus,
    MACDStatus,
    RSIStatus,
)


def _make_result(
    macd_status: MACDStatus,
    rsi_status: RSIStatus = RSIStatus.NEUTRAL,
    trend_status: TrendStatus = TrendStatus.BULL,
) -> TrendAnalysisResult:
    result = TrendAnalysisResult(
        code="000001",
        trend_status=trend_status,
        ma_alignment="",
        trend_strength=50.0,
        ma5=10.0,
        ma10=9.5,
        ma20=9.0,
        ma60=8.5,
        current_price=10.0,
        bias_ma5=1.0,
        bias_ma10=0.0,
        bias_ma20=0.0,
        volume_status=VolumeStatus.NORMAL,
        volume_ratio_5d=1.0,
        volume_trend="",
        support_ma5=False,
        support_ma10=False,
        macd_status=macd_status,
        macd_signal="⚠ MACD 空头区域，持续下跌" if macd_status == MACDStatus.BEARISH else "✓ MACD 多头区域，持续上涨",
        rsi_status=rsi_status,
        rsi_signal="RSI 中性",
    )
    return result


class TrendAnalyzerSignalClassificationTests(unittest.TestCase):
    """验证 MACD/RSI 分类在 _generate_signal 中的正确归属."""

    def setUp(self) -> None:
        self.analyzer = StockTrendAnalyzer()

    @patch("src.stock_analyzer.get_config")
    def test_macd_bearish_not_in_reasons(self, mock_get_config: MagicMock) -> None:
        """MACD BEARISH 不应进入买入理由 signal_reasons."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(macd_status=MACDStatus.BEARISH)
        self.analyzer._generate_signal(result)

        reasons_joined = "\n".join(result.signal_reasons)
        self.assertNotIn("空头", reasons_joined)
        self.assertNotIn("MACD 空头区域", reasons_joined)

    @patch("src.stock_analyzer.get_config")
    def test_macd_bearish_goes_to_risks(self, mock_get_config: MagicMock) -> None:
        """MACD BEARISH 应进入 risk_factors."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(macd_status=MACDStatus.BEARISH)
        self.analyzer._generate_signal(result)

        risks_joined = "\n".join(result.risk_factors)
        self.assertIn("MACD 空头区域", risks_joined)

    @patch("src.stock_analyzer.get_config")
    def test_rsi_neutral_goes_to_neutral_observations(self, mock_get_config: MagicMock) -> None:
        """RSI NEUTRAL 应进入 neutral_observations，不进 reasons 也不进 risks."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(
            macd_status=MACDStatus.BULLISH,
            rsi_status=RSIStatus.NEUTRAL,
        )
        self.analyzer._generate_signal(result)

        self.assertTrue(
            any("RSI" in obs for obs in result.neutral_observations),
            msg=f"期望 RSI 出现在 neutral_observations，实际: {result.neutral_observations}",
        )
        self.assertFalse(
            any("RSI 中性" in r for r in result.signal_reasons),
            msg=f"RSI 中性不应出现在 signal_reasons: {result.signal_reasons}",
        )

    @patch("src.stock_analyzer.get_config")
    def test_macd_golden_cross_in_reasons(self, mock_get_config: MagicMock) -> None:
        """MACD GOLDEN_CROSS 应进入 reasons."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(macd_status=MACDStatus.GOLDEN_CROSS)
        result.macd_signal = "✓ 金叉"
        self.analyzer._generate_signal(result)

        reasons_joined = "\n".join(result.signal_reasons)
        self.assertIn("金叉", reasons_joined)

    def test_macd_text_has_area_keyword(self) -> None:
        """_analyze_macd 产出的文案应使用 'MACD 多头区域 / MACD 空头区域' 口径 (不再使用 '多头排列/空头排列')."""
        import inspect
        src = inspect.getsource(StockTrendAnalyzer._analyze_macd)
        self.assertIn("MACD 多头区域", src)
        self.assertIn("MACD 空头区域", src)
        self.assertNotIn("✓ 多头排列", src)
        self.assertNotIn("⚠ 空头排列", src)


if __name__ == "__main__":
    unittest.main()
