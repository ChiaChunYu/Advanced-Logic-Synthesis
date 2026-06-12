# Case Recipes

每個 case 一個 JSON 檔，記錄該 case 的優化狀態與歷史，加速後續優化並輔助復現。

由 `student/recipe_store.py` 自動維護：

```bash
python3 student/recipe_store.py --refresh   # 從 output/ 與 logs/ 更新所有 recipe
python3 student/recipe_store.py --summary   # 列出所有 case（依 ratio 排序）
python3 student/recipe_store.py             # 兩者都做
```

## JSON 欄位

| 欄位 | 說明 | 來源 |
|------|------|------|
| `case` | case 名稱（ex200–ex299） | — |
| `classification` | 電路家族標籤、有效支撐數、建議策略 | `logs/classification.csv`（boolean_fingerprint） |
| `initial_synthesis` | 最近 pipeline 選中的初始合成方法與 flow | `logs/reproduce_candidates.csv` |
| `reference_adp` | 助教參考 ADP | `reference_result.csv` |
| `ratio_vs_reference` | 我們的 ADP / 參考 ADP（< 1 表示贏過助教） | 計算 |
| `best` | 目前最佳 area / delay / ADP 與日期 | `output/<case>.aig` 量測 |
| `history` | 每次 ADP 變動的紀錄（append-only） | 自動累積 |
| `notes` | 自由筆記（人工編輯，refresh 不會覆蓋） | 手動 |

## 慣例

- `notes` 用來記錄該 case 的結構分析、已嘗試但無效的策略、待試想法。
- 改善某個 case 後執行 `--refresh`，歷史會自動累積。
- `reproduce_best.sh` 結尾會自動 refresh，確保 recipe 與最終結果同步。
