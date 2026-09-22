# MILP 結果回報格式

跑完 `milp_energy_saving.py` 之後，麻煩把結果整理成一份 CSV（檔名例如
`milp_results.csv`），欄位如下，**每個 (topo, batch) 一列**：

```
topo,level,seed_file,batch,n_switches,n_links,n_flows,energy_saving_percent,mip_gap,solve_time_sec,status
grid_2x2,low,seed_milp_grid2x2_low.json,1,4,4,1,0.03,0.0,0.01,OPTIMAL
grid_2x2,mid,seed_milp_grid2x2_mid.json,1,4,4,2,25.03,0.0,0.01,OPTIMAL
...
```

**2026-09-17 更新：種子檔已經改成每個拓樸各有 `low`／`mid`／`high` 三個流量強度**（對應論文的 50%/25%/12.5% 拓樸理論流量上限），檔名多了 `_low`／`_mid`／`_high` 後綴，CSV 多一欄 `level` 記錄是哪個強度，其餘格式不變。

## 欄位說明

| 欄位 | 說明 |
|---|---|
| `topo` | 拓樸名稱，用跟 `--topo` 參數一樣的字串（`grid_2x2`／`grid_3x3`／`grid_4x4`／`grid_4x4_allhosts`／`grid_5x5`） |
| `seed_file` | 用的種子檔檔名 |
| `batch` | 這個種子檔裡的第幾個 batch（1-based，對應 seed json 的 `batch_id`） |
| `n_switches` / `n_links` | 這個拓樸的 switch／link 總數（跑起來 `milp_energy_saving.py` 會自動印出來，照抄即可） |
| `n_flows` | 這個 batch 有幾條 flow |
| `energy_saving_percent` | `result['energy_saving_percent']`，MILP 求出的最優節能率 |
| `mip_gap` | `result['mip_gap']`，0 代表證明最優，非 0 代表卡 TimeLimit 提前停下的次佳解 |
| `solve_time_sec` | 這個 batch 實際求解花的秒數 |
| `status` | `result['status_name']`（`OPTIMAL`／`TIME_LIMIT(次佳解)`／`SUBOPTIMAL`） |

## 目前這批種子檔（每個拓樸 low/mid/high 三組，各 10 個 batch）

| topo | low (n_flows) | mid (n_flows) | high (n_flows) |
|---|---|---|---|
| grid_2x2 | 1 | 2 | 4 |
| grid_3x3 | 8 | 15 | 30 |
| grid_4x4 | 15 | 30 | 60 |
| grid_4x4_allhosts | 30 | 60 | 120 |
| grid_5x5 | 30 | 60 | 120 |

檔名規則：`seed_milp_<topo>_<level>.json`，例如 `seed_milp_grid4x4_high.json`。

`milp_energy_saving.py` 目前一次只吃一個 `--batch-id`，跑完 10 個 batch 需要迴圈呼叫 10 次（或直接改 `solve()` 的呼叫端寫個小迴圈也可以，看你們那邊方便）。

## 回傳方式

直接把整理好的 CSV 內容貼在對話裡就好（不用真的傳檔案過來），我這邊會自己存成檔案，跟我這邊 `sweep_sorted.py` 產出的 `sweep_comparison.csv` 對齊比較。
