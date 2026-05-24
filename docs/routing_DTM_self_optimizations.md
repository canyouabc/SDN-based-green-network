# routing_DTM_self.py 效能優化紀錄

本文件記錄對 `routing_DTM_self.py`（及少量 `DTM.py`）進行的效能優化，
依類別說明動機、作法與效果。

---

## 一、Load 時預算靜態資料結構

### 1. `_global_min_hop` — 預算每個 pair 的全局最短 hop 數

**Before**：`_ns_increment`、`_ns_decrement`、`_is_ns_path`、`_compute_path`
各自呼叫 `min(dist.keys())`，每次都掃 hop 群的 keys。

**After**：`load_k_short_dist` 結束後一次建表：
```python
self._global_min_hop = {k: min(v.keys()) for k, v in self.k_short_dist.items() if v}
```
所有呼叫點改為 `self._global_min_hop[(host_a, host_b)]`，O(1) 查表。

---

### 2. `_ns_sw_list` — 預算每個 pair 的 NS 權重目標 switch 清單

**Before**：`_ns_increment`/`_ns_decrement` 每次呼叫都需兩層 dict 查表
（`k_short_dist[(ha,hb)]` → `.get(global_min_hop, [])`）。

**After**：同在 `load_k_short_dist` 結束後建表：
```python
self._ns_sw_list = {k: v[self._global_min_hop[k]] for k, v in self.k_short_dist.items()
                    if k in self._global_min_hop}
```
`_ns_increment`/`_ns_decrement` 簡化為單次 `.get()` 查表。

---

### 3. `k_short_paths_by_hop` + `k_short_hop_keys` — 按 hop 分群的路徑表

**Before**：路徑以平坦 list 儲存，`_compute_path` 每次從全部路徑中分組掃描。

**After**：`load_k_short_paths` 結束後預建：
```python
# k_short_paths_by_hop[(ha,hb)][hop] = [(path, links), ...]
# k_short_hop_keys[(ha,hb)] = sorted([hop1, hop2, ...])
```
其中 `links` 為預算的正規化 link tuple 清單（見下節），`hop_keys` 為已排序的 hop 值列表。

---

### 4. Link tuple 預算 — 消除 Phase 1 熱迴圈的重複計算

**Before**：Phase 1 每次對每條路徑都即時計算
`(min(path[i], path[i+1]), max(path[i], path[i+1]))`。
k=500 時每次 `_compute_path` 約 2500 次 `min()`/`max()`/tuple 建構。

**After**：load 時一次算好，存入 `k_short_paths_by_hop` 的 `links` 欄位：
```python
links = tuple((min(path[i], path[i+1]), max(path[i], path[i+1]))
              for i in range(len(path) - 1))
```
Phase 1 overload 檢查改為直接迭代 `links`：
```python
if any(link in self._overload_links for link in links): continue
```

---

## 二、執行期快取結構

### 5. `sw_count` — 增量維護的 active switch 計數表

**Before**：`_build_active_switches()` 在每個 flow 的 `_compute_path` 呼叫時，
遍歷所有 active flows 重建 active switch 集合，O(F²) 複雜度。

**After**：`sw_count` 隨 `add_active_flow`/`remove_active_flow`/cascade 換路同步維護，
`_compute_path` 直接從 `sw_count` 建 `active_switches` set，O(F)。
`_build_active_switches()` 方法完全移除。

NS flow（非最短 hop）不計入 `sw_count`，以維持語意正確性。

---

### 6. `_overload_links` — Monitor 每秒更新的 OVERLOAD/DANGER link 快取

**Before**：`_compute_path` 每次呼叫 `get_all_link_status()`，cascade 中每條 flow 各呼叫一次，O(F) 次/cascade。

**After**：`routing_module.refresh_link_cache()` 由 `DTM.py` 的 `_bandwidth_monitor`
每秒呼叫一次，結果存為 frozenset：
```python
self._overload_links = frozenset(
    link for link, info in all_status.items()
    if info.get('status') in ('OVERLOAD', 'DANGER')
)
```
Phase 1 overload 檢查變為純 frozenset membership test，O(1) per link。

---

