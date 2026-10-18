# -*- coding: utf-8 -*-
"""经济周期监测模块:数据采集(econ_cycle.collectors) → 周期判定(econ_cycle.engine)
→ 决策信号(econ_cycle.signals) → 历史回测(econ_cycle.backtest)。

数据铁律:每条序列都带 period(所属期间)/capture_time(采集时间)/source(来源)。
历史阶段着色基于规则回放,非事后人工标注。
"""
