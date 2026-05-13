# -*- coding: utf-8 -*-
class RoutingBase:
    def __init__(self, app):
        self.app = app

    def find_path_for_new_flow(self, host_a, host_b):
        """新流量進來時呼叫，回傳 switch dpid 路徑或 None"""
        raise NotImplementedError

    def find_reroute_path(self, host_a, host_b, remove_path=None, retrans_path=None):
        """
        _monitor_DTM 呼叫，尋找重路由路徑。
        remove_path:  強制排除的路徑
        retrans_path: 若結果與此相同，回傳 None（不換路）
        """
        raise NotImplementedError
