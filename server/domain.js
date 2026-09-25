import { randomUUID } from "node:crypto";

const EMOTION_LEVELS = ["CALM", "CONCERNED", "FRUSTRATED", "ANGRY"];

export const clone = (value) => structuredClone(value);

export function addHours(iso, hours) {
  return new Date(new Date(iso).getTime() + hours * 3_600_000).toISOString();
}

export function derivePromise(caseInput) {
  const candidates = caseInput.conversation
    .filter((message) => message.speaker === "AGENT")
    .map((message) => ({ ...message, match: message.text.match(/(\d+)\s*小时内发出/) }))
    .filter((message) => message.match);
  if (!candidates.length) return null;
  const source = candidates.at(-1);
  const hours = Number(source.match[1]);
  return {
    promise_type: "REPLACEMENT_SHIPMENT",
    raw_text: source.text,
    deadline: addHours(source.timestamp, hours),
    source_ids: [source.message_id],
    owner: "BRAND",
  };
}

function emotionFor(text) {
  const cueSets = [
    { emotion: "ANGRY", intensity: 4, patterns: ["投诉", "曝光", "12315", "气死", "愤怒"] },
    { emotion: "FRUSTRATED", intensity: 3, patterns: ["已经", "到底", "怎么还", "又要", "重新", "等了", "前天"] },
    { emotion: "CONCERNED", intensity: 2, patterns: ["急", "不行", "坏", "没有"] },
  ];
  for (const set of cueSets) {
    const matched_cues = set.patterns.filter((cue) => text.includes(cue));
    if (matched_cues.length) return { emotion: set.emotion, intensity: set.intensity, matched_cues };
  }
  return { emotion: "CALM", intensity: 1, matched_cues: [] };
}

export function deriveEmotion(caseInput) {
  const events = caseInput.conversation
    .filter((message) => message.speaker === "CONSUMER")
    .map((message) => {
      const inferred = emotionFor(message.text);
      return {
        at: message.timestamp,
        source_type: "CONVERSATION",
        source_id: message.message_id,
        quote: message.text,
        observed_cues: inferred.matched_cues,
        inference: {
          label: inferred.emotion,
          intensity: inferred.intensity,
          confidence: inferred.matched_cues.length ? 0.82 : 0.55,
          method: "LEXICAL_CUE_DEMO_RULE",
          is_inference: true,
        },
      };
    });
  const current = events.at(-1)?.inference ?? { label: "CALM", intensity: 1, confidence: 0.5 };
  const first = events[0]?.inference ?? current;
  const trend = current.intensity > first.intensity ? "ESCALATING" : current.intensity < first.intensity ? "IMPROVING" : "STABLE";
  const causes = [];
  const allText = caseInput.conversation.map((message) => message.text).join(" ");
  if (/重新|发过|又要|怎么还要/.test(allText)) causes.push("REPEATED_REQUEST");
  if (/前天|等了|到底有没有发/.test(allText)) causes.push("WAITING_WITHOUT_UPDATE");
  const sourceIds = events.map((event) => event.source_id);
  const inferences = [
    { field: "current", value: current.label, confidence: current.confidence, derived_from: events.at(-1) ? [events.at(-1).source_id] : [], is_inference: true },
    { field: "trend", value: trend, confidence: events.length > 1 ? 0.78 : 0.5, derived_from: sourceIds, is_inference: true },
    { field: "causes", value: causes, confidence: 0.72, derived_from: sourceIds, is_inference: true },
  ];
  const actionSupport = [];
  if (causes.includes("REPEATED_REQUEST")) actionSupport.push({ type: "ACKNOWLEDGE_REPETITION", suggestion: "先确认用户已经说明或提交过的信息，再继续处理。", source_ids: sourceIds });
  if (causes.includes("WAITING_WITHOUT_UPDATE")) actionSupport.push({ type: "GIVE_CONCRETE_UPDATE", suggestion: "说明当前进度、责任方和下一次更新时间，避免只做泛化道歉。", source_ids: sourceIds });
  if (trend === "ESCALATING") actionSupport.push({ type: "USE_CALM_DIRECT_TONE", suggestion: "使用简短、直接、承担责任的表达；是否升级仍由事实规则决定。", source_ids: sourceIds });
  return {
    current: current.label,
    intensity: current.intensity,
    trend,
    causes,
    events,
    inferences,
    action_support: actionSupport,
    confidence: current.confidence,
    governance: {
      advisory_only: true,
      overrides_existing_rules: false,
      included_in_risk_score: false,
      prediction: false,
      disclaimer: "情绪字段来自对话线索的推断，仅辅助客服理解与表达，不改变体验防线、权限或责任结论。",
    },
  };
}

