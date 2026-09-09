# 專案說明（CLAUDE.md）

## ⚠️ 開啟專案提示清單

每次開啟此專案時，請確認以下事項：

- [ ] **priority counter 暴力解**：`DTM.py` 的 `_get_next_flow_priority()` 採用只增不減策略，
      根本解法應追蹤並主動刪除舊 flow 規則（目前靠 `idle_timeout=5` 自然過期）

- [ ] **`[TOPO_READY]` 已棄用**：watchdog 改為等待 `[LINK_READY]`（由 `DTM.py` 的
      `_link_ready_watcher` 每 2 秒輪詢 switch/link 數量穩定後發出）。
      `[TOPO_READY]` 舊機制仍存在於 DTM.py 中，但 watchdog 不再依賴它。

- [ ] **`cap_topo.py` 尚未完整驗證**：新版校園拓撲（45 switch、27 host）已套用
      `controller-rate-limit`，但實際實驗結果仍需持續觀察連線正確性。

- [ ] **切換拓撲時記得同步 `data/`（僅限 Mininet／`DTM.py`）**：`sim.py` 已改為
      依 `--topo` 自動讀取 `data/grid/`／`data/cap/`（見下方 sim.py 說明），不受此限制。
      但 **Mininet 實驗（`DTM.py`）仍讀扁平的 `data/k_short.txt`、`k_short_dist.txt`、
      `link_bw.txt`、`switch_energy.txt`**，切換拓撲時仍需手動複製對應版本蓋過去。
      `animate_activeflow.py` 頂部的 `TOPO` 旗子也需一併切換（`'cap'` 或 `'grid'`）。

- [ ] **`miss_send_len=128` 限制**：`DTM.py` 的 table-miss 與 ARP rule 都只把封包前 128 bytes 送到 controller。
      目前夠用（我們只讀 Ethernet/IP/TCP/UDP header，最多 ~54 bytes），
      但若未來需要讀取 payload（如深度封包檢測、應用層識別）或其他更深層 header，
      需改回 `OFPCML_NO_BUFFER`（送完整封包）。
      有 controller-rate-limit 保護的情況下，改回 NO_BUFFER 的頻寬代價可接受（100 pkt/s × 1500 bytes ≈ 150 KB/s）。

- [ ] **OVS `controller-rate-limit` 數值待觀察**：已驗證有效（OVS 2.13.8）。
      **正確語法**（欄位在 Controller table，不是 Bridge table）：
      ```
      ovs-vsctl set controller <sw_name> controller-rate-limit=100 controller-burst-limit=25
      ```
      驗證是否寫入：
      ```
      ovs-vsctl get controller <sw_name> controller-rate-limit controller-burst-limit
      ```
      錯誤語法（無效，勿用）：
      - `set bridge ... controller-rate-limit` → 報錯，欄位不存在
      - `set bridge ... other-config:controller-rate-limit` → 寫入但 OVS 不讀
      最小值限制：rate 最低 100、burst 最低 25（低於此值報 constraint violation）。
      `cap_topo.py` 已套用 rate=100 burst=25，為 OVS 2.13.8 可設的最低值。
      `grid_topo.py` **尚未**套用此設定。

- [ ] **`routing_DTM_self.py` cascade 已知問題（待根本解）**：
      - `_ns_only_mode` 與 `_cascade_depth` 若 cascade 過程中拋出例外，不會自動還原，
        導致後續所有 cascade 行為損壞。目前僅在 `admit_flow` / `on_flow_removed`
        進入點加 `[CASCADE_WARN]` log 偵測，根本解應加 `try/finally` 保護。
      - 新 flow 的 cascade 在 `add_active_flow` 之前執行，其他 flow 重算時的
        `_build_active_switches` 不含新 flow 的 switch，屬設計取捨，非 crash 類 bug。
      - `select_path` 舊路徑（`ENABLE_NEW_ALGO=False` 分支）為死碼，
        若未來有人把旗子改成 False，Step 0 的暫時 +1 可能造成雙重計數。

- [ ] **DANGER 狀態（>100% 鏈路使用率）**：已新增至 `link_status.py`。
      行為與 OVERLOAD 完全一致（選路排除、LINK 觸發器主動重路由、HIGH_LOAD 觸發器跳過）。
      三個路由模組（self / 2020 / dijkstra）與 `DTM.py` 均已同步更新。

