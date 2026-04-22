# -*- coding: utf-8 -*-
"""
Step 1 计算层单元测试：技术指标增强

覆盖 src/stock_analyzer.py 中新增的指标：
- 长周期均线 MA30/MA60/MA120/MA250 及其乖离率
- 斐波那契回撤（120 日窗口主升浪）
- 60/120/250 日历史高低点
- ATR(14) 与 ATR 占比
- HV(20)/HV(60) 年化历史波动率 + 波动等级

@author Amadeus
"""

import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult


def _build_rise_then_fall_df(days: int = 300, seed: int = 42) -> pd.DataFrame:
    """构造先涨后跌的合成日 K 线数据，保证存在清晰的主升浪以便测试斐波那契。"""
    np.random.seed(seed)
    dates = pd.date_range('2025-01-01', periods=days, freq='D')
    half = days // 2
    rising = np.linspace(10.0, 20.0, half)
    falling = np.linspace(20.0, 15.0, days - half)
    prices = np.concatenate([rising, falling])
    noise = np.random.randn(days) * 0.3
    close = prices + noise

    high_noise = np.abs(np.random.randn(days)) * 0.5
    low_noise = np.abs(np.random.randn(days)) * 0.5

    df = pd.DataFrame({
        'date': dates,
        'open': close + np.random.randn(days) * 0.2,
        'high': close + high_noise,
        'low': close - low_noise,
        'close': close,
        'volume': np.random.randint(100000, 1000000, days),
    })
    return df


def _build_short_df(days: int = 20) -> pd.DataFrame:
    """构造少量样本的 DataFrame，用于测试数据不足时的静默返回。"""
    dates = pd.date_range('2026-04-01', periods=days, freq='D')
    close = np.linspace(10.0, 12.0, days)
    df = pd.DataFrame({
        'date': dates,
        'open': close - 0.1,
        'high': close + 0.2,
        'low': close - 0.2,
        'close': close,
        'volume': [500000] * days,
    })
    return df


class TestEnhancedIndicators(unittest.TestCase):
    """计算层核心验证：跑完整 analyze() 后断言各新字段。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.analyzer = StockTrendAnalyzer()
        cls.df = _build_rise_then_fall_df(days=300)
        cls.result = cls.analyzer.analyze(cls.df, '000001')

    def test_long_ma_all_computed(self) -> None:
        self.assertGreater(self.result.ma30, 0)
        self.assertGreater(self.result.ma60, 0)
        self.assertGreater(self.result.ma120, 0)
        self.assertGreater(self.result.ma250, 0)
        # 乖离率应被填充（理论上合成数据下不会恰好为 0）
        self.assertNotEqual(self.result.bias_ma30, 0.0)
        self.assertNotEqual(self.result.bias_ma60, 0.0)
        self.assertNotEqual(self.result.bias_ma120, 0.0)
        self.assertNotEqual(self.result.bias_ma250, 0.0)

    def test_fibonacci_monotonic(self) -> None:
        r = self.result
        self.assertGreater(r.fib_peak, r.fib_trough)
        self.assertGreater(r.fib_0236, r.fib_0382)
        self.assertGreater(r.fib_0382, r.fib_0500)
        self.assertGreater(r.fib_0500, r.fib_0618)
        self.assertGreater(r.fib_0618, r.fib_0786)
        self.assertNotEqual(r.fib_current_position, "")

    def test_period_highlow_consistency(self) -> None:
        r = self.result
        self.assertGreaterEqual(r.high_60d, r.low_60d)
        self.assertGreaterEqual(r.high_120d, r.low_120d)
        self.assertGreaterEqual(r.high_250d, r.low_250d)
        # 250 日窗口覆盖 60 日窗口，故其最高价应 >= 60 日最高
        self.assertGreaterEqual(r.high_250d, r.high_60d)
        self.assertLessEqual(r.low_250d, r.low_60d)

    def test_atr_positive(self) -> None:
        self.assertGreater(self.result.atr_14, 0)
        self.assertGreater(self.result.atr_pct, 0)

    def test_hv_and_level(self) -> None:
        r = self.result
        self.assertGreater(r.hv_20, 0)
        self.assertGreater(r.hv_60, 0)
        self.assertIn(r.volatility_level, ("低", "中", "高", "极高", "N/A"))

    def test_to_dict_contains_new_fields(self) -> None:
        d = self.result.to_dict()
        expected_keys = [
            'ma30', 'ma120', 'ma250',
            'bias_ma30', 'bias_ma60', 'bias_ma120', 'bias_ma250',
            'fib_peak', 'fib_peak_date', 'fib_trough', 'fib_trough_date',
            'fib_0236', 'fib_0382', 'fib_0500', 'fib_0618', 'fib_0786',
            'fib_current_position',
            'high_60d', 'low_60d', 'high_120d', 'low_120d', 'high_250d', 'low_250d',
            'atr_14', 'atr_pct', 'hv_20', 'hv_60', 'volatility_level',
        ]
        for key in expected_keys:
            self.assertIn(key, d, f"to_dict 缺少字段 {key}")


class TestBackwardCompatibility(unittest.TestCase):
    """向后兼容性：短数据不抛异常且新字段保持默认值。"""

    def test_short_data_does_not_crash(self) -> None:
        analyzer = StockTrendAnalyzer()
        df = _build_short_df(days=20)
        # 20 天满足 analyze() 最低要求（>=20），但不足长周期指标门槛
        result = analyzer.analyze(df, '000002')

        # 基础字段仍应被计算
        self.assertGreater(result.ma5, 0)
        self.assertGreater(result.ma20, 0)

        # 长周期字段应保持默认 0
        self.assertEqual(result.ma30, 0.0)
        self.assertEqual(result.ma120, 0.0)
        self.assertEqual(result.ma250, 0.0)
        self.assertEqual(result.bias_ma30, 0.0)
        self.assertEqual(result.bias_ma120, 0.0)

        # 斐波那契需要 >=30 天，20 天应保持默认 0
        self.assertEqual(result.fib_peak, 0.0)
        self.assertEqual(result.fib_trough, 0.0)
        self.assertEqual(result.fib_current_position, "")

        # 60/120/250 日高低点需对应窗口，20 天都不满足
        self.assertEqual(result.high_60d, 0.0)
        self.assertEqual(result.high_120d, 0.0)
        self.assertEqual(result.high_250d, 0.0)

        # ATR(14) 需要 >=15 天，20 天满足 —— 这里只确保不为负且不抛异常
        self.assertGreaterEqual(result.atr_14, 0.0)

        # HV(20) 需要 >=21 天，20 天不满足
        self.assertEqual(result.hv_20, 0.0)
        self.assertEqual(result.hv_60, 0.0)
        self.assertIn(result.volatility_level, ("", "N/A"))


class TestFibonacciInsufficientData(unittest.TestCase):
    """斐波那契在极短数据下必须静默返回。"""

    def test_fibonacci_under_30_days(self) -> None:
        analyzer = StockTrendAnalyzer()
        df = _build_short_df(days=10)
        result = TrendAnalysisResult(code='000003')

        # 不应抛异常
        analyzer._calculate_fibonacci(df, result, lookback=120)

        self.assertEqual(result.fib_peak, 0.0)
        self.assertEqual(result.fib_trough, 0.0)
        self.assertEqual(result.fib_0500, 0.0)
        self.assertEqual(result.fib_current_position, "")


if __name__ == "__main__":
    unittest.main()