export function deriveIntent(caseInput) {
  const text = caseInput.conversation.filter((m) => m.speaker === "CONSUMER").at(-1)?.text ?? "";
  if (/退款/.test(text)) return { current_goal: "REFUND", expected_resolution: "REFUND_STATUS", rejected_resolution: ["REPEAT_TROUBLESHOOTING"] };
  if (/换货|有没有发|进度/.test(text)) return { current_goal: "CHECK_REPLACEMENT_STATUS", expected_resolution: "REPLACEMENT_DELIVERED", rejected_resolution: ["ASK_SAME_EVIDENCE", "REPEAT_EXPLANATION"] };
  return { current_goal: "RESOLVE_PRODUCT_ISSUE", expected_resolution: "WORKING_PRODUCT", rejected_resolution: [] };
}

export function deriveEvidenceStatus(caseInput, requestedScope = caseInput.current_issue, observationOverrides = []) {
  if (!caseInput.evidence_images.length) return "NEED_HUMAN_REVIEW";
  if (observationOverrides.some((item) => item.readability === "LOW" || item.sku_match === "UNKNOWN")) return "NEED_HUMAN_REVIEW";
  if (observationOverrides.some((item) => item.sku_match === "MISMATCH")) return "MISMATCHED";
  if (caseInput.evidence_images.some((item) => /blur/i.test(item.file_name))) return "NEED_HUMAN_REVIEW";
  const appearsGiftOnly = caseInput.evidence_images.every((item) => /gift/i.test(`${item.evidence_id} ${item.file_name}`));
  const requestedPrimary = requestedScope?.sku_id && !/GIFT/i.test(requestedScope.sku_id);
  if (appearsGiftOnly && requestedPrimary) return "MISMATCHED";
  return "VALID";
}

export function deriveEffort(caseInput, evidenceStatus, promise) {
  const consumerMessages = caseInput.conversation.filter((message) => message.speaker === "CONSUMER");
  const contactDays = new Set(consumerMessages.map((message) => message.timestamp.slice(0, 10))).size;
  const sourceUploads = new Set(caseInput.evidence_images.map((item) => item.source_message_id).filter(Boolean)).size;
  const repeatedExplanation = Math.max(0, consumerMessages.length - contactDays);
  const repeatedUpload = Math.max(0, sourceUploads - 1);
  const repeatedEvidenceRequest = evidenceStatus === "VALID" && caseInput.prepared_action?.action_type === "ASK_EVIDENCE" ? 1 : 0;
  const evaluation = new Date(caseInput.evaluation_time);
  const first = new Date(caseInput.conversation[0]?.timestamp ?? caseInput.evaluation_time);
  const waitingHours = Math.max(0, Math.round((evaluation - first) / 3_600_000));
  const promiseOverdueHours = promise ? Math.max(0, Math.round((evaluation - new Date(promise.deadline)) / 3_600_000)) : 0;
  const rawScore = (Math.max(0, contactDays - 1) * 15) + (repeatedExplanation * 10) + (repeatedUpload * 12) + (repeatedEvidenceRequest * 20) + Math.min(waitingHours, 72) / 6 + (promiseOverdueHours > 0 ? 20 : 0);
  const level = rawScore >= 45 ? "HIGH" : rawScore >= 20 ? "MEDIUM" : "LOW";
  return {
    level,
    score: Math.min(100, Math.round(rawScore)),
    contact_count: contactDays,
    repeated_contact: Math.max(0, contactDays - 1),
    repeated_explanation: repeatedExplanation,
    upload_events: sourceUploads,
    repeated_upload: repeatedUpload,
    repeated_evidence_request: repeatedEvidenceRequest,
    waiting_hours: waitingHours,
    transfer_count: 0,
    ineffective_ai_reply: 0,
    promise_overdue_hours: promiseOverdueHours,
  };
}