- [ ] **`routing_DTM_sorted.py` 使用 `weight_map`（動態）**：Phase 2 打分改為動態權重圖。
      每次 admit/cascade 開始前，掃描當前所有 active flows，將每條 flow 的全局最短 hop switch 集合
      （來自 `k_short_dist`）貢獻 +1，反映「多少條 flow 的最短路徑集合覆蓋此 switch」。
      `ENABLE_WEIGHT_MAP` 旗子可開關此功能（`False` 時並列候選直接 random 選，
      已修正過去 `False` 時誤走 `candidates[0]` 固定選第一個、從未真正 random 的 bug）。
      `routing_DTM_self.py` 也同步加入相同語義的 `weight_map`，供動畫顯示使用。

- [ ] **`routing_DTM_sorted.py` 三個可切換旗標**（皆為模組頂部常數，改了要重跑）：
      - `SORT_MODE`：五選一，決定 flow 處理順序（優先度最高排最前面）
        - `'LPF'`（現行／預設）：依理論最短 hop 由大到小（對應 SGH 的 Shortest Path Last）
        - `'SPF'`：依理論最短 hop 由小到大（Shortest Path First）
        - `'HDF'`：依 flow 已知頻寬（`_get_flow_bw`）由大到小（Highest Demand First）
        - `'SDF'`：依 flow 已知頻寬由小到大（Smallest Demand First）
        - `'DENSITY'`：依 flow 的最小路徑集合在 `weight_map` 上的平均權重排序，
          擁擠密度越高越優先，跟 hop 數無關（本研究提出，非 SGH 原始四種之一）
        - `SPF`／`HDF`／`SDF` 對應 SGH 論文（`docs` 提到的 2014 論文）原始的四種排序條件，
          跟現行 `LPF` 湊成完整四種；`HDF`／`SDF` 依賴 `_get_flow_bw`，
          只在 `sim.py`（`_flow_sizes` 已知）時排序才有意義——`DTM.py` 沒有這個屬性，
          所有 flow 的排序 key 都會是 0，等同沒排序（不會噴錯，但沒有實質效果）
      - `WEIGHT_MODE`：`'STATIC'`（`weight_map` 整輪處理期間固定不變，現行／預設）
        或 `'DECAY'`（每條 flow 選路完成後，扣除該 flow 對 `weight_map` 的貢獻，
        讓還沒處理的 flow 看到「已解決」的 flow 不再算進擁擠度）
      - `LOAD_CHECK_MODE`：`'INCREMENTAL'`（現行／預設，見下方 DANGER 前瞻檢查說明）
        或 `'LIVE'`（每次檢查都重新掃一次 `active_flows` 現算，較簡單但較耗運算）

- [ ] **`routing_DTM_sorted.py` DANGER 前瞻檢查（`_would_exceed_danger`）**：
      因為 `sim.py` 的流量 BW 是模擬時已知的合成值，`Simulator.admit()` 呼叫 `admit_flow` 前
      會先把 BW 存進 `self.app._flow_sizes[(src,dst)]`（[sim.py:611](sim.py:611)），
      路由模組透過 `_get_flow_bw` 讀取（`getattr(self.app, '_flow_sizes', {})`），
      在 Phase 1 候選路徑篩選時多一層檢查：「加入這條 flow 的已知 BW 後，
      是否會把路徑上某段 link 推過 100%（DANGER）」，會的話排除該候選（現有 OVERLOAD 排除不受影響）。
      - **只在 `sim.py` 生效**：`DTM.py` 的 `ProjectController` 沒有 `_flow_sizes`，
        `getattr` 保底回傳 0，等同不啟用，跟改動前行為完全一致。
      - **負載來源不依賴 `link_status` 的更新時機**：`LOAD_CHECK_MODE='INCREMENTAL'`（預設）
        由路由模組自己維護 `self.link_load`（Mbps），在每次 admit/cascade 開始前用
        `_build_link_load` 從 active_flows 重建一次，之後隨每條 flow 的選路結果即時
        `_add_link_load`／`_remove_link_load` 增減——這樣同一輪 cascade 內連續處理多條
        flow 時，後面的 flow 才看得到前面的 flow 剛加上去的負載，不會因為
        `link_status` 用 `--link-update periodic`（預設每秒才更新一次）而漏看。
      - **仍會保留無法避免的 DANGER（設計取捨）**：若某條 flow 的所有 k-short 候選路徑
        都會導致 DANGER，一律 fallback 選一條裝上去（優先「流量有路可走」而非「拒絕新增」），
        並印出 `[DANGER_UNAVOIDABLE] {src} -> {dst}: ...`，可搜尋此關鍵字確認 log 裡的
        DANGER 是否為真實無解的擁塞情境，而非檢查邏輯漏掉。`parse_log.py` 會統計每個
        batch 的 `[DANGER_UNAVOIDABLE]` 次數（`danger_unavoidable_count` 欄位），
        `matplotlib_DTM.py` 的彙總表也會一併顯示。

