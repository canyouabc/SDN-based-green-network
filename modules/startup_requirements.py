# -*- coding: utf-8 -*-
"""
startup_requirements.py — 契約層：DTM.py 啟動時「誰需要什麼、誰該不該跑」
的單一事實來源。

跟 routing_base.py（介面形狀）、routing_host.py（app 該提供什麼）是同一類
東西——純資料宣告 + 純函式，從不被實例化、不持有跨時間狀態，是描述
Layer 之間該怎麼連的規則，不是 Layer 1 或 Layer 2 的成員。

原名 routing_requirements.py，只處理「Layer 1（routing 模組）需要哪些
Layer 2 資源」。2026-09-15 擴充成「全域」：DTM.py `__init__` 裡 8 個
monitor 背景執行緒的 spawn 條件，原本散落在 8 個地方各自的 if 判斷（有的看
ENABLE_* 旗標、有的看 ROUTING_ALGORITHM 成員、有的無條件）——跟原本
ALGORITHM_DEPENDENCIES 想解決的問題是同一類：旗標跟演算法選擇是各自獨立
設定的，沒有機制保證兩者一致，容易漂移出「旗標開著但演算法用不到」或
「演算法需要但漏開旗標」的問題。集中成一張表後，順便修掉一個已知缺口：
`_monitor_energy` 原本的條件 `ROUTING_ALGORITHM in ('self', 'sorted')`
漏了 `sorted_link`（跟 `sorted` 同一套 cascade/權重圖機制，理當同組）。

── 第一部分：ALGORITHM_DEPENDENCIES（Layer 1 需要的 Layer 2 資源）──────
（內容跟語意跟改名前完全一樣，只是搬到這個檔案）

DTM.py 用一批獨立的 ENABLE_* 旗標（ENABLE_DELAY_DETECTION、
ENABLE_BANDWIDTH_MEASUREMENT）決定要不要建立某些 Layer 2 模組，但這些
旗標跟 ROUTING_ALGORITHM 各自獨立設定，沒有任何機制保證兩者一致：
- 選了 'sorted' 卻忘記關 ENABLE_DELAY_DETECTION → 白白啟動用不到的東西
- 選了 '2014' 卻忘記開 ENABLE_DELAY_DETECTION → routing_2014 拿到 None，
  可能要等真的送 TCP 封包才會發現（fail silent，難查）

ALGORITHM_DEPENDENCIES 是單一事實來源：宣告「這個演算法需要哪些
self.app.<屬性名稱> 必須存在」。check_dependencies() 在啟動時比對，
不符合就直接讓程式炸掉（fail fast），不讓漏掉的東西悄悄溜過去。

兩層防護：
1. 查表本身用 `ALGORITHM_DEPENDENCIES[algorithm]`（不是 `.get(..., set())`）：
   忘記幫新演算法加依賴條目 → KeyError，啟動當下就炸
2. check_dependencies() 逐一檢查宣告的依賴是否真的被建出來（非 None）：
   依賴表寫對了、但沒有真的建立 → RuntimeError，一樣啟動當下就炸

已知會被這個檢查抓到的既有問題（寫這個檔案時意外發現）：
modules/routing_2014.py 呼叫 `self.app.get_link_delay_func`，但整個
DTM.py 沒有任何地方定義過這個屬性/方法——如果 ROUTING_ALGORITHM 曾經被
設成 '2014'，這裡的檢查會在啟動當下就報錯，而不是要等到真的送 TCP
封包才 AttributeError。這不是這個檔案造成的新問題，是既有問題被
提早攔截。

為什麼查 delay_detection / link_delay_measurement 而不是
link_delay / link_used_bw：routing_2014 / routing_auto_k_short 實際讀的是
self.app.link_delay / self.app.link_used_bw（資料本身），但這兩個 dict 在
DTM.py 是無條件初始化的（永遠不是 None，ENABLE_DELAY_DETECTION 關閉時
只是永遠是空的 {}），拿它們做「存不存在」的檢查測不出問題。真正反映
ENABLE_DELAY_DETECTION 狀態、會在關閉時變成 None 的，是
delay_detection / link_delay_measurement 這兩個物件本身——用它們當
「資料管線是否真的在運作」的代理指標。

── 第二部分：MONITOR_CONDITIONS（8 個背景執行緒該不該 spawn）──────────

逐一檢視過每個執行緒實際做的事，不是把舊的 if 條件原樣照抄：

- monitor／link_ready_watcher／flow_stats_monitor：無條件——分別是
  host 學習、拓撲穩定判斷、per-flow 診斷統計，全部跟 ROUTING_ALGORITHM
  無關，每種演算法都需要或都不影響，維持無條件不變。
- bandwidth_monitor：只看 ENABLE_BANDWIDTH_MEASUREMENT——link_status 是
  現行 5 個演算法（2020/dijkstra/self/sorted/sorted_link）都需要的
  Layer 2 資源，但「旗標關掉時該演算法用不到 link_status」已經由
  check_dependencies() 在啟動時攔截，這裡不用重複判斷演算法。
- monitor_dtm：只看 ROUTING_ALGORITHM in ('2020', 'dijkstra')——self／
  sorted／sorted_link 用自己的 cascade/權重圖機制觸發重路由，不靠這個
  執行緒的輪詢重路由，維持原條件不變。
- monitor_energy：ROUTING_ALGORITHM in ('self', 'sorted', 'sorted_link')
  ——**修正**：原條件漏了 sorted_link（架構跟 sorted 同源，理當同組，
  是已知缺口，見 CLAUDE.md／memory 記錄）。
- legacy_detector／legacy_dynamic_test：**收緊**——原本只看
  ENABLE_DELAY_DETECTION／ENABLE_ROUTING 單一旗標，現在改成同時要求
  ROUTING_ALGORITHM in ('2014', 'auto_k_short')。原因：這兩個執行緒只
  服務 2014／auto_k_short（見 modules/legacy_algorithm_support.py），
  只看旗標的話，旗標開著但演算法選別的時，會白白多跑一個永遠用不到的
  背景執行緒（legacy_dynamic_test 甚至是每次都會發生：對其餘 5 個現行
  演算法，這個執行緒 spawn 後睡 10 秒、兩個 if 都不成立、直接結束，
  等於平白多開一個 green thread 又立刻關掉）。

使用方式：
    from modules.startup_requirements import (
        check_dependencies, MonitorFlags, should_spawn_monitor,
    )
    check_dependencies(self, ROUTING_ALGORITHM)               # L2 資源檢查
    flags = MonitorFlags(ENABLE_ROUTING, ENABLE_DELAY_DETECTION,
                          ENABLE_BANDWIDTH_MEASUREMENT, ROUTING_ALGORITHM)
    if should_spawn_monitor('monitor_energy', flags):
        self.energy_monitor_thread = hub.spawn(self._monitor_energy)
"""

