# routing_DTM_self.py 設計說明

## 概覽

`Routing_DTM_Self` 是基於 2020 演算法延伸的選路模組，啟用 `ENABLE_NEW_ALGO = True` 後採用兩階段選路邏輯，並引入「非最短 hop 清單」機制對特殊流量進行管理。

---

## 資料結構

| 名稱 | 型別 | 說明 |
|------|------|------|
| `k_short_paths` | `{(src, dst): [[dpid, ...], ...]}` | 預載的 k 條最短路徑 |
| `k_short_dist` | `{(src, dst): {hop: [sw, ...]}}` | 各 hop 數對應的 switch 集合（固定不變） |
| `switch_weight_map` | `{dpid: int}` | 各 switch 的累積佔用權重；**所有流量**（含非最短 hop）皆以 `global_min_hop` switch 群計入 |
| `ns_weight_map` | `{dpid: int}` | 僅非最短 hop flow 額外維護的第二層權重圖 |
| `base_weight_map` | `{dpid: int}` | 拓撲天生偏好，啟動時從 `k_short_dist` 靜態計算，不隨 flow 變動 |
| `非最短hop清單` | `{(src, dst): (best_hop, best_path)}` | Phase 1 選出的非全局最短 hop flow |
| `待檢查路徑` | `set` | 當前 cascade session 中已排入檢查的 flow，防止重複進入 |
| `_cascade_depth` | `int` | cascade 巢狀深度計數器（debug 用） |
| `_cascade_time_total` | `float` | 所有 cascade 執行時間累計（秒） |
| `_cascade_count` | `int` | cascade 執行次數，與 `_cascade_time_total` 合算平均成本 |

> `k_short_dist` 的特性：在此拓撲中，同一 `(src, dst)` 在同一 hop 數下，switch 集合為**固定不變值**。因此「active flow 的實際路徑 switch」與「該 flow 的 hop 群 switch 集合」等價。

---

## 兩階段選路（`_compute_path`）

### Phase 1

1. 掃描所有 k-short 路徑，統計每條路徑的 **SN link 數**與 **hop 數**，排除含 OVERLOAD link 的路徑
   - 若所有路徑都含 OVERLOAD，第二輪將全部納入
2. 以 `(最少 SN link, 最短 hop)` 排序，取並列最優的路徑為**候選集**
3. 計算 `global_min_hop = min(k_short_dist[(src, dst)].keys())`
4. 判斷候選集的最優 hop 數：
   - `best_hop == global_min_hop` → 進入 Phase 2
   - `best_hop > global_min_hop` → **NS 分支**（見下節）

### Phase 2

1. 對候選集套用 `switch_weight_map` 評分（沿路 switch 的累積佔用權重加總）
2. 選最高分者；真正同分才隨機選一條
3. 觸發 `_cascade`

---

## NS 分支（`best_hop > global_min_hop`）

1. 呼叫 `_increment_sw_weight_by_shortest`：對 `global_min_hop` switch 群虛擬 +1，模擬此 flow 若走最短 hop 的影響
2. 對候選集評分，取最高分者（tied list）
3. 若 `prefer_current` 在 tied list 中 → `_decrement_sw_weight_by_shortest` 退回 +1，**回傳 `None`**（不換路）
4. 否則：
   - 寫入 `非最短hop清單[(src, dst)] = (best_hop, selected_path)`
   - 呼叫 `_ns_increment`（更新 `ns_weight_map`）
   - 呼叫 `_cascade`（進入 cascade 重算其他 flow）
   - 回傳 `selected_path`

> **注意**：`switch_weight_map` 的 +1 在選路完成後**保留**（不退回），代表此 NS flow 對最短 hop switch 群的實際負擔。

---

## 權重圖更新原則

**所有流量統一使用 `global_min_hop` switch 群更新 `switch_weight_map`**，無論路徑實際是最短還是非最短 hop：

| 事件 | `switch_weight_map` | `ns_weight_map` |
|------|---------------------|-----------------|
| 最短 hop flow 新增 | `_increment_weight`（依實際 hop 群） | 不動 |
| NS flow 新增 | `_increment_sw_weight_by_shortest`（global_min_hop 群） | `_ns_increment` |
| 最短 hop flow 移除 | `_decrement_weight`（依實際 hop 群） | 不動 |
| NS flow 移除 | `_decrement_sw_weight_by_shortest`（global_min_hop 群） | `_ns_decrement` |

---

