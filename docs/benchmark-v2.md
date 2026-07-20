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

## モデル構成

現在の完全版は次の構成です。

- 対象: GPT-5.6 Sol、GPT-5.4 mini、Gemini 3.5 Flash、Gemini 3.1 Flash-Lite、Claude Haiku 4.5
- ユーザー役: GPT-5.4 mini
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- 対象生成はthinkingを最小化し、Judgeはlowに固定
- APIが返すinput、output、reasoning、cached tokenと定価換算費用を保存

鍵は設定ファイルへ書かず、`OPENAI_API_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY`から読みます。実行は途中成果をターン単位で保存し、同じ出力先を指定すれば欠けた箇所から再開します。

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
