# Mininet 驗證 sim 節能率：改動紀錄（2026-09-29）

基準點：commit `4aef31b`（tag `checkpoint/pre-mininet-validation-2026-09-29`）。
以下是之後所有改動，逐項標明「性質／影響範圍／實驗後要不要還原」。

本資料夾檔案：
- `code_changes.patch`：程式碼與文件的完整 diff（`git diff 4aef31b -- CLAUDE.md modules/routing_DTM_sorted.py`）
- `routing_DTM_sorted.before.py` / `.after.py`：改前、改後完整檔案

還原全部：`git checkout 4aef31b -- CLAUDE.md modules/routing_DTM_sorted.py data/`

---

## 1. `modules/routing_DTM_sorted.py`：priority 漏傳（bug 修正，要保留）

| | 內容 |
|---|---|
| 位置 | 第 482、665 行（cascade 換路的兩處） |
| 改前 | `self.app.add_active_flow(fa, fb, selected, is_reroute=True)` |
| 改後 | `self.app.add_active_flow(fa, fb, selected, is_reroute=True, priority=new_priority)` |
| 參照 | `routing_DTM_self.py:524`、`DTM.py:326`（2020/dijkstra）本來就這樣寫，sorted 漏了 |

**bug 機制**：換路後 `active_flows[pair]['priority']` 變成 `None` →
約 5 秒後舊路徑 switch 的 rule idle 過期 → `DTM.py:501` 的「比現行 priority 低就忽略」
判斷因 `None` 被跳過 → flow 被移出 `active_flows`，但流量還在新路徑上跑 →
**能耗計算漏算，節能率高估**。

**證據**（第一次 Mininet SPF run，`log/real-2026-09-29_14-54-04/`）：
每 batch 約 47 條 flow 在 seed 存活期間內被「移除」後又以相同路徑重新 admit；
Mininet 節能率 37.50% > sim 36.07%（照理 Mininet 因 idle_timeout 延遲應偏低）。

**影響範圍**：
- `priority` 欄位唯一讀取者是 `DTM.py:501`（`flow_registry.py:108` 讀的是另一個 dict `flow_priority`）。
- **sim.py 不受影響**：`MockApp.add_active_flow` 收 `priority` 但不存、不用。過去所有 sim 數據有效。
- 驗證：`py_compile` 過；sim 單 batch smoke test 正常（ENERGY 151 行、HISTORY total_flows=162）。

## 2. `modules/routing_DTM_sorted.py`：`ENABLE_WEIGHT_MAP` True → False（實驗設定，**實驗後要還原**）

| | 內容 |
|---|---|
| 位置 | 第 11 行 |
| 目的 | 驗證的兩組是「SPF」與「SPF+ESP」，都不開權重圖 |
| ⚠️ 副作用 | `sim.py` CLI 直接跑時也會吃到這個預設值（`sweep_sorted.py` 會從 BASELINE 重設，不受影響） |

另：跑 ESP 組時會把第 23 行 `PRESEED_ENDPOINTS` 改成 `True`，**同樣實驗後要還原成 `False`**。

## 3. 扁平 `data/*.txt` 換成 grid 版（實驗設定，**實驗後要還原**）

`k_short.txt`／`k_short_dist.txt`／`link_bw.txt`／`link_energy.txt`／`switch_energy.txt`
從 `data/grid/` 複製覆蓋（原本 = `data/cap/`）。已用 `cmp` 確認與 `data/grid/` 逐位元組相同，
`data/grid/` 本身未被改動。`base_weight_map.txt` 未動（sorted 不讀它）。

還原：`cp data/cap/{k_short,k_short_dist,link_bw,link_energy,switch_energy}.txt data/`

## 4. `CLAUDE.md`：watchdog 啟動指令去掉 `sudo`（文件修正，要保留）

`sudo python3 watchdog_new.py` → `python3 watchdog_new.py`，並補說明。
原因：以 root 執行會找 `/tmp/tmux-0`，但 gnome-terminal 開的 tmux 在使用者 socket，
導致 Ryu log 接不到、`[LINK_READY]` 逾時（使用者確認平常就不加 sudo）。

## 5. 新增檔案

- `seed_mininet_grid5x5_xlow_3b.json`：`seed_000_grid5x5_xlow.json` 前 3 個 batch
- `seed_mininet_grid5x5_xlow_1b.json`：同上只取 batch 1（簡易版實驗用）

---

## 已知但未處理的 Mininet／sim 差異

- **iperf 反向 flow**：每 batch 約 60～70 條 dst→src 被當新 flow admit（推測是 iperf UDP
  server 結束時回傳的報告封包）。會讓 Mininet 節能率偏低，sim 無此現象。
- 每 batch 1～2 條 seed flow 在 Mininet 從未被 admit（可能是 tmux 送指令漏掉）。

## sim 基準（簡易版：`seed_mininet_grid5x5_xlow_1b.json`，mean_after_100，各跑 5 次）

| 設定 | 5 次結果 | 範圍 |
|---|---|---|
| SPF | 35.68 / 35.76 / 35.92 / 35.94 / 35.71 | 35.68～35.94 |
| SPF+ESP | 38.46 ×5 | 38.46 |

## 結果（grid 5x5、xlow batch 1、`ENABLE_WEIGHT_MAP=False`、mean_after_100）

| | sim | Mininet | Mininet run |
|---|---|---|---|
| SPF（bug 修正前，作廢） | 35.8 | 37.50（3 batch 平均） | `log/real-2026-09-29_14-54-04` |
| SPF | 35.8 | **33.93** | `log/real-2026-09-29_15-20-48` |
| SPF+ESP | 38.46 | **37.51** | `log/real-2026-09-29_15-28-24` |
| ESP 增益 | +2.7 | +3.6 | |

**結論**：Mininet 重現了 sim 的趨勢（ESP > SPF，增益量級相近）；Mininet 絕對值系統性低
1～2 個百分點，與 iperf 反向 flow（SPF 53 條／ESP 81 條）、idle_timeout 延遲一致。
單一 batch、Mininet 各跑 1 次，屬驗證性質，不是統計結論。

**未解**：修正後仍有「無 cascade、idle 移除後同路徑重新 admit」（SPF 30 筆／ESP 47 筆），
DTM log 無時間戳，無法判斷是 iperf 結束殘留封包，還是存活中的 flow 被提早移除。

## 還原狀態（實驗後）

- `ENABLE_WEIGHT_MAP` → `True`、`PRESEED_ENDPOINTS` → `False`：已還原
- 扁平 `data/*.txt` → cap 版：已還原（`git diff 4aef31b -- data/` 為空）
- 保留：第 1 項 priority 修正、第 4 項 CLAUDE.md
