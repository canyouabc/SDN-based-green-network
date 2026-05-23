# 專案說明（CLAUDE.md）

## 專案目的

節能路由實驗與論文實作。基於 Ryu SDN 控制器，在 Mininet 模擬環境中比較不同路由演算法的節能效果。

---

## 目錄結構

```
Dijkstra/
├── DTM.py                  # 主控制器（Ryu app）
├── new_topo.py             # 校園網路拓撲
├── grid_topo.py            # 5×5 Grid 拓撲
├── watchdog_new.py         # 批次實驗自動化腳本
├── animate_activeflow.py   # 從 activeflow log 產出 HTML 動畫
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
│   ├── link_status.py
│   ├── bandwidth_measurement.py
│   ├── delay_detection.py
│   └── link_delay_measurement.py
├── data/                   # 預計算資料
│   ├── k_short.txt             # 當前使用的 k-short 路徑
│   ├── k_short_dist.txt        # 各 hop 群的 switch 集合
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
│   └── mininet-2026-*.txt      # Mininet log
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
sudo python new_topo.py        # 或 grid_topo.py
```

### 批次實驗
```bash
sudo python3 watchdog_new.py
```

watchdog 每批實驗結束後自動：
1. 從 Ryu log 整理出 `log/activeflow-2026-*.txt`
2. 背景產出 `log/anim-2026-*.html` 動畫（可自行用瀏覽器開啟）
3. 產出錯誤若發生，記錄於同名 `.log` 檔

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

## 拓撲

| 檔案 | 拓撲 | 說明 |
|------|------|------|
| `new_topo.py` | 校園網路 | 實際校園網路結構 |
| `grid_topo.py` | 5×5 Grid | 16 hosts（h1–h16） |

兩者會依實驗需求切換，無固定主力。切換拓撲時，`data/` 下的對應資料檔也需要一併替換。

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
python3 animate_activeflow.py log/activeflow-2026-YYYY-MM-DD_HH-MM-SS.txt --save out.html
```

---

## animate_activeflow.py 說明

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

## 重要提醒

- 處理任何路由模組前，請先閱讀對應的 `docs/` 設計文件：
  - `routing_DTM_self.py` → `docs/routing_DTM_self.md`
  - `routing_DTM_2020.py` → `docs/routing_DTM_2020.md`
  - `routing_DTM_dijkstra.py` → `docs/routing_DTM_dijkstra.md`
- `data/demands.txt` 為舊版殘留，不再使用
- `k_short_dist.txt` 的 switch 集合在此拓撲中為**固定不變值**（同一 src/dst、同一 hop 數下，switch 集合不隨路徑選擇改變）
- `[SNAPSHOT]` 格式為 JSON：`{"active": [[src, dst, path], ...], "ns": [[src, dst, hop], ...], "wmap": {"dpid": weight, ...}}`
