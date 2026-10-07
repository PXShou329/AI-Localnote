# AI Localnote：第一次使用（Windows PowerShell）

AI Localnote 是單使用者、個人使用的 **CLI 命令列工具**。在 PowerShell
輸入指令、閱讀文字結果；它不會開啟 GUI 或網站。這份頁面是使用教學。

2026-10-07 已使用既有 `.venv`、Python 3.12.10、本機 Ollama 親自跑過流程。
所有示範都是本輪新建的虛構筆記，沒有操作正式資料庫。

## 1. 進入專案，沿用現有環境

開啟 PowerShell，把第一行換成實際專案路徑。資料夾裡應有 README、
pyproject.toml、src 和 .venv。

```powershell
Set-Location -LiteralPath "<你的 AI Localnote 專案資料夾>"
$localnotePython = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$localnoteCli = (Resolve-Path '.\.venv\Scripts\localnote.exe').Path
& $localnotePython --version
& $localnoteCli --version
& $localnoteCli --help
```

本輪輸出為 Python 3.12.10、`localnote 0.1.0`。不必啟用或重建 `.venv`，
不用修改全域 Python、PATH、執行政策或 Windows 安全設定。
只有 Python 可用但專案套件未安裝時，才用同一個虛擬環境的
`python.exe -m pip install -e ".[dev]"`。本輪已安裝，沒有重裝。
若遇到環境或政策阻擋，停止並記錄錯誤。

## 2. 第一次先指定獨立示範 DB

先執行這段，再新增筆記。每次產生新的檔名，不會混入正式資料。

```powershell
$localnoteDemoDir = Join-Path (Get-Location) 'dist\demo'
New-Item -ItemType Directory -Path $localnoteDemoDir -Force | Out-Null
$env:LOCALNOTE_DB_PATH = Join-Path $localnoteDemoDir ('demo-' + [guid]::NewGuid().ToString('N') + '.db')
$localnoteDemoDb = $env:LOCALNOTE_DB_PATH
$env:PYTHONIOENCODING = 'utf-8'
$localnoteUtf8 = New-Object System.Text.UTF8Encoding
$OutputEncoding = $localnoteUtf8
[Console]::OutputEncoding = $localnoteUtf8
Write-Host "目前示範 DB：$localnoteDemoDb"
```

保存顯示的 DB 完整路徑，供下次使用。第一次需要資料庫的指令才會建立檔案。
dist 裡的示範 DB／JSON 不提交到 Git。

`$env:` 設定只存在於**你執行指令的 PowerShell 視窗**。Codex 驗證子程序
不會把設定套用到你原本的終端機；`.env` 不會自動載入。

## 3. 新增不使用 AI 的筆記，取得真正的 ID

`add` 必須有 **title 和 body 兩個參數**。先顯示新增結果，再取出 ID：

