# Playbook 作成ガイド

## Playbook とは

Playbook は特定のタスクタイプに対する標準的な実行手順を定義したMarkdownファイルです。
LocalDevinがタスクを実行する際に、関連するPlaybookが自動的または手動で適用されます。

## Playbook の構造

```markdown
# Playbook名

## 概要
このPlaybookが対応するタスクの説明

## 前提条件
- 必要なツール
- 必要なアクセス権

## 手順
1. ステップ1
2. ステップ2

## 完了基準
- 条件1
- 条件2

## 注意事項
- 注意点
```

## 使用方法

```bash
localdevin run "Fix bug in authentication" --repo . --playbook bug-triage
```
