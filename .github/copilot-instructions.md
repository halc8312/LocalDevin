# GitHub Copilot カスタム指示 for LocalDevin

## プロジェクト概要

LocalDevin は Devin AI のワークフローをローカル環境（RTX 4060 Ti 16GB）で再現するプロジェクトです。

## コーディング規約

- **Python バージョン**: 3.11+
- **型アノテーション**: 全ファイル・全メソッドに必須。`-> None`, `-> str`, `list[str]` 等
- **Docstring**: 全 public メソッドに Google style docstring
- **非同期**: コア（orchestrator, executor, llm/client）は `async/await` で実装
- **エラーハンドリング**: 全外部呼び出し（LLM API, ファイルI/O, Git）に `try-except`
- **ログ**: `logging` モジュール + Rich ハンドラー

## ディレクトリ構造の原則

- `config/`: 設定ファイル（Pydantic Settings, YAML, プロンプト）
- `core/`: ビジネスロジック（オーケストレーター、プランナー等）
- `llm/`: LLM クライアント・ルーター・トークントラッカー
- `tools/`: BaseTool を継承したアトミックツール群
- `memory/`: SQLite・ChromaDB を使った記憶層
- `review/`: PR レビュー・バグ検出・自動修正
- `insights/`: セッション分析・プロンプト改善
- `integrations/`: GitHub・Slack・スケジューラー
- `cli/`: Typer CLI エントリーポイント

## 重要な設計原則

1. **冪等性**: 全ツールは複数回実行しても安全であること
2. **サーキットブレーカー**: 同一ツール3回連続失敗で停止
3. **DAG 計画**: ステップ間の依存関係を有向非巡回グラフで管理
4. **ReAct ループ**: Think → Act → Observe の繰り返し
5. **セッション状態管理**: `SessionStatus` enum で明示的に状態遷移

## モデル割り当て

- 計画・コーディング・デバッグ: `qwen3.6:35b-a3b-q4_K_M`（main）
- 簡単な質問・補完: `qwen3.5:9b`（fast）
- 画像・スクリーンショット: `gemma4:26b`（vision）

## テスト

- `pytest` + `pytest-asyncio`
- モックを使って LLM なしでテスト可能にすること
- 各コアモジュールに最低 3 つのテストケース
