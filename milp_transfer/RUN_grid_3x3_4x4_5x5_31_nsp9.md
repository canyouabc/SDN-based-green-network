# grid 3×3／4×4／5×5、能耗 3:1 的 Gurobi 快照實驗（2026-10-06）

對照 heuristic（SGH／SGH+NSP／ESP／ESP+NSP）在 3:1 下 9 組平均流量的結果。快照 seed 都是既有的
`seed_milpsnap_*.json`（跟 811:1 的 `results_milpsnap/` 同一批），只換成 3:1 的拓撲資料。

| 拓撲 | 平均流量 | 快照 seed | `--topo` | 題數 | 狀態 |
|---|---|---|---|---|---|
| 3×3 | 5.625 | `seed_milpsnap_grid3x3_k03.json` | `grid_3x3_31` | 766 | **要跑** |
| 3×3 | 7.5 | `seed_milpsnap_grid3x3_low.json` | `grid_3x3_31` | 899 | **要跑** |
| 3×3 | 9.375 | `seed_milpsnap_grid3x3_k05.json` | `grid_3x3_31` | 1038 | **要跑** |
| 4×4 | 7.5 | `seed_milpsnap_grid4x4_xlow.json` | `grid_4x4_31` | 974 | **要跑** |
| 4×4 | 11.25 | `seed_milpsnap_grid4x4_k03.json` | `grid_4x4_31` | 1148 | **要跑** |
| 4×4 | 15 | `seed_milpsnap_grid4x4_low.json` | `grid_4x4_31` | 1272 | **要跑** |
| 5×5 | 15 | `seed_milpsnap_grid5x5_xlow.json` | `grid_5x5_31` | — | 已有 |
| 5×5 | 22.5 | `seed_milpsnap_grid5x5_k03.json` | `grid_5x5_31` | 1421 | **要跑** |
| 5×5 | 30 | `seed_milpsnap_grid5x5_low.json` | `grid_5x5_31` | — | 已有 |

- 新增拓撲資料 `data/grid_3x3_31/`、`data/grid_4x4_31/`（switch=3、link=1，link_bw 與 811:1 版相同），
  host 對應已加進 `milp_energy_saving.py` 的 `_BORDER_GRID_N`
- 結果放 `results_milpsnap_31/`；參數沿用：`--time-limit 60`、不設 `--mip-gap`

## 執行（在 `milp_transfer/` 底下）

```
python milp_energy_saving.py --topo grid_3x3_31 --seed-path seed_milpsnap_grid3x3_k03.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid3x3_k03_results.csv
python milp_energy_saving.py --topo grid_3x3_31 --seed-path seed_milpsnap_grid3x3_low.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid3x3_low_results.csv
python milp_energy_saving.py --topo grid_3x3_31 --seed-path seed_milpsnap_grid3x3_k05.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid3x3_k05_results.csv
python milp_energy_saving.py --topo grid_4x4_31 --seed-path seed_milpsnap_grid4x4_xlow.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid4x4_xlow_results.csv
python milp_energy_saving.py --topo grid_4x4_31 --seed-path seed_milpsnap_grid4x4_k03.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid4x4_k03_results.csv
python milp_energy_saving.py --topo grid_4x4_31 --seed-path seed_milpsnap_grid4x4_low.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid4x4_low_results.csv
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_k03.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_k03_results.csv
```

跑完確認 csv 的 `topo` 欄是 `*_31`、`status` 大多是 `OPTIMAL`，commit `results_milpsnap_31/*.csv` 並 push 回來。
