export type Provider = "opencode";

export type ScoreKey =
  | "summary"
  | "roleFidelity"
  | "quality"
  | "personaStability"
  | "robustness"
  | "recovery";

export type ScenarioKey =
  | "careerMentor"
  | "windGuide"
  | "museumCurator"
  | "teaRoom"
  | "nikechanBaseline"
  | "nikechanAdversarial";

export type ModelResult = {
  id: string;
  name: string;
  provider: Provider;
  providerLabel: string;
  rank: number;
  summary: number;
  summaryCi95: [number, number];
  firstPlaceProbability: number;
  majorFreeRate: number;
  majorRate: number;
  metrics: Record<Exclude<ScoreKey, "summary">, number>;
  scenarios: Record<ScenarioKey, number>;
};

export const benchmarkMeta = {
  title: "Japanese-RP-Bench v2",
  updatedAt: "2026-07-30",
  modelCount: 8,
  scenariosPerModel: 6,
  generationsPerScenario: 10,
  conversationsPerModel: 60,
  judgeCount: 3,
  judgeOutputs: 6480,
  note:
    "8モデル × Challenge 6シナリオ × 10生成の反復評価。順位はMajor-free率、Major率、RP Summaryの順。95%区間と順位確率を含む。",
};

export const metricMeta: Record<
  ScoreKey,
  { label: string; short: string; description: string }
> = {
  summary: {
    label: "Challenge RP Summary",
    short: "RP要約",
    description:
      "6シナリオのRole Fidelity・Quality・Persona Stabilityと、対象4シナリオのRobustness・Recoveryを同じ重みで平均した補助指標",
  },
  roleFidelity: {
    label: "Role Fidelity",
    short: "役柄追従",
    description: "人格、設定、関係性、知識境界、口調などのルールへの追従性",
  },
  quality: {
    label: "Conversation Quality",
    short: "会話品質",
    description: "自然さ、表現力、創造性、会話の楽しさ",
  },
  personaStability: {
    label: "Persona Stability",
    short: "人格安定",
    description: "会話の進行に伴って人格・設定への追従度が低下しなかったか",
  },
  robustness: {
    label: "Robustness",
    short: "耐性",
    description: "人格置換、引用内命令、偽記憶などへの耐性。Probeを持つ4シナリオで算出",
  },
  recovery: {
    label: "Recovery",
    short: "復帰",
    description: "攻撃や誤誘導のあと、元の人格へ戻れるか。Probeを持つ4シナリオで算出",
  },
};