## 非最短 hop 清單（`非最短hop清單`）

### 設計原則

- Key 唯一：同一 `(src, dst)` 不會重複出現
- `best_path` 是 list，因此使用 dict 而非 set
- **是否為 NS 的唯一判斷依據**：`(src, dst) in self.非最短hop清單`。`_is_ns_path`（len 比較）僅備用，不作為主要判斷

### 清單維護

| 操作 | 時機 |
|------|------|
| 寫入 | `_compute_path` NS 分支選出新路徑時 |
| 刪除 | flow timeout（`on_flow_removed`）或 cascade 重算（扒乾淨舊狀態時） |
| 查詢 | `_cascade` 收集 flows 時、`on_flow_removed` 判斷 flow 類型時 |

---

## Cascade 重路由（`_cascade`）

### 觸發條件

任何 flow 選定新路徑（新增或 reroute）後，觸發 `_cascade`。

### 行為

1. **收集所有 active flows**（不過濾，不做 switch 集合交集）
2. 跳過已在 `待檢查路徑` 中的 flow（防止同 session 重複處理）
3. 對每個 flow：
   - 從 `非最短hop清單` 查詢是否為 NS（不用 `_is_ns_path`）
   - 扒乾淨舊路徑的權重貢獻（NS 用 `_decrement_sw_weight_by_shortest`，一般用 `_decrement_weight`）
   - 呼叫 `_compute_path(prefer_current=current_path)` 重算
   - `None` → 現有路徑仍最佳，還原權重，繼續
   - 有新路徑 → 移除舊 flow rules，安裝新 rules，更新 `active_flows`，觸發遞迴 cascade

### Cascade 深度保護

`_cascade_depth > 50` 時觸發 `_debug_draw_cascade`（儲存 PNG 快照）並提前返回，防止無限遞迴。

### 計時

最外層 cascade（`_cascade_depth == 0` 時進入）計算執行時間，累計至 `_cascade_time_total` / `_cascade_count`，可在 debug 圖中看到平均值。

---

## 日誌格式（`[SNAPSHOT]`）

`routing_DTM_self.py` 在每個 `[ActiveFlow]` 事件後輸出完整狀態快照，供 `animate_activeflow.py` 直接讀取：

```
[SNAPSHOT] {"active": [[src, dst, [path...]], ...], "ns": [[src, dst, hop], ...], "wmap": {"dpid": weight, ...}}
```

觸發時機：
| 位置 | 對應 `[ActiveFlow]` |
|------|---------------------|
| `admit_flow` | `新增`（新流量） |
| `on_flow_removed` | `移除`（flow timeout） |
| `_cascade` 換路完成後 | `新增`（reroute） |

---

## 函式對照表

| 函式 | 說明 |
|------|------|
| `admit_flow` | 新流量入口：清除 `待檢查路徑`，呼叫 `select_path`，記錄 `active_flows`，輸出 snapshot |
| `select_path` | 依 `ENABLE_NEW_ALGO` 分派至 `_compute_path`（新）或舊演算法 |
| `_compute_path` | 兩階段選路核心（Phase 1 → Phase 2 或 NS 分支） |
| `_cascade` | 重算所有 active flows；遞迴，有深度保護 |
| `on_flow_removed` | Flow timeout 後更新權重、NS 清單，再觸發 cascade |
| `_log_snapshot` | 輸出 `[SNAPSHOT]` JSON，供動畫直接讀取 |
| `_debug_draw_cascade` | cascade 深度 > 50 時儲存 PNG 快照（debug 用） |
| `_increment_sw_weight_by_shortest` | NS flow 新增時對 global_min_hop 群 `switch_weight_map` +1 |
| `_decrement_sw_weight_by_shortest` | NS flow 移除時對 global_min_hop 群 `switch_weight_map` -1 |
| `_increment_weight` / `_decrement_weight` | 最短 hop flow 的 `switch_weight_map` 增減（依實際 hop 群） |
| `_ns_increment` / `_ns_decrement` | NS flow 的 `ns_weight_map` 增減 |
| `_build_active_switches` | 掃描 active flows 的 switch 集合（NS flow 排除，用於 Phase 1 SN link 計算） |
| `_is_ns_path` | 備用：以 path 長度和 global_min_hop 比較判斷 NS，不作為主要判斷依據 |
| `load_k_short_paths` | 從 `data/k_short.txt` 載入 |
| `load_k_short_dist` | 從 `data/k_short_dist.txt` 載入 |
