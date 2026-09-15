# -*- coding: utf-8 -*-
"""
legacy_algorithm_support.py - 只服務 2014／auto_k_short 的歷史程式碼

這裡打包的東西，在現行 ROUTING_ALGORITHM（'sorted' 等 2020/dijkstra/self/
sorted/sorted_link 這條主線）下完全不會被用到：

- detector／switch_to_switch_delay_count／handle_echo_reply：延遲偵測執行緒，
  依 startup_requirements.py 的依賴表，只有 '2014' 跟 'auto_k_short' 需要，
  且 ENABLE_DELAY_DETECTION 預設就是 False。這兩個執行緒（連同
  dynamic_test）的 spawn 條件現在也收在 startup_requirements.py 的
  MONITOR_CONDITIONS 表裡（同時檢查旗標跟 ROUTING_ALGORITHM），DTM.py
  不會在演算法用不到時還白白 spawn。
- dynamic_test：對現行 5 個演算法完全是 no-op（函式跑完什麼都不做），只有
  '2014'（目前會被 startup_requirements.py 的 fail-fast 檢查攔下來，因為
  routing_2014.py 呼叫的 self.app.get_link_delay_func 從未被定義過）跟
  'auto_k_short'（離線 k-shortest path 產生工具，不是常態路由演算法）分支
  才有實際內容。
- request_stats：定義了但目前整個專案零呼叫點的死碼，一併帶過來存查。

這次只是把這些「現行主線用不到」的東西搬出 DTM.py 集中放，沒有刪除、沒有
改行為——ENABLE_DELAY_DETECTION／ROUTING_ALGORITHM 若之後改回會用到這些的
設定，這裡的邏輯照樣會被呼叫，功能不受影響。未來如果 2014／auto_k_short／
延遲偵測那邊出問題，可以先來這個檔案找。

使用方式：
    self.legacy_algorithm_support = LegacyAlgorithmSupport(
        self, ENABLE_DELAY_DETECTION, ROUTING_ALGORITHM
    )                                                       # DTM.py __init__ 建立
    hub.spawn(self.legacy_algorithm_support.detector)         # 取代 hub.spawn(self._detector)
    hub.spawn(self.legacy_algorithm_support.dynamic_test)      # 取代 hub.spawn(self.dynamic_Dijkstra_test)
    self.legacy_algorithm_support.handle_echo_reply(dpid)      # echo_reply_handler 呼叫
"""

import os

from ryu.lib import hub


class LegacyAlgorithmSupport:
    def __init__(self, app, enable_delay_detection, routing_algorithm):
        self.app = app
        self.enable_delay_detection = enable_delay_detection
        self.routing_algorithm = routing_algorithm
        self.temp_adjacency = {}
        self.temp_mymac = {}   # 從 DTM.py __init__ 帶過來，一直沒被用到
        self.arp_count = 1     # 同上，一直沒被用到

    def detector(self):
        """
        detector 是處理延遲偵測的執行緒
        定期掃描拓撲，將所有 link 對加入檢測隊列
        """
        hub.sleep(10)  # 等待拓撲穩定
        while True:
            self.temp_adjacency = dict(self.app.adjacency)
            detection_queue = self.app.delay_detection.build_detection_queue(self.temp_adjacency)
            print(f"[DETECTOR] 開始測量，共 {len(detection_queue)} 對", flush=True)
            for switch_a, switch_b in detection_queue:
                self.switch_to_switch_delay_count(switch_a, switch_b)
                hub.sleep(0)  # ← 先加這個測試
            print(f"[DETECTOR] 測量完成", flush=True)
            hub.sleep(30)

    def switch_to_switch_delay_count(self, switch_a, switch_b):
        if not self.enable_delay_detection:
            return

        # ← 直接傳遞 delay_detection 的模組函式作為回調
        self.app.link_delay_measurement.measure_pair_delay(
            switch_a, switch_b,
            lambda sa, sb: self.app.delay_detection.send_lldp_for_delay_detection(sa, sb, self.temp_adjacency, self.app.datapaths),
            lambda s, ps: self.app.delay_detection.send_echo_for_delay_detection(s, ps, self.app.datapaths),
            hub.sleep
        )

    def handle_echo_reply(self, dpid):
        if not self.enable_delay_detection:
            return
        # ← 使用 delay_detection module 處理 Echo Reply
        self.app.delay_detection.handle_echo_reply_event(dpid)

    '''
    這段用來測試 Dijkstra 動態更新路徑的功能
    '''
    def dynamic_test(self):

        # ← 等待 10 秒，確保拓撲和主機表完全建立
        hub.sleep(10)

        # ← 2014 版本是被動式（packet_in 觸發），不需要長期線程
        if self.routing_algorithm == '2014':
            print("*** 2014 被動式路由已啟用 - 路由計算將在 packet_in 事件時觸發")
            return

        if self.routing_algorithm == 'auto_k_short':
            print("*** k-shortest paths 計算模組已啟用 - 等待 sendarp 完成...")
            # 清掉可能殘留的舊旗標（例如上一輪實驗中途中斷），避免這次一啟動
            # 就誤判成「sendarp 已完成」而跳過等待
            if os.path.exists('arp_done.flag'):
                os.remove('arp_done.flag')
            # 先等 send_arp_all() 送完 ARP 後寫出的旗標檔，避免在使用者於 Mininet
            # CLI 真正打 sendarp 之前，host_macs 就因為背景流量短暫持平而誤判穩定
            while not os.path.exists('arp_done.flag'):
                hub.sleep(1)
            os.remove('arp_done.flag')
            print("*** 偵測到 sendarp 已完成，開始等待 host_macs 穩定...")
            # 輪詢 host_macs 數量直到穩定（連續 3 次不再增加）才開始算，
            # sendarp 送出後 packet-in 仍需時間陸續抵達 controller，這裡當作最後一道緩衝
            last_count = -1
            stable_ticks = 0
            while stable_ticks < 3:
                hub.sleep(2)
                cur_count = len(self.app.host_macs)
                if cur_count > 0 and cur_count == last_count:
                    stable_ticks += 1
                else:
                    stable_ticks = 0
                last_count = cur_count
            print(f"\n*** host_macs 已穩定（共 {last_count} 個 host），開始計算 K-Shortest Paths...")
            self.app.routing_module.compute_all_k_shortest_paths_once(
                k=16,
                output_filepath='data/k_short.txt',
                host_range=(1, 16)
            )
            return

    def request_stats(self, datapath):
        """搬過來前就已經是零呼叫點的死碼，原樣帶過來存查。"""
        #self.logger.debug('send stats request: %016x', datapath.id)
        #print 'send stats request:', datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)
