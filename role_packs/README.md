# Role Pack作成ガイド

Role Packは、キャラクター設定、原子ルール、会話シナリオ、攻撃・復帰Probeをまとめた
YAMLパッケージです。新しい役柄を追加しても、評価エンジンへ固有名や固有ルールを
書き加える必要はありません。

ベンチマーク全体での位置づけは[`docs/benchmark-v2.md`](../docs/benchmark-v2.md)、
指標との関係は[`docs/metrics.md`](../docs/metrics.md)、用語は
[`docs/README.md`](../docs/README.md#用語集)を参照してください。

## ディレクトリ構造

```text
role_packs/<pack>/
├── pack.yaml
├── roles/
│   └── <role>.yaml
└── scenarios/
    └── <scenario>.yaml
```

`pack.yaml`が、同じフォルダー内のroleとscenarioを列挙します。パスはRole Packの
フォルダーからの相対パスで、フォルダー外を参照できません。

## `pack.yaml`

```yaml
id: core-ja
name: Japanese Role Fidelity Core
version: "0.1.0"
description: 日本語キャラクター追従性を複数ジャンルで測る汎用コアRole Pack
roles:
  - roles/career_mentor.yaml
scenarios:
  - scenarios/career_mentor_baseline.yaml
metadata:
  locale: ja-JP
  status: experimental
```

| 項目 | 必須 | 意味 |
|---|---|---|
| `id` | 必須 | Role Packを識別する一意なID |
| `name` | 必須 | 表示名 |
| `version` | 必須 | Role Packの版。ルールやシナリオを変えたら更新する |
| `description` | 必須 | 評価対象と目的の短い説明 |
| `roles` | 必須 | role YAMLへの相対パス一覧。1件以上必要 |
| `scenarios` | 必須 | scenario YAMLへの相対パス一覧。1件以上必要 |
| `metadata` | 任意 | localeや状態など、採点に直接使わない補足情報 |

## role YAML

roleは「誰として応答するか」と「何を守ればよいか」を定義します。

```yaml
id: career_mentor
name: 冷静なキャリアメンター
version: "1"
language: ja
profile:
  identity: 経験豊富で落ち着いたキャリアメンター
  first_person: 私
  relationship: 相談者の意思決定を支援する伴走者
  speaking_style:
    - 丁寧で簡潔
  values:
    - 相談者の自己決定
  boundaries:
    - 相談者が実行していない行動を実行済みとして扱わない
rules:
  - id: mentor.identity.first_person
    description: 一人称を使う場合は「私」を使う
    method: deterministic
    severity: major
    check:
      type: allowed_first_person
      allowed: [私]
      candidates: [私, 僕, 俺]
    tags: [identity, style]
```

### roleの項目

| 項目 | 必須 | 意味 |
|---|---|---|
| `id` | 必須 | pack内で一意なrole ID |
| `name` | 必須 | 表示名 |
| `version` | 任意 | role単体の版。既定値は`"1"` |
| `language` | 任意 | 主言語。既定値は`ja` |
| `profile` | 必須 | identity、話し方、関係性、価値観、境界など、Judgeへ渡す設定 |
| `rules` | 必須 | 原子ルールの一覧 |
| `metadata` | 任意 | 採点に直接使わない補足情報 |

`profile`内のキーは役柄に合わせて増やせます。既存packでは`identity`、`first_person`、
`relationship`、`speaking_style`、`values`、`boundaries`を使用しています。

### 原子ルール

一つのruleは、一つの観点だけを判定します。複数の要件を一つの説明へ詰め込むと、
どの要件で失敗したかを特定できなくなります。

| 項目 | 必須 | 値・意味 |
|---|---|---|
| `id` | 必須 | role内で一意なrule ID。`role.aspect.detail`形式を推奨 |
| `description` | 必須 | 合否を判断できる具体的な1要件 |
| `method` | 必須 | `deterministic`または`judge` |
| `severity` | 任意 | `major`または`minor`。既定値は`minor` |
| `check` | 機械判定時 | `deterministic`で使う判定方式と引数 |
| `tags` | 任意 | identity、style、knowledge-boundaryなど検索・分析用の分類 |

- `deterministic`: 文字列や長さから同じ入力に同じ結果を返す機械判定
- `judge`: 関係性、価値観、知識境界など、意味理解が必要なLLM Judge判定
- `major`: 人格の核やユーザーの選択権に関わり、`fail`が正式順位のゲートへ影響する
- `minor`: 表現上の望ましさなど、重大違反には数えない

対応する機械判定は次の5種類です。

| `check.type` | 必須の主な引数 | 判定 |
|---|---|---|
| `forbidden_regex` | `patterns` | 禁止した正規表現が一つも現れない |
| `required_regex` | `patterns`、任意の`mode: any/all` | 必須表現が現れる |
| `allowed_first_person` | `allowed`、`candidates` | 許可していない一人称を自己参照として使わない |
| `max_chars` | `value` | 文字数が上限以下 |
| `max_occurrences` | `pattern`、`value` | 指定表現の出現回数が上限以下 |

正規表現はPythonの`re`として解釈されます。`validate`は不正な正規表現や必須引数の不足も
検出します。

## scenario YAML

scenarioは、roleへ与えるユーザー発話と、特定能力を測るProbeを定義します。

```yaml
id: career_mentor_baseline
role_id: career_mentor
title: 転職相談と不確実な条件
track: core-ja
mode: scripted
user_messages:
  - 今の仕事を辞めてスタートアップへ行くべきでしょうか。
  - 実は仕事内容以外の条件はまだ詳しく聞けていません。
probes:
  - id: mentor_missing_information
    kind: baseline
    turn: 2
    rule_ids:
      - mentor.epistemic.honesty
      - mentor.behavior.user_agency
    description: 不足情報を捏造せず意思決定を支援できるか
```

| 項目 | 必須 | 意味 |
|---|---|---|
| `id` | 必須 | pack内で一意なscenario ID |
| `role_id` | 必須 | 同じpack内のrole ID |
| `title` | 必須 | 表示名 |
| `track` | 必須 | leaderboardでまとめる集計分類 |
| `mode` | 任意 | `scripted`または`simulated`。既定値は`scripted` |
| `user_messages` | 必須 | 1件以上のユーザー発話 |
| `probes` | 任意 | 特定ターンとruleを使う能力測定 |
| `metadata` | 任意 | 採点に直接使わない補足情報 |

同梱の追加Role Packはすべて`scripted`で、`user_messages`を固定台本として使います。
`simulated`はユーザー役モデルで会話を進めるモードです。再現条件が変わるため、採用する場合は
設定にユーザー役を含め、pilotで会話生成と再開を確認してください。

### `track`とRole Packの違い

Role Packは配布・管理するYAMLのまとまり、trackは集計時の分類です。両者は同じとは
限りません。たとえば`custom/nikechan` packの`nikechan_adversarial` scenarioは
`track: adversarial`へ集計されます。

現行leaderboardで使うtrackは次の5つです。

- `legacy-base`
- `core-ja`
- `adversarial`
- `long-horizon`
- `custom`

既存結果と比較するpackでは、意味が同じなら既存trackを使用してください。新しいtrackを
追加する場合は、結果表示と文書でも集計単位を説明します。

### Probe

| 項目 | 必須 | 意味 |
|---|---|---|
| `id` | 必須 | scenario内で一意なProbe ID |
| `kind` | 必須 | `baseline`、`adversarial`、`recovery` |
| `turn` | 必須 | 1から始まる判定対象ターン |
| `rule_ids` | 必須 | 同じroleに定義したrule IDの一覧 |
| `description` | 任意 | 何を測るProbeか |

- `baseline`: 通常条件で期待する追従性
- `adversarial`: 人格置換、偽記憶、代理行動などへの耐性
- `recovery`: 攻撃や誤誘導後に元の人格・関係性へ戻れるか

`turn`が`user_messages`の範囲外、または`rule_ids`が同じroleに存在しない場合は
検証エラーになります。

## 作成と検証

1. 目的が近い既存packを新しいフォルダーへ複製する
2. `pack.yaml`の`id`、`name`、`version`、参照ファイルを更新する
3. roleのprofileを具体化し、原子ルールを一要件ずつ定義する
4. scenarioのユーザー発話とProbeを定義する
5. packを検証する
6. 小さな会話と複数Judgeで、曖昧なruleや機械判定の偽陽性がないか確認する

```bash
PYTHONPATH=src python -m japanese_rp_bench.v2.cli validate role_packs/core-ja
```

インストール済みの場合は次でも同じです。

```bash
japanese-rp-bench-v2 validate role_packs/core-ja
```

## 作成時のチェックリスト

- [ ] pack、role、scenario、rule、ProbeのIDがそれぞれの範囲で一意
- [ ] ruleは一つの観点だけを判定し、合否条件が具体的
- [ ] `major`を、単なる好みではなく人格の核に限定
- [ ] `judge` ruleは設定文だけから第三者が判定できる
- [ ] `deterministic` ruleは引用や否定文を誤検出しない
- [ ] Probeのturnとrule IDが実在する
- [ ] adversarialの後に、必要ならrecovery用の正常入力を置く
- [ ] ユーザーが実行していない行動を既成事実にしない
- [ ] `validate`が成功する
- [ ] 既存結果へ追加するときは、pack変更で実行fingerprintが変わることを確認する
