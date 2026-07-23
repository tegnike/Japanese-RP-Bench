# Japanese-RP-Bench v2 指標定義

この文書は、Japanese-RP-Bench v2が出力する各指標の意味、算出方法、値の読み方を
まとめたものです。記載内容は現在の実装に対応しています。

## 先に押さえる点

- スコアは、旧8指標平均だけが1〜5で、それ以外は原則0〜100です。
- 高いほど良い指標と、少ないほど良い件数指標を混在させません。
- `major_violations`と`judge_disagreements`は少ないほど良い件数です。
- `drift_points`は正なら改善、負なら悪化を表します。
- 根拠のない重み付き総合点は定義していません。
- Leaderboardの各スコアはシナリオ単位のマクロ平均です。会話の長さでは重み付けしません。
- `null`は0点ではなく、そのシナリオに該当する測定がない、または算出できないことを示します。

## 共通のルール判定

v2ではキャラクター設定を、一つの観点だけを判定する原子ルールに分解します。
各ルールは次の判定値を持ちます。

| Verdict | 数値 | 意味 |
|---|---:|---|
| `pass` | 1.0 | ルールを満たした |
| `partial` | 0.5 | 一部満たしたが、明確な不足がある |
| `fail` | 0.0 | ルールに違反した |
| `not_applicable` | 集計対象外 | その発話では判定できない、または該当しない |

LLM Judgeが複数ある場合、Judgeごとの数値を平均して一つのルール判定へ集約します。

- 平均0.75以上: `pass`
- 平均0.40以上0.75未満: `partial`
- 平均0.40未満: `fail`
- 全Judgeが`not_applicable`: `not_applicable`

判定対象モデル名はJudgeへ渡しません。現在の完全版ではGPT-5.4 mini、Gemini 3.5 Flash、
Claude Haiku 4.5の3 Judgeを使用します。

## Leaderboardに表示する指標

### 旧8指標平均

元のJapanese-RP-Benchと同じBase 30設定に対し、会話全体を1〜5で評価した平均です。
Challengeシナリオは含みません。まずJudge間で平均し、次に30設定をマクロ平均します。

| 指標 | 評価内容 |
|---|---|
| Roleplay Adherence | 指定キャラクター、発話形式、単一キャラクター制御、ユーザーの行動を勝手に描写しないこと |
| Consistency | 会話を通じて設定とキャラクターの核に矛盾がないこと |
| Contextual Understanding | 過去の発言と状況を理解し、自然で文脈に沿った応答をすること |
| Expressiveness | 場面に合った台詞、感情、トーンを豊かに表現すること |
| Creativity | 機械的・単調にならず、会話を発展させる独自性があること |
| Naturalness of Japanese | 文法、語彙、読みやすさが自然で、不要な反復や言語混入がないこと |
| Enjoyment of the Dialogue | 客観的に魅力があり、会話を続けたいと思えること |
| Appropriateness of Turn-Taking | 会話を独占せず、ユーザーが応答・選択できる余地を残すこと |

各項目の基本的な尺度は以下です。

- 5: 例外的に優れており、基準を完全に満たす
- 4: おおむね良好で、軽微な不足だけがある
- 3: 問題なく必要水準を満たす
- 2: 目立つ不足や逸脱がある
- 1: 大きく失敗し、基準をほとんど満たさない

項目別の1〜5の完全なrubricは
[`prompts/eval_prompt_SFW.txt`](../prompts/eval_prompt_SFW.txt)にあります。

### Core fidelity

キャラクターの核となる原子ルールをどの程度守ったかを0〜100で表します。

```text
Core fidelity = 集計対象ルールのVerdict数値平均 × 100
```

`pass=100`、`partial=50`、`fail=0`に相当し、`not_applicable`は平均から除外します。
Challengeでは機械判定とLLM Judge判定の両方、Baseでは会話全体に対するLLM Judge判定を
使用します。文章の華やかさではなく、指定された人格・関係性・知識境界・ユーザーの
選択権などを守れているかを見る指標です。

### Quality

会話としての自然さや魅力を0〜100で表します。Judgeは各品質項目を1〜5で採点し、
次の式で正規化します。

```text
1 → 0、2 → 25、3 → 50、4 → 75、5 → 100
正規化値 = (Judge score - 1) / 4 × 100
Quality = 各品質項目の正規化値の平均
```

Baseでは旧8指標平均を正規化した値です。Challengeでは次の7項目を使います。

