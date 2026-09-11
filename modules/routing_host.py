# -*- coding: utf-8 -*-
"""
routing_host.py — Layer 0 ↔ Layer 1 的介面契約

繼承 `RoutingBase` 的路由模組（Layer 1：routing_DTM_2020 / dijkstra / self /
sorted / sorted_link）在程式裡透過 `self.app.<成員>` 存取 Layer 0。這個 `app`
啟動時由 Layer 0 塞進來：`DTM.py` 跑就是 `ProjectController`、`sim.py` 跑就是
`MockApp`。

這個檔案把「app 必須提供什麼」寫成一份 `typing.Protocol`。

── 這個檔案「不做」什麼 ────────────────────────────────────────────
- 不參與執行期的對接。實際對接跟現在完全一樣（`routing_module(self)` →
  模組內 `self.app = app` → duck typing 直接用）。
- 執行期零影響。`typing.Protocol` 不會在 runtime 檢查任何東西。
- 執行期其實**沒有任何地方 import 這個檔案**（`routing_base.py` 只在
  `TYPE_CHECKING` 區塊引用它）。這裡刻意寫成連舊 Python（3.6+）也能 import，
  純粹是為了「手動 import 檢查語法」與衛生。
- Layer 0 / MockApp 不需要 `class X(RoutingHost)` 去繼承它（結構式定型：
  物件剛好有全部成員就算數）。

── 這個檔案「做」什麼 ──────────────────────────────────────────────
- 是這道接縫的單一權威文件：要知道 Layer 1 需要 Layer 0 給什麼，看這裡。
- 接上型別檢查器（pyright / mypy / VS Code 的 Pylance）後，新增
  `self.app.<新東西>` 卻忘了在某個 Layer 0 實作時，會被靜態指出。
- 寫新的 Layer 0 變體時，這是「要實作這些」的 checklist。

參考：CLAUDE.md「分層架構」節。
"""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

try:                                  # Python 3.8+
    from typing import Protocol
except ImportError:                   # 舊 Python
    try:
        from typing_extensions import Protocol  # type: ignore
    except ImportError:               # 最後退路：這個檔案執行期用不到，object 就夠
        Protocol = object             # type: ignore

if TYPE_CHECKING:                     # 只給型別檢查器看，執行期不 import，避免循環
    from .link_status import Link_Status


# path：一律是 switch dpid 的序列，例如 [1, 4, 7]
Path = List[int]
# (src_mac, dst_mac, path)
ActiveFlow = Tuple[str, str, "Path"]


class RoutingHost(Protocol):
    """所有繼承 `RoutingBase` 的路由模組都依賴這組成員。
    `DTM.py::ProjectController` 和 `sim.py::MockApp` 都必須滿足。"""

    # ── 拓撲（啟動時建好，執行期不變）────────────────────────────
    myswitches: List[int]
    """所有 switch 的 dpid 列表。"""

    adjacency: Any
    """`adjacency[dpid_a][dpid_b]` → 連通則 truthy、不連通則 None
    （型別是 `defaultdict(lambda: defaultdict(lambda: None))`）。

    ⚠️ 「值」的語意兩個 Layer 0 不一致，Layer 1 **只可以**拿它判連通性
       （`is not None` / `dpid_b in adjacency[dpid_a]`），不可依賴值本身：
       - `DTM.py`：值是 dpid_a 通往 dpid_b 的實體 out_port 號
       - `MockApp`：值是鄰居 dpid（dummy 佔位，sim 不裝真流表所以不需要真 port）
       真正需要 port 的只有各 Layer 0 自己的 `build_path_with_ports()`。"""

    host_macs: Dict[str, Tuple[int, int]]
    """`{mac: (dpid, port)}`。"""

    # ── 能耗 / 頻寬資料（啟動時從 data/<topo>/*.txt 載入）──────────
    link_bw: Dict[Tuple[int, int], float]
    """`{(u, v): Mbps}`，雙向都存（同時有 (u,v) 和 (v,u)）。"""

    link_energy: Dict[Tuple[int, int], float]
    """`{(u, v): 瓦特}`，雙向都存。選路邏輯不查它，只有事後算節能報表用
    （`sorted_link` 的候選排序是唯一例外，會查 link_energy 當邊際成本）。"""

    switch_energy: Dict[int, float]
    """`{dpid: 瓦特}`。"""

    # ── 連線狀態模組（Layer 2，由 Layer 0 實例化，這裡借參照）────
    link_status: "Link_Status"
    """`Link_Status` 物件。路由模組呼叫 `.get_all_link_status()` /
    `.count_links_by_status()` 等。"""

    # ── active flow 狀態 ────────────────────────────────────────
    def get_active_flows(self):
        # type: () -> List[ActiveFlow]
        """回傳 `[(src_mac, dst_mac, path), ...]`，path 是 dpid 序列。"""
        ...

    def add_active_flow(self, host_a, host_b, path, is_reroute=False, priority=None):
        # type: (str, str, Path, bool, Optional[int]) -> None
        ...

    def remove_active_flow(self, host_a, host_b, path=None, hard_timeout=None):
        # type: (str, str, Optional[Path], Optional[float]) -> None
        ...

    # ── 流表操作 ────────────────────────────────────────────────
    def install_flows_for_path(self, path, src_mac, dst_mac, priority,
                               hard_timeout=0, idle_timeout=0):
        # type: (Any, str, str, int, int, int) -> None
        """DTM.py 下發 OpenFlow rule；MockApp 是 no-op。
        `priority` 契約上「必給」：MockApp 有預設值 1，當它不存在。"""
        ...

    def build_path_with_ports(self, switch_path, src_mac, dst_mac):
        # type: (Path, str, str) -> Any
        """把 dpid 序列轉成帶 port 的 path。
        - `DTM.py`：回傳 `[(dpid, in_port, out_port), ...]`，查不到 port 回 `None`
        - `MockApp`：原樣回傳 `switch_path`（sim 不需要 port）
        Layer 1 只判斷回傳是不是 `None`。"""
        ...

    def _get_next_flow_priority(self, src_mac, dst_mac):
        # type: (str, str) -> int
        """同一 pair 每次安裝新路徑就 +1（只增不減，見 DTM.py 的說明）。
        MockApp 固定回 1。"""
        ...


class RoutingHostDelay(RoutingHost, Protocol):
    """`routing_2014`（被動式最短路徑，延遲為權重）額外需要的成員。
    只有 `DTM.py` 提供；`MockApp` 沒有 → `routing_2014` 無法在 sim 跑。
    `routing_2014` 凍結時，這整個 class 可以直接刪。"""

    link_delay: Dict[Tuple[int, int], float]
    """`{(u, v): 毫秒}`，由 LLDP / echo 延遲探測填。"""

    link_used_bw: Dict[Tuple[int, int], float]
    """`{(u, v): 已用 Mbps}`。"""

    get_link_delay_func: Callable
    """查詢 link 延遲的 callable，傳給 `pure_Dijkstra.get_min_delay_path()`。"""


# ── 可選成員：不放進上面的 Protocol ──────────────────────────────
#
# _flow_sizes: Dict[Tuple[str, str], float]
#     `{(src_mac, dst_mac): Mbps}`。**只有 MockApp 有**（sim 的合成流量大小）。
#     `routing_DTM_sorted` / `sorted_link` 用
#     `getattr(self.app, '_flow_sizes', {})` 防禦性取用：DTM.py 沒有時回 {}，
#     DANGER 前瞻檢查自動停用。因為是 optional，不列入 required 契約。