- [ ] **`sweep_sorted.py`：批次比較 `routing_DTM_sorted.py` 多組設定**：對同一份 seed，
      依序套用 `COMBOS` 清單裡的每組設定（`SORT_MODE`／`WEIGHT_MODE`／`LOAD_CHECK_MODE`／
      `ENABLE_WEIGHT_MAP` 任意組合），各自跑完整個 `sim → parse_log → matplotlib_DTM`
      流程，最後把所有組合的逐 batch 結果（含 AVERAGE）疊成一份 `sweep_comparison.csv`。
      - **`COMBOS` 只需寫要覆蓋的欄位**，其餘旗標一律重置回 `BASELINE`（不是沿用上一組
        combo 跑完的殘留值），確保每組互相獨立、可重現；標記在結果裡的也是**完整解析後
        的設定**（`resolved`），不是 combo 字典本身寫了什麼。
      - **每個 batch 都要重新建一個 `Simulator`**（比照原本 `sim.py` CLI 的寫法）。
        曾經寫成整個 combo 共用一個 `Simulator`，導致 `flow_history_count` 等 HISTORY
        計數器跨 batch 累加（batch2 顯示的其實是 batch1+batch2 的加總），已修正。
      - **`_AppendTee`**：把 stdout（`[DANGER_UNAVOIDABLE]` 等 `print()` 訊息）跟
        `Simulator._log()`（`BATCH`/`ENERGY`/`HISTORY` 行）合併寫進同一份 log，
        才能讓 `parse_log.py` 一次讀到全部。**必須用 append（`'a'`）模式持續開檔**，
        不能用 `sim._Tee` 的 `'w'`（截斷）模式，否則兩邊各自開檔寫入同一個檔案會互相
        打架、漏字。
      - **沒有固定 `random.seed`**：並列候選的 `random.choice` 沒有播種，同一組設定
        重跑可能得到不同結果（曾經誤判為「SPF 演算法有 bug」，後來確認是這個原因）。
        這是刻意保留的設計（隨機並列候選本來就是 SGH 類演算法的一部分），不是待修的錯誤。
      - 每組 combo 的細節存在 `log/sweep-{name}-{timestamp}/`（`run.log`／
        `experiment.csv`／`energy_saving_summary.csv`，可選擇是否連 `batch_N.png` 都出）。

- [ ] **GEANT 拓撲與 SNDlib 真實流量整合**（`geant_topo.py`／`data/geant/`／`data/geant_31/`）：
      新增 22 switch、22 host、36 條鏈路的 GEANT 拓撲（比照 grid/cap 慣例，host=switch 一對一），
      節點 dpid 依 `geant_topo.py` 的 `NODE_NAMES` 順序（`at1.at`=1 … `uk1.uk`=22）。
      - `data/geant/`：鏈路容量從真實 40000 Mbps 縮小為 1000 Mbps（Mininet TCLink 上限），
        switch／link 能耗沿用專案既有慣例（146W／0.18W，比例 ≈811:1）。
      - `data/geant_31/`：能耗改用下面「論文」自己的比例 3:1（switch=3, link=1），
        `k_short.txt`／`k_short_dist.txt` 跟 `data/geant/` **完全共用**（flat 能耗值下，
        Yen's k-shortest 排序只跟 hop 數有關，不受 switch:link 絕對比例影響，兩者結果必然相同）。
      - `k_short.txt`／`k_short_dist.txt` 是**離線產生**的，不需要真的開 Mininet：
        `Auto_routing_k_short` 只依賴 `adjacency`／`link_bw`／`link_energy`／`switch_energy`／
        `host_macs` 這些純 Python 資料結構，跟 `sim.py` 的 `MockApp` 建圖方式相同，
        `host_macs` 手動組（1 host 對 1 switch，port 號不影響結果，`k_short.txt` 也沒有寫入 port 資訊）。
      - `sim.py` 的 `_TOPO_FILES` 已新增 `'geant'`／`'geant_31'` 兩個 key，`--topo geant` 可直接用。

