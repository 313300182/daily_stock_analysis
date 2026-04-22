# -*- coding: utf-8 -*-
"""
Step 2 导出层单元测试：

1. 验证 pipeline._enhance_context 把 TrendAnalysisResult 的新字段（ma30/60/120/250、fib、
   highlow、atr、hv）透传到 enhanced['trend_analysis']。
2. 验证 analyzer 的 _fmt_num / _format_bias 辅助函数在 None/0/NaN/合法值下的行为。

保持对环境依赖最小：pipeline 测试复用 test_pipeline_realtime_indicators 的 Config setup 方式；
analyzer 辅助测试直接调用静态方法，不走 litellm 链路。

@author Amadeus
"""

import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.stock_analyzer import TrendAnalysisResult, TrendStatus, VolumeStatus, BuySignal


class TestEnhanceContextPropagatesNewFields(unittest.TestCase):
    """pipeline._enhance_context 必须把 Step 1 新增字段透传到 trend_analysis dict"""

    def setUp(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "test_step2.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with patch.dict(os.environ, {"DATABASE_PATH": self._db_path}):
            from src.config import Config
            Config._instance = None
            self.config = Config._load_from_env()
        from src.core.pipeline import StockAnalysisPipeline
        self.pipeline = StockAnalysisPipeline(config=self.config)

    def _make_trend_result(self) -> TrendAnalysisResult:
        r = TrendAnalysisResult(
            code="600519",
            trend_status=TrendStatus.BULL,
            volume_status=VolumeStatus.NORMAL,
            buy_signal=BuySignal.HOLD,
            ma5=15.5, ma10=15.2, ma20=14.9, ma60=14.0,
        )
        r.ma30 = 14.5
        r.ma120 = 12.0
        r.ma250 = 10.0
        r.bias_ma30 = 3.5
        r.bias_ma60 = 10.7
        r.bias_ma120 = 29.2
        r.bias_ma250 = 55.0
        r.fib_peak = 21.31
        r.fib_peak_date = "2026-04-03"
        r.fib_trough = 13.41
        r.fib_trough_date = "2026-02-24"
        r.fib_0236 = 19.45
        r.fib_0382 = 18.29
        r.fib_0500 = 17.36
        r.fib_0618 = 16.43
        r.fib_0786 = 15.10
        r.fib_current_position = "中等回调(0.382~0.5)"
        r.high_60d = 21.31
        r.low_60d = 13.41
        r.high_120d = 21.31
        r.low_120d = 8.10
        r.high_250d = 21.31
        r.low_250d = 7.99
        r.atr_14 = 0.92
        r.atr_pct = 5.12
        r.hv_20 = 68.5
        r.hv_60 = 52.3
        r.volatility_level = "极高"
        return r

    def test_new_fields_present_in_trend_analysis(self) -> None:
        context = {
            "code": "600519",
            "date": date.today().isoformat(),
            "today": {"close": 18.0},
        }
        trend = self._make_trend_result()
        enhanced = self.pipeline._enhance_context(context, None, None, trend, "贵州茅台")

        ta = enhanced.get("trend_analysis")
        self.assertIsNotNone(ta, "trend_analysis 必须存在")

        expected_keys = [
            "ma30", "ma60", "ma120", "ma250",
            "bias_ma30", "bias_ma60", "bias_ma120", "bias_ma250",
            "fib_peak", "fib_peak_date", "fib_trough", "fib_trough_date",
            "fib_0236", "fib_0382", "fib_0500", "fib_0618", "fib_0786",
            "fib_current_position",
            "high_60d", "low_60d", "high_120d", "low_120d", "high_250d", "low_250d",
            "atr_14", "atr_pct", "hv_20", "hv_60", "volatility_level",
        ]
        for k in expected_keys:
            self.assertIn(k, ta, f"trend_analysis 缺少字段 {k}")

        self.assertAlmostEqual(ta["ma30"], 14.5)
        self.assertAlmostEqual(ta["fib_0500"], 17.36)
        self.assertEqual(ta["fib_current_position"], "中等回调(0.382~0.5)")
        self.assertEqual(ta["volatility_level"], "极高")
        self.assertAlmostEqual(ta["atr_14"], 0.92)

    def test_default_trend_result_yields_zero_fields(self) -> None:
        """未算出的字段应保持默认值 0/"" —— 让 md 层优雅降级为 N/A"""
        context = {"code": "000001", "today": {"close": 10.0}}
        trend = TrendAnalysisResult(code="000001")
        enhanced = self.pipeline._enhance_context(context, None, None, trend, "平安银行")

        ta = enhanced["trend_analysis"]
        self.assertEqual(ta["ma30"], 0.0)
        self.assertEqual(ta["ma250"], 0.0)
        self.assertEqual(ta["fib_peak"], 0.0)
        self.assertEqual(ta["fib_current_position"], "")
        self.assertEqual(ta["atr_14"], 0.0)
        self.assertEqual(ta["volatility_level"], "")


class TestAnalyzerFormatters(unittest.TestCase):
    """_fmt_num / _format_bias 的边界场景"""

    def test_fmt_num_none_zero_nan(self) -> None:
        from src.analyzer import GeminiAnalyzer
        self.assertEqual(GeminiAnalyzer._fmt_num(None), "N/A")
        self.assertEqual(GeminiAnalyzer._fmt_num(0), "N/A")
        self.assertEqual(GeminiAnalyzer._fmt_num(0.0), "N/A")
        self.assertEqual(GeminiAnalyzer._fmt_num(float("nan")), "N/A")
        self.assertEqual(GeminiAnalyzer._fmt_num("abc"), "N/A")

    def test_fmt_num_normal_values(self) -> None:
        from src.analyzer import GeminiAnalyzer
        self.assertEqual(GeminiAnalyzer._fmt_num(17.356789), "17.36")
        self.assertEqual(GeminiAnalyzer._fmt_num(17.356789, digits=4), "17.3568")
        self.assertEqual(GeminiAnalyzer._fmt_num("12.5"), "12.50")

    def test_format_bias_sign(self) -> None:
        from src.analyzer import GeminiAnalyzer
        self.assertEqual(GeminiAnalyzer._format_bias(3.5), "上方 +3.50%")
        self.assertEqual(GeminiAnalyzer._format_bias(-2.1), "下方 -2.10%")
        self.assertEqual(GeminiAnalyzer._format_bias(0), "N/A")
        self.assertEqual(GeminiAnalyzer._format_bias(None), "N/A")
        self.assertEqual(GeminiAnalyzer._format_bias(float("nan")), "N/A")


class TestPromptRendering(unittest.TestCase):
    """端到端：把新字段塞进 context，生成 md 里应出现"技术锚点增强数据"章节"""

    def _render(self, trend_dict) -> str:
        from src.analyzer import GeminiAnalyzer
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        # 绕过 __init__，补足 _format_prompt 用到的最小私有方法
        analyzer._get_skill_prompt_sections = lambda: ("", "", True)
        analyzer._get_runtime_config = lambda: None
        analyzer._get_section_snippet = lambda *args, **kwargs: ""
        context = {
            "code": "600519",
            "date": date.today().isoformat(),
            "today": {
                "close": 18.0, "open": 17.5, "high": 18.2, "low": 17.3,
                "pct_chg": 2.5, "ma5": 17.9, "ma10": 17.5, "ma20": 17.0,
            },
            "yesterday": {"close": 17.6, "volume": 1000000},
            "trend_analysis": trend_dict,
        }
        return analyzer._format_prompt(context, "贵州茅台")

    def _full_trend(self) -> dict:
        return {
            "trend_status": "多头排列",
            "ma_alignment": "多头排列 MA5>MA10>MA20",
            "trend_strength": 75,
            "bias_ma5": 0.56,
            "bias_ma10": 2.86,
            "volume_status": "量能正常",
            "volume_trend": "量能正常",
            "buy_signal": "持有",
            "signal_score": 70,
            "signal_reasons": ["✅ 多头排列"],
            "risk_factors": [],
            "neutral_observations": [],
            "ma30": 14.5, "ma60": 14.0, "ma120": 12.0, "ma250": 10.0,
            "bias_ma30": 24.1, "bias_ma60": 28.6,
            "bias_ma120": 50.0, "bias_ma250": 80.0,
            "fib_peak": 21.31, "fib_peak_date": "2026-04-03",
            "fib_trough": 13.41, "fib_trough_date": "2026-02-24",
            "fib_0236": 19.45, "fib_0382": 18.29, "fib_0500": 17.36,
            "fib_0618": 16.43, "fib_0786": 15.10,
            "fib_current_position": "中等回调(0.382~0.5)",
            "high_60d": 21.31, "low_60d": 13.41,
            "high_120d": 21.31, "low_120d": 8.10,
            "high_250d": 21.31, "low_250d": 7.99,
            "atr_14": 0.92, "atr_pct": 5.12,
            "hv_20": 68.5, "hv_60": 52.3, "volatility_level": "极高",
        }

    def test_full_fields_rendered(self) -> None:
        prompt = self._render(self._full_trend())
        self.assertIn("技术锚点增强数据", prompt)
        self.assertIn("| MA30", prompt)
        self.assertIn("| MA250", prompt)
        self.assertIn("斐波那契回撤", prompt)
        self.assertIn("17.36", prompt)  # fib_0500
        self.assertIn("ATR(14)", prompt)
        self.assertIn("2×ATR止损距", prompt)
        self.assertIn("1.84", prompt)  # 2×atr_14
        self.assertIn("历史波动率", prompt)
        self.assertIn("极高", prompt)
        self.assertIn("上方 +", prompt)
        self.assertIn("中等回调(0.382~0.5)", prompt)

    def test_missing_fields_graceful(self) -> None:
        """新字段全缺时章节不应出现 —— 避免渲染一堆 N/A 垃圾行"""
        minimal = {
            "trend_status": "震荡",
            "ma_alignment": "均线缠绕",
            "trend_strength": 50,
            "bias_ma5": 0.0,
            "bias_ma10": 0.0,
            "volume_status": "量能正常",
            "volume_trend": "",
            "buy_signal": "观望",
            "signal_score": 40,
            "signal_reasons": [],
            "risk_factors": [],
            "neutral_observations": [],
            # 新字段全部缺失/为 0
            "ma30": 0, "ma60": 0, "ma120": 0, "ma250": 0,
            "fib_peak": 0, "fib_trough": 0,
            "high_60d": 0, "high_120d": 0, "high_250d": 0,
            "atr_14": 0, "hv_20": 0, "hv_60": 0,
        }
        prompt = self._render(minimal)
        self.assertNotIn("技术锚点增强数据", prompt)

    def test_partial_fields_render_na(self) -> None:
        """部分字段有值（如 MA30/60 但没 MA120/250）时，章节渲染 + 缺失位 N/A"""
        partial = self._full_trend()
        partial["ma120"] = 0
        partial["ma250"] = 0
        partial["bias_ma120"] = 0
        partial["bias_ma250"] = 0
        partial["high_250d"] = 0
        partial["low_250d"] = 0
        prompt = self._render(partial)
        self.assertIn("技术锚点增强数据", prompt)
        # MA120/MA250 行应存在但数值显示 N/A
        self.assertIn("| MA120 | N/A |", prompt)
        self.assertIn("| MA250 | N/A |", prompt)


if __name__ == "__main__":
    unittest.main()