export const results: ModelResult[] = [
  {
    id: "opencode-go-grok-4.5",
    name: "Grok 4.5",
    provider: "opencode",
    providerLabel: "OpenCode Go",
    rank: 1,
    summary: 95.763997,
    summaryCi95: [93.55623, 96.954678],
    firstPlaceProbability: 79.35,
    majorFreeRate: 96.666667,
    majorRate: 5,
    metrics: { roleFidelity: 99.2004, quality: 82.7178, personaStability: 99.714283, robustness: 97.5, recovery: 99.6875 },
    scenarios: { careerMentor: 93.7835, windGuide: 95.21038, museumCurator: 96.15556, teaRoom: 96.11562, nikechanBaseline: 94.657133, nikechanAdversarial: 95.16304 },
  },
  {
    id: "opencode-go-hy3",
    name: "Hy3",
    provider: "opencode",
    providerLabel: "OpenCode Go",
    rank: 2,
    summary: 94.555342,
    summaryCi95: [91.601736, 96.579424],
    firstPlaceProbability: 10.31,
    majorFreeRate: 86.666667,
    majorRate: 15,
    metrics: { roleFidelity: 98.222233, quality: 84.005883, personaStability: 98.361117, robustness: 97.5, recovery: 94.687475 },
    scenarios: { careerMentor: 93.003067, windGuide: 94.4008, museumCurator: 90.70032, teaRoom: 96.18032, nikechanBaseline: 94.669733, nikechanAdversarial: 96.57194 },
  },
  {
    id: "opencode-go-minimax-m3",
    name: "MiniMax M3",
    provider: "opencode",
    providerLabel: "OpenCode Go",
    rank: 3,
    summary: 93.619562,
    summaryCi95: [89.897596, 96.271906],
    firstPlaceProbability: 1.08,
    majorFreeRate: 86.666667,
    majorRate: 23.333333,
    metrics: { roleFidelity: 97.35515, quality: 82.339867, personaStability: 97.361117, robustness: 96.25, recovery: 94.791675 },
    scenarios: { careerMentor: 94.3924, windGuide: 91.3891, museumCurator: 91.29594, teaRoom: 93.01896, nikechanBaseline: 95.410867, nikechanAdversarial: 95.71474 },
  },
  {
    id: "opencode-go-glm-5.2",
    name: "GLM-5.2",
    provider: "opencode",
    providerLabel: "OpenCode Go",
    rank: 4,
    summary: 93.733935,
    summaryCi95: [91.059919, 95.995847],
    firstPlaceProbability: 5.63,
    majorFreeRate: 85,
    majorRate: 16.666667,
    metrics: { roleFidelity: 96.946433, quality: 81.667717, personaStability: 97.1389, robustness: 96.875, recovery: 96.041625 },
    scenarios: { careerMentor: 89.292833, windGuide: 94.3017, museumCurator: 90.64762, teaRoom: 93.18726, nikechanBaseline: 95.3711, nikechanAdversarial: 96.30202 },
  },
  {
    id: "opencode-go-kimi-k3",
    name: "Kimi K3",
    provider: "opencode",
    providerLabel: "OpenCode Go",
    rank: 5,
    summary: 89.587545,
    summaryCi95: [78.193453, 96.312469],
    firstPlaceProbability: 3.11,
    majorFreeRate: 78.333333,
    majorRate: 40,
    metrics: { roleFidelity: 96.236067, quality: 83.972483, personaStability: 97.83335, robustness: 73.4375, recovery: 96.458325 },
    scenarios: { careerMentor: 92.215867, windGuide: 72.07908, museumCurator: 95.05182, teaRoom: 93.4707, nikechanBaseline: 94.7231, nikechanAdversarial: 96.80196 },
  },
  {
    id: "opencode-go-qwen3.7-max",
    name: "Qwen3.7 Max",
    provider: "opencode",
    providerLabel: "OpenCode Go",
    rank: 6,
    summary: 88.24073,
    summaryCi95: [75.52402, 96.019307],
    firstPlaceProbability: 0.12,
    majorFreeRate: 71.666667,
    majorRate: 46.666667,
    metrics: { roleFidelity: 95.365033, quality: 82.109433, personaStability: 96.958333, robustness: 73.4375, recovery: 93.33335 },
    scenarios: { careerMentor: 92.612833, windGuide: 67.25408, museumCurator: 92.04714, teaRoom: 94.77882, nikechanBaseline: 94.167833, nikechanAdversarial: 96.5876 },
  },
  {
    id: "opencode-go-deepseek-v4-pro",
    name: "DeepSeek V4 Pro",
    provider: "opencode",
    providerLabel: "OpenCode Go",
    rank: 7,
    summary: 88.194067,
    summaryCi95: [77.468367, 95.954556],
    firstPlaceProbability: 0.39,
    majorFreeRate: 68.333333,
    majorRate: 46.666667,
    metrics: { roleFidelity: 95.257883, quality: 81.4436, personaStability: 96.45635, robustness: 74.6875, recovery: 93.125 },
    scenarios: { careerMentor: 93.994933, windGuide: 70.78184, museumCurator: 87.92752, teaRoom: 94.8207, nikechanBaseline: 93.586, nikechanAdversarial: 95.96078 },
  },
  {
    id: "opencode-go-mimo-v2.5-pro",
    name: "MiMo V2.5 Pro",
    provider: "opencode",
    providerLabel: "OpenCode Go",
    rank: 8,
    summary: 85.668573,
    summaryCi95: [75.532126, 93.839669],
    firstPlaceProbability: 0.01,
    majorFreeRate: 55,
    majorRate: 75,
    metrics: { roleFidelity: 93.406733, quality: 78.544317, personaStability: 96.496017, robustness: 63.22915, recovery: 96.66665 },
    scenarios: { careerMentor: 91.455633, windGuide: 69.13912, museumCurator: 87.47858, teaRoom: 87.38662, nikechanBaseline: 92.474167, nikechanAdversarial: 95.69092 },
  },
];

export const getScore = (result: ModelResult, key: ScoreKey) =>
  key === "summary" ? result.summary : result.metrics[key];
