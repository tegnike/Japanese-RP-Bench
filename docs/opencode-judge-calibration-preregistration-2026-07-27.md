# OpenCode Judge校正 事前登録（2026-07-27）

この文書は、中国系6対象のChallenge反復測定を開始する前に、OpenCode GoのJudge候補を
校正する段階Aの固定条件です。機械可読な正本は
[`configs/opencode_judge_calibration_2026-07-27.json`](../configs/opencode_judge_calibration_2026-07-27.json)
です。候補Judgeの出力を確認した後に、分割、合格基準、Reasoning、token上限、候補選択順を
変更しません。現行Leaderboardは更新しません。

## 推定対象と限界

段階Aは、OpenCode Judgeが保存済みの正式3 Judge ensembleとどの程度一致し、同じ会話の
再評価時にどの程度変動するかを測ります。正式Judge成果物は校正基準であり、人間による真値では
ありません。合格後の段階Bも、固定したChallenge 6シナリオと実験期間内のモデル実装に限る
探索的評価です。

## データ分割

正式15モデルの保存済みChallenge会話90件、対象応答405件を、候補Judge出力を見る前に
モデル単位で分けます。

| 分割 | モデル | 会話 | 対象応答 | 用途 |
|---|---:|---:|---:|---|
| calibration | 非中国系9モデル | 54 | 243 | 候補評価と3 Judge選択 |
| holdout | 中国系正式6対象 | 36 | 162 | 固定ensembleの最終確認 |

holdoutには段階Bと同じ6対象、全6シナリオを入れます。calibrationだけで3 Judgeを一度固定し、
holdoutは一度だけ開きます。holdout不合格時はJudgeを差し替えず、OpenCode Judgeによる比較を
停止します。

参照値には、正式判定と2026-07-26の固定会話再Judge 2 roundを使用します。連続指標は、同じ
正式3 Judge ensembleによる3測定の分布として扱います。Major参照ラベルは3測定の多数決とし、
3測定間で判定が変わったcaseも別に報告します。

解析実装を曖昧にしないため、2026-07-27T14:30:08Z（構造・終了状態だけを確認した後、指標値を
集計する前）に、元JSONのhashを変えず
[`opencode_judge_calibration_analysis_2026-07-27.json`](../configs/opencode_judge_calibration_analysis_2026-07-27.json)
へ次を明文化しました。連続指標は対象モデルごとにChallenge 6件を平均し、候補
ensembleの各反復を正式3測定のそれぞれと比較します。Spearmanは3比較の最小値、MAEは最大値を
gateに使い、2反復とも合格を要求します。Majorは54会話単位で正式3測定の多数決を参照ラベルに
します。同系列leave-one-judge-outは系列一致が生じる中国系holdoutだけに適用します。

## 候補Judge

候補集合は次の5モデルです。正式6対象と同一モデルIDは含めません。

| Judge候補 | API形式 | 抽象Reasoning | 実リクエスト |
|---|---|---|---|
| `grok-4.5` | OpenAI互換 | `low` | `reasoning_effort: low` |
| `hy3` | OpenAI互換 | `low` | `reasoning_effort: low` |
| `qwen3.7-plus` | Anthropic互換 | `low` | `thinking: enabled`, `budget_tokens: 1024` |
| `deepseek-v4-flash` | OpenAI互換 | `low` | `reasoning_effort: low` |
| `kimi-k2.6` | OpenAI互換 | `low` | `reasoning_effort: low` |

Judgeは会話生成の比較対象ではなく、全ルールの網羅、根拠抽出、構造化JSON生成を行う測定器
なので、対象生成用の最小Reasoningではなく、既存正式Judgeと同じ抽象設定`low`に固定します。
候補がこの設定を拒否した場合、`none`へ落として救済しません。技術pilot不合格とします。

## Token・sampling条件

