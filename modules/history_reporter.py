# -*- coding: utf-8 -*-
"""
history_reporter.py - HISTORY 統計 log 輸出

從 DTM.py 的 _monitor 抽出：偵測 stats_request.flag 檔案存在時，彙整累計
平均 hop 數／reroute 各類觸發次數／shortest_ratio，印一行 HISTORY log，
然後刪掉旗標檔（避免重複輸出）。

使用方式：
    self.history_reporter = HistoryReporter(self)   # DTM.py __init__ 建立
    self.history_reporter.maybe_log_history()         # _monitor 每輪呼叫
"""

import os
import logging

# DTM.py 在 import 這個模組之前已經設定好 "energy" logger 的 handler
energy_logger = logging.getLogger("energy")


class HistoryReporter:
    def __init__(self, app):
        self.app = app

    def maybe_log_history(self):
        if not os.path.exists("stats_request.flag"):
            return

        avg_hops = self.app.get_history_avg_hops()
        shortest_ratio = (
            self.app.routing_module.get_shortest_ratio()
            if hasattr(self.app.routing_module, 'get_shortest_ratio') else 0.0
        )
        energy_logger.info(
            f"HISTORY avg_hops={avg_hops:.4f} total_flows={self.app.flow_registry.flow_history_count} "
            f"reroute_link={self.app.reroute_count_link} "
            f"reroute_high_hop={self.app.reroute_count_high_hop} "
            f"reroute_low_share={self.app.reroute_count_low_share} "
            f"reroute_high_load={self.app.reroute_count_high_load} "
            f"shortest_ratio={shortest_ratio:.4f}"
        )
        os.remove("stats_request.flag")