- [ ] **GEANT 15-分鐘真實流量轉換**（`gen_geant_seed.py`）：把 SNDlib 的 GEANT dynamic trace
      （11460 個 15-分鐘 demand matrix，4 個月）轉成 `sim.py` seed json。一個 15-分鐘 snapshot
      = 一個獨立 batch，snapshot 內每個非零 OD demand = 一條聚合巨流（`interval=0`，
      `flow_duration=900` 撐滿整個視窗）——因為原始資料本身就是視窗內的平均聚合值，視窗內
      個別 flow 的到達順序/起伏/存活時間都不可考，不去憑空捏造。
      - demand 數值統一乘上 `1/40` 縮放（對應鏈路容量從 40000→1000 Mbps 的縮放比例）。
      - 分類規則（一般化、不寫死日期）：`EMPTY`（`num_flows==0`，687 筆）排除；
        `ANOMALY_SPIKE`（`total_demand_mbps > 150000`，12 筆，含 readme 已知的 `20050527-1745`
        bug，跟一組先前未被 readme 記載的 `20050627-1200~1445` 異常尖峰）排除；
        `NEAR_EMPTY`（1~99 flows，4 筆）／`NORMAL`（其餘 10765 筆）保留。
      - **已驗證的事實**：整份資料裡完全沒有任何一筆 `num_flows` 剛好等於 212（100~369 之間
        是空白帶，一個檔案都沒有），但 98（`20050628-1630`）跟 449（`20050505-1415`／
        `20050627-1045`）都精確吻合——這幾個數字來自論文 *Assefa & Ozkasap, "Link Utility
        and Traffic Aware Energy Saving in SDN", BlackSeaCom 2017* Section V 宣稱的
        low/medium/high 流量情境（20%/50%/80% of capacity = 98/212/449 flows），該論文確實
        引用同一份 SNDlib GEANT trace，但「212」這個數字目前對不上真實資料。

- [ ] **GEANT 隨機流量產生器**（`gen_geant_random_seed.py`）：跟上面同一種「固定 flow 數、
      全部 `interval=0`、撐滿 900 秒」建模方式，但改成隨機取不重複 host pair
      （`random.sample`）、隨機頻寬（預設 0.1~20 Mbps）。用來測試「flow 數（=host 覆蓋率）
      本身」對節能效果的影響，不受真實資料的特定分布限制。

- [ ] **極簡模式批次執行**（`run_geant_seed.py`）：仿 `sweep_sorted.py` 的 `run_one_combo`，
      直接 instantiate `sim.Simulator` 逐 batch 跑，**不經過 `sim.py` 的 CLI 路徑**（那條路徑
      才會產生 snapshot trace 跟背景動畫——單一 batch 就能生出 11MB 的 snapshot 檔，跑滿 4
      個月會撐爆到 ~120GB，完全不適合大量 batch 的統計分析用途）。預設 `KEEP_RAW_LOG=False`，
      `parse_log.py` 轉完 csv 就把中繼 `experiment.log` 刪掉，只留 `experiment.csv`／
      `energy_saving_summary.csv`。

- [ ] **GEANT 拓撲下的節能上限問題（重要發現，非 bug）**：22 節點、host=switch 一對一的模型下，
      只要有夠多節點被牽涉到流量（哪怕只當端點、不當轉發），對應 switch 就無法睡眠。實測：
      連論文宣稱的「low traffic」情境（98 flows）在真實資料裡都是 **22/22 節點全覆蓋**，
      switch 層級節能空間從一開始就被封頂在 0；隨機流量測試也證實 **flow 數從 10 加到 40，
      節能百分比從 ~30% 崩到 ~1%**，是斷崖式下降，不是線性遞減。這代表這類「switch/link
      睡眠」節能路由演算法，比較適合節點多、host 只佔邊緣層、有明顯核心/邊緣分層的拓撲
      （校園網路、資料中心），不適合像 GEANT 這種小節點數、流量密集覆蓋所有節點的骨幹網路。

- [ ] **能耗比例（switch:link）大幅影響節能結果，論文用 3:1，專案原本用 811:1**：專案既有
      `switch_energy`／`link_energy` 慣例是 146W／0.18W（≈811:1，來源不明，`docs/`／
      `CLAUDE.md` 都沒有註明出處），但上述論文 Section III 的節能公式直接把 switch 設為 3、
      link 設為 1。兩種比例下**路徑選擇完全相同**（`routing_DTM_sorted.py` 的選路邏輯完全
      沒有查詢過 `link_energy`／`switch_energy`，只在 `calculate_energy_saving()` 事後算報表
      時才用到），但**算出來的節能百分比天差地遠**。`data/geant_31/` 就是為了比對這個落差
      另外建的 3:1 版本，兩者的 `k_short` 系列檔案共用（見上）。