段階AのChallenge Judgeは全候補共通で`max_output_tokens=8192`です。正式Challenge Judgeの
4,096 tokenでは固定会話監査中に少数の`max_tokens`が発生し、Anthropic互換の`low`では
1,024 thinking tokenも同じ出力枠を使います。8,192は候補間の条件を変えず、構造化本文の
残り枠を確保するための校正専用上限です。上限を高くしても、必要以上の出力を要求するpromptへは
変更しません。

sampling値は現行正式プロトコルと同様に明示せず、provider既定を使います。送信payloadに
sampling指定がないこと、実際のReasoning断片、要求上限、終了理由、input/output/reasoning tokenを
各成果物へ保存します。

段階Bの対象生成は現行正式条件を維持します。

- Kimi K3、GLM-5.2、MiMo V2.5 Pro: `reasoning_effort: none`
- DeepSeek V4 Pro: 受理可能な最小値`reasoning_effort: low`
- Qwen3.7 Max、MiniMax M3: `thinking: disabled`
- 対象出力上限: 4,096 token

## 実行順序

### A0: snapshotとprepare

OpenCode Goモデル一覧、repository commit、plan hash、Role Packとscenario、prompt/schema実装、
採用元会話・正式判定・再Judge成果物のSHA-256をmanifestへ保存します。歴史的artifact stemは
会話中のscenario IDから現行pack IDへ正規化します。

### A1: 技術pilot

calibration内の固定2モデル×全6シナリオについて、各会話の最終ターンだけを各候補が評価します。
候補ごとに12リクエスト、全候補で60出力です。

次をすべて満たした候補だけをcalibrationへ進めます。

- 登録済みReasoning payloadが受理される
- 12/12がproduction Challenge Judge schemaでparseできる
- 上限到達、本文欠落、未知の終了理由がない
- `requested_max_output_tokens=8192`と実Reasoning設定が成果物に残る

### A2: calibration

合格候補すべてが、54会話・243対象応答を2回ずつ独立に評価します。候補5つが残れば
Judge出力は2,430件です。反復は別root、別fingerprintに保存し、前回判定を再利用しません。

3候補の全組み合わせをcalibrationだけで評価します。hard gateをすべて満たす組み合わせを、
正本JSONの固定順序で一つ選び、Judge IDと成果物hashを凍結します。

### A3: holdout

固定した3 Judgeが、中国系6対象の36会話・162対象応答を各1回評価します。486出力です。
holdoutで同じgateを確認し、通過時だけ段階Bへ進みます。不合格なら停止し、holdoutを
calibrationへ取り込みません。

## 合格基準

- 構造化出力の初回成功率99.5%以上
- retry後の未解決失敗0、打ち切り0
- Role Fidelity、Quality、Persona Stabilityのモデル平均Spearman 0.90以上
- Challenge 6件尺度のモデル平均MAE上限:
  - Role Fidelity 1.250
  - Quality 1.851
  - Persona Stability 3.274
  - Robustness 9.375
- MajorのCohen's kappa 0.60以上
- Majorの陽性一致率、陰性一致率、参照ラベルのprevalenceを併記
- holdoutで同系列Judgeを除くleave-one-judge-outにより最小実用差以上の変動がない

Spearmanとkappaだけで合否を決めません。kappaはMajor prevalenceの影響を受けるため、陽性・
陰性一致も必ず残します。系列偏りは一系列一対象しかないため、因果的な系列効果ではなく
「対象モデル／系列別残差」として慎重に扱います。

## 失敗・429・resume

`Use balance`は開始前にconsoleで無効を確認します。Go上限到達後にZen残高へフォールバックさせません。
APIキーの値はmanifest、ログ、例外へ保存しません。

429時は同じprompt、Reasoning、token上限のまま、成功済み成果物を保持し、不足taskだけを
`workers 2 → 1`へ縮退して再開します。schema不正は初回を含め最大3試行までです。モデル自身の
拒否や評価内容を見た除外は行いません。terminalな上限到達・本文欠落は保存して不完全扱いとし、
異なる上限でその候補だけを再実行しません。

