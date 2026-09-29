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

---

# 第二階段：watchdog 直接告知 controller flow 結束（驗證用）

基準點：commit `c4515c6`。完整 diff：`phase2_flow_end_changes.patch`。

**目的**：reactive controller 只能靠 idle_timeout（5 秒）得知 flow 結束，sim 則是到期立刻 depart。
讓 watchdog 在 flow 到期當下直接通知 controller，驗證「偵測延遲」是否就是 Mininet／sim 差距的主因。
**真實網路做不到這件事**，只用於驗證，預設全部關閉。

| 檔案 | 改動 | 預設行為是否改變 |
|---|---|---|
| `modules/external_flow_end.py`（新） | 輪詢 `flow_end.queue`，每行 `src_mac dst_mac`：移出 active_flows + 觸發 `on_flow_removed`（cascade 風格）；不動 switch 規則（見下方版本 2b） | 否（沒 spawn 就不會執行） |
| `DTM.py` | 新旗標 `ENABLE_EXTERNAL_FLOW_END = False`、建立 `ExternalFlowEnd`、spawn `_external_flow_end_listener`（每 0.2 秒 poll） | 否 |
| `modules/startup_requirements.py` | `MonitorFlags` 加第 4 欄 `enable_external_flow_end`（`defaults=(False,)`，舊的 3 參數寫法照常可用）；`MONITOR_CONDITIONS` 加 `external_flow_end`（旗標開且 `REROUTE_STYLE` 不為 None）；註解 8→9 個執行緒 | 否 |
| `watchdog_new.py` | 新參數 `--notify-end`；`run_experiment_from_seed` 改成合併「啟動／結束」事件排序；每批開始清空 queue 檔 | 否（不加參數時事件只有啟動，順序與原本相同，已驗證） |

**版本 2a（已作廢）：邏輯移除 + 刪 switch 規則**
- 做法：通知時移出 active_flows、觸發 cascade，並對所有 switch 送 non-strict `OFPFC_DELETE`
  （match `eth_src=src, eth_dst=dst`，只刪正向），讓同 pair 重開能重新 packet-in。
- 結果（`log/real-2026-09-29_15-46-18`）：SPF 35.01%（原 33.93%，sim 35.8%），通知 149/149 送達無錯誤；
  但 iperf 尾巴封包（實際啟動晚於 watchdog 時鐘＋FIN 重送）在規則刪掉後 packet-in 被重新 admit，
  重複 admit 30→115，等於在 controller 邏輯裡又造出幽靈 flow。
- 作廢原因（使用者決定）：不該動網路實際行為。

**版本 2b（現行）：只做邏輯移除，不動 switch 規則**
- 概念：把兩層分開——
  - 網路實際行為：規則照舊靠 idle_timeout 過期（已知缺陷，保留）。
  - controller 邏輯狀態（能耗計算、cascade 選路看到的 active flows）：在理論到期那一刻移除，
    時間軸與 sim.py 的 depart 一致。
- 規則之後真的 idle 過期時，`flow_removed_handler` 查不到 entry 直接略過，不會重複移除；
  iperf 尾巴封包命中仍在的規則，不會 packet-in，不會造出幽靈 flow。
- **已知限制**：同 pair 在舊規則過期前（5 秒內）重開，新 flow 的封包直接命中舊規則、不會 packet-in，
  controller 看不到它。`seed_mininet_grid5x5_xlow_1b.json` 有 6 次（最短間隔 0.41 秒）。

**靜態驗證**（`verify_flow_end.py`，假 app／假 datapath，不需 Ryu，2b 版重跑通過）：3.8 語法；
spawn 條件（預設關／旗標開才 spawn／routing_module=None 不 spawn）；殘留內容略過；半行留到下一輪；
反方向 flow 不受影響；不對 switch 送任何 FlowMod；不在 active_flows 時略過不 cascade；
watchdog 不加旗標時 162 條啟動順序不變、加旗標多 149 條結束通知。

**實驗設定（實驗後要還原）**：`ENABLE_EXTERNAL_FLOW_END=True`、`ENABLE_WEIGHT_MAP=False`、
扁平 `data/` = grid。

**驗證用 seed（配合 2b）**：`seed_mininet_grid5x5_xlow_1b_norelaunch.json`，由 `..._1b.json` 拿掉
「同 pair 在上一條結束後 8 秒內重開」的 flow（idle 5 秒 + 3 秒緩衝；5～8 秒門檻結果相同），162 → 156 條。
sim 與 Mininet 用同一份，輸入完全一致。

sim 基準（mean_after_100，各 5 次）：SPF 36.29～36.64（平均 36.44）；SPF+ESP 38.99～39.02（平均 39.00）。