- [ ] **`routing_DTM_sorted_link.py`（新演算法：link 能耗也納入邊際成本比較）**：複製自
      `routing_DTM_sorted.py`，唯一差異在 `_run_phase1` 的候選排序邏輯——原版只算「新增幾個
      switch」（`inactive_counter`，單純計數，不看 link）；這版改成「新增能耗」（新開的 switch
      能耗總和 + 新開的 link 能耗總和，用真正的 `switch_energy`／`link_energy` 加權），一樣
      跨所有 hop 層攤平比較選全域最小值（沿用原版 `_run_phase1` 本來就有的「跨 hop 層比較
      inactive switch 數」架構，只是把比較的量從單純計數換成真正的能耗值，並多算 link 這個
      維度）。需要新維護一個 `active_links`（比照既有 `active_sw` 的維護方式，在
      `admit_flow`／`_cascade` 裡同步更新）。
      - 已註冊進 `sim.py`（`--algorithm sorted_link`）與 `sweep_sorted.py`
        （`ALGORITHM='sorted_link'` 時，`run_one_combo` 會動態 import
        `modules.routing_DTM_sorted_link` 而不是 `modules.routing_DTM_sorted`，
        COMBOS 的設定才套得到正確的模組身上）。
      - 811:1 下 `sorted` 跟 `sorted_link` 結果幾乎沒差（link 能耗占比太小，改了也比不出高下）；
        **3:1 下有實質、全面性的提升**（隨機 30-flow×10 組，`sorted` 12.35%→`sorted_link`
        15.88%，10 組沒有一組變差）。3:1、10-flow 情境下 `sorted_link` 的節能範圍
        （36.9%~40.4%）已經直接落在論文宣稱的 low-traffic 38~44% 區間內。

---

## 專案目的

節能路由實驗與論文實作。基於 Ryu SDN 控制器，在 Mininet 模擬環境中比較不同路由演算法的節能效果。

目前以 `routing_DTM_sorted.py`（SGH + 最小路徑權重圖）為主線，準備校內口試初稿。

### 論文第三章架構（初稿）

**3.1 SGH**：介紹 SGH（2014 論文）、4種排序條件（SPF/LPF/SDF/HDF）、選路流程、research gap（並列候選未定義）

**3.2 最小路徑集合**：本研究提出，定義為特定 src→dst 在全局最短 hop 數下，所有可能路徑經過的 switch 聯集（$\mathcal{S}(s,d)$）

**3.3 最小路徑權重圖**：將 3.2 延伸至所有 active flows，每個 switch 的權重 $W(v)$ 為被幾條 active flow 的最小路徑集合覆蓋的計數（動態，每次 admit/cascade 重算）

**3.4 SGH 與最小路徑權重圖的結合**：並列候選時選 $p^* = \arg\max_{p \in \mathcal{C}} \sum_{v \in p} W(v)$，Pseudocode 待與教授討論

---

## 目錄結構