2026-07-27T14:48:54Z、構造gateで失格した候補も含めて同条件の2反復試行を揃えるよう、マスターの
指示で補足収集を登録しました。詳細は
[`opencode_judge_calibration_supplement_2026-07-27.json`](../configs/opencode_judge_calibration_supplement_2026-07-27.json)
に固定しています。元の失敗成果物は上書きせず、Reasoning、8192 token上限、workers 2を変更
しません。追加試行は失敗確率を観測するためのもので、元のhard gate失格を取り消しません。

## 段階Bの固定規模

段階A合格後、中国系6対象×Challenge 6件を10生成まで全モデル同条件で実行します。5生成時点は
運用上のcheckpointに限定し、結果や順位を理由に一部モデルだけ追加しません。

| 項目 | 固定値 |
|---|---:|
| 独立生成 | 各モデル・scenario 10 |
| 会話 | 360 |
| 対象応答 | 1,620 |
| 固定Judge | 3 |
| Judge出力 | 4,860 |

10個の完全なblockを作り、各blockに6モデル×6シナリオを一度ずつ含めます。block内順序は
固定seed `20260727`でランダム化し、時間帯や利用枠の影響を全対象へ分散します。

独立標本は会話です。ターンやJudge出力を独立標本として数えません。シナリオを固定block、
生成反復を会話単位、Judgeを固定ensemble効果として解析し、会話を保った階層bootstrapで
95%信頼区間と順位確率を求めます。6モデル全15ペアは指標ごとにHolm補正します。

## 実行CLI

以下はrepository rootで実行します。`OPENCODE_GO_API_KEY`は環境変数から読み、コマンド引数や
manifestへ含めません。`run-pilot`と`run-calibration`は`--confirm-use-balance-off`がなければ
API call前に停止します。

```bash
PYTHONPATH=src python -m japanese_rp_bench.v2.opencode_calibration validate-plan
PYTHONPATH=src python -m japanese_rp_bench.v2.opencode_calibration snapshot-models \
  --output tmp/opencode-judge-calibration-20260727-v1/model-snapshot.json
PYTHONPATH=src python -m japanese_rp_bench.v2.opencode_calibration \
  --source-repo /Users/user/WorkSpace/Japanese-RP-Bench prepare \
  --output tmp/opencode-judge-calibration-20260727-v1 \
  --model-snapshot tmp/opencode-judge-calibration-20260727-v1/model-snapshot.json
PYTHONPATH=src python -m japanese_rp_bench.v2.opencode_calibration \
  --source-repo /Users/user/WorkSpace/Japanese-RP-Bench run-pilot \
  --output tmp/opencode-judge-calibration-20260727-v1 \
  --confirm-use-balance-off
```

pilot合格後だけ、候補ごと・反復ごとに次を実行します。429後の再実行も同じコマンドを使い、
成功済みtaskをresumeします。

```bash
PYTHONPATH=src python -m japanese_rp_bench.v2.opencode_calibration \
  --source-repo /Users/user/WorkSpace/Japanese-RP-Bench run-calibration \
  --output tmp/opencode-judge-calibration-20260727-v1 \
  --candidate judge-opencode-grok-4.5 --repetition 1 --workers 2 \
  --confirm-use-balance-off
```

全候補の構造gateが確定した後、API callを行わない解析で候補を選定します。失敗runは
`reconcile-calibration`で保存済み成果物だけからmanifestを確定でき、異なる条件で再生成しません。

```bash
PYTHONPATH=src python -m japanese_rp_bench.v2.opencode_calibration \
  --source-repo /Users/user/WorkSpace/Japanese-RP-Bench analyze-calibration \
  --output tmp/opencode-judge-calibration-20260727-v1
```

## 公開境界

- 段階A、Bは現行正式Leaderboardへ混ぜない
- OpenCode Judge探索結果と、将来の正式3 Judge確認結果を同じ列へ混ぜない
- 平均、中央値、標準偏差、95%信頼区間、標本数、Judge構成を併記する
- holdout完了前にモデルの優劣を公開しない
- 結果公開は完全性確認後の別作業とする
