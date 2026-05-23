# routing_DTM_dijkstra.py 設計說明

## 概覽

`Routing_DTM_Dijkstra` 以即時 link 狀態為權重跑 **Dijkstra**，並支援雙模式比較：

- **Energy mode**：最小化 SN link 數（節能優先）
- **Shortest mode**：最小化 hop 數（路徑長度優先）

可透過開關決定是否進行兩模式比較，以及比較候選的來源（Dijkstra shortest 或 2020 k-short 邏輯）。

---

## 模式設定（頂部常數）

| 常數 | 預設值 | 說明 |
|------|--------|------|
| `SN_WEIGHT` | 1000 | Energy mode：SN link 的高成本，讓演算法優先繞開 |
| `NORMAL_WEIGHT` | 1 | Energy mode：非 SN link 的低成本 |
| `SHORTEST_HOP_WEIGHT` | 100 | Shortest mode：非 SN link 成本 |
| `SHORTEST_SN_WEIGHT` | 101 | Shortest mode：SN link 略高，同 hop 數時 SN 多的輸 |
| `ENABLE_SHORTEST_PATH` | `True` | `False` → 僅跑 energy mode，不比較 |
| `SHORTEST_CANDIDATE` | `'kshort'` | `'dijkstra'` 或 `'kshort'`，決定 shortest 候選來源 |
| `SHORTEST_HOP_TOLERANCE` | 3 | 容忍差距：`energy_hops - candidate_hops >= N` 才選 candidate |

---

## 選路邏輯（`select_path`）

### Round 1（排除 OVERLOAD）

1. 跑 `_find_best_path`（energy vs candidate 比較）
2. 若有路徑 → 回傳

### Round 2（放寬 OVERLOAD）

Round 1 無可用路徑時，`exclude_overload=False` 重跑一次。

### `_find_best_path` 內部流程

```
energy_path  = Dijkstra(energy mode)
candidate    = Dijkstra(shortest mode) 或 k-short 2020 邏輯

若 candidate_hops + SHORTEST_HOP_TOLERANCE <= energy_hops
    → 選 candidate（更短的路徑值得用）
否則
    → 選 energy_path
```

---

## Dijkstra 實作（`_dijkstra`）

- 使用 `app.adjacency`（鄰接表）與 `app.myswitches`（switch 清單）
- link 權重由 link 狀態決定（energy 或 shortest mode）
- `exclude_overload=True` → OVERLOAD link 視為不通

---

## 統計

| 屬性 | 說明 |
|------|------|
| `total_path_selections` | 總選路次數 |
| `shortest_selected_count` | 選到 shortest 模式路徑的次數 |
| `get_shortest_ratio()` | `shortest_selected_count / total_path_selections` |

---

## 與其他模組的差異

| 項目 | routing_DTM_dijkstra | routing_DTM_2020 | routing_DTM_self |
|------|---------------------|-----------------|-----------------|
| 選路核心 | Dijkstra（即時計算） | k-short 預算路徑 | k-short + 兩階段 |
| 雙模式比較 | ✅ energy vs shortest | ❌ | ❌ |
| 權重圖 | ❌ 無 | ❌ 無 | ✅ `switch_weight_map` |
| Cascade | ❌ 無 | ❌ 無 | ✅ 有 |
| 統計 | ✅ `shortest_ratio` | ❌ | ❌ |
| `on_flow_removed` | ❌ 無 | ❌ 無 | ✅ 有 |

---

## 函式對照表

| 函式 | 說明 |
|------|------|
| `admit_flow` | 新流量入口，呼叫 `select_path`，呼叫 `add_active_flow` |
| `select_path` | 兩輪選路（Round 1 排 OVERLOAD，Round 2 放開） |
| `_find_best_path` | energy vs candidate 比較，回傳 `(path, used_shortest)` |
| `_dijkstra` | 核心 Dijkstra，支援 energy / shortest 兩種 mode |
| `_find_kshort_path` | 2020 k-short 邏輯，用於 `SHORTEST_CANDIDATE='kshort'` 時 |
| `_compare_paths` | 依 `SHORTEST_HOP_TOLERANCE` 決定選哪條路徑 |
| `get_shortest_ratio` | 回傳 shortest 路徑被選中的比例 |
| `load_k_short_paths` | 從 `data/k_short.txt` 載入（供 kshort 候選模式使用） |
