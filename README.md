# 喫茶店の材料在庫管理（ローカル実装フェーズ1）

Flask と SQLAlchemy による材料管理、入出庫、履歴、不足警告、管理者・担当者の認証と権限分離を実装しています。ローカルテストは SQLite を使用します。本番 DB、GitHub、Render、Gmail には接続しません。

## ローカル再構築

Python 3.9 以上を用意し、プロジェクト直下で次を実行します。パスワードには自分で用意した**ローカル試験専用の値**を入力します。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
export APP_ENV=development
export APP_SECRET_KEY=dev-only-change-me
.venv/bin/flask --app 'app:create_app' init-db
.venv/bin/flask --app 'app:create_app' create-admin admin
.venv/bin/flask --app 'app:create_app' run --host 127.0.0.1
```

`http://127.0.0.1:5000` にアクセスします。`APP_SECRET_KEY` の例は開発専用のダミーであり、本番では使えません。ローカル DB は `instance/inventory.sqlite3` に生成され、Git から除外されます。

## テストと安全な模擬実験

```sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/scan_secrets.py
.venv/bin/python scripts/probe_hooks.py
.venv/bin/python scripts/check_critical.py tests/test_auth.py
```

`probe_hooks.py` はツール入力を**文字列として** Hook に渡すだけです。`git push` などの文字列を含む試験でも、シェル操作は実行しません。Hook がない状態と設定後を同一の無害な `printf HOOK_BLOCK_PROBE` で比較します。Codex ランタイムでの Hook 起動・信頼状態はこの試験では検証しません。

### フェーズ2.5のHookと検知範囲

プロジェクト内の `.codex/hooks.json` は `PreToolUse` の `Bash` と `apply_patch` を対象にします。シェル入力は `shlex` で引用符と区切りを分け、`git -C . push`、`&&` や `;` を含む複合コマンド、`sh -c` の単純な入れ子を調べます。`printf 'README says git push'` は説明文として許可します。動的コマンド置換、リダイレクト、未知の Git グローバルオプション、シェルスクリプトの直接実行など、解析できない構文は拒否します。このため、読み取りだけの `cat < README.md` も現状では誤検知します。

`apply_patch` は変更ヘッダーから対象パスを読み、重要ファイルと新規ファイルには警告を返します。対象パスが不明、または相対パスでプロジェクト外を指す場合は拒否します。重要ファイルの警告は公開承認ではありません。Python など別のインタプリタ内で組み立てるコマンド、シェルの全構文、特殊なツール経路までは解析できません。Hook は無効化・改変可能なので、安全性を保証する境界として扱いません。

重要ファイル分類器は、Git差分の追加・変更・削除・改名を状態付きで報告し、未知の Python ファイルや新規ファイルを確認対象に回します。未知の既存設定ファイルの変更などは取りこぼし得ます。将来の公開には、AIが編集できない別のサービス／GitHub Appに分類ポリシーと検査コードを置き、そのAppが発行するステータスをGitHub rulesetで必須にします。変更されたPRコードや設定を特権付きの検査環境で実行しない構成が必要です。

重要ファイルの変更検知は現段階ではローカルの助言的チェックです。GitHub ruleset、独立した外部チェック、Gmail 通知、Render 公開ゲートは未設定です。

## Docker での再構築案

Docker が使える環境なら `docker compose up --build` の後、`docker compose exec web flask --app 'app:create_app' init-db` と `create-admin admin` を実行します。現在の開発端末では Docker コマンドが見つからず、Docker 起動・PostgreSQL 接続は未検証です。Compose のパスワードはローカル専用ダミーです。

## 運用上の未対応事項

本番マイグレーション、DB バックアップ、通知、GitHub 側の必須検査・承認、実際の Codex Hook 起動確認は次フェーズです。`init-db` は初期テーブル作成専用であり、既存 DB のスキーマ変更には使いません。パスワードの再設定、アカウント無効化、監査履歴のページ送りも未対応です。

<!-- Phase 3-F disposable branch protection experiment; do not merge. -->
