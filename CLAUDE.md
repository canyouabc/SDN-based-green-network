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

- [ ] **切換拓撲時記得同步 `data/`**：`k_short.txt`、`k_short_dist.txt`、
      `link_bw.txt`、`switch_energy.txt` 等檔案需對應正確拓撲版本。
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

---

## 專案目的

節能路由實驗與論文實作。基於 Ryu SDN 控制器，在 Mininet 模擬環境中比較不同路由演算法的節能效果。

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
├── parse_log.py            # 將 experiment.log 匯出為 CSV
├── matplotlib_DTM.py       # 將 CSV 輸出為圖表與統計
├── experiment.log          # 實驗記錄
├── experiment.csv          # 匯出的 CSV
├── modules/                # 路由與量測模組
│   ├── routing_base.py
│   ├── routing_2014.py
│   ├── routing_DTM_2020.py
│   ├── routing_DTM_dijkstra.py
│   ├── routing_DTM_self.py     ← 最新論文實作
│   ├── routing_auto_k_short.py
│   ├── link_status.py          ← 鏈路狀態（SN/LOW/NORMAL/HIGH/OVERLOAD/DANGER）
│   ├── bandwidth_measurement.py
│   ├── delay_detection.py
│   └── link_delay_measurement.py
├── data/                   # 預計算資料
│   ├── k_short.txt             # 當前使用的 k-short 路徑
│   ├── k_short_dist.txt        # 各 hop 群的 switch 集合
│   ├── base_weight_map.txt     # DTM-Self 拓撲天生偏好權重（首次執行自動生成）
│   ├── k_short-grid-16.txt     # Grid 拓撲備用
│   ├── k_short-grid-500.txt
│   ├── k_short_校園網路.txt
│   ├── link_bw.txt
│   ├── link_bw_校園網路.txt
│   ├── link_energy.txt
│   ├── link_energy_校園網路.txt
│   ├── switch_energy.txt
│   └── switch_energy_校園網路.txt
├── log/                    # 實驗執行後產生
│   ├── DTM-2026-*.txt          # Ryu 完整 log
│   ├── activeflow-2026-*.txt   # 整理後的 activeflow log（動畫來源）
│   ├── anim-2026-*.html        # HTML 動畫（用瀏覽器開）
│   ├── anim-2026-*.log         # 動畫產出的 stdout/stderr（錯誤診斷用）
│   ├── mininet-2026-*.txt      # Mininet log
│   ├── bw.log                  # 頻寬監控即時 log（每批覆寫）
│   └── cascade_debug.log       # cascade 詳細 debug log（每批覆寫）
└── docs/
    ├── routing_DTM_self.md         ← DTM-Self 演算法設計文件
    ├── routing_DTM_2020.md         ← 2020 k-short 演算法設計文件
    └── routing_DTM_dijkstra.md     ← Dijkstra 雙模式演算法設計文件
```

---

## 啟動方式

### 單次實驗
```bash
ryu-manager DTM.py --observe-links
sudo python cap_topo.py        # 或 grid_topo.py
```

### 批次實驗
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
| `routing_DTM_self.py` | **最新論文實作方向**，兩階段選路 + 非最短 hop 清單機制 |

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

---

## 拓撲

| 檔案 | 拓撲 | 說明 |
|------|------|------|
| `cap_topo.py` | 校園網路 | 45 switch，27 host，已套用 controller-rate-limit |
| `new_topo.py` | 校園網路（舊） | 保留備用 |
| `grid_topo.py` | 5×5 Grid | 16 hosts（h1–h16），尚未套用 controller-rate-limit |

切換拓撲時，`data/` 下的對應資料檔與 `animate_activeflow.py` 的 `TOPO` 旗子需一併替換。

---

## 實驗流程

```
執行實驗 → log/DTM-2026-*.txt（Ryu log）
         → watchdog 整理 → log/activeflow-2026-*.txt
         → animate_activeflow.py --save → log/anim-2026-*.html（動畫）

         → experiment.log
         → parse_log.py → experiment.csv
         → matplotlib_DTM.py → 圖表 / 統計
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