**仍存在、未處理的差異**：iperf 反向封包（dst→src）仍會被 admit 成 flow，且不會收到結束通知，
要等 idle 過期才移除；sim 沒有這些 flow。

## 第二階段結果（2b：邏輯移除，seed `_1b_norelaunch`，mean_after_100）

| | sim（5 次平均） | Mininet | 差距 | Mininet run |
|---|---|---|---|---|
| SPF | 36.44 | 35.71 | −0.73 | `log/real-2026-09-29_15-59-33` |
| SPF+ESP | 39.00 | 38.03 | −0.97 | `log/real-2026-09-29_16-08-26` |
| ESP 增益 | +2.56 | +2.32 | | |

對照：同 SPF、靠 idle_timeout 偵測時差距 −1.9（第一階段）。兩次 run 通知皆 144/144 處理、0 錯誤。

**剩餘差距的已知來源（皆 Mininet 特有，非演算法差異）**：
- **反向規則誤刪（程式碼已確認存在，影響量未量化）**：`path_installer.install_flows_for_path` 每台 switch
  另裝 match `src=dst_mac, dst=src_mac` 的反向規則，priority 沿用正向 pair、帶 `OFPFF_SEND_FLOW_REM`。
  它幾乎沒流量，5 秒後 idle 過期送 FlowRemoved，`DTM.py flow_removed_handler` 只看 MAC＋priority，
  會把同時存活的反方向 flow (b,a) 誤當成過期移除。對應 log 中 `admit → idle 移除 → 再 admit` 的 pattern。
  這是 DTM 既有設計問題，不是這次驗證引入的；之前所有 Mininet 實驗都受影響。
- iperf 反向封包被 admit 成 flow（SPF 51 條／ESP 78 條），不會收到結束通知。
- 重複 admit：SPF 39／ESP 47（上述兩者混合，未逐一歸因）。

---

# 第三階段：通知機制關閉，idle_timeout 5 → 1 秒（實驗設定，實驗後要還原）

使用者原本要 0.5 秒，但 OpenFlow `idle_timeout` 是 uint16 整數秒（0 = 永不過期），最小只能 1 秒。
0.1 Mbps UDP 約每 0.12 秒一個封包，1 秒不會把存活中的 flow 誤判過期。

| 位置 | 改前 → 改後 |
|---|---|
| `modules/packet_handler_v1.py:110`、`:197`（新 flow 安裝路徑） | `idle_timeout=5` → `idle_timeout=1` |
| `modules/routing_DTM_sorted.py:473`、`:655`（cascade 換路） | `idle_timeout=5` → `idle_timeout=1` |

未動：`routing_DTM_self.py:508`、`DTM.py:323`（本實驗不會執行到）；`packet_handler_v1` 的 priority 1
臨時 DROP 規則（`idle_timeout=3/5`）。

設定：`ENABLE_EXTERNAL_FLOW_END=False`、watchdog 不加 `--notify-end`、seed `_1b_norelaunch`
（與 2b 同一份，可直接對照 sim 36.44／39.00）。

預期副作用：反向規則也變成 1 秒過期，「反向規則誤刪反方向 flow」可能更頻繁。

**第三階段結果**（`log/real-2026-09-29_16-20-45`，seed `_1b_norelaunch`）：SPF 34.87%（sim 36.44，差 −1.57；
對照 idle=5 秒 −1.87、通知模式 −0.73）。只改善約 0.3，是否超出單次 run 的雜訊未確認。
**已還原**：4 處 `idle_timeout=1` → 5（`packet_handler_v1.py` 與 commit `c4515c6` 無差異）。

---

# 第四階段：Oracle 模式（取代第二階段的 `external_flow_end`）

**前提**：比照多數論文，controller 事先知道每條 flow 的起訖、頻寬與結束時間。
controller 的 active flow 完全由 watchdog 告知，不再依賴 packet-in／FlowRemoved。
完整 diff：`phase4_flow_oracle_changes.patch`（基準 `c4515c6`）。

| 檔案 | 改動 | 預設行為是否改變 |
|---|---|---|
| `modules/flow_oracle.py`（新；取代未 commit 的 `external_flow_end.py`，已刪） | 輪詢 `flow_oracle.queue`：`start src dst bw` → 寫 `app._flow_sizes`、`admit_flow`、主動裝規則（idle 5）、回寫 priority；`end src dst` → 刪 `_flow_sizes`、`remove_active_flow`、`on_flow_removed`（順序同 `sim.Simulator.depart`）；switch 規則不動 | 否（旗標關時不建立） |
| `DTM.py` | `ENABLE_FLOW_ORACLE = False`；`self.flow_oracle = FlowOracle(...) if 旗標 else None`；監聽執行緒每 0.05 秒 poll；`flow_removed_handler` 開頭：oracle 模式直接 return | 否 |
| `modules/packet_handler_v1.py` | TCP/UDP：`pair in active_flows` 檢查之後、admit 之前，oracle 模式直接 return（不 admit iperf 回傳報告等非 oracle 流量） | 否（`flow_oracle` 為 None） |
| `modules/startup_requirements.py` | `MonitorFlags` 第 4 欄改名 `enable_flow_oracle`（`defaults=(False,)`）；條件 `flow_oracle` | 否 |
| `watchdog_new.py` | `--notify-end` 改為 `--oracle`：每條 flow 先寫 `start`（含 bw）再 launch；到期寫 `end` | 否（不加參數時只有 launch，順序不變） |

