# routing_DTM_self.py 設計說明

## 概覽

`Routing_DTM_Self` 是基於 2020 演算法延伸的選路模組，啟用 `ENABLE_NEW_ALGO = True` 後採用兩階段選路邏輯，並引入「非最短 hop 清單」機制對特殊流量進行隔離管理。

---

## 資料結構

| 名稱 | 型別 | 說明 |
|------|------|------|
| `k_short_paths` | `{(src, dst): [[dpid, ...], ...]}` | 預載的 k 條最短路徑 |
| `k_short_dist` | `{(src, dst): {hop: [sw, ...]}}` | 各 hop 數對應的 switch 集合（固定不變） |
| `switch_weight_map` | `{dpid: int}` | 各 switch 的累積佔用權重 |
| `待檢查路徑` | `set` | 當前 cascade session 中已排入檢查的 flow，防止重複進入 |
| `非最短hop清單` | `{(src, dst): (best_hop, best_path)}` | Phase 1 選出的非全局最短 hop flow |

> `k_short_dist` 的特性：在此拓撲中，同一 `(src, dst)` 在同一 hop 數下，switch 集合為**固定不變值**。因此「active flow 的實際路徑 switch」與「該 flow 的 hop 群 switch 集合」等價。

---

## 兩階段選路（`_find_path_new_algo`）

### Phase 1

1. 掃描所有 k-short 路徑，統計每條路徑的 **SN link 數**與 **hop 數**，排除含 OVERLOAD link 的路徑
   - 若所有路徑都含 OVERLOAD，第二輪將全部納入
2. 以 `(最少 SN link, 最短 hop)` 排序，取並列最優的路徑為**候選集**
3. 計算 `global_min_hop = min(k_short_dist[(src, dst)].keys())`
4. 判斷：
   - `best_hop == global_min_hop` → 進入 Phase 2
   - `best_hop > global_min_hop` → 寫入**非最短 hop 清單**，隨機選一條候選路徑，**跳過 Phase 2 與 cascade**，直接回傳

### Phase 2

1. 對候選集套用 `switch_weight_map` 評分（沿路 switch 的累積佔用權重加總）
2. 選最高分者；真正同分才隨機選一條
3. 觸發 `_cascade_reroute`

---

## 非最短 hop 清單（`非最短hop清單`）

### 設計原則

- 這些 flow 的最優路徑，在當前網路狀態下無法走到全局最短 hop（因為最短 hop 路徑上的 SN link 數較多）
- 它們被**完全隔離**：
  - 不進入 Phase 2（不參與 switch_weight_map 評分）
  - 不觸發 cascade（不影響其他 flow 的路徑判斷）
  - 仍登記於 `active_flows`，節能計算正常涵蓋這些 flow

### 結構

```python
非最短hop清單 = {(host_a, host_b): (best_hop, best_path)}
```

- Key 唯一，同一 `(src, dst)` 不會重複出現
- `best_path` 是 list，因此使用 dict 而非 set

---

## Cascade 重路由（`_cascade_reroute`）

觸發條件：某條路徑被選定後，找出 hop 群 switch 集合有交集的所有 active flow。

由於拓撲的 switch 集合固定，這等價於「兩個 hop 群集合是否有交集」。

### 對非最短 hop 清單的處理

Cascade 掃描 active flows 時，若遇到 `非最短hop清單` 中的 flow：
- **不加入** `flows_to_check`（不觸發 cascade 連鎖）
- 改為直接呼叫 `reevaluate_non_shortest_flow`

```python
if (fa, fb) in self.非最短hop清單:
    _, current_path = self.非最短hop清單[(fa, fb)]
    self.reevaluate_non_shortest_flow(fa, fb, current_path)
    continue
```

---

## 非最短 hop Flow 重評估（`reevaluate_non_shortest_flow`）

**觸發來源**：`_cascade_reroute` 偵測到 hop 群交集時呼叫。

**流程**：

1. 以 Phase 1 邏輯重算當前的候選集
2. 若 `current_path` 仍在候選集中 → **不動作**
3. 若已非最佳：
   - 從 `非最短hop清單` 刪除舊記錄
   - 呼叫 `find_reroute_path` 重新選路
     - 若新路徑仍是非最短 hop → `_find_path_new_algo` 自動寫回 `非最短hop清單`
     - 若新路徑已是最短 hop → 進入 Phase 2，不寫回清單
   - 移除舊 flow rules，安裝新路徑，更新 `active_flows`

**成本**：O(k)，k 為預先計算的 k-short 路徑數，與 active flows 數量無關。

---

## 函式對照表

| 函式 | 說明 |
|------|------|
| `find_path_for_new_flow` | 新流量入口，清除 `待檢查路徑`，呼叫選路，登記 `active_flows` |
| `find_reroute_path` | 選路入口，依 `ENABLE_NEW_ALGO` 分派至新舊演算法 |
| `_find_path_new_algo` | 兩階段選路核心 |
| `_cascade_reroute` | Cascade 掃描與重路由 |
| `reevaluate_non_shortest_flow` | 非最短 hop flow 的獨立重評估 |
| `on_flow_removed` | Flow timeout 後觸發 cascade |
| `_decrement_weight` | 路徑移除時歸還 switch_weight_map 權重 |