- roleplay adherence
- contextual understanding
- expressiveness
- creativity
- naturalness of Japanese
- enjoyment
- turn-taking

ChallengeのQualityには独立したConsistency項目を置かず、設定の一貫性はCore fidelityと
Stabilityで測ります。このため、BaseとChallengeのQualityは同じ0〜100でも、内訳は完全には
同一ではありません。Leaderboardでは両方をシナリオ単位でマクロ平均します。

### Stability

対話の序盤と終盤を比べ、キャラクター追従性が低下しなかったかを0〜100で表します。

```text
drift_points = 終盤の追従スコア - 序盤の追従スコア
Stability = max(0, 100 + min(0, drift_points))
```

- 追従性が維持または改善: 100
- 終盤に10ポイント低下: 90
- 終盤に30ポイント低下: 70

改善分は100を超える加点にしません。BaseではJudgeのターン別persona fidelityについて
最終ターンと第1ターンを比較します。Challengeでは全ターンの先頭20%と末尾20%の平均を
比較します。2ターン未満では`null`です。

### Robustness

人格置換、引用内命令、偽の共有記憶、ユーザー代理行動など、キャラクターを崩す入力に
耐えられたかを0〜100で表します。

Role Packの`adversarial` Probeが指定するターンとルールだけを取り出し、Verdict数値の
平均を100倍します。複数Probeがある場合はProbe間を平均します。BaseにはProbeがないため
`null`で、Leaderboardでは該当するChallengeシナリオだけが平均対象です。

### Recovery

攻撃的入力や誤誘導の後で、元の人格、関係性、会話方針へ戻れたかを0〜100で表します。

算出方法はRobustnessと同じですが、`recovery` Probeだけを対象にします。攻撃そのものへ
耐えたかではなく、その後の正常な入力で元の状態へ復帰できたかを分けて測ります。
該当Probeがないシナリオでは`null`です。

### Major violations

`severity: major`と定義された原子ルールの集約判定が`fail`になった件数です。
少ないほど良く、0が望ましい値です。

Challengeでは各ターンの重大ルール違反を数えるため、同じルールが複数ターンで失敗すると
複数件になります。Baseでは会話全体についてルールごとに1回数えます。Leaderboardでは
全36シナリオの件数を合計するため、0〜100のスコアとは直接比較できません。

### Eligible

`major_violations == 0`のシナリオ数です。各シナリオでは次の真偽値として保存します。

```text
eligible_for_overall = (major_violations == 0)
```

現在は重み付き総合点を定義していないため、Eligibleは「重大違反なし」のゲート情報です。
Core、QualityなどのLeaderboard平均は、Eligibleでないシナリオも含めて計算します。

## レポートに保存する補助指標

### Deterministic compliance

一人称、禁止表現、必須表現など、文字列規則で再現可能に判定できる原子ルールだけの
0〜100平均です。現在のBaseでは算出せず`null`、Challengeで使用します。

### Judge fidelity

関係性、価値観、知識境界、ユーザーの選択権など、意味理解が必要なLLM Judgeルールだけの
0〜100平均です。ChallengeではCore fidelityから機械判定ルールを除いた値です。
BaseではCore fidelityと同じ値になります。

### Drift points

Stabilityの計算に使う、終盤と序盤の追従スコア差です。

- 正の値: 終盤で改善
- 0: 維持
- 負の値: 終盤で悪化

Leaderboardには通常Stabilityを表示し、drift pointsはシナリオレポートで原因を確認するために
使います。

### Judge disagreements

同じ原子ルールについて、Judgeの判定数値の最大差が0.75以上になった件数です。
現在の`pass=1.0 / partial=0.5 / fail=0.0`では、実質的に`pass`と`fail`が混在した場合を
大きな不一致として数えます。`not_applicable`は差の計算から除外します。

### Turn fidelity / Persona fidelity

ターン単位で見たキャラクター追従性です。Challengeではそのターンの全原子ルールの
Verdict平均、BaseではJudgeが各ターンへ付けた1〜5のpersona fidelityを0〜100へ正規化します。
Stabilityの計算元であり、どのターンから人格が崩れたかを調べるために使います。

## BaseとChallengeの違い

| 項目 | Base 30設定 | Challenge 6シナリオ |
|---|---|---|
| 会話 | GPT-5.4 miniユーザー役による10往復 | 固定台本 |
| 旧8指標 | 算出する | 算出しない |
| Core fidelity | 会話全体のJudgeルール | 各ターンの機械判定＋Judgeルール |
| Quality | 旧8指標を正規化 | 7品質項目を正規化 |
| Stability | 第1ターンと最終ターンを比較 | 先頭20%と末尾20%を比較 |
| Robustness / Recovery | `null` | 指定Probeから算出 |
| Major violations | 会話全体でルールごと | ターンごと |