export function deriveRisk({ emotion, effort, promise, evaluationTime, hasFailedResolution = false, text = "" }) {
  const factors = [];
  const add = (code, label, weight, evidence) => factors.push({ code, label, weight, evidence });
  if (effort.contact_count >= 3) add("THIRD_CONTACT", "同一问题第三次及以上联系", 20, `Contact ×${effort.contact_count}`);
  else if (effort.contact_count >= 2) add("SECOND_CONTACT", "同一问题第二次联系", 10, `Contact ×${effort.contact_count}`);
  if (effort.repeated_evidence_request) add("REPEATED_EVIDENCE", "已有证据仍被再次索要", 15, "ASK_EVIDENCE + VALID");
  if (hasFailedResolution) add("FAILED_RESOLUTION", "已有处理未解决", 10, "ticket still open");
  if (promise) {
    const remainingHours = (new Date(promise.deadline) - new Date(evaluationTime)) / 3_600_000;
    if (remainingHours < 0) add("PROMISE_OVERDUE", "服务承诺已经超时", 30, `${Math.abs(Math.round(remainingHours))}h overdue`);
    else if (remainingHours <= 4) add("PROMISE_NEAR_DEADLINE", "服务承诺接近截止", 10, `${Math.round(remainingHours)}h remaining`);
  }
  if (/投诉|曝光|12315/.test(text)) add("ESCALATION_KEYWORD", "出现投诉或曝光信号", 30, text.match(/投诉|曝光|12315/)?.[0]);
  const score = Math.min(100, factors.reduce((sum, item) => sum + item.weight, 0));
  const level = score >= 81 ? "CRITICAL" : score >= 61 ? "HIGH" : score >= 31 ? "ATTENTION" : "NORMAL";
  return {
    score,
    level,
    factors,
    context_signals: [{
      code: "EMOTION_CONTEXT",
      label: `情绪推断 ${emotion.current} / ${emotion.trend}`,
      weight: 0,
      used_for_score: false,
      source_ids: emotion.inferences.flatMap((item) => item.derived_from),
      purpose: "仅辅助客服表达和人工判断",
    }],
    policy_version: "competition-v1.2-emotion-advisory",
    prediction: false,
    purpose: "OPERATIONAL_TRIAGE",
  };
}

export function buildMultiSourceFusion(caseInput) {
  const conversationIds = caseInput.conversation.map((item) => item.message_id);
  const imageIds = caseInput.evidence_images.map((item) => item.evidence_id);
  const orderIds = caseInput.order?.order_id ? [caseInput.order.order_id] : [];
  const ticketIds = caseInput.service_tickets.map((item) => item.ticket_id);
  const sources = [
    { type: "CONVERSATION", present: conversationIds.length > 0, count: conversationIds.length, source_ids: conversationIds, authority: "CONSUMER_AND_AGENT_STATEMENTS" },
    { type: "IMAGE", present: imageIds.length > 0, count: imageIds.length, source_ids: imageIds, authority: "OBSERVATIONAL_EVIDENCE" },
    { type: "ORDER", present: orderIds.length > 0, count: orderIds.length, source_ids: orderIds, authority: "SYSTEM_OF_RECORD" },
    { type: "TICKET", present: ticketIds.length > 0, count: ticketIds.length, source_ids: ticketIds, authority: "SYSTEM_OF_RECORD" },
  ];
  const presentCount = sources.filter((source) => source.present).length;
  const issue = caseInput.current_issue;
  const conflicts = [];
  if (caseInput.order && !caseInput.order.items.some((item) => item.sku_id === issue.sku_id)) {
    conflicts.push({ code: "ISSUE_SKU_NOT_IN_ORDER", fields: ["current_issue.sku_id", "order.items[].sku_id"], requires_human_review: true });
  }
  return {
    status: conflicts.length ? "CONFLICT" : presentCount === sources.length ? "COMPLETE" : "PARTIAL",
    completeness: presentCount / sources.length,
    sources,
    joins: [
      { from: "CONVERSATION", to: "ORDER", key: "source_session_id → order_id", status: orderIds.length ? "LINKED" : "MISSING" },
      { from: "CONVERSATION", to: "IMAGE", key: "message_id → source_message_id", status: imageIds.length ? "LINKED" : "MISSING" },
      { from: "ORDER", to: "TICKET", key: "order_id / case_id", status: ticketIds.length ? "LINKED" : "MISSING" },
    ],
    entity_keys: {
      source_session_id: caseInput.data_provenance?.source_session_id ?? null,
      order_id: caseInput.order?.order_id ?? null,
      sku_id: issue?.sku_id ?? null,
      ticket_ids: ticketIds,
    },
    conflicts,
    provenance_policy: "SYSTEM_FACTS_OVER_HUMAN_EDITS_OVER_RULES_OVER_MODEL_INFERENCE",
  };
}

