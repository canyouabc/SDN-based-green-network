# -*- coding: utf-8 -*-
"""
reroute_policy.py - 重路由觸發條件的優先順序引擎

從 DTM.py 的 _monitor_DTM 抽出「依序檢查各觸發條件，第一個成功就停」這段。
四個觸發條件本來是寫死的 if/elif 分支，現在順序本身變成資料
（DTM.py 開頭的 REROUTE_TRIGGER_ORDER），這裡是讀這份資料、依序執行的通用引擎
——調整優先順序只要改 DTM.py 的常數，不用動這個檔案。

LINK 觸發形狀跟其他三個不同（先掃 link 狀態、再找經過該 link 的 flow，
沒有 top_n/threshold，也沒有 ENABLE_* 開關，永遠檢查），單獨處理。
HIGH_HOP/HIGH_LOAD/LOW_SHARE 三個形狀一致：依 REROUTE_TRIGGER_CONFIG 的
enabled/top_n/threshold，向 flow_registry 要候選 flow 列表（透過命名規則
_get_{trigger小寫}_flows 找對應方法），依序嘗試重路由。

使用方式：
    self.reroute_policy = ReroutePolicy(self, REROUTE_TRIGGER_ORDER, REROUTE_TRIGGER_CONFIG)
    self.reroute_policy.attempt_rebalance()   # _monitor_DTM 每輪呼叫一次
"""


class ReroutePolicy:
    def __init__(self, app, trigger_order, trigger_config):
        self.app = app
        self.trigger_order = trigger_order
        self.trigger_config = trigger_config

    def attempt_rebalance(self):
        """依 trigger_order 依序檢查，第一個成功觸發重路由就停。
        回傳是否有觸發重路由。"""
        for trigger in self.trigger_order:
            if trigger == 'LINK':
                if self._try_link_trigger():
                    return True
                continue

            cfg = self.trigger_config.get(trigger)
            if cfg is None or not cfg['enabled']:
                continue

            getter = getattr(self.app.flow_registry, f'_get_{trigger.lower()}_flows')
            for host_a, host_b, path in getter(cfg['top_n'], cfg['threshold']):
                if self.app._do_reroute(host_a, host_b, path, reason=trigger):
                    return True
        return False

    def _try_link_trigger(self):
        """LINK 觸發：LOW / OVERLOAD / DANGER"""
        all_link_status = self.app.link_status.get_all_link_status()
        for (dpid_a, dpid_b), link_info in all_link_status.items():
            status = link_info.get('status', 'NORMAL')
            if status not in ('LOW', 'OVERLOAD', 'DANGER'):
                continue
            for host_a, host_b, path in self.app.get_active_flows():
                has_link = any(
                    (min(path[i], path[i+1]), max(path[i], path[i+1])) == (dpid_a, dpid_b)
                    for i in range(len(path) - 1)
                )
                if not has_link:
                    continue
                if self.app._do_reroute(host_a, host_b, path, reason="LINK"):
                    return True
        return False
