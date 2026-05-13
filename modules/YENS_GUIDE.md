# Yen's K-Shortest Paths 使用指南

## 概述

本模組提供 Yen's k-shortest paths 演算法實現，用於在網絡拓撲中計算 k 條最短路徑。

## 函數簽名

```python
yens_k_shortest_paths(
    k, src, dst, first_port, final_port,
    switches, adjacency, link_delay, link_energy, link_bw,
    link_used_bw, switch_energy, get_link_delay,
    required_bw=0
)
```

## 參數說明

| 參數名 | 類型 | 說明 |
|--------|------|------|
| `k` | int | 要找的路徑數量 |
| `src` | int | 源 switch DPID |
| `dst` | int | 目標 switch DPID |
| `first_port` | int | 源 switch 的入埠號 |
| `final_port` | int | 目標 switch 的出埠號 |
| `switches` | list | 拓撲中所有 switch 的 DPID 列表 |
| `adjacency` | dict | 鄰接表，格式為 `{src: {dst: port_number}}` |
| `link_delay` | dict | 鏈路延遲字典，格式為 `{(src, dst): delay}` |
| `link_energy` | dict | 鏈路能耗字典，格式為 `{(src, dst): energy}` |
| `link_bw` | dict | 鏈路頻寬字典，格式為 `{(src, dst): bandwidth}` |
| `link_used_bw` | dict | 鏈路已用頻寬字典 |
| `switch_energy` | dict | 交換機能耗字典，格式為 `{switch_id: energy}` |
| `get_link_delay` | callable | 函數引用，用於查詢鏈路延遲 |
| `required_bw` | int | 所需頻寬（Mbps），預設 0（不檢查） |

## 返回值

```python
[
    (path_list_1, switch_path_1),
    (path_list_2, switch_path_2),
    ...
]
```

其中：
- `path_list`: 列表，包含 `(switch_id, in_port, out_port)` 元組
- `switch_path`: switch DPID 序列，如 `[1, 2, 3]` 表示路由 `s1->s2->s3`

## 使用示例

```python
from modules import Base_Dijkstra

# 定義拓撲
switches = [1, 2, 3, 4]
adjacent = {
    1: {2: 1, 4: 2},
    2: {1: 1, 3: 2},
    3: {2: 1, 4: 2},
    4: {1: 1, 3: 2},
}

# 定義能耗（鏈路和交換機）
link_energy = {
    (1, 2): 10, (2, 1): 10,
    (2, 3): 5,  (3, 2): 5,
    (1, 4): 12, (4, 1): 12,
    (4, 3): 12, (3, 4): 12,
}
switch_energy = {1: 1, 2: 2, 3: 1, 4: 2}

# 其他必需的參數
link_delay = {(u, v): 1 for u, v in link_energy.keys()}
link_bw = {}
link_used_bw = {}

def get_link_delay_func(u, p):
    return 1

# 計算 2 條最短路徑
paths = Base_Dijkstra.yens_k_shortest_paths(
    k=2, src=1, dst=3, first_port=0, final_port=0,
    switches=switches, adjacency=adjacency,
    link_delay=link_delay, link_energy=link_energy,
    link_bw=link_bw, link_used_bw=link_used_bw,
    switch_energy=switch_energy, get_link_delay=get_link_delay_func
)

# 輸出結果
for i, (path_list, switch_path) in enumerate(paths, 1):
    print(f"Path {i}: {switch_path}")
```

## 演算法特性

### 優點
1. **多路徑支持**：返回最多 k 條不同的路徑
2. **能耗優化**：考慮鏈路和交換機能耗
3. **頻寬約束**：可選支持頻寬檢查
4. **成本排序**：返回的路徑按成本遞增排序

### 局限
1. **路徑不保證完全不相交**：可能共享某些鏈路或交換機
2. **找不到 k 條路徑時**：返回可用的所有路徑（< k）
3. **計算複雜度**：隨 k 增加而線性增長

## 實現細節

### 演算法流程
1. **初始化**：第一次迭代計算最短路徑
2. **路徑禁用**：已找到的路徑上的邊和交換機設為極高能耗（999999）
3. **迭代尋找**：重複調用 Dijkstra，直到找到 k 條路徑或無可用路徑
4. **去重**：按 `path_list` 完整比對避免重複
5. **排序返回**：按成本遞增排序

### 時間複雜度
- O(k × |V|²)，其中 k 是路徑數，|V| 是 switch 數量

## 與現有系統的集成

目前 `routing_base.py` 使用單路徑 `get_min_delay_path()`。集成 k-shortest paths 的建議方案：

1. **直接替換**（簡單）：
   ```python
   paths = yens_k_shortest_paths(k=3, ...)
   use_path = paths[0]  # 選用最優路徑
   ```

2. **負載均衡**（適合高流量）：
   ```python
   paths = yens_k_shortest_paths(k=3, ...)
   for demand in demands:
       path = paths[hash(demand) % len(paths)]  # 輪流使用
   ```

3. **故障轉移**（可靠性）：
   ```python
   paths = yens_k_shortest_paths(k=3, ...)
   try:
       install_flows(paths[0])
   except:
       install_flows(paths[1])  # 使用備用路徑
   ```

## 測試

執行測試：
```bash
python test_yens.py
```

覆蓋的測試場景：
- ✓ k=1（與標準 Dijkstra 對比）
- ✓ k=2（驗證替代路徑）
- ✓ k>可用路徑數（返回所有可用路徑）
- ✓ 無法達到目標（返回空列表）