```powershell
$localnoteAdded = & $localnoteCli add '第一次使用練習' '這是一筆虛構的 Localnote 練習筆記。' --no-llm --tags '練習,個人'
$localnoteAdded
$localnoteNoteId = [regex]::Match(($localnoteAdded -join "`n"), 'Added note (\d+):').Groups[1].Value
if (-not $localnoteNoteId) { throw '新增未成功；先查看錯誤，不要使用空白 ID。' }
```

本輪乾淨示範 DB 實際顯示：

```text
Added note 1: 第一次使用練習
Tags: 練習, 個人
```

你的 ID 以自己的輸出為準；後續使用 `$localnoteNoteId`，不套用其他人的 ID。
`--no-llm` 不呼叫模型，summary 為空，保留使用者 tags。

## 4. list、show、edit、search

```powershell
& $localnoteCli list
& $localnoteCli show $localnoteNoteId
& $localnoteCli edit $localnoteNoteId --body 'Localnote 練習：我已經學會編輯筆記。' --no-llm
& $localnoteCli search 'Localnote' --limit 3
```

show 顯示整筆資料。search 顯示 ID、title、created_at、summary、tags，
不輸出完整 body；沒有摘要／標籤時顯示 `(none)`。沒有結果也是正常成功。
limit 預設 20，必須 >0。只搜尋 title/body/summary，不搜尋 tags；
`%`、`_`、`\` 都按字面搜尋。較新插入的 ID 在前，不是最近編輯在前。
list 的既有格式沒有改動。

**edit --no-llm 會保留舊摘要。** 修改已有摘要的 body 後，摘要可能過時，
不會自動清除。修改 body 並拿掉 --no-llm 才會重新摘要；只改 title/tags 不呼叫模型。

## 5. 確認本機 Ollama 與模型

```powershell
ollama list
Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 5
```

本輪服務已在運作，CLI/API 驗證成功，已安裝模型包含 qwen38-dev-16k:latest。
這台電腦可設定：

```powershell
$env:LOCALNOTE_OLLAMA_URL = 'http://localhost:11434'
$env:LOCALNOTE_OLLAMA_MODEL = 'qwen38-dev-16k:latest'
```

其他電腦必須換成 **自己的 ollama list 真正列出的名稱**。本流程不下載新模型、不切換雲端。
如果 API 連不上，先開啟已安裝的 Ollama，或在另一個 PowerShell 執行
`ollama serve` 並保持該視窗開啟，再回來確認。本輪服務已啟動，沒有重啟；
「服務未啟動」分支未另行驗證。沒有存取權或可用模型時，跳過 AI 段落，使用 no-LLM 功能。

## 6. summarize 不保存；AI add 才保存

```powershell
& $localnoteCli summarize '這是虛構示例：星期五要完成測試。'
$localnoteAiAdded = & $localnoteCli add 'AI 練習筆記' '這是虛構示例：星期五要完成測試。'
$localnoteAiAdded
$localnoteAiNoteId = [regex]::Match(($localnoteAiAdded -join "`n"), 'Added note (\d+):').Groups[1].Value
if (-not $localnoteAiNoteId) { throw 'AI 新增未成功；請先查看錯誤。' }
& $localnoteCli show $localnoteAiNoteId
```

summarize 只顯示摘要／標籤，**不保存筆記**。add 才會新增到目前的 DB。
本輪 AI add 實際回傳 `Added note 2: AI 練習筆記`，摘要及標籤成功生成。
模型文字每次可能不同，不要求逐字相同。

## 7. 匯出 JSON

```powershell
$localnoteExportPath = Join-Path $localnoteDemoDir ('notes-' + [guid]::NewGuid().ToString('N') + '.json')
& $localnoteCli export $localnoteExportPath
```

匯出當前 DB 全部筆記，UTF-8 JSON v1 支援繁中、日文和 emoji，不呼叫模型。
父目錄須存在，已有目的地預設拒絕；只有確定替換自己的匯出檔時才加 --force。
**JSON 匯出不是還原演練**：v0.1.0 沒有 Import。

## 8. 取消刪除，再明確刪除

```powershell
& $localnoteCli delete $localnoteNoteId
```

本輪實際提示為 `Delete note 1: 第一次使用練習? [y/N]:`。
先輸入 n 再按 Enter，或只按 Enter，預設不刪除，顯示 `Deletion cancelled.`，exit 0。
沒有可讀回應／stdin EOF 時保留資料、非零結束。不存在 ID 直接報錯，不先詢問。

```powershell
& $localnoteCli show $localnoteNoteId
```

要練習正常 yes 確認，另加一筆可丟棄的虛構筆記：

```powershell
$localnoteDisposable = & $localnoteCli add '刪除確認演練' '這筆虛構筆記可以刪除。' --no-llm
$localnoteDisposable
$localnoteDisposableId = [regex]::Match(($localnoteDisposable -join "`n"), 'Added note (\d+):').Groups[1].Value
if (-not $localnoteDisposableId) { throw '演練筆記新增失敗。' }
& $localnoteCli delete $localnoteDisposableId
```

確認 ID/title 是剛新增的演練筆記後，輸入 yes 並按 Enter。
本輪 ID 3 的 yes 刪除成功。要明確略過確認，可用：

```powershell
& $localnoteCli delete $localnoteNoteId --yes
& $localnoteCli list
```

這會刪除本流程原始練習筆記，不再詢問。自動化腳本也須明確加 --yes。
此為核准的行為變更，沒有移除刪除功能或降低測試標準；刪除全程不呼叫 LLM。

## 9. SQLite 備份與還原（不是 JSON Import）

本輪 temporary source DB 經 stdlib sqlite3.Connection.backup() 備份後，
另一個子程序以 LOCALNOTE_DB_PATH 指向備份。ID 4、3、1 的 title/body、
summary/tags、created_at/updated_at 七欄全部一致，list/show/search 成功，
source 未改變，所有連線已關閉。可重跑這個只用虛構 temporary DB 的演練：

```powershell
& $localnotePython -m pytest tests/test_backup_restore.py -q -s
```

若想備份剛剛的示範 DB，先確認 $localnoteDemoDb 是步驟 2 的新檔，再執行：

```powershell
$env:LOCALNOTE_DB_PATH = $localnoteDemoDb
$env:LOCALNOTE_BACKUP_PATH = Join-Path $localnoteDemoDir ('backup-' + [guid]::NewGuid().ToString('N') + '.db')
@'
import os, sqlite3
from contextlib import closing
from pathlib import Path
source = Path(os.environ['LOCALNOTE_DB_PATH']).resolve()
target = Path(os.environ['LOCALNOTE_BACKUP_PATH']).resolve()
formal = (Path.home() / '.localnote' / 'localnote.db').resolve()
if not source.is_file() or source == formal or source == target:
    raise SystemExit('請使用已存在的獨立示範 DB，備份目的地不能是原檔。')
