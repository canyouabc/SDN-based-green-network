# GEANT、能耗 3:1 的 Gurobi 快照實驗（2026-10-06）

對照 heuristic（SGH／SGH+NSP／ESP／ESP+NSP，皆開 LINK_WEIGHT）在 3:1 下平均流量 3／5／7 的結果。
快照 seed 是既有的 `seed_milpsnap_geant_k0{3,5,7}.json`（跟 811:1 的 `results_milpsnap/` 同一批），只換成 3:1 的拓撲資料。

| 平均流量 | 快照 seed | `--topo` | 題數 |
|---|---|---|---|
| 3 | `seed_milpsnap_geant_k03.json` | `geant_31` | 493 |
| 5 | `seed_milpsnap_geant_k05.json` | `geant_31` | 710 |
| 7 | `seed_milpsnap_geant_k07.json` | `geant_31` | 917 |

- 新增拓撲資料 `data/geant_31/`（switch=3、link=1，link_bw 與 `geant` 相同）；GEANT 是 host:switch 1:1，
  `host_to_switch` 不用改
- 結果放 `results_milpsnap_31/`；參數沿用：`--time-limit 60`、不設 `--mip-gap`

## 執行（在 `milp_transfer/` 底下）

```
python milp_energy_saving.py --topo geant_31 --seed-path seed_milpsnap_geant_k03.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_geant_k03_results.csv
python milp_energy_saving.py --topo geant_31 --seed-path seed_milpsnap_geant_k05.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_geant_k05_results.csv
python milp_energy_saving.py --topo geant_31 --seed-path seed_milpsnap_geant_k07.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_geant_k07_results.csv
```

跑完確認 csv 的 `topo` 欄是 `geant_31`、`status` 大多是 `OPTIMAL`，commit `results_milpsnap_31/*.csv` 並 push 回來。
