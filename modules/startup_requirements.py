# -*- coding: utf-8 -*-
"""
startup_requirements.py — 契約層：DTM.py 啟動時「誰需要什麼、誰該不該跑」
的通用檢查/決策函式。

跟 routing_base.py（介面形狀）、routing_host.py（app 該提供什麼）是同一類
東西——純函式，從不被實例化、不持有跨時間狀態，是描述 Layer 之間該怎麼連
的規則，不是 Layer 1 或 Layer 2 的成員。

── 2026-09-15 的演進：從「中央表」改成「自我宣告」────────────────────
原名 routing_requirements.py，原本用兩張中央表（ALGORITHM_DEPENDENCIES、
以及散落在 DTM.py／packet_handler_v1.py 裡各處的
`ROUTING_ALGORITHM in ('2020','dijkstra','self','sorted')` 這類判斷）
決定「這個演算法需要哪些 Layer 2 資源」「這個演算法該不該觸發某段通用
行為」。問題是：新增一個路由變體時，要記得同步改好幾個地方——
`routing_DTM_sorted_link.py` 曾經漏改其中 6 處（TCP/UDP 路由分派、
flow_removed_handler 的守門/on_flow_removed 呼叫、refresh_link_cache、
_monitor_energy 的 spawn 條件），變成「選了 sorted_link 幾乎等於路由
完全不運作」，事後才發現，決定砍掉 sorted_link 重新設計（見
memory: dijkstra-systematic-review）。

修正方式：把「需要什麼」「該不該參與某種通用行為」改成**路由模組自己宣告**
的類別屬性（見 modules/routing_base.py 的 REROUTE_STYLE／
REQUIRED_APP_FEATURES／USES_LEGACY_DELAY_INFRA，以及 routing_2014.py／
routing_auto_k_short.py 各自宣告的同名屬性），這個檔案只剩「怎麼讀這些
宣告、怎麼查」的通用函式，不再有任何地方寫死演算法名稱字串。新增一個
路由變體，只要在它自己的檔案宣告這三個屬性，DTM.py／
packet_handler_v1.py／這個檔案都不用改一行。

── check_dependencies(app, routing_module) ────────────────────────
讀 routing_module.REQUIRED_APP_FEATURES（**不用 getattr 給預設值**，
故意讓忘記宣告這個屬性的新路由模組直接 AttributeError——保留跟原本
ALGORITHM_DEPENDENCIES[algorithm] 用中括號查表同樣的 fail-fast 紀律）。
逐一檢查宣告的依賴是否真的被建出來（self.app.<屬性> 非 None），不符合
就 RuntimeError。

為什麼查 delay_detection / link_delay_measurement 而不是
link_delay / link_used_bw：routing_2014 / routing_auto_k_short 實際讀的是
self.app.link_delay / self.app.link_used_bw（資料本身），但這兩個 dict 在
DTM.py 是無條件初始化的（永遠不是 None，ENABLE_DELAY_DETECTION 關閉時
只是永遠是空的 {}），拿它們做「存不存在」的檢查測不出問題。真正反映
ENABLE_DELAY_DETECTION 狀態、會在關閉時變成 None 的，是
delay_detection / link_delay_measurement 這兩個物件本身。

── MonitorFlags / should_spawn_monitor ─────────────────────────────
9 個背景執行緒該不該 spawn，同樣改成讀路由模組的自我宣告：
- monitor／link_ready_watcher／flow_stats_monitor：無條件——跟哪個
  routing_module 無關，每種都需要或都不影響。
- bandwidth_monitor：只看 ENABLE_BANDWIDTH_MEASUREMENT 旗標——
  check_dependencies() 已經確保旗標關掉時，需要 link_status 的演算法會
  在啟動當下就 fail-fast，這裡不用重複判斷。
- monitor_dtm：routing_module.REROUTE_STYLE == 'monitor_poll'
- monitor_energy：routing_module.REROUTE_STYLE == 'cascade'
- flow_oracle：ENABLE_FLOW_ORACLE 旗標開，且 routing_module 有參與
  REROUTE_STYLE 派送（跟 flow_removed_handler 同一個守門條件）
- legacy_detector／legacy_dynamic_test：
  routing_module.USES_LEGACY_DELAY_INFRA（legacy_detector 另外還要
  ENABLE_DELAY_DETECTION 旗標也開）

使用方式：
    from modules.startup_requirements import (
        check_dependencies, MonitorFlags, should_spawn_monitor,
    )
    check_dependencies(self, self.routing_module)              # L2 資源檢查
    flags = MonitorFlags(self.routing_module, ENABLE_DELAY_DETECTION,
                          ENABLE_BANDWIDTH_MEASUREMENT)
    if should_spawn_monitor('monitor_energy', flags):
        self.energy_monitor_thread = hub.spawn(self._monitor_energy)
"""

from collections import namedtuple


def check_dependencies(app, routing_module):
    """啟動時呼叫一次。routing_module 沒宣告 REQUIRED_APP_FEATURES →
    AttributeError（忘記幫新路由模組宣告這個屬性）。宣告的依賴存在、但
    self.app.<屬性> 是 None（沒被建出來）→ RuntimeError（宣告寫對了、
    沒真的建立）。"""
    needed = routing_module.REQUIRED_APP_FEATURES
    missing = [feature for feature in needed if getattr(app, feature, None) is None]
    if missing:
        raise RuntimeError(
            "{} 需要 {}，但沒有被建出來（檢查對應的 ENABLE_* 旗標是否開啟）".format(
                type(routing_module).__name__, missing
            )
        )


MonitorFlags = namedtuple('MonitorFlags', [
    'routing_module', 'enable_delay_detection', 'enable_bandwidth_measurement',
    'enable_flow_oracle',
], defaults=(False,))

# {monitor 名稱: 條件 function(MonitorFlags) -> bool}
# 全部 9 個 hub.spawn 都透過這張表決定，即使條件是「永遠 True」也放進來，
# 讓這張表成為「誰會被 spawn」的單一事實來源。
MONITOR_CONDITIONS = {
    'monitor':             lambda f: True,
    'link_ready_watcher':  lambda f: True,
    'flow_stats_monitor':  lambda f: True,
    'bandwidth_monitor':   lambda f: f.enable_bandwidth_measurement,
    'monitor_dtm':         lambda f: getattr(f.routing_module, 'REROUTE_STYLE', None) == 'monitor_poll',
    'monitor_energy':      lambda f: getattr(f.routing_module, 'REROUTE_STYLE', None) == 'cascade',
    'flow_oracle':         lambda f: f.enable_flow_oracle and getattr(f.routing_module, 'REROUTE_STYLE', None) is not None,
    'legacy_detector':     lambda f: f.enable_delay_detection and getattr(f.routing_module, 'USES_LEGACY_DELAY_INFRA', False),
    'legacy_dynamic_test': lambda f: getattr(f.routing_module, 'USES_LEGACY_DELAY_INFRA', False),
}


def should_spawn_monitor(name, flags):
    """name 不在 MONITOR_CONDITIONS 裡 → KeyError（忘記幫新執行緒加條目，
    fail-fast，跟 check_dependencies 同一種紀律）。"""
    return MONITOR_CONDITIONS[name](flags)
