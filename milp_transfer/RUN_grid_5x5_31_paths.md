# grid 5×5、能耗 3:1、xlow：重跑並輸出最優路徑（2026-10-06）

跟 `RUN_grid_5x5_31.md` 的 xlow **同一份 seed、同一個拓撲、同樣參數**，唯一差別是多加
`--paths-out`，把每一題的最優路徑存下來，回來後用 `combine_milp_snapshot.py --paths`
產生 `snap_player.html` 能播放的 snap 檔。之前的結果 csv 只存節能率，沒有路徑，所以要重解。

- 快照 seed：`seed_milpsnap_grid5x5_xlow.json`（1287 題，上次全部 OPTIMAL）
- 拓撲：`--topo grid_5x5_31`
- 參數沿用：`--time-limit 60`、不設 `--mip-gap`
- 新輸出 `results_milpsnap_31/seed_milpsnap_grid5x5_xlow_paths.jsonl`：一行一題，
  記錄每條 flow 的 host／頻寬／最優路徑，以及每條 link 的使用率
- csv 另存成 `_rerun_results.csv`，**不要**覆蓋上次的 `seed_milpsnap_grid5x5_xlow_results.csv`；
  回來後兩份節能率逐題對照，確認這次重解跟上次一致

## 執行前

先 `git pull`，確認 `milp_energy_saving.py` 有 `--paths-out` 參數：

```
python milp_energy_saving.py --help
```

輸出裡要看得到 `--paths-out`。

## 執行（在 `milp_transfer/` 底下）

```
python milp_energy_saving.py --topo grid_5x5_31 --seed-path seed_milpsnap_grid5x5_xlow.json --all-batches --time-limit 60 --csv-out results_milpsnap_31/seed_milpsnap_grid5x5_xlow_rerun_results.csv --paths-out results_milpsnap_31/seed_milpsnap_grid5x5_xlow_paths.jsonl
```

跑完最後會印出兩行「已存檔」（`.jsonl` 和 `.csv` 各一行）。

無解（`no feasible solution found`）或 `TIME_LIMIT(次佳解)` 的題目照常寫進兩個檔案、不影響其他題；
snap 檔那邊會把它們標成「無解」／「次佳解」顯示。

## 跑完

commit 這兩個檔案並 push 回來：

- `results_milpsnap_31/seed_milpsnap_grid5x5_xlow_rerun_results.csv`
- `results_milpsnap_31/seed_milpsnap_grid5x5_xlow_paths.jsonl`

## 回來後（這邊做）

```
python combine_milp_snapshot.py milp_transfer/seed_milpsnap_grid5x5_xlow.json milp_transfer/results_milpsnap_31/seed_milpsnap_grid5x5_xlow_rerun_results.csv log/milpsnap31-grid5x5_xlow_paths --paths milp_transfer/results_milpsnap_31/seed_milpsnap_grid5x5_xlow_paths.jsonl
```

`log/milpsnap31-grid5x5_xlow_paths/` 底下會有 `b1-snap.txt`～`b10-snap.txt`，用 `snap_player.html` 開。
