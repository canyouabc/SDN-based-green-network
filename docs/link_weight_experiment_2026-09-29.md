# Link 能耗納入選路權重（LINK_WEIGHT）實驗（2026-09-29）

## 背景

`routing_DTM_sorted.py`（SGH 實作）的 Phase 1 只看「要新開幾台 switch」（`inactive_counter`），
選路時完全不讀 `link_energy`／`switch_energy`。因此會出現「路徑上的 switch 都已開啟，
但中間的 link 原本是關的」卻被當成零成本的情況。這也是 NSP／NMU（Assefa & Ozkasap,
BlackSeaCom 2017）事後修剪 link 想補的缺口；本實驗改在**選路當下**就把 link 納入成本。

## 實作（`modules/routing_DTM_sorted.py`）

新增旗標 `LINK_WEIGHT = False`（預設關閉，行為與原本完全相同）。開啟時：

| 位置 | 原本 | `LINK_WEIGHT=True` |
|---|---|---|
| Phase 1-a（clean zero） | 路徑上所有 switch 已開啟 | 所有 switch **且所有 link** 已開啟 |
| Phase 1-b 成本 | 新開 switch 台數 | Σ 新開 switch 能耗 + Σ 新開 link 能耗（W，直接讀能耗檔，權重與能耗等比例） |
| 平手判斷 | 成本相同再比 hop 數 | 同左（成本 round 到 6 位小數避免浮點加總順序誤差） |

- 已開啟的 link 由 `_ActiveElements`（`set` 子類別，`update(path)` 時記錄 link）追蹤；
  旗標關閉時 `_new_active_sw()` 回傳原本的 `set()`，預設路徑不多任何開銷。
- 目前只有 `sim.py` 的 `MockApp` 提供 `switch_energy`／`link_energy`；DTM 上開啟會直接 `RuntimeError`。
- 其他配合改動：`sim.py` `_TOPO_FILES` 新增 `grid_31`；`sweep_sorted.py` `BASELINE` 新增
  `LINK_WEIGHT: False`（沒加的話 sweep 會忽略此旗標）；新增 `data/grid_31/`
  （grid 5x5，switch=3、link=1，比照 `geant_31`；k_short 系列複製自 `data/grid`）。

**驗證**：固定 random seed，`LINK_WEIGHT=False` 與改動前程式跑 3 batch × {SPF, SPF+ESP}，
912 筆 ENERGY／HISTORY 數值完全相同（比對時需忽略時間戳：`_AppendTee` 會讓部分行黏在一起）。
成本函式另以單元測試確認只計入新開的 switch／link、ESP 預開端點只開 switch 不開 link。

## 實驗設定

- 拓撲：grid 5×5（16 host），流量 `seed_000_grid5x5_xlow.json`（10 batch，λ=1，
  flow 15 秒，0.1～0.5 Mbps，平均同時 15.3 條）
- 演算法：`sorted`，`SORT_MODE='SPF'`、`ENABLE_WEIGHT_MAP=False`、`PRESEED_ENDPOINTS=False`
- 能耗比例：811:1（`grid`，146W／0.18W）與 3:1（`grid_31`）
- 每組 5 次（random seed 0～4，SPF 平手時 random），每次 10 batch；指標 `mean_after_100`

## 結果

| 組別 | 能耗比 | link 權重 | 節能率 平均（5 次範圍） | 平均開啟 switch | 平均開啟 link |
|---|---|---|---|---|---|
| 1 | 811:1 | 有 | 35.77（35.62～35.91） | 16.09 | **15.48** |
| 2 | 811:1 | 無 | 35.79（35.75～35.85） | 16.07 | 16.09 |
| 3 | 3:1 | 有 | **44.62**（44.47～44.75） | 16.09 | **15.48** |
| 4 | 3:1 | 無 | 44.13（44.07～44.18） | 16.07 | 16.09 |

（開啟數為有 flow 時的逐秒平均；grid 5×5 共 25 switch、40 link。）

## 觀察

1. **link 權重有實際改變選路**：switch 數幾乎不變（16.07 → 16.09），link 平均少開 0.61 條（約 −3.8%）。
2. **兩種能耗比例下選出的路徑相同**（組 1 與組 3 的開啟數一致）：在這份低流量 grid 上，
   3:1 並沒有出現「多開 1 台 switch 換少開 ≥4 條 link」的取捨，link 權重實際上只扮演
   「新開 switch 數相同時，挑新開 link 較少者」的角色。
3. **節能率差異完全取決於能耗比例**：811:1 下少開 0.6 條 link 僅約 0.1W，節能率不變（差 −0.02，
   在 random 波動內）；3:1 下同樣的選路差異帶來 **+0.49 個百分點**，5 次範圍不重疊。
4. 3:1 整體節能率（約 44%）比 811:1（約 36%）高，是能耗比例本身造成（link 占比變大，
   低流量時多數 link 關閉），非演算法差異。

## 計算時間（3 batch × 3 次，只計 `admit_flow`／`on_flow_removed`）

| | 選路總時間 |
|---|---|
| 改動前原始程式 | 8.04 s |
| 新程式，`LINK_WEIGHT=False` | 8.10 s（差異在誤差內） |
| 新程式，`LINK_WEIGHT=True` | 12.74 s（**約 +58%**，每事件約 9 ms → 14 ms） |

增加主因：clean zero 條件變嚴格，更常落入 Phase 1-b 掃描全部 hop 層候選並逐條計算成本。

## 3:1 下加入 ESP，並與 Gurobi 最優解比較

