# routing_DTM_2020.py 設計說明

## 概覽

`Routing_DTM_2020` 是以 **k-short 預算路徑**為底的選路模組。不使用 Dijkstra，也不維護任何權重圖或 cascade 機制，邏輯輕量。

核心概念：根據路徑上各 link 的即時狀態，以「最少 SN link 數、最短 hop 數」排序，選出最優路徑。

---

## Link 狀態定義

| 狀態 | 使用率範圍 | 說明 |
|------|------------|------|
| SN | 0–1% | 視為無流量（idle）的 link |
| S0 | 1–20% | LOW |
| S1 | 20–60% | NORMAL |
| S2 | 60–80% | HIGH（緩衝區，不參與接受或分流） |
| S3 / OVERLOAD | 80–100% | OVERLOAD |

---

## 選路邏輯（`select_path`）

### Round 1（排除 OVERLOAD）

對每條 k-short 路徑：
1. 逐 link 統計 `sn_counter`（SN link 數）與 `hop_counter`
2. 若路徑含 OVERLOAD link → 排除
3. 存活路徑以 `(sn_counter, hop_counter)` 排序，最小者優先
4. 並列最優的路徑**隨機選一條**

### Round 2（放寬 OVERLOAD）

Round 1 無可用路徑時，把含 OVERLOAD link 的路徑也納入，重新跑同樣邏輯。

### `retrans_path` 參數

若選出的路徑與 `retrans_path` 相同 → 回傳 `None`（不換路，維持原路徑）。

---

## 資料結構

| 名稱 | 型別 | 說明 |
|------|------|------|
| `k_short_paths` | `{(src, dst): [[dpid, ...], ...]}` | 預載的 k 條最短路徑 |

---

## 與其他模組的差異

| 項目 | routing_DTM_2020 | routing_DTM_self |
|------|-----------------|-----------------|
| 權重圖 | ❌ 無 | ✅ `switch_weight_map` |
| Cascade | ❌ 無 | ✅ 有 |
| NS 清單 | ❌ 無 | ✅ `非最短hop清單` |
| `on_flow_removed` | ❌ 無（不處理 timeout） | ✅ 有 |
| 選路依據 | link 狀態（即時） | link 狀態 + switch 佔用權重 |

---

## 函式對照表

| 函式 | 說明 |
|------|------|
| `admit_flow` | 新流量入口，呼叫 `select_path`，呼叫 `add_active_flow` |
| `select_path` | 兩輪選路核心（Round 1 排 OVERLOAD，Round 2 放開） |
| `load_k_short_paths` | 從 `data/k_short.txt` 載入 |