```
Dijkstra/
├── DTM.py                  # 主控制器（Ryu app）
├── cap_topo.py             # 校園網路拓撲（45 switch，27 host）← 目前主力
├── new_topo.py             # 校園網路拓撲（舊版，保留備用）
├── grid_topo.py            # 5×5 Grid 拓撲（16 hosts，h1–h16）
├── watchdog_new.py         # 批次實驗自動化腳本
├── animate_activeflow.py   # 從 activeflow log 產出 HTML 動畫（支援 grid / cap）
├── parse_log.py            # 將 experiment.log 匯出為 CSV（含 danger_unavoidable_count 統計，函式可被 import）
├── matplotlib_DTM.py       # analyze() 函式：CSV → 圖表 + energy_saving_summary.csv（含 AVERAGE 那一列）
├── sim.py                  # 純路由模擬器（不依賴 Ryu/Mininet）← 目前主要模擬方式
├── gen_seed.py             # 產生 sim.py 用的種子檔（seed_*.json）
├── animate_sim.py          # 從 sim.py 的 snap 檔產出 HTML 動畫
├── sweep_sorted.py         # 批次比較 routing_DTM_sorted.py 多組設定 → sweep_comparison.csv
├── experiment.log          # 實驗記錄
├── experiment.csv          # 匯出的 CSV
├── sweep_comparison.csv    # sweep_sorted.py 產出的多組設定比較彙總表
├── modules/                # 路由與量測模組
│   ├── routing_base.py
│   ├── routing_2014.py
│   ├── routing_DTM_2020.py
│   ├── routing_DTM_dijkstra.py
│   ├── routing_DTM_self.py     # 2020 延伸，遞迴 cascade（過渡版本，已知有 cascade 失控問題）
│   ├── routing_DTM_sorted.py   ← 目前論文主線（SGH 排序 + 最小路徑權重圖）
│   ├── routing_auto_k_short.py
│   ├── link_status.py          ← 鏈路狀態（SN/LOW/NORMAL/HIGH/OVERLOAD/DANGER）
│   ├── bandwidth_measurement.py
│   ├── delay_detection.py
│   └── link_delay_measurement.py
├── data/                   # 預計算資料
│   ├── k_short.txt             # 扁平版本，供 Mininet（DTM.py）使用，需手動同步對應拓撲
│   ├── k_short_dist.txt        # 各 hop 群的 switch 集合（扁平版本，同上）
│   ├── base_weight_map.txt     # DTM-Self 拓撲天生偏好權重（首次執行自動生成，扁平版本）
│   ├── link_bw.txt
│   ├── link_energy.txt
│   ├── switch_energy.txt
│   ├── grid/                   # sim.py --topo grid 專用資料（k_short/k_short_dist/link_bw/link_energy/switch_energy/base_weight_map）
│   └── cap/                    # sim.py --topo cap  專用資料（同上，45 switch 校園拓撲）
├── log/                    # 實驗執行後產生
│   ├── DTM-2026-*.txt          # Ryu 完整 log
│   ├── activeflow-2026-*.txt   # 整理後的 activeflow log（動畫來源）
│   ├── anim-2026-*.html        # HTML 動畫（用瀏覽器開）
│   ├── anim-2026-*.log         # 動畫產出的 stdout/stderr（錯誤診斷用）
│   ├── mininet-2026-*.txt      # Mininet log
│   ├── bw.log                  # 頻寬監控即時 log（每批覆寫）
│   ├── cascade_debug.log       # cascade 詳細 debug log（每批覆寫）
│   ├── sim-{topo}-{seed}-{algorithm}-{timestamp}/   # sim.py 每次執行的輸出資料夾
│   │   ├── run.log             # 完整 stdout
│   │   ├── b{batch_id}-snap.txt    # [SIM_SNAPSHOT] JSON 快照（動畫來源）
│   │   └── b{batch_id}-anim.html   # animate_sim.py 產出的動畫
│   └── sweep-{name}-{timestamp}/    # sweep_sorted.py 每組 combo 的輸出資料夾
│       ├── experiment.log      # BATCH/ENERGY/HISTORY + [DANGER_UNAVOIDABLE] 合併寫入同一份
│       ├── experiment.csv      # parse_log.py 產出
│       └── energy_saving_summary.csv   # matplotlib_DTM.analyze() 產出（含 AVERAGE）
└── docs/
    ├── routing_DTM_self.md         ← DTM-Self 演算法設計文件
    ├── routing_DTM_2020.md         ← 2020 k-short 演算法設計文件
    └── routing_DTM_dijkstra.md     ← Dijkstra 雙模式演算法設計文件
```

---

## 啟動方式

### 純模擬模式（sim.py）← 目前主要模擬方式

不依賴 Ryu / Mininet，純 Python 直接呼叫路由模組計算路徑與能耗，跑得快，適合大量批次實驗。
Link status 由「active flow × 流量大小 × 路徑」直接算出，不像 Mininet 版本需要真的量測封包。

```bash
python3 sim.py --seed seed_1.json --algorithm sorted --topo grid
```

| 參數 | 說明 |
|------|------|
| `--seed` | 種子檔路徑（`seed_*.json`），由 `gen_seed.py` 產生；不指定則跑內建的 3 條流量 demo（30 秒） |
| `--batch` | 只跑種子檔中指定的 `batch_id`（不指定則跑全部 batch） |
| `--algorithm` | `self` / `2020` / `dijkstra` / `sorted`（同 `DTM.py` 的 `ROUTING_ALGORITHM`，缺 `2014`／`auto_k_short`），預設依檔案頂部 `ROUTING_ALGORITHM` |
| `--topo` | `grid` / `cap`，預設依檔案頂部 `TOPO` |
| `--link-update` | `realtime`（每次 admit/depart 即時更新 link load）或整數秒數（週期更新），預設依檔案頂部 `LINK_LOAD_UPDATE` |
| `--trace` | 開啟逐步追蹤模式，每條 flow 產生 4 幀快照（除錯用） |

輸出至 `log/sim-{topo}-{seed}-{algorithm}-{timestamp}/`，每個 batch 各自一份 `run.log`／`b{batch_id}-snap.txt`／`b{batch_id}-anim.html`（動畫在背景產出，不阻塞 terminal）。

`--topo grid`／`--topo cap` 會自動讀取對應的 `data/grid/`／`data/cap/` 子資料夾（k_short/k_short_dist/link_bw/link_energy/switch_energy/base_weight_map），**不需要**再手動同步或覆蓋扁平的 `data/*.txt`。扁平版本只給 Mininet（`DTM.py`）用，兩者互不影響。

