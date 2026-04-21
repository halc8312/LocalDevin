# Knowledge Base

## 概要

Knowledge Base には、LocalDevinがタスクを実行する際に自動的に参照する知識を格納します。

## Knowledge の作成方法

1. このディレクトリに `.md` ファイルを作成する
2. `triggers.yaml` にトリガーキーワードを追加する
3. Knowledge は自動的にインデックスされ、関連タスクで参照されます

## ファイル形式

```markdown
# Knowledge名

## 概要
この Knowledge が対応する状況の説明

## 内容
具体的な手順・情報・注意点

## 参考リンク
- https://example.com
```