**oracle 模式下消除的差異**：
- flow 開始不靠 packet-in → 同 pair 在舊規則過期前重開也能正確 admit（新規則 priority 較高），不需過濾 seed
- FlowRemoved 不影響記帳 → 反向規則誤刪、idle 提早移除都不再影響 active_flows
- 非 oracle 流量不 admit → iperf 回傳報告不再變成反向 flow
- `_flow_sizes` 有值 → sorted 的 DANGER 前瞻檢查、HDF/SDF 排序在 Mininet 也生效（`app.link_bw` 與 sim 讀同一份
  data、唯讀，輸入一致）

**仍存在的差異**：事件時間（sim 整秒批次處理 vs Mininet 實際時間）、鏈路負載來源（Mininet 為量測值）、
並列候選 random。另：oracle start 與 iperf 首封包之間若有封包先到，會被 packet-in 直接丟棄（UDP，不影響記帳）。

**靜態驗證**（`verify_flow_oracle.py`，假 app，不需 Ryu，全過）：3.8 語法；spawn 條件；DTM／packet_handler
守門位置（原始碼檢查：在動 active_flows／admit 之前）；start 在 admit 前寫入 bw、priority／idle 正確、
未發現 host 略過；end 順序同 sim、刪 `_flow_sizes`；同 pair 重開直接 admit 且 priority 遞增；
半行／殘留處理；watchdog 不加旗標行為不變、加旗標每條 start 皆在 launch 之前、檔案往返解析 bw／MAC 全對。

**實驗設定（實驗後要還原）**：`ENABLE_FLOW_ORACLE=True`、`ENABLE_WEIGHT_MAP=False`、扁平 `data/` = grid。
seed 用原本的 `seed_mininet_grid5x5_xlow_1b.json`（sim：SPF 35.68～35.94、SPF+ESP 38.46）。

## 第四階段結果（oracle 模式，seed `seed_mininet_grid5x5_xlow_1b.json`，mean_after_100）

| | sim（5 次） | Mininet oracle | 差距 | Mininet run |
|---|---|---|---|---|
| SPF | 35.68～35.94（平均 35.80） | 35.82 | +0.02 | `log/real-2026-09-29_16-42-26` |
| SPF+ESP | 38.46（5 次相同） | 38.37 | −0.09 | `log/real-2026-09-29_16-50-50` |
| ESP 增益 | +2.66 | +2.55 | | |

兩次 run：`ORACLE_START` 162/162、`ORACLE_END` 149/149 全部處理，`FLOW_NEW` 162（無重複 admit、無反向 flow），
`total_flows` 162 與 sim 相同，0 錯誤。

**結論**：在「controller 事先知道 flow 起訖／頻寬／結束」的前提下，Mininet（真實 OVS 轉送 + Ryu 安裝規則）
與 sim 的節能率一致（SPF 落在 sim 5 次範圍內，ESP 差 0.09）。先前的差距來自 reactive SDN 取得 flow 資訊的方式
（packet-in、idle_timeout、反向規則、iperf 報告封包），不是選路演算法本身。
範圍限制：grid 5x5、低負載（0.1～0.5 Mbps，DANGER 前瞻檢查未觸發）、sorted SPF／SPF+ESP、單一 batch、Mininet 各 1 次。

**實驗後還原**：`ENABLE_FLOW_ORACLE=False`、`ENABLE_WEIGHT_MAP=True`、`PRESEED_ENDPOINTS=False`、扁平 `data/` = cap。

---

# 第五階段：反向規則誤刪 bug 的兩種修法（reactive 模式，oracle 關閉）

**bug**：`path_installer.install_flows_for_path` 為 (a,b) 裝的反向規則（match `src=b, dst=a`，priority 沿用 (a,b)、
帶 `OFPFF_SEND_FLOW_REM`）在 UDP 下沒流量、5 秒必過期；`DTM.py flow_removed_handler` 只看 MAC＋priority，
若 (b,a) 同時 active 且 priority 不高於它，會把 (b,a) 誤刪並觸發 cascade → 能耗漏算、節能率高估。

