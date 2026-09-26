const DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone";
const DEFAULT_MODEL = "jev-latest";

function redactText(value) {
  let masked = 0;
  const replace = (pattern, token) => {
    value = value.replace(pattern, () => {
      masked += 1;
      return token;
    });
  };
  replace(/\b1[3-9]\d{9}\b/g, "[PHONE]");
  replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[EMAIL]");
  replace(/\b\d{8,}\b/g, "[LONG_ID]");
  return { value, masked };
}

export function buildJevState(snapshot) {
  let piiMaskedCount = 0;
  const contacts = snapshot.caseInput.conversation.map((message, index) => {
    const redacted = redactText(message.text);
    piiMaskedCount += redacted.masked;
    return {
      sequence: index + 1,
      at: message.timestamp,
      speaker: message.speaker,
      text: redacted.value,
    };
  });
  const state = snapshot.customerState;
  return {
    state: {
      issue: {
        type: state.facts.issue.issue_type,
        affected_component: state.facts.issue.affected_component,
      },
      contact_history: contacts,
      deterministic_signals: {
        evidence_status: state.evidence.status,
        contact_count: state.effort.contact_count,
        repeated_contact: state.effort.repeated_contact,
        repeated_explanation: state.effort.repeated_explanation,
        repeated_evidence_request: state.effort.repeated_evidence_request === 1,
        waiting_hours: state.effort.waiting_hours,
        promise_status: state.promises.active[0]?.status ?? (state.promises.raw ? "RECORDED_NOT_ACTIVATED" : "NONE"),
        promise_overdue_hours: state.effort.promise_overdue_hours,
        open_ticket_count: snapshot.caseInput.service_tickets.filter((ticket) => ticket.status !== "已完结").length,
        current_intent: state.intent.current_goal,
        evidence_requires_human_review: state.evidence.status === "NEED_HUMAN_REVIEW",
      },
      existing_rule_output: {
        operational_risk_level: state.risk.level,
        next_best_action: snapshot.suggestedAction.type,
        prohibited_actions: snapshot.accountabilityState.prohibited_actions,
      },
    },
    pii_masked_count: piiMaskedCount,
  };
}

export const JEV_QUESTIONS = {
  emotion_change: {
    type: "choice",
    instructions: "How is the consumer's emotional state changing across the full contact history? Base the decision on change over time, not only the latest message.",
    criteria: {
      improving: "The consumer becomes calmer, more reassured, or less frustrated over time.",
      stable: "There is no meaningful directional change, or the evidence is mixed.",
      worsening: "The consumer becomes more frustrated, urgent, distrustful, or confrontational over time.",
    },
  },
  needs_human_review: {
    type: "noul",
    instructions: "Does this service case need human review because facts are ambiguous, evidence is uncertain, stakes are high, or judgment is required beyond deterministic rules?",
    criteria: {
      true: "Human judgment is needed before the next consequential service action.",
      false: "The case can continue under the existing deterministic workflow and approval rules.",
    },
  },
  service_urgency: {
    type: "score",
    instructions: "Rate the urgency for a service operator to review this case now.",
    criteria: [
      "Normal queue; no immediate operator attention needed.",
      "Needs attention today but can follow the normal workflow.",
      "Needs priority review soon because delay or repeated effort is material.",
      "Needs immediate human review because service harm may compound now.",
    ],
  },
};

function validateAnswers(payload) {
  const emotion = payload?.answers?.emotion_change;
  const human = payload?.answers?.needs_human_review;
  const urgency = payload?.answers?.service_urgency;
  if (emotion?.type !== "choice" || !emotion.probabilities || typeof emotion.confidence !== "number") throw new Error("JEV emotion_change answer is invalid");
  if (human?.type !== "noul" || typeof human.noul !== "number") throw new Error("JEV needs_human_review answer is invalid");
  if (urgency?.type !== "score" || typeof urgency.score !== "number" || !urgency.probabilities) throw new Error("JEV service_urgency answer is invalid");
  return { emotion, human, urgency };
}

function mockPayload(state, model) {
  const signals = state.deterministic_signals;
  const worsening = signals.promise_overdue_hours > 0 || signals.repeated_evidence_request || signals.repeated_contact > 0;
  const needsHuman = signals.evidence_requires_human_review;
  return {
    model: `${model}-contract-mock`,
    answers: {
      emotion_change: {
        type: "choice",
        choice: worsening ? "worsening" : "stable",
        confidence: worsening ? 0.78 : 0.66,
        probabilities: worsening ? { improving: 0.04, stable: 0.18, worsening: 0.78 } : { improving: 0.12, stable: 0.66, worsening: 0.22 },
      },
      needs_human_review: { type: "noul", noul: needsHuman ? 0.9 : 0.28 },
      service_urgency: {
        type: "score",
        score: worsening ? 2.2 : 0.8,
        confidence: 0.72,
        legend: { 0: JEV_QUESTIONS.service_urgency.criteria[0], 1: JEV_QUESTIONS.service_urgency.criteria[1], 2: JEV_QUESTIONS.service_urgency.criteria[2], 3: JEV_QUESTIONS.service_urgency.criteria[3] },
        probabilities: worsening ? { 0: 0.04, 1: 0.18, 2: 0.52, 3: 0.26 } : { 0: 0.42, 1: 0.4, 2: 0.14, 3: 0.04 },
      },
    },
    usage: { input_tokens: 0, output_tokens: 0 },
  };
}

