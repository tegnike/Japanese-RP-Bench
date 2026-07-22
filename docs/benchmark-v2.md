# Japanese-RP-Bench v2（実験実装）

v2は旧版を置き換える別ベンチではなく、元の30ロール・10往復・従来8指標をBaseとして完全に含む拡張版です。同じ会話に「指定されたキャラクターの核を維持できるか」という追加評価を重ね、追加Role PackはChallengeとして分けて表示します。

## 評価の考え方

評価対象を一つの総合点へ早期に潰さず、次を別々に出力します。

- `core_fidelity_score`: 客観ルールとJudgeルールを合わせた追従性
- `deterministic_compliance_score`: 一人称や禁止表現など、機械的に判定できる制約
- `judge_fidelity_score`: 関係性、価値観、知識境界など、意味理解が必要な制約
- `conversation_quality_score`: 自然さ、表現力、楽しさなど従来型の会話品質
- `long_term_stability_score`: 対話序盤から終盤への追従性低下
- `robustness_score`: 人格置換、偽記憶、代理行動などへの耐性
- `recovery_score`: 攻撃や誤誘導後に元の人格へ戻れるか
- `judge_disagreements`: Judge間で大きく判定が割れた原子ルール数

重大ルールのfailが一つでもあれば`eligible_for_overall=false`になります。会話品質が高くても重大な人格逸脱を相殺しません。現段階では、根拠のない重み付き総合点を定義していません。

各指標の算出式、値の読み方、BaseとChallengeの違いは
[`metrics.md`](metrics.md)にまとめています。

## Role Pack

Role Packは、役を評価エンジンから分離するYAMLパッケージです。

```text
role_packs/<pack>/
├── pack.yaml
├── roles/
│   └── <role>.yaml
└── scenarios/
    └── <scenario>.yaml
```

各ルールは一つの観点だけを判定する原子ルールとし、`deterministic`または`judge`を指定します。`major`は人格の核、`minor`は表現上の望ましさに使います。AIニケちゃんは`custom/nikechan`に置かれた一つのRole Packであり、評価コードには固有名や固有ルールを持ち込みません。

同梱パックは次の通りです。

- `core-ja`: 実務的メンター、ファンタジー案内人
- `adversarial-ja`: 引用内命令、人格置換、ユーザー代理行動
- `long-horizon-ja`: 12ターンでの人格、関係性、会話内事実の維持
- `custom/nikechan`: AIニケちゃん固有の人格追従性

## アーティファクトと実行

v2はプロバイダー非依存の会話・Judge JSONを中間成果物として保存します。CLIからOpenAI／Gemini APIを呼ぶ一括ランナーもありますが、既存の会話JSONを後から別のJudgeで再評価できます。

```bash
# Role Pack検証
PYTHONPATH=src python -m japanese_rp_bench.v2.cli validate role_packs/core-ja

# 各ターンのブラインドJudge依頼をJSONLへ書き出す
PYTHONPATH=src python -m japanese_rp_bench.v2.cli prepare-judging \
  --role-pack role_packs/custom/nikechan \
  --conversation conversation.json \
  --output judge-requests.jsonl

# 複数Judgeの返答をまとめて採点する
PYTHONPATH=src python -m japanese_rp_bench.v2.cli score \
  --role-pack role_packs/custom/nikechan \
  --conversation conversation.json \
  --judgments judgments.jsonl \
  --output report.json
```

Judge依頼には対象モデル名を含めません。Judge JSONLは各行に`judge_id`、`turn`、全Judgeルールの`findings`、全品質項目の`quality_scores`を含めます。
採点時はデフォルトで各ターン2つ以上の異なるJudge評価を要求し、同一Judge・同一ターンの重複や欠落をエラーにします。検証用途では`--minimum-judges`で変更できます。

## 2024年版との比較

構成は次の三層です。

