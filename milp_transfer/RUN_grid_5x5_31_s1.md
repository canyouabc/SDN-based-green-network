# grid 5×5、能耗 3:1、流量 seed=1 的 Gurobi 快照實驗（2026-09-30）

原本 3:1 的快照（`seed_milpsnap_grid5x5_{level}.json`）都來自流量 seed=0。這批換成 **seed=1**
（完全不同的一組 flow），用來確認「SGH 在 low→mid 節能率反常上升、ESP 修正此現象」不是 seed 0 的特例，
並提供 MILP 最佳解做對照。頻寬仍是 0.1～0.5 Mbps（與上一輪相同，求解應該很快）。

- 快照 seed：`seed_milpsnap_grid5x5_{xlow,low,mid}_s1.json`（`gen_milp_snapshot.py` 由
  `seed_001_grid5x5_{xlow,low,mid}.json` 產生）
- 拓撲：`--topo grid_5x5_31`
- 結果放在 `results_milpsnap_31/`，檔名多 `_s1`
- **優先順序**：這批比 `RUN_grid_5x5_31_bw25.md`（25～50 Mbps）優先；bw25 那批若還沒跑可以先跑這批

## 執行（在 `milp_transfer/` 底下）

```
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_xlow_s1.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_xlow_s1_results.csv
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_low_s1.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_low_s1_results.csv
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_mid_s1.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_mid_s1_results.csv
```

跑完 commit `results_milpsnap_31/*_s1_results.csv` 並 push 回來。