### 單次實驗（Mininet）
```bash
ryu-manager DTM.py --observe-links
sudo python cap_topo.py        # 或 grid_topo.py
```

### 批次實驗（Mininet）
```bash
sudo python3 watchdog_new.py
```

watchdog 每批實驗流程：
1. 等待 Ryu `[LINK_READY]`（switch/link 數量穩定）後才送 sendarp
2. 等待 ARP 完成、iperf server 啟動、link status 就緒後開始流量
3. 實驗結束後整理 `log/activeflow-2026-*.txt`
4. **背景**產出 `log/anim-2026-*.html` 動畫（與 cleanup 並行）
5. cleanup tmux → cleanup mininet

### 重新產生 k_short.txt
將 `DTM.py` 的 `ROUTING_ALGORITHM` 改為 `'auto_k_short'`，開啟對應 topo 即自動計算並輸出。

---

## 路由演算法

| 模組 | 說明 |
|------|------|
| `routing_2014.py` | 舊版基準演算法，不再主動維護 |
| `routing_DTM_2020.py` | DTM 主要參考演算法（2020） |
| `routing_DTM_dijkstra.py` | 純 Dijkstra 為底，加入額外功能改造 |
| `routing_DTM_self.py` | 2020 延伸，兩階段選路 + 非最短 hop 清單 + 遞迴 cascade（過渡版本） |
| `routing_DTM_sorted.py` | **目前論文主線**：flow 依 `SORT_MODE`（`LPF`／`SPF`／`HDF`／`SDF`／`DENSITY`）排序後單一 pass 選路，`ENABLE_WEIGHT_MAP` 切換「純 SGH（並列 random）」與「SGH + 最小路徑權重圖」，`WEIGHT_MODE` 控制權重圖是否隨選路過程遞減；`sim.py` 情境下額外有 DANGER 前瞻檢查（`LOAD_CHECK_MODE`），見上方提示清單 |

`DTM.py` 頂部的 `ROUTING_ALGORITHM` 變數切換使用哪個模組。

---

## 鏈路狀態（link_status.py）

| 狀態 | 使用率 | 選路行為 |
|------|--------|----------|
| SN | < 1% | 優先使用（節能） |
| LOW | 1–20% | 正常可用，LINK 觸發器會主動重路由 |
| NORMAL | 20–60% | 正常 |
| HIGH | 60–80% | 正常，HIGH_LOAD 觸發器評分較高 |
| OVERLOAD | 80–100% | 選路排除（第二輪放寬），LINK 觸發器主動重路由 |
| **DANGER** | **> 100%** | **同 OVERLOAD，選路排除，LINK 觸發器主動重路由** |

OVERLOAD / DANGER 在 `REROUTE_LOAD_WEIGHT` 中均設為 `-999`，HIGH_LOAD 觸發器不重複處理。

上表是「加入前的鏈路現況」判斷，`self`／`2020`／`dijkstra` 都只依賴這個快照。
`routing_DTM_sorted.py` 在 `sim.py` 情境下另外多一層**加入後**的前瞻檢查（見上方提示清單「DANGER 前瞻檢查」），
判斷「這條流量加進去後」會不會讓某段 link 超過 100%，不只是看目前狀態。

---

## 拓撲

| 檔案 | 拓撲 | 說明 |
|------|------|------|
| `cap_topo.py` | 校園網路 | 45 switch，27 host，已套用 controller-rate-limit |
| `new_topo.py` | 校園網路（舊） | 保留備用 |
| `grid_topo.py` | 5×5 Grid | 16 hosts（h1–h16），尚未套用 controller-rate-limit |

切換拓撲時，`data/` 下的對應資料檔（Mininet 用，扁平版本）與 `animate_activeflow.py` 的 `TOPO` 旗子需一併替換。
`sim.py` 不受影響，`--topo` 會自動切到 `data/grid/`／`data/cap/`。

---

## 實驗流程

### 單次實驗（Mininet）

```
執行實驗 → log/DTM-2026-*.txt（Ryu log）
         → watchdog 整理 → log/activeflow-2026-*.txt
         → animate_activeflow.py --save → log/anim-2026-*.html（動畫）

         → experiment.log
         → parse_log.py → experiment.csv
         → matplotlib_DTM.py → 圖表 / 統計
```

### 單一設定的 sim.py 實驗

```
python3 sim.py --seed seed_1.json --algorithm sorted
    → experiment.log（或 log/sim-.../run.log）
    → parse_log.py → experiment.csv
    → matplotlib_DTM.py（analyze()）→ energy_saving_summary.csv（含 AVERAGE）
```

### 批次比較多組設定（routing_DTM_sorted.py 專用）