- `legacy-2024-frozen`: リポジトリに保存された32モデル、960会話、3,840個のJudge評価をそのまま再集計する公開結果の凍結版
- `legacy-base`: 元と同じ30ロール、システムプロンプト、10往復、従来8指標を現行モデルで実行し、同じ会話へ原子ルールとターン別追従度も追加する本体
- Challenge tracks: 敵対的指示、長期対話、復帰、AIニケちゃんなど、元データにない能力を測る追加問題

凍結版はAPIを呼ばず、入力ファイルのSHA-256も記録します。

```bash
PYTHONPATH=src python -m japanese_rp_bench.v2.cli legacy-snapshot \
  --evaluations evaluations \
  --output tmp/legacy-2024-snapshot.json \
  --markdown tmp/legacy-2024-snapshot.md
```

元版はユーザー役にClaude 3.5 Sonnet（2024-06-20）、JudgeにGPT-4o、o1-mini、Claude 3.5 Sonnet、Gemini 1.5 Proを使用していました。`legacy-base`は30設定と採点rubricを保持しますが、ユーザー役とJudgeは現行の固定ensembleへ更新します。このため、旧公開値との比較は参考比較として表示し、プロトコル差も結果へ明記します。

完全版は次のコマンドで実行します。Baseの各会話について、Judge一回の応答から従来8指標、5つの原子ルール、全10ターンの追従度を同時に取得します。

```bash
japanese-rp-bench-v2 run \
  --config configs/benchmark_full.yaml \
  --output tmp/benchmark-full \
  --workers 4
```

## Reasoning policy

このベンチマークの**評価対象モデル（target）は、各APIで明示できる最小のReasoning設定**で実行する。これは「モデルが最大限考えた場合の能力上限」ではなく、追加の推論計算を極力使わない通常会話で、人格追従、自然さ、長期安定性、敵対的指示からの復帰を比較するためのプロトコルである。

Reasoning量は単なる実装詳細ではない。Snell et al.は、推論時に割り当てる計算量を増減すると同じモデルでもタスク性能が変化し、その効果は問題とモデルによって異なることを示している。このため、Reasoning設定が異なるモデルの点数をそのまま比較すると、モデル差に加えてtest-time compute差が混入する。本ベンチでは、HELMが重視する「同一シナリオ・指標を標準化された条件で比較する」という考え方を参考に、対象モデルへ与える推論余裕を各APIの最小値へ固定し、設定値とreasoning tokenを成果物へ記録する。

最小Reasoningを主トラックにする理由は次の通り。

- 測りたい中心能力が、数学・探索・長い計画ではなく、即時的な日本語会話とロールプレイ追従だから。
- 高いReasoningを許したモデルだけが追加のtest-time computeを使う交絡を避けるため。
- 推論トークンが本文の出力枠、レイテンシ、費用を消費し、会話体験そのものを変えるため。
- プロバイダー既定値はモデルごとに異なり、将来変更されうるため、既定値任せでは再現可能な比較にならないから。

2026-07-22時点の主トラック設定は次の通り。

| 経路 | 対象モデル | 設定 |
|---|---|---|
| OpenAI Responses API | GPT-5.6 Sol、GPT-5.4 mini | `reasoning.effort: none` |
| Gemini API | Gemini 3.5 Flash、Gemini 3.1 Flash-Lite | `thinkingLevel: minimal` |
| Anthropic Messages API | Claude Haiku 4.5 | `thinking`を有効化しない |
| OpenCode Go / OpenAI互換 | Kimi K3、GLM-5.2、MiMo V2.5 Pro | `reasoning_effort: none` |
| OpenCode Go / OpenAI互換 | DeepSeek V4 Pro | エンドポイントが受理する最小値`reasoning_effort: low` |
| OpenCode Go / Anthropic互換 | Qwen3.7 Max、MiniMax M3 | `thinking: {type: disabled}` |

Geminiの`minimal`は、多くの要求で「ほぼ思考なし」に相当するが、複雑な入力でごく少量のthinkingを行う可能性があり、完全な無効化を保証しない。OpenCode Goの設定は公開メタデータだけでなく、各モデルへの短い事前疎通で受理可否とreasoning出力を確認した値である。APIがReasoning無効化を提供しないモデルは、受理される最小値を使用し、その例外を設定ファイルと結果へ明記する。

