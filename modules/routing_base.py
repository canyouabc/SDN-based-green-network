# -*- coding: utf-8 -*-
"""
routing_base.py — Layer 1 路由模組的抽象父類別（介面契約）

繼承 `RoutingBase` 的模組須自己實作 `admit_flow` / `select_path`。
這個檔案本身不執行任何邏輯，只保證 5 個 DTM 路由演算法對 Layer 0
露出同一組方法名。

子類透過 `self.app` 存取 Layer 0，`app` 須滿足
`modules.routing_host.RoutingHost` 介面（見該檔）。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .routing_host import RoutingHost


class RoutingBase:
    # 子類自我宣告的能力旗標，取代散落在 DTM.py／packet_handler_v1.py／
    # startup_requirements.py 裡的 ROUTING_ALGORITHM in (tuple) 判斷——
    # 新增一個路由變體只需要在它自己的檔案宣告這些屬性，不用同步改別的
    # 檔案（2026-09-15 系統性回顧，因為 sorted_link 曾經漏改 6 處而起）。
    REROUTE_STYLE = None            # 'monitor_poll' 或 'cascade'，子類覆寫
    REQUIRED_APP_FEATURES = set()   # 需要非 None 的 self.app.<屬性名稱>，子類覆寫
    USES_LEGACY_DELAY_INFRA = False # 只有 2014／auto_k_short（不繼承這個類別）會是 True

    def __init__(self, app: "RoutingHost"):
        self.app = app

    def admit_flow(self, host_a, host_b):
        """新流量進來時呼叫，回傳 switch dpid 路徑或 None"""
        raise NotImplementedError

    def select_path(self, host_a, host_b, remove_path=None, retrans_path=None):
        """
        _monitor_DTM 呼叫，尋找重路由路徑。
        remove_path:  強制排除的路徑
        retrans_path: 若結果與此相同，回傳 None（不換路）
        """
        raise NotImplementedError