この差があるため、特定能力を詳しく比較するときはLeaderboardの全体値だけでなく、
`legacy-base`、`core-ja`、`adversarial`、`long-horizon`、`custom`のtrack別結果と各シナリオ
レポートも確認してください。

## Leaderboard集計

- Core、Quality、Stability、Robustness、Recoveryは、値が存在するシナリオだけをマクロ平均
- Baseの30設定もChallengeの各シナリオも、Leaderboardでは1シナリオを1票として扱う
- Major violationsはシナリオ間で合計
- Eligibleは重大違反0のシナリオ数を合計
- 旧8指標はBase 30設定だけで項目別に平均し、8項目をさらに平均
- track別にはシナリオ数とCore fidelityを表示
- 重み付き総合点と単一順位は定義しない

## 設計根拠と参考研究

v2の追加指標は、単一の既存ベンチマークを再実装したものではありません。近年の
Role-Playing Agent研究で指摘されている評価上の課題を、Japanese-RP-Benchの日本語・
複数ロール・マルチターン構成へ適用したものです。

| v2の設計要素 | 参考にした研究 | 取り入れた観点 |
|---|---|---|
| Core fidelityと原子ルール | [Spotting Out-of-Character Behavior: Atomic-Level Evaluation of Persona Fidelity in Open-Ended Generation](https://aclanthology.org/2025.findings-acl.1349/) (ACL Findings 2025) | 応答全体の単一スコアでは見逃しやすい細かな人格逸脱を、より小さな単位へ分解して評価する |
| Stabilityと長期ドリフト | [Persistent Personas? Role-Playing, Instruction Following, and Safety in Extended Interactions](https://aclanthology.org/2026.eacl-long.246/) (EACL 2026) | 長い対話の進行に伴うpersona fidelityの低下を、序盤と終盤の比較で捉える |
| 知識境界と偽の共有記憶 | [Memory-Driven Role-Playing: Evaluation and Enhancement of Persona Knowledge Utilization in LLMs](https://aclanthology.org/2026.findings-acl.1175/) (ACL Findings 2026) | キャラクター知識のAnchoring、Selecting、Bounding、Enactingを細かく診断する |
| 知らないことへの応答 | [Tell Me What You Don't Know: Enhancing Refusal Capabilities of Role-Playing Agents via Representation Space Analysis and Editing](https://aclanthology.org/2025.findings-acl.311/) (ACL Findings 2025) | 設定知識と衝突する質問を識別し、過剰拒否せず適切に回答を控えられるかを見る |
| Robustnessの価値・指示衝突 | [RoleCDE: Benchmarking and Mitigating Role-Alignment Trade-offs in Role-Playing Agents](https://aclanthology.org/2026.findings-acl.106/) (ACL Findings 2026) | ロール固有の価値観と外部の要求・制約が衝突する状況での判断を評価する |
| Robustnessの動的シナリオ | [PersonaArena: Dynamic Simulation for Evaluating and Enhancing Persona-Level Role-Playing in Large Language Models](https://aclanthology.org/2026.findings-acl.471/) (ACL Findings 2026) | 静的な一問一答ではなく、状況が変化するマルチターン対話で人格維持を評価する |
| Recovery | [One Battle After Another: Probing LLMs' Limits on Multi-Turn Instruction Following with a Benchmark Evolving Framework](https://aclanthology.org/2026.acl-long.433/) (ACL 2026, EvolIF) | マルチターンでの失敗後の回復を、最終結果だけでなく過程として測る |

旧8指標は元のJapanese-RP-Benchを継承しています。対して、0〜100への換算式、
`major_violations`ゲート、Challengeの具体的な攻撃・回復Probe、シナリオ単位のマクロ平均、
重み付き総合点を設けない方針は、このリポジトリ独自の設計です。特にRecoveryは、
persona fidelity専用の既存指標をそのまま移植したものではなく、マルチターン指示追従研究の
failure recoveryをキャラクター追従性へ応用した実験的指標です。

実際の判定ルールは各Role Pack、算出実装は
[`scoring.py`](../src/japanese_rp_bench/v2/scoring.py)と
[`base.py`](../src/japanese_rp_bench/v2/base.py)が正本です。
