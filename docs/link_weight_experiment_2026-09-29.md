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

## 限制與後續

- 只測了低流量（xlow）的 grid 5×5；流量更高或拓撲有更多替代路徑（如 GEANT、cap）時，
  3:1 下才可能出現 switch／link 的真正取捨。舊版 `sorted_link`（已刪）在 GEANT 3:1 30-flow
  測得 12.35% → 15.88%，量級明顯較大。
- 尚未與 SGH+ESP 疊加測試，也尚未與 NSP／NMU（事後修剪 link）比較。
- 原始結果資料夾：`log/sweep-LW_{grid,grid_31}_{True,False}_{0..4}-2026-09-29_*`。
