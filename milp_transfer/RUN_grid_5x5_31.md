# grid 5×5、能耗 3:1 的 Gurobi 快照實驗（2026-09-29）

跟原本 `grid_5x5`（811:1，146W／0.18W）**同一個拓撲、同一批快照 seed**，只把能耗改成
switch=3、link=1（比照 `geant_31`），用來對照 heuristic 在 3:1 下的結果
（見 `docs/link_weight_experiment_2026-09-29.md`）。

- 拓撲名稱：`--topo grid_5x5_31`（資料在 `data/grid_5x5_31/`；host 對應已加進
  `_BORDER_GRID_N`，與 `grid_5x5` 相同）
- 結果放在 `results_milpsnap_31/`，**不要**覆蓋原本 811:1 的 `results_milpsnap/`
- 參數沿用上次：`--time-limit 60`、不設 `--mip-gap`

## 執行（在 `milp_transfer/` 底下）

```
mkdir results_milpsnap_31
```

**優先跑 xlow**（對應 heuristic 3:1 實驗用的 `seed_000_grid5x5_xlow`，1287 題）：

```
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_xlow.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_xlow_results.csv
```

有時間的話再跑其他流量等級（每行一個，檔名規則相同）：

```
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_xxlow.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_xxlow_results.csv
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_low.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_low_results.csv
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_mid.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_mid_results.csv
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_high.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_high_results.csv
```

跑完後確認 csv 的 `topo` 欄是 `grid_5x5_31`、`status` 大多是 `OPTIMAL`，然後
commit `results_milpsnap_31/*.csv` 並 push 回來。

## 回來之後（這台電腦）

```
python combine_milp_snapshot.py milp_transfer/seed_milpsnap_grid5x5_xlow.json milp_transfer/results_milpsnap_31/seed_milpsnap_grid5x5_xlow_results.csv log/milpsnap31-grid5x5_xlow
```

（第三個參數要指定：預設輸出資料夾由 seed 檔名決定，不指定會蓋掉 811:1 的整理結果。）

得到逐 batch 的 `mean_after_100`，直接跟 heuristic 3:1 的結果對照
（SPF 44.13、SPF+link 權重 44.62，10 batch × 5 次平均）。