一方、**Judgeは最小Reasoningではなく`low`固定**である。Judgeは会話生成能力の比較対象ではなく、全ルールの網羅、根拠抽出、構造化JSON生成を安定させる測定器だからである。Judge ensembleでは同じ3モデルと同じ設定を全targetへ適用する。Gemini／AnthropicのBatch API利用は実行時期と価格だけを変え、Reasoning設定は変えない。

この方針は「最小Reasoningがあらゆるベンチマークの標準」という主張ではない。能力上限を測る場合は、主トラックの値へ混ぜず、同一モデルを高Reasoningで再実行する`capability-ceiling`トラックとして分離する。

根拠とAPI仕様:

- Percy Liang et al., [Holistic Evaluation of Language Models (HELM)](https://arxiv.org/abs/2211.09110) — 同じシナリオと指標を標準化された条件で比較し、入力と出力を公開する評価設計。
- Charlie Snell et al., [Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters](https://arxiv.org/abs/2408.03314) — test-time computeの量と配分がモデル性能を変えることを示す研究。
- OpenAI, [Model guidance](https://developers.openai.com/api/docs/guides/latest-model) — GPT-5系の`reasoning.effort`設定。
- Google, [Gemini thinking](https://ai.google.dev/gemini-api/docs/thinking)および[Gemini 3.5の変更点](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5) — `minimal`を含むthinking levelと、完全な無効化を保証しない点。
- Anthropic, [Extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking) — thinkingの有効化、無効化、モデル別対応。
- OpenCode, [OpenCode Go](https://dev.opencode.ai/docs/go/)および[model variants](https://opencode.ai/docs/models) — Goのモデル別API経路とプロバイダー固有Reasoning設定。

## モデル構成

現在の完全版は次の構成です。

- 対象: GPT-5.6 Sol、GPT-5.4 mini、Gemini 3.5 Flash、Gemini 3.1 Flash-Lite、Claude Haiku 4.5
- ユーザー役: GPT-5.4 mini
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- 対象生成は上記Reasoning policyに従って最小化し、Judgeはlowに固定
- APIが返すinput、output、reasoning、cached tokenと定価換算費用を保存

鍵は設定ファイルへ書かず、`OPENAI_API_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY`から読みます。実行は途中成果をターン単位で保存し、同じ出力先を指定すれば欠けた箇所から再開します。

GeminiまたはAnthropicのJudgeへ`batch: true`を指定すると、同期APIではなく各社の非同期Batch APIを使用します。対象会話をすべて保存してから不足しているJudge要求をまとめて投入し、ジョブIDを`<output>/batches/`へ保存します。同じ出力先で再実行した場合は既存ジョブを追跡するため、完了待ちや結果回収の途中で終了しても、通常は同じ要求を再投入しません。Batch呼び出しは定価と50%割引後の推定額を分けてleaderboardへ記録します。

```yaml
evaluation:
  batch:
    poll_interval_seconds: 30
    max_attempts: 2
models:
  judges:
    - id: judge-gemini
      provider: gemini
      # 通常のモデル設定は省略
      batch: true
    - id: judge-claude
      provider: anthropic
      # 通常のモデル設定は省略
      batch: true
```

Batchは即時実行を保証せず、プロバイダー側で最長24時間程度の処理枠を持ちます。`max_attempts`はジョブ全体の再実行回数ではなく、エラー・期限切れ・不正JSONなどで欠けた個別要求を新しいBatchへ再投入できる上限です。

```bash
export OPENAI_API_KEY=...
export GEMINI_API_KEY=...
export ANTHROPIC_API_KEY=...

japanese-rp-bench-v2 run \
  --config configs/benchmark_full.yaml \
  --output tmp/benchmark-full \
  --workers 4
```

小規模なブラインド人手評価は「本採点」ではなくJudgeの校正用としてのみ検討します。