if not source.name.startswith('demo-'):
    raise SystemExit('演練只接受步驟 2 的 demo- 開頭檔案。')
target.open('xb').close()
with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
    with closing(sqlite3.connect(target)) as copied:
        original.backup(copied)
        copied.commit()
print('備份成功：', target)
'@ | & $localnotePython -
if ($LASTEXITCODE -ne 0) { throw '備份失敗；不要使用不完整備份。' }
$env:LOCALNOTE_DB_PATH = $env:LOCALNOTE_BACKUP_PATH
& $localnoteCli list
& $localnoteCli show $localnoteAiNoteId
& $localnoteCli search '虛構示例' --limit 3
$env:LOCALNOTE_DB_PATH = $localnoteDemoDb
```

CLI 每次都是另一個子程序。指令完成後才備份，source 以唯讀開啟，目的地
必須是新檔案；closing() 明確關閉 SQLite 連線。「還原」是把應用程式指向
已驗證的 SQLite 備份，不覆蓋原 DB。備份失敗時，不把留下的檔案當有效備份。
本輪沒有新增公開 backup/import 指令。

## 10. 切回正式 DB，確認資料位置

沒有 LOCALNOTE_DB_PATH override 時，預設是你的使用者資料夾下
`.localnote\localnote.db`。你決定存正式筆記時，移除目前視窗的 override：

```powershell
Remove-Item Env:\LOCALNOTE_DB_PATH -ErrorAction SilentlyContinue
& $localnotePython -c "from localnote.config import load_settings; print(load_settings().db_path)"
```

最後一行只顯示路徑，不開啟 DB。本輪只確認設定路徑，沒有對正式 DB 執行
list/show/add/edit/delete。若原本有自訂正式 DB，明確設回自己的路徑。
要繼續試用，切回示範資料：

```powershell
$env:LOCALNOTE_DB_PATH = $localnoteDemoDb
```

SQLite／JSON 是明文，請妥善保存。正式備份也應使用 backup API 建立獨立新檔，
先在另一個路徑驗證，不要在連線／交易仍開啟時直接覆蓋原 DB。
本流程不要求覆蓋、刪除或修改真實正式資料。

## 11. 下次開機或重新開 PowerShell

新視窗須重設變數，不必重建 .venv 或重裝套件：

```powershell
Set-Location -LiteralPath "<你的 AI Localnote 專案資料夾>"
$localnoteCli = (Resolve-Path '.\.venv\Scripts\localnote.exe').Path
$env:LOCALNOTE_DB_PATH = '<上次保存的示範 DB 完整路徑>'
$env:PYTHONIOENCODING = 'utf-8'
$localnoteUtf8 = New-Object System.Text.UTF8Encoding
$OutputEncoding = $localnoteUtf8
[Console]::OutputEncoding = $localnoteUtf8
& $localnoteCli list
```

需要 AI 時再確認 Ollama、執行 ollama list，並設定本機 model／URL。
使用預設正式 DB 則不要設定示範 override。先 list 找到真正 ID，再 show/edit，
不要把本輪 ID 1、2、3 當所有資料庫的固定 ID。

本輪已驗證 no-LLM 流程、本機 summarize/add、刪除取消／yes／--yes、JSON export、
SQLite backup 子程序還原及隔離安裝 wheel。完整結果見 [STATUS.md](STATUS.md)。