export function detectEmergingIssues(signals, options = {}) {
  if (!signals.length) return [];
  const threshold = options.threshold ?? 3;
  const windowHours = options.windowHours ?? 24;
  const latest = options.now ? new Date(options.now) : new Date(Math.max(...signals.map((item) => new Date(item.occurred_at).getTime())) + 3_600_000);
  const currentStart = new Date(latest.getTime() - windowHours * 3_600_000);
  const previousStart = new Date(currentStart.getTime() - windowHours * 3_600_000);
  const fingerprint = (item) => [item.sku_id, item.affected_component, item.issue_type].join("::");
  const groups = new Map();
  for (const signal of signals) {
    const key = fingerprint(signal);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(signal);
  }
  const issues = [];
  for (const [key, items] of groups) {
    const current = items.filter((item) => new Date(item.occurred_at) > currentStart && new Date(item.occurred_at) <= latest);
    const previous = items.filter((item) => new Date(item.occurred_at) > previousStart && new Date(item.occurred_at) <= currentStart);
    const uniqueCustomers = new Set(current.map((item) => item.customer_key));
    if (uniqueCustomers.size < threshold) continue;
    const exemplar = current[0];
    const previousUnique = new Set(previous.map((item) => item.customer_key)).size;
    const growthPercent = previousUnique === 0 ? null : Math.round(((uniqueCustomers.size - previousUnique) / previousUnique) * 100);
    issues.push({
      issue_id: `emerging_${key.replaceAll("::", "_").toLowerCase()}`,
      fingerprint: { sku_id: exemplar.sku_id, product_name: exemplar.product_name, affected_component: exemplar.affected_component, issue_type: exemplar.issue_type },
      status: "EMERGING_CANDIDATE",
      window: { start: currentStart.toISOString(), end: latest.toISOString(), hours: windowHours },
      unique_consumer_count: uniqueCustomers.size,
      signal_count: current.length,
      previous_unique_consumer_count: previousUnique,
      growth_percent: growthPercent,
      source_coverage: [...new Set(current.flatMap((item) => item.source_types))].sort(),
      supporting_signal_ids: current.map((item) => item.signal_id),
      severity: uniqueCustomers.size >= 5 ? "HIGH" : "ATTENTION",
      requires_human_confirmation: true,
      prediction: false,
      explanation: `${windowHours} 小时内 ${uniqueCustomers.size} 个独立消费者出现相同 SKU、组件与问题类型。`,
      data_provenance: [...new Set(current.map((item) => item.data_provenance))],
    });
  }
  return issues.sort((a, b) => b.unique_consumer_count - a.unique_consumer_count);
}

export function buildTimeline(caseInput, emotion, promise, runtime) {
  const items = caseInput.conversation.map((message) => ({
    at: message.timestamp,
    type: message.speaker === "CONSUMER" ? "CONTACT" : "SERVICE",
    source_type: "CONVERSATION",
    source_ids: [message.message_id],
    title: message.speaker === "CONSUMER" ? "消费者联系" : "客服回复",
    detail: message.text,
    emotion: emotion.events.find((event) => event.source_id === message.message_id)?.inference.label ?? null,
  }));
  const firstObservedAt = caseInput.conversation[0]?.timestamp ?? caseInput.evaluation_time;
  if (caseInput.order?.order_id) items.push({ at: firstObservedAt, type: "ORDER", source_type: "ORDER", source_ids: [caseInput.order.order_id], title: "订单已关联", detail: `${caseInput.order.order_id} · ${caseInput.order.items.length} 个商品`, derived_time: true });
  for (const evidence of caseInput.evidence_images) items.push({ at: evidence.submitted_at, type: "EVIDENCE", source_type: "IMAGE", source_ids: [evidence.evidence_id, evidence.source_message_id].filter(Boolean), title: "证据已提交", detail: evidence.file_name });
  for (const ticket of caseInput.service_tickets) items.push({ at: ticket.created_at, type: "TICKET", source_type: "TICKET", source_ids: [ticket.ticket_id], title: `${ticket.ticket_type} 工单`, detail: `${ticket.ticket_id} · ${ticket.status}` });
  if (promise) items.push({ at: promise.deadline, type: "PROMISE", source_type: "CONVERSATION", source_ids: promise.source_ids, title: "承诺截止时间", detail: promise.raw_text });
  for (const audit of runtime?.audit_trail ?? []) items.push({ at: audit.at, type: "ACTION", source_type: "SYSTEM_EVENT", source_ids: [audit.request_id], title: audit.action, detail: audit.changed_fields.join("、") });
  return items.sort((a, b) => new Date(a.at) - new Date(b.at));
}

export function requestId() {
  return `req_${randomUUID()}`;
}

export function idempotencyFingerprint(body) {
  const stable = (value) => {
    if (Array.isArray(value)) return value.map(stable);
    if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
    return value;
  };
  return JSON.stringify(stable(body));
}

export { EMOTION_LEVELS };