| 修法 | 改動 |
|---|---|
| A | `path_installer.py` 反向規則的 `OFPFlowMod` 拿掉 `flags=ofproto.OFPFF_SEND_FLOW_REM`（過期不通知） |
| B | 反向規則加 cookie，`flow_removed_handler` 見到該 cookie 就忽略（過期會通知但被忽略） |

兩者都不改轉送行為。對照組：`log/real-2026-09-29_15-20-48`（priority 修正後、reactive、seed `_1b`）
SPF 33.93%、重複 admit 30；sim 35.8。

實驗設定：`ENABLE_FLOW_ORACLE=False`、`ENABLE_WEIGHT_MAP=False`、`PRESEED_ENDPOINTS=False`、data=grid、
watchdog 不加 `--oracle`。

**修法 A 結果**（`log/real-2026-09-29_17-04-37`）：SPF 36.06%（對照 33.93、sim 35.8），FLOW_NEW 206（對照 229）、
重複 admit 21（30）、反向 58（53）、「idle 移除後又被 admit」的 pair 21（24）。
**與假設方向相反**（預期修掉誤刪 → 節能率下降，實際上升 2.1），且「移除後再 admit」幾乎沒變 →
反向規則誤刪不是該 pattern 的主因。reactive 模式的 run-to-run 波動從未量過，+2.1 可能大多是雜訊，未下結論。

**修法 B 實作**：A 已還原；`path_installer.py` 新增 `REVERSE_RULE_COOKIE = 0x5245`，反向規則帶此 cookie
（仍送 FLOW_REM）；`DTM.py` import 該常數，`flow_removed_handler` 在 priority 檢查後
`if msg.cookie == REVERSE_RULE_COOKIE: return`。正向規則 cookie 仍為 0；`flow_stats` 查詢 cookie_mask=0 不受影響。

**修法 B 結果**（`log/real-2026-09-29_17-09-25`）：SPF 36.34%，FLOW_NEW 208、重複 admit 23、反向 58、
「idle 移除後又被 admit」的 pair 22 —— 與 A 一致。

**第五階段結論（使用者定調：先維持、低優先，之後再 debug）**：
- 保留修法 B（反向規則帶 `REVERSE_RULE_COOKIE`、`flow_removed_handler` 忽略）：反向規則過期本來就不代表任何
  flow 結束，邏輯上正確，不以數字為保留依據。
- A／B 使 reactive SPF 從 33.93 → 36.1～36.3（sim 35.8），但**方向與假設相反**（修掉誤刪應使節能率下降），
  且仍有約 5 秒偵測延遲與 58 條 iperf 反向 flow，推測是誤差互相抵銷，不能當成「修好就對上 sim」的證據。
  能穩定對上 sim 的是 oracle 模式。
- 待 debug：(1) 在 B 的 cookie 分支加 log 數「原本會誤刪」的次數；(2) 對照組（未修）重跑，確認 33.93 是否偏低；
  (3) 查「idle 移除後又被 admit」的真正原因（與反向規則無關）。

## 附：同一份 xlow batch 1 與 Gurobi 最優解逐秒對照

Gurobi 快照結果 `milp_transfer/results_milpsnap/seed_milpsnap_grid5x5_xlow_results.csv`（來源即 `seed_000_grid5x5_xlow`）。

| | 節能率 | 與最優差 | 追平最優的秒數 |
|---|---|---|---|
| Gurobi 最優 | 41.36 | — | — |
| sim SPF+ESP | 38.45 | −2.9 | 36/151 |
| Mininet oracle SPF+ESP | 38.26 | −3.1 | 32/151 |
| sim SPF | 35.60 | −5.8 | 19/151 |
| Mininet oracle SPF | 35.65 | −5.7 | 22/151 |

sim 與 Mininet oracle 逐秒：ESP 131/151 秒完全相同（|差| 平均 0.61）；SPF |差| 平均 2.33 但整段平均差 −0.05
（並列候選 random，逐秒路徑常不同、平均抵銷）。

grid 5x5 各流量等級（10 batch 平均，sim）：xxlow Gurobi 47.29／ESP 44.92／SPF 42.42；xlow 41.68／38.80／35.71；
low 37.94／36.89／35.18；mid 36.70／36.49／35.77；high 36.48／36.44／36.33 —— 流量越低節能率越高、與最優差距越大，
高流量收斂到 36%（內部 9/25 台可睡）。xlow 是 heuristic 與最優差距最大的一檔。

**目前狀態**：實驗設定已還原（`ENABLE_FLOW_ORACLE=False`、`ENABLE_WEIGHT_MAP=True`、`PRESEED_ENDPOINTS=False`、
data=cap）；保留 oracle 功能（預設關）與修法 B。
