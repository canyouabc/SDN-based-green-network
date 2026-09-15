# -*- coding: utf-8 -*-
"""
topology_readiness.py - 拓撲穩定判斷 + 被動 host 學習

從 DTM.py 抽出的 _check_link_ready / _link_ready_watcher / update_host_mac_table：
- _link_ready_watcher：背景執行緒，每 2 秒輪詢一次 switch/link 數量，數量連續
  兩輪不變就判定拓撲穩定，發出 [LINK_READY] 並觸發 host_discovery.discover()。
- update_host_mac_table：被動學習——從 Ryu topology 的 get_host() 讀取目前已知
  的 host，寫進 self.app.host_macs（跟 host_discovery.py 共用同一份 dict，
  兩邊都會寫入，所以 host_macs 本身仍留在 self.app 上，不搬進這個模組）。

使用方式：
    self.topology_readiness = TopologyReadiness(self)         # DTM.py __init__ 建立
    self.link_ready_thread = hub.spawn(self.topology_readiness._link_ready_watcher)
    self.topology_readiness.update_host_mac_table()            # _monitor 呼叫
"""

from ryu.topology.api import get_switch, get_link, get_host
from ryu.lib import hub


class TopologyReadiness:
    def __init__(self, app):
        self.app = app
        self._topo_ready_logged = False  # [TOPO_READY] 只發一次
        self._link_ready_logged = False  # [LINK_READY] 只發一次
        self._last_sw_count = 0
        self._last_link_count = 0
        self.dpid_to_mac = {}            # {dpid: mac}

    def _check_link_ready(self):
        """檢查 switch 和 link 數量是否穩定，穩定則發出 [LINK_READY]"""
        sw_count   = len(get_switch(self.app.topology_api_app, None))
        link_count = len(get_link(self.app.topology_api_app, None))
        if (sw_count > 0 and link_count > 0
                and sw_count   == self._last_sw_count
                and link_count == self._last_link_count
                and not self._link_ready_logged):
            self._link_ready_logged = True
            print(f"[LINK_READY] 共 {sw_count} 個 switch，{link_count} 條 link")
            # 2026-09-11：曾因 ARP_REPLY 落入 OFPP_FLOOD（無防迴圈的網狀
            # 拓撲）造成永久性廣播風暴，根因已修（見上方 ARP 封包處理
            # 段落，return 移出 REQUEST 判斷之外）。修好後完整實測通過
            # （cap_topo.py，全程不打 sendarp，iperf 直接成功），正式啟用。
            self.app.host_discovery.discover()
        self._last_sw_count   = sw_count
        self._last_link_count = link_count

    def _link_ready_watcher(self):
        """快速輪詢直到 [LINK_READY] 確認，之後結束"""
        hub.sleep(3)
        while not self._link_ready_logged:
            self._check_link_ready()
            hub.sleep(2)

    def update_host_mac_table(self):
        """从拓扑信息更新主机MAC表"""
        hosts = get_host(self.app.topology_api_app, None)
        new_added = 0

        for host in hosts:
            mac = host.mac
            dpid = host.port.dpid
            port_no = host.port.port_no

            if mac not in self.app.host_macs:
                self.app.host_macs[mac] = (dpid, port_no)
                self.dpid_to_mac[dpid] = mac
                print(f"Added host: {mac} at switch {dpid}, port {port_no}")
                new_added += 1

        # 這輪沒有新增 host，且已有資料 → 拓撲穩定，發一次 [TOPO_READY]
        if new_added == 0 and self.app.host_macs and not self._topo_ready_logged:
            self._topo_ready_logged = True
            print(f"[TOPO_READY] 所有 host 已學習完成，共 {len(self.app.host_macs)} 個")