### 7. `_wmap_ready` — `_ensure_weight_map` 一次性初始化旗標

**Before**：`_ensure_weight_map` 每次呼叫都掃遍所有 switch。

**After**：首次初始化後設 `_wmap_ready = True`，後續呼叫立即 return。

---

## 三、Phase 1 演算法改進

### 8. Phase 1 hop-group 早退機制（語意變更）

**Before**：掃所有 k 條路徑，找 `best_inactive`（最小 inactive switch 數），
再找最短 hop，O(k)。

**After（快速路徑）**：按 hop 群從小到大迭代，找第一個有「無 overload 且 inactive=0」
路徑的群，找到即 break。常態下只掃最短 hop 群（5–10 條），略過其餘 ~490 條。

**語意變更**：優先選「較長路徑但不喚醒新 switch」，而非「較短路徑但喚醒 1 個 switch」。

**Fallback**：若無任何群有 inactive=0（冷啟動或全網忙），退回原有全量掃描邏輯，
語意與原算法相同（找 best_inactive）。

---

### 9. 合併掃描 + O(N) min-finding

**Before**：Path 掃描分兩輪（overload 過濾 + inactive 計算），min 用 `sorted()` O(N log N)。

**After**：單輪掃描同時建 `valid_paths` 和 `fallback_paths`；
min-finding 改為 O(N) `min()` + 一次線性過濾取 `best_hop` candidates。

---

### 10. 單一 candidate 短路

Phase 2（及 NS 分支）在 `len(candidates) == 1` 時跳過所有評分計算，直接選唯一路徑。

---

### 11. `sorted()` → `max()` + list comprehension

Phase 2 五處評分（core_weight / ns_weight / base_weight）原為 `sorted()` O(N log N)，
全改為 O(N) `max()` + list comprehension。

---

## 四、Cascade 結構清理

### 12. `_cascade_depth` 移除

非遞歸重構後 `_cascade_depth` 永遠為 0/1，`CASCADE_DEEP_LOG` 和 `> 50` 檢查
從未觸發。移除：常數 `CASCADE_DEEP_LOG`、`__init__` 欄位、兩個 CASCADE_WARN
入口檢查、`_cascade` 中的遞增遞減與條件分支。

---

### 13. Cascade 雙迴圈合一

**Before**：
```python
for fa, fb, _, _ in flows_to_check:       # 第一輪：pre-mark 待檢查路徑
    self.待檢查路徑.add((fa, fb))
for fa, fb, current_path, is_ns in flows_to_check:   # 第二輪：處理
    ...
```

**After**：`待檢查路徑.add((fa, fb))` 移到處理迴圈第一行，省掉一次完整迭代。
非遞歸後 pre-marking 不影響語意正確性。

---

## 五、I/O 與 Log 開銷

### 14. `_log_snapshot` — `ENABLE_SNAPSHOT` 旗標

**Before**：`admit_flow`、`on_flow_removed`、cascade 結束三處無條件呼叫，
每次建構 JSON 並 `print()`。

**After**：`_log_snapshot` 頂部加 `if not ENABLE_SNAPSHOT: return`，
預設 `ENABLE_SNAPSHOT = False`，三處呼叫零成本。

---

### 15. `_cd_log` f-string guard

**Before**：`_cd_log(f"...")` 即使 `CD_DEBUG=False`，f-string 依然被 evaluate，
包含 `dict(self.非最短hop清單)` 等非輕量物件的複製與 repr。

**After**：所有呼叫點加 `if CD_DEBUG:` guard，f-string 完全不 evaluate。

---

### 16. PKT-IN PAIR log 節流（DTM.py）

**Before**：每個 pkt-in pair 超過閾值就印 log。

**After**：改為每 100 個才印一次：
```python
if self.pkt_in_pair_counter[_pair] % 100 == 0:
```

---

### 17. `_ensure_weight_map` 呼叫點前移

**Before**：在 `_compute_path` 內呼叫，cascade 中每條 flow 各觸發一次（雖有早返回，
仍有函式呼叫 overhead）。

**After**：移到 `select_path`（admit_flow 路徑）和 `_cascade` 頂部（cascade 路徑），
每次 cascade 只觸發一次。
