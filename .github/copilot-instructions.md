# Copilot Instructions (VolAI)

## Tech context
- OS: Windows dev, GitHub Actions: windows-latest / ubuntu-latest
- Stack: FastAPI, Uvicorn, pytest, Python 3.11, PowerShell (pwsh)
- CI: .github/workflows/ci.yml で Windows (pwsh) 実行、`pytest -k "offline or schema"`
- Secrets: FMP_API_KEY / FRED_API_KEY（.envは絶対コミットしない）

## Optimize for
- CIが常にグリーン（外部APIに触れないオフラインテスト）
- 変更は最小、ログは多め、失敗時は原因が読めるメッセージ

## Do
- Windowsでは `shell: pwsh` 前提のスクリプトを提案
- `pip install` は `if (Test-Path requirements*.txt)` で存在チェック
- `.env` は `Out-File -Append -Encoding ascii` で追記
- .gitignoreを尊重（models/*.pkl、logs、data等は無視）

## Don’t
- `.env` をコミットする提案をしない
- 長時間の外部API呼び出しをテストに入れない
- Linux前提コマンドをWindows CIに提案しない

## Commit style
- chore/fix/feat/test の接頭辞を使い、1〜2行で要点
