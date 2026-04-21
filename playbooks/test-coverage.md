# Test Coverage Playbook

## 概要
テストカバレッジを向上させるための標準手順。

## 前提条件
- `pytest` と `pytest-cov` がインストールされていること

## 手順

1. **現状確認**
   ```bash
   pytest --cov=. --cov-report=term-missing
   ```

2. **カバレッジの低いモジュールを特定**
   - カバレッジ < 60% のファイルを優先
   - ビジネスロジックを含むファイルを重視

3. **テストの追加**
   - 正常系・異常系・境界値のテストを追加
   - モックを活用して外部依存を排除
   - pytest fixtures を活用して重複を排除

4. **検証**
   ```bash
   pytest --cov=. --cov-report=term-missing --cov-fail-under=80
   ```

## 完了基準
- [ ] 全体カバレッジ 80% 以上
- [ ] 重要モジュールのカバレッジ 90% 以上
- [ ] 全テストがパス
