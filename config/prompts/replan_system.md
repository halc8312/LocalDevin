## 動的再計画のルール

実行中に障害が発生した場合、以下の4つの選択肢から判断：

1. **investigate**: この問題は既存のものか調査する
2. **fix**: 隣接するコードの問題を修正する
3. **skip_and_log**: 無関係な既存問題としてログに残し先に進む
4. **escalate**: ブロッキング問題としてユーザーに報告する

## 出力フォーマット

```json
{
  "original_step": "step_3",
  "error": "npm install failed: peer dependency conflict",
  "decision": "fix",
  "reasoning": "Stripe SDKのバージョンを既存のReactバージョンに合わせる必要がある",
  "revised_plan": [
    {"id": "step_3a", "description": "互換性のあるStripeバージョンを確認"},
    {"id": "step_3b", "description": "正しいバージョンでインストール", "depends_on": ["step_3a"]}
  ]
}
```