Gurobi：`milp_transfer/results_milpsnap_31/seed_milpsnap_grid5x5_xlow_results.csv`（`--topo grid_5x5_31`，
1287 題全部 OPTIMAL，求解總時間 440 秒），經 `combine_milp_snapshot.py` 還原成逐 batch
`mean_after_100`（輸出 `log/milpsnap31-grid5x5_xlow/`）。heuristic 每 batch 為 5 個 random seed 平均；
ESP 兩組資料夾 `log/sweep-LWESP_grid_31_{True,False}_{0..4}-*`。

| 組別 | 設定（3:1） | 節能率（5 次範圍） | 與最優差距 | 平均開啟 switch | 平均開啟 link |
|---|---|---|---|---|---|
| — | **Gurobi 最優** | **50.18** | — | — | — |
| 4 | SPF | 44.13（44.07～44.18） | −6.05 | 16.07 | 16.09 |
| 3 | SPF + link 權重 | 44.62（44.47～44.75） | −5.56 | 16.09 | 15.48 |
| 6 | SPF + ESP | 47.05（47.04～47.08） | −3.12 | 15.31 | 14.95 |
| 5 | SPF + ESP + link 權重 | **47.22**（47.21～47.23） | **−2.95** | 15.32 | 14.74 |

逐 batch（括號為與最優差距）：

| batch | Gurobi | SPF | SPF+link | ESP | ESP+link |
|---|---|---|---|---|---|
| 1 | 49.88 | 44.02（−5.9） | 44.46（−5.4） | 46.74（−3.1） | 46.68（−3.2） |
| 2 | 49.60 | 43.64（−6.0） | 44.25（−5.4） | 47.15（−2.4） | 47.22（−2.4） |
| 3 | 49.94 | 45.52（−4.4） | 45.81（−4.1） | 48.01（−1.9） | 48.25（−1.7） |
| 4 | 49.70 | 43.62（−6.1） | 44.02（−5.7） | 46.73（−3.0） | 47.06（−2.6） |
| 5 | 50.35 | 44.18（−6.2） | 44.76（−5.6） | 47.40（−3.0） | 47.60（−2.8） |
| 6 | 50.06 | 43.22（−6.8） | 43.86（−6.2） | 46.45（−3.6） | 46.68（−3.4） |
| 7 | 49.26 | 42.70（−6.6） | 43.38（−5.9） | 46.25（−3.0） | 46.41（−2.9） |
| 8 | 52.03 | 46.29（−5.7） | 46.50（−5.5） | 48.29（−3.7） | 48.47（−3.6） |
| 9 | 50.85 | 44.50（−6.3） | 45.11（−5.7） | 46.96（−3.9） | 47.20（−3.6） |
| 10 | 50.08 | 43.58（−6.5） | 44.03（−6.1） | 46.55（−3.5） | 46.68（−3.4） |

觀察：
1. **ESP 是縮小差距的主力**：差距 6.05 → 3.12（約減半），主要來自少開 0.76 台 switch；
   與 811:1 下的趨勢一致（811:1：SPF −5.89、ESP 約 −2.9）。
2. **link 權重在兩種基底上都有效但幅度不同**：SPF 上 +0.49（差距縮 8.1%，10/10 batch 改善），
   ESP 上只剩 +0.17（差距縮 5.4%，9/10 batch 改善，batch 1 小退 0.06）。ESP 已先把流量集中到
   固定開啟的端點 switch，路徑重疊度高，可省的 link 較少（link 少開 0.21 條，SPF 上是 0.61 條）。
3. 最佳組合 ESP+link 權重仍距最優 2.95，10 個 batch 都未追平；剩餘差距應主要來自 switch
   （heuristic 依 k-short 候選、逐條 flow 貪婪決策）。

## 限制與後續

- 只測了低流量（xlow）的 grid 5×5；流量更高或拓撲有更多替代路徑（如 GEANT、cap）時，
  3:1 下才可能出現 switch／link 的真正取捨。舊版 `sorted_link`（已刪）在 GEANT 3:1 30-flow
  測得 12.35% → 15.88%，量級明顯較大。
- 尚未與 NSP／NMU（事後修剪 link）比較。
- 原始結果資料夾：`log/sweep-LW_{grid,grid_31}_{True,False}_{0..4}-2026-09-29_*`。

## ⚠️ 資料版本說明（2026-09-29 晚間補記）

本文件與 `thesis_figures/plot_link_weight_31.py`（`link_weight_31_*.png`）的 heuristic 數字，
來自 `sweep_sorted._AppendTee` 修正**之前**的執行：舊版 8KB 區塊緩衝會讓 `print()` 半行與
`Simulator._log()` 的整行黏在一起，`parse_log` 以行首比對時漏掉約 2% 的 ENERGY 取樣
（70 次 run 全數受影響）。已改為逐行緩衝（`buffering=1`）並驗證黏行數 0。

修正後重跑 xlow（`log/sweep-L31_xlow_*`）與本文件數字差距 ≤ 0.05 個百分點，結論不變：

| 設定（3:1、xlow） | 本文件（修正前） | 修正後 |
|---|---|---|
| SPF | 44.13 | 44.08 |
| SPF + link 權重 | 44.62 | 44.57 |
| SPF + ESP | 47.05 | 47.04 |
| SPF + ESP + link 權重 | 47.22 | 47.20 |

修正後的五個流量等級（xxlow～high）完整結果，以及 NSP 變種（`LINK_PRUNE='NSP_COUNT'`）的結果，
見 `thesis_figures/plot_nsp_31.py` 開頭的資料來源說明與 `log/sweep-{L31,N31}_*`。
