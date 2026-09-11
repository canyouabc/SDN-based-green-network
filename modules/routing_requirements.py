# -*- coding: utf-8 -*-
"""
routing_requirements.py — 契約層：Layer 1（routing 槽位佔用者）各自需要哪些
Layer 0 上建立的 Layer 2/其他資源，以及啟動時的存在性檢查。

跟 routing_base.py（介面形狀）、routing_host.py（app 該提供什麼）是同一類
東西——純資料宣告 + 一個純函式，從不被實例化、不持有跨時間狀態，不是
Layer 1 或 Layer 2 的成員，是描述它們之間該怎麼連的規則。

── 這個檔案解決的問題 ─────────────────────────────────────────────
DTM.py 用一批獨立的 ENABLE_* 旗標（ENABLE_DELAY_DETECTION、
ENABLE_BANDWIDTH_MEASUREMENT）決定要不要建立某些 Layer 2 模組，但這些
旗標**跟 ROUTING_ALGORITHM 各自獨立設定，沒有任何機制保證兩者一致**：
- 選了 'sorted' 卻忘記關 ENABLE_DELAY_DETECTION → 白白啟動用不到的東西
- 選了 '2014' 卻忘記開 ENABLE_DELAY_DETECTION → routing_2014 拿到 None，
  可能要等真的送 TCP 封包才會發現（fail silent，難查）

ALGORITHM_DEPENDENCIES 是單一事實來源：宣告「這個演算法需要哪些
self.app.<屬性名稱> 必須存在」。check_dependencies() 在啟動時比對，
不符合就直接讓程式炸掉（fail fast），不讓漏掉的東西悄悄溜過去。

── 兩層防護 ────────────────────────────────────────────────────
1. 查表本身用 `ALGORITHM_DEPENDENCIES[algorithm]`（不是 `.get(..., set())`）：
   忘記幫新演算法加依賴條目 → KeyError，啟動當下就炸
2. check_dependencies() 逐一檢查宣告的依賴是否真的被建出來（非 None）：
   依賴表寫對了、但沒有真的建立 → RuntimeError，一樣啟動當下就炸

── 已知會被這個檢查抓到的既有問題（寫這個檔案時意外發現）───────────
modules/routing_2014.py 呼叫 `self.app.get_link_delay_func`，但整個
DTM.py 沒有任何地方定義過這個屬性/方法——如果 ROUTING_ALGORITHM 曾經被
設成 '2014'，這裡的檢查會在啟動當下就報錯，而不是要等到真的送 TCP
封包才 AttributeError。這不是這個檔案造成的新問題，是既有問題被
提早攔截。

── 為什麼查 delay_detection / link_delay_measurement 而不是
   link_delay / link_used_bw ────────────────────────────────────
routing_2014 / routing_auto_k_short 實際讀的是 self.app.link_delay /
self.app.link_used_bw（資料本身），但這兩個 dict 在 DTM.py 是**無條件
初始化**的（永遠不是 None，ENABLE_DELAY_DETECTION 關閉時只是永遠是空的
{}），拿它們做「存不存在」的檢查測不出問題。真正反映
ENABLE_DELAY_DETECTION 狀態、會在關閉時變成 None 的，是
delay_detection / link_delay_measurement 這兩個物件本身——用它們當
「資料管線是否真的在運作」的代理指標。
"""

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