export class JevClient {
  constructor(options = {}) {
    this.mode = options.mode ?? process.env.JEV_MODE ?? "mock";
    this.apiKey = options.apiKey ?? process.env.TYPESAFE_API_KEY ?? "";
    this.model = options.model ?? process.env.JEV_MODEL ?? DEFAULT_MODEL;
    this.endpoint = options.endpoint ?? process.env.JEV_ENDPOINT ?? DEFAULT_ENDPOINT;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
    this.timeoutMs = Number(options.timeoutMs ?? process.env.JEV_TIMEOUT_MS ?? 4_000);
  }

  status() {
    return {
      mode: this.mode,
      configured: this.mode === "mock" || (this.mode === "live" && Boolean(this.apiKey)),
      model: this.model,
      endpoint: this.mode === "live" ? this.endpoint : null,
    };
  }

  async evaluate(snapshot) {
    const projection = buildJevState(snapshot);
    if (this.mode === "off") return this.unavailable("DISABLED", projection.pii_masked_count);
    if (this.mode === "live" && !this.apiKey) return this.unavailable("API_KEY_MISSING", projection.pii_masked_count);
    const startedAt = Date.now();
    let payload;
    if (this.mode === "mock") {
      payload = mockPayload(projection.state, this.model);
    } else if (this.mode === "live") {
      const response = await this.fetchImpl(this.endpoint, {
        method: "POST",
        headers: { authorization: `Bearer ${this.apiKey}`, "content-type": "application/json" },
        body: JSON.stringify({ state: projection.state, model: this.model, questions: JEV_QUESTIONS }),
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      if (!response.ok) throw new Error(`JEV request failed with HTTP ${response.status}`);
      payload = await response.json();
    } else {
      return this.unavailable("INVALID_MODE", projection.pii_masked_count);
    }
    const { emotion, human, urgency } = validateAnswers(payload);
    const worseningProbability = emotion.probabilities.worsening ?? 0;
    const softSignalPoints = Math.round((20 * worseningProbability) + (30 * human.noul));
    return {
      status: "READY",
      provider: this.mode === "live" ? "TYPESAFE_JEV" : "JEV_CONTRACT_MOCK",
      mode: this.mode,
      model: payload.model,
      generated_at: new Date().toISOString(),
      latency_ms: Date.now() - startedAt,
      pii_masked_count: projection.pii_masked_count,
      signals: {
        emotion_change: { selected: emotion.choice, confidence: emotion.confidence, probabilities: emotion.probabilities, primitive: "choice" },
        needs_human_review: { probability: human.noul, threshold: 0.8, candidate: human.noul >= 0.8, primitive: "noul" },
        service_urgency: { score: urgency.score, confidence: urgency.confidence, probabilities: urgency.probabilities, legend: urgency.legend, primitive: "score" },
      },
      decision_support: {
        human_review_candidate: human.noul >= 0.8,
        experimental_formula_preview: {
          expression: "20 × P(emotion_worsening) + 30 × P(needs_human_review)",
          soft_signal_points: softSignalPoints,
          used_for_operational_risk: false,
        },
      },
      usage: payload.usage,
      governance: {
        calibrated_claim_applies: this.mode === "live",
        simulated_probabilities: this.mode !== "live",
        advisory_only: true,
        overrides_existing_rules: false,
        changes_operational_risk_score: false,
        requires_human_confirmation: true,
        disclaimer: this.mode === "live"
          ? "JEV 提供概率化软信号；Covenia 的硬规则、权限与人工审批继续生效。上线前必须使用本企业标注数据完成校准验证。"
          : "当前为接口契约 Mock，概率不是 JEV 实际输出，不得作为模型效果或校准能力证据。",
      },
    };
  }

  unavailable(reason, piiMaskedCount) {
    return {
      status: "UNAVAILABLE",
      provider: "TYPESAFE_JEV",
      mode: this.mode,
      model: this.model,
      reason,
      pii_masked_count: piiMaskedCount,
      signals: null,
      governance: {
        advisory_only: true,
        overrides_existing_rules: false,
        changes_operational_risk_score: false,
        requires_human_confirmation: true,
      },
    };
  }
}