from collections import namedtuple

# ============================================================
# 第一部分：Layer 1 需要的 Layer 2 資源
# ============================================================

# {演算法字串（對應 ROUTING_ALGORITHM）: {需要的 self.app.<屬性名稱>, ...}}
#
# 只列「會被某個 ENABLE_* 旗標條件式建立、可能是 None」的東西。
# flow_stats 一律無條件建立、bandwidth_measurement 沒有任何 routing
# module 直接用到（只有 DTM.py 自己的 _bandwidth_monitor 拿它去更新
# link_status），兩者都不會漂移出問題，不放進表裡增加雜訊。
ALGORITHM_DEPENDENCIES = {
    '2014':         {'delay_detection', 'link_delay_measurement', 'get_link_delay_func'},
    '2020':         {'link_status'},
    'dijkstra':     {'link_status'},
    'self':         {'link_status'},
    'sorted':       {'link_status'},
    'sorted_link':  {'link_status'},
    'auto_k_short': {'delay_detection', 'link_delay_measurement'},
}


def check_dependencies(app, algorithm):
    """啟動時呼叫一次。algorithm 不在 ALGORITHM_DEPENDENCIES 裡 → KeyError
    （忘記幫新演算法加依賴條目）。依賴條目存在、但 self.app.<屬性> 是
    None（沒被建出來）→ RuntimeError（依賴表寫對了、沒真的建立）。"""
    needed = ALGORITHM_DEPENDENCIES[algorithm]
    missing = [feature for feature in needed if getattr(app, feature, None) is None]
    if missing:
        raise RuntimeError(
            "ROUTING_ALGORITHM='{}' 需要 {}，但沒有被建出來（檢查對應的 "
            "ENABLE_* 旗標是否開啟）".format(algorithm, missing)
        )


# ============================================================
# 第二部分：8 個背景執行緒（monitor）該不該 spawn
# ============================================================

MonitorFlags = namedtuple('MonitorFlags', [
    'enable_routing', 'enable_delay_detection', 'enable_bandwidth_measurement', 'routing_algorithm',
])

# {monitor 名稱: 條件 function(MonitorFlags) -> bool}
# 全部 8 個 hub.spawn 都透過這張表決定，即使條件是「永遠 True」也放進來，
# 讓這張表成為「誰會被 spawn」的單一事實來源，不會有漏看的散落 if。
MONITOR_CONDITIONS = {
    'monitor':             lambda f: True,
    'link_ready_watcher':  lambda f: True,
    'flow_stats_monitor':  lambda f: True,
    'bandwidth_monitor':   lambda f: f.enable_bandwidth_measurement,
    'monitor_dtm':         lambda f: f.routing_algorithm in ('2020', 'dijkstra'),
    'monitor_energy':      lambda f: f.routing_algorithm in ('self', 'sorted', 'sorted_link'),
    'legacy_detector':     lambda f: f.enable_delay_detection and f.routing_algorithm in ('2014', 'auto_k_short'),
    'legacy_dynamic_test': lambda f: f.enable_routing and f.routing_algorithm in ('2014', 'auto_k_short'),
}


def should_spawn_monitor(name, flags):
    """name 不在 MONITOR_CONDITIONS 裡 → KeyError（忘記幫新執行緒加條目，
    fail-fast，跟 check_dependencies 同一種紀律）。"""
    return MONITOR_CONDITIONS[name](flags)
