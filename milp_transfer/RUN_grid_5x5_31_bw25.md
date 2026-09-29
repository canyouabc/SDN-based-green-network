# grid 5×5、能耗 3:1、每條 flow 25～50 Mbps 的 Gurobi 快照實驗（2026-09-29）

跟 `RUN_grid_5x5_31.md` **同一個拓撲、同樣的 flow（起訖點與到達時間完全相同）**，只把每條 flow 的
頻寬從 0.1～0.5 Mbps 放大到 25～50 Mbps（單條 link 容量 250 Mbps 的 10～20%），讓容量限制真的起作用。

- 快照 seed：`seed_milpsnap_grid5x5_{xxlow,xlow,low}_bw25.json`（由 `gen_milp_snapshot.py` 產生，
  已驗證同一支產生器能逐題逐段重現既有的 `seed_milpsnap_grid5x5_*.json`）
- 拓撲：`--topo grid_5x5_31`（同上一輪）
- 結果放在 `results_milpsnap_31/`，檔名多 `_bw25`，不會覆蓋上一輪
- 參數沿用：`--time-limit 60`、不設 `--mip-gap`
- mid／high 不做：估算全網最少 link 負載在 mid 尖峰達總容量 126%、high 平均 170%，物理上塞不下

**注意**：頻寬變大後容量限制會生效，可能出現：
- `no feasible solution found`（該秒的流量在容量限制下無解，節能率欄位會是 nan）
- `TIME_LIMIT(次佳解)`（60 秒內沒證明最優）

都照常寫進 csv、不影響其他題，回來後這邊會統計各有幾題再決定怎麼處理。

## 執行（在 `milp_transfer/` 底下，建議依序）

```
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_xxlow_bw25.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_xxlow_bw25_results.csv
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_xlow_bw25.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_xlow_bw25_results.csv
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_low_bw25.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_low_bw25_results.csv
```

跑完 commit `results_milpsnap_31/*_bw25_results.csv` 並 push 回來。