```
編輯 sweep_sorted.py 的 COMBOS 清單
    → python3 sweep_sorted.py
    → 每組 combo 各自跑一輪上面「單一設定」的完整流程
    → 全部組合疊成 sweep_comparison.csv（逐 batch + AVERAGE，標上完整解析後的設定）
```

### 手動產出動畫
```bash
# campus 拓撲（預設）
python3 animate_activeflow.py log/activeflow-2026-YYYY-MM-DD_HH-MM-SS.txt --save out.html

# grid 拓撲
python3 animate_activeflow.py log/activeflow-2026-YYYY-MM-DD_HH-MM-SS.txt --topo grid --save out.html
```

---

## animate_activeflow.py 說明

### 拓撲切換
- 檔案頂部 `TOPO = 'cap'`（預設 campus）或 `'grid'`
- CLI 參數 `--topo grid|cap` 可覆蓋檔案設定

### 資料來源
動畫**完全從 log 讀取**，不推算、不累積狀態。每個 `[ActiveFlow]` 事件後面緊跟一行 `[SNAPSHOT]`，動畫直接解析該快照。

**重要**：`[SNAPSHOT]` 格式只有 `routing_DTM_self.py` 才會輸出。對其他演算法的 log，動畫將只顯示拓撲但無狀態。

### log 關鍵字（activeflow log 過濾條件）
```
[ActiveFlow] 新增 / 移除
[SNAPSHOT]
[NonShortest] 新增 / 移除
[FLOW_NEW] / [FLOW_CASCADE] / [FLOW_CASCADE_NS]
```

### 動畫佈局（self 模式）
- **左圖**：所有 active flows（含非最短 hop）
- **中圖**：僅最短 hop flows（排除非最短 hop）
- **右側文字**：flow 清單，`★` 標記非最短 hop flow

---

## routing_DTM_self.py 關鍵 log 訊號

| 訊號 | 意義 |
|------|------|
| `[FLOW_NEW]` | 新 flow 選路完成 |
| `[FLOW_CASCADE]` | cascade 重路由（最短 hop flow） |
| `[FLOW_CASCADE_NS]` | cascade 重路由（非最短 hop flow） |
| `[NonShortest] 新增/移除` | 非最短 hop 清單變動 |
| `[CASCADE_TIME]` | 每次完整 cascade 耗時與累積平均 |
| `[CASCADE_DEEP]` | cascade 深度超過 `CASCADE_DEEP_LOG`（預設 10） |
| `[CASCADE_ABORT]` | cascade 深度超過 50，強制中止 |
| `[CASCADE_2ND]` | 第一道 pass 有路徑變換，啟動 NS second pass |
| `[CASCADE_WARN]` | **異常**：進入 admit_flow/on_flow_removed 時狀態變數未還原，前次 cascade 可能異常中止 |
| `[SNAPSHOT]` | 完整狀態快照（JSON），動畫直接使用 |

---

## 重要提醒

- 處理任何路由模組前，請先閱讀對應的 `docs/` 設計文件：
  - `routing_DTM_self.py` → `docs/routing_DTM_self.md`
  - `routing_DTM_2020.py` → `docs/routing_DTM_2020.md`
  - `routing_DTM_dijkstra.py` → `docs/routing_DTM_dijkstra.md`
- `data/demands.txt` 為舊版殘留，不再使用
- `k_short_dist.txt` 的 switch 集合在此拓撲中為**固定不變值**（同一 src/dst、同一 hop 數下，switch 集合不隨路徑選擇改變）
- `[SNAPSHOT]` 格式為 JSON：`{"active": [[src, dst, path], ...], "ns": [[src, dst, hop], ...], "wmap": {"dpid": weight, ...}}`
- `base_weight_map.txt`：DTM-Self 拓撲天生偏好權重，首次執行時自動從 `k_short_dist.txt` 計算並存檔，之後直接讀取。切換拓撲時需刪除舊檔讓它重新生成。
- **測試／除錯 `sim.py` 時，記得用 `--log` 指到暫存路徑**：`sim.py` 預設的 `EXPERIMENT_LOG='experiment.log'`
  跟根目錄的 `experiment.log`／`experiment.csv` 是共用檔案，`Simulator._log()` 用 append 模式寫入，
  隨手跑一次 demo（沒指定 `--seed`）就會把假流量的 `BATCH 0` 資料混進真實實驗紀錄，
  且 `experiment.csv`／`energy_saving_summary.csv` 一旦被 `parse_log.py`／`matplotlib_DTM.py` 重新產生
  就會直接覆蓋、無法從 git 復原（這兩個檔案在成為目前內容前就已經是未 commit 狀態）。
