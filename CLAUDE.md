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
└── docs/
    └── routing_DTM_self.md     ← DTM-Self 演算法設計文件
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
執行實驗 → experiment.log
        → parse_log.py → experiment.csv
        → matplotlib_DTM.py → 圖表 / 統計
```

---

## 重要提醒

- 處理 `modules/routing_DTM_self.py` 前，請先閱讀 `docs/routing_DTM_self.md`
- `data/demands.txt` 為舊版殘留，不再使用
- `k_short_dist.txt` 的 switch 集合在此拓撲中為**固定不變值**（同一 src/dst、同一 hop 數下，switch 集合不隨路徑選擇改變）
