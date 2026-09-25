import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  addHours,
  buildTimeline,
  clone,
  deriveEffort,
  deriveEmotion,
  deriveEvidenceStatus,
  deriveIntent,
  derivePromise,
  deriveRisk,
  idempotencyFingerprint,
  requestId,
} from "./domain.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fixturesPath = path.resolve(__dirname, "../fixtures/demo-cases.json");

export class ServiceError extends Error {
  constructor(code, message, status = 400, retryable = false) {
    super(message);
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

export class CoveniaService {
  constructor(fixtures = JSON.parse(fs.readFileSync(fixturesPath, "utf8"))) {
    this.fixtures = new Map(fixtures.map((item) => [item.demo_case_id, clone(item)]));
    this.runtime = new Map();
    this.idempotency = new Map();
  }

  getFixture(caseId) {
    const fixture = this.fixtures.get(caseId);
    if (!fixture) throw new ServiceError("CASE_NOT_FOUND", `未找到案例 ${caseId}`, 404);
    return clone(fixture);
  }

  buildSnapshot(caseId, options = {}) {
    const fixture = this.getFixture(caseId);
    const caseInput = options.caseInput ?? fixture.case_input;
    const evaluationTime = options.evaluationTime ?? caseInput.evaluation_time ?? new Date().toISOString();
    caseInput.evaluation_time = evaluationTime;
    const runtime = this.runtime.get(caseId) ?? { audit_trail: [] };
    const requestedScope = options.requestedScope ?? caseInput.current_issue;
    const evidenceStatus = deriveEvidenceStatus(caseInput, requestedScope, options.observationOverrides);
    const promise = derivePromise(caseInput);
    const emotion = deriveEmotion(caseInput);
    const intent = deriveIntent(caseInput);
    const effort = deriveEffort({ ...caseInput, prepared_action: fixture.prepared_action }, evidenceStatus, promise);
    const allText = caseInput.conversation.map((message) => message.text).join(" ");
    let risk = deriveRisk({
      emotion,
      effort,
      promise,
      evaluationTime,
      hasFailedResolution: caseInput.service_tickets.some((ticket) => ticket.status !== "已完结"),
      text: allText,
    });
    if (runtime.case_status === "RESOLVED") {
      risk = { ...risk, score: 0, level: "NORMAL", factors: [], resolved_from_score: risk.score };
    }
    const issue = caseInput.current_issue;
    const order = caseInput.order;
    const primary = order.items.find((item) => item.sku_id === issue.sku_id) ?? order.items[0];
    const commitmentStatus = runtime.commitment_status ?? (promise && new Date(evaluationTime) > new Date(promise.deadline) ? "AT_RISK" : "ACTIVE");
    const activeCommitments = promise && commitmentStatus !== "COMPLETED" ? [{ ...promise, status: commitmentStatus }] : [];
    const prohibitedActions = [];
    if (evidenceStatus === "VALID") prohibitedActions.push("ASK_SAME_EVIDENCE", "ASK_REPEAT_EXPLANATION");
    if (intent.current_goal === "CHECK_REPLACEMENT_STATUS") prohibitedActions.push("SHIFT_FOLLOW_UP_TO_CONSUMER");
    if (runtime.case_status !== "RESOLVED") prohibitedActions.push("CLOSE_BEFORE_RESOLUTION");
    const knownFacts = [
      { label: "订单", value: order.order_id, source: "order" },
      { label: "商品", value: `${primary.product_name} · ${primary.sku_id}`, source: "order.items" },
      { label: "问题", value: `${issue.issue_type} / ${issue.affected_component}`, source: "current_issue" },
      { label: "证据", value: `${caseInput.evidence_images.length} 项 · ${evidenceStatus}`, source: "evidence_images" },
    ];
    if (caseInput.service_tickets[0]) knownFacts.push({ label: "工单", value: `${caseInput.service_tickets[0].ticket_id} · ${caseInput.service_tickets[0].status}`, source: caseInput.service_tickets[0].source_sheet });
    const suggestedAction = this.nextBestAction({ evidenceStatus, intent, risk, runtime, caseInput });
    const customerState = {
      case_id: caseId,
      version: runtime.version ?? 1,
      updated_at: evaluationTime,
      facts: { order_id: order.order_id, product: primary.product_name, sku_id: primary.sku_id, issue, known_information: knownFacts },
      evidence: { status: evidenceStatus, count: caseInput.evidence_images.length, items: caseInput.evidence_images.map((item) => ({ id: item.evidence_id, file_name: item.file_name, source_id: item.source_message_id })) },
      intent,
      emotion,
      effort,
      actions: { attempted: runtime.attempted_actions ?? [], next_best_action: suggestedAction },
      promises: { active: activeCommitments, raw: promise },
      risk,
      resolution: { status: runtime.case_status ?? (caseInput.service_tickets.length ? "AT_RISK" : "READY_FOR_BRAND"), completion_condition: "REPLACEMENT_DELIVERED", owner: "BRAND" },
    };
    const accountabilityState = {
      case_id: caseId,
      case_status: customerState.resolution.status,
      consumer_input_required: evidenceStatus !== "VALID",
      accountable_side: evidenceStatus === "MISMATCHED" ? "CONSUMER" : "BRAND",
      evidence_status: evidenceStatus,
      current_scope: { order_id: order.order_id, fulfillment_item_id: issue.fulfillment_item_id, sku_id: issue.sku_id, issue_type: issue.issue_type },
      active_commitments: activeCommitments,
      prohibited_actions: [...new Set(prohibitedActions)],
      experience_gap_diagnosis: {
        consumer_expression: caseInput.conversation.filter((m) => m.speaker === "CONSUMER").at(-1)?.text ?? "",
        traceable_service_facts: knownFacts.map((fact) => ({ fact_type: "OTHER", statement: `${fact.label}：${fact.value}`, source_ids: [fact.source] })),
        deterioration_cause: risk.factors.slice(0, 3).map((item) => item.label).join("、") || "暂无明显升级因素",
        latent_need: intent.expected_resolution,
        responsibility_judgment: { consumer_input_complete: evidenceStatus === "VALID", accountable_side: evidenceStatus === "MISMATCHED" ? "CONSUMER" : "BRAND" },
        action_impacts: [evidenceStatus === "VALID" ? "BLOCK_REPEAT_EVIDENCE" : "REQUEST_MISSING_INPUT", "CHECK_EXISTING_FULFILLMENT"],
        reply_strategy: "先确认已知事实和消费者付出，再说明品牌下一步动作与更新时间。",
      },
      open_obligation: runtime.open_obligation ?? null,
      service_progress_receipt: runtime.service_progress_receipt ?? null,
      experience_risk: risk.level === "CRITICAL" || risk.level === "HIGH" ? "HIGH" : risk.level === "ATTENTION" ? "MEDIUM" : "LOW",
      audit_trail: runtime.audit_trail ?? [],
    };
    const timeline = buildTimeline(caseInput, emotion, promise, runtime);
    return { fixture, caseInput, runtime, customerState, accountabilityState, knownFacts, timeline, suggestedAction };
  }

  nextBestAction({ evidenceStatus, intent, risk, runtime, caseInput }) {
    if (runtime.case_status === "RESOLVED") return { type: "NO_ACTION", label: "案件已解决", reason: "完成条件已满足", requires_approval: false };
    if (evidenceStatus === "NEED_HUMAN_REVIEW") return { type: "HANDOFF_TO_SPECIALIST", label: "转人工复核证据", reason: "当前证据可读性或范围无法确定", requires_approval: true };
    if (evidenceStatus === "MISMATCHED") return { type: "REQUEST_MISSING_EVIDENCE", label: "只请求当前范围缺失材料", reason: "已有证据不覆盖当前商品或问题范围", requires_approval: false };
    if (["CRITICAL", "HIGH"].includes(risk.level)) return { type: "PRIORITY_ESCALATION", label: "优先升级并核查换货进度", reason: risk.factors.slice(0, 3).map((item) => item.label).join("、"), requires_approval: true };
    if (intent.current_goal === "CHECK_REPLACEMENT_STATUS" || caseInput.service_tickets.length) return { type: "CHECK_REPLACEMENT_STATUS", label: "查询已有换货进度", reason: "消费者材料已齐，品牌应接续履约", requires_approval: false };
    return { type: "CONTINUE_SERVICE", label: "继续处理当前问题", reason: "暂无高风险或禁止动作", requires_approval: false };
  }

  analyze(body = {}) {
    if (!body.case_id) throw new ServiceError("SCHEMA_INVALID", "case_id 必填");
    if (body.case_input && body.challenge_mode !== true) throw new ServiceError("SCHEMA_INVALID", "case_input 仅可在 challenge_mode 下使用");
    const snapshot = this.buildSnapshot(body.case_id, { caseInput: body.case_input, evaluationTime: body.evaluation_time });
    const latestConsumer = snapshot.caseInput.conversation.filter((m) => m.speaker === "CONSUMER").at(-1)?.text ?? "";
    const doNotAsk = snapshot.accountabilityState.prohibited_actions.map((code) => ({ code, label: ({ ASK_SAME_EVIDENCE: "不要再次索要相同图片", ASK_REPEAT_EXPLANATION: "不要要求用户重复说明", SHIFT_FOLLOW_UP_TO_CONSUMER: "不要让用户继续催进度", CLOSE_BEFORE_RESOLUTION: "不要在完成前关闭案件" })[code] }));
    const response = this.suggestedReply(snapshot);
    return {
      case_id: body.case_id,
      title: snapshot.fixture.title,
      customer_state: snapshot.customerState,
      accountability_state: snapshot.accountabilityState,
      consumer_story: {
        what_happened: `${snapshot.customerState.facts.product}：${snapshot.customerState.facts.issue.affected_component} ${snapshot.customerState.facts.issue.issue_type}`,
        latest_message: latestConsumer,
        what_we_know: snapshot.knownFacts,
        what_has_been_tried: snapshot.caseInput.service_tickets.map((ticket) => `${ticket.ticket_type} ${ticket.status}`),
        what_the_consumer_wants: snapshot.customerState.intent.current_goal,
        do_not_ask_again: doNotAsk,
        next_best_action: snapshot.suggestedAction,
        suggested_response: response,
      },
      handoff_package: {
        summary: latestConsumer,
        emotion: snapshot.customerState.emotion,
        effort: snapshot.customerState.effort,
        promise: snapshot.customerState.promises,
        risk: snapshot.customerState.risk,
        unresolved_questions: snapshot.customerState.evidence.status === "VALID" ? [] : ["当前证据是否覆盖问题范围"],
      },
      timeline: snapshot.timeline,
      model_metadata: { provider: "DETERMINISTIC_DEMO_ENGINE", model: "covenia-rules-v1.1", cached_result: false, pii_masked_count: 0 },
      cost_metrics: { latency_ms: 8, token_usage: 0, rules_applied: snapshot.customerState.risk.factors.length },
    };
  }

  suggestedReply(snapshot) {
    const state = snapshot.customerState;
    if (state.evidence.status === "MISMATCHED") return "我已看到您之前提交的材料，但它不覆盖当前商品和问题。我只会说明当前缺少的具体证据，不会让您重复提交已有内容。";
    if (state.evidence.status === "NEED_HUMAN_REVIEW") return "我看到您已经提交了图片。当前图片需要人工复核，我会直接转交专员，不会让您重复完成已做过的步骤。";
    const overdue = state.effort.promise_overdue_hours > 0;
    return `我看到您已经说明过问题并提交了 ${state.evidence.count} 项证据，不需要重新提供。${overdue ? `之前的处理承诺已超时约 ${state.effort.promise_overdue_hours} 小时。` : "我会接续已有处理。"}现在我直接为您${snapshot.suggestedAction.label}，并由品牌侧继续跟进。`;
  }

  evaluate(body = {}) {
    if (!body.case_id || !body.prepared_action?.action_type) throw new ServiceError("SCHEMA_INVALID", "case_id 与 prepared_action 必填");
    if (body.challenge_overrides && body.challenge_mode !== true) throw new ServiceError("SCHEMA_INVALID", "challenge_overrides 仅可在 challenge_mode 下使用");
    const requestedScope = body.challenge_mode && body.challenge_overrides?.requested_scope ? body.challenge_overrides.requested_scope : body.prepared_action.requested_scope;
    const snapshot = this.buildSnapshot(body.case_id, {
      evaluationTime: body.evaluation_time,
      requestedScope,
      observationOverrides: body.challenge_mode ? body.challenge_overrides?.image_observation_overrides : [],
    });
    const action = body.prepared_action.action_type;
    const prohibitedMap = { ASK_EVIDENCE: "ASK_SAME_EVIDENCE", ASK_REPEAT_EXPLANATION: "ASK_REPEAT_EXPLANATION", SHIFT_FOLLOW_UP_TO_CONSUMER: "SHIFT_FOLLOW_UP_TO_CONSUMER", CLOSE_CASE: "CLOSE_BEFORE_RESOLUTION" };
    let decision = "ALLOW";
    let ruleId = "E0_NO_RULE_MATCHED";
    let priority = 0;
    let reason = "没有限制性规则命中，可以继续执行。";
    const suppressed = [];
    if (prohibitedMap[action] && snapshot.accountabilityState.prohibited_actions.includes(prohibitedMap[action])) {
      decision = "INTERVENE"; ruleId = "P0_PROHIBITED_ACTION"; priority = 400; reason = "该动作会让消费者重复已完成的工作或造成假性结案。";
    } else if (snapshot.customerState.evidence.status === "VALID" && action === "ASK_EVIDENCE") {
      decision = "INTERVENE"; ruleId = "E1"; priority = 300; reason = "当前范围已有有效证据，不应再次索取。";
    } else if (snapshot.customerState.evidence.status === "NEED_HUMAN_REVIEW" || snapshot.caseInput.current_issue.issue_type === "ADVERSE_REACTION") {
      decision = "HUMAN_REVIEW"; ruleId = "H1"; priority = 200; reason = "事实不确定或属于高风险边界，需要人工复核。";
    } else if (snapshot.customerState.evidence.status === "MISMATCHED" && action === "ASK_EVIDENCE") {
      decision = "ALLOW"; ruleId = "E2"; priority = 100; reason = "已有证据不覆盖当前范围，可只请求明确缺失项。";
    }
    if (ruleId === "P0_PROHIBITED_ACTION" && snapshot.customerState.evidence.status === "VALID" && action === "ASK_EVIDENCE") suppressed.push("E1");
    return {
      case_id: body.case_id,
      decision,
      rule_id: ruleId,
      rule_priority: priority,
      reason,
      challenge_mode: body.challenge_mode === true,
      fact_trace: {
        evidence_status: snapshot.customerState.evidence.status,
        prepared_action: action,
        scope_match: snapshot.customerState.evidence.status === "VALID",
        active_promise_count: snapshot.accountabilityState.active_commitments.length,
        suppressed_rule_ids: suppressed,
      },
      accountability_state: snapshot.accountabilityState,
      resolution_path: {
        candidate_type: snapshot.customerState.evidence.status === "MISMATCHED" ? "ASK_CURRENT_SCOPE_EVIDENCE" : snapshot.customerState.evidence.status === "NEED_HUMAN_REVIEW" ? "HUMAN_EVIDENCE_REVIEW" : "CHECK_REPLACEMENT_FULFILLMENT",
        next_best_action: snapshot.suggestedAction,
        consumer_reply_draft: this.suggestedReply(snapshot),
        requires_human_approval: snapshot.suggestedAction.requires_approval,
      },
    };
  }

  withIdempotency(scope, body, operation) {
    if (!body.idempotency_key || body.idempotency_key.length < 8) throw new ServiceError("VALIDATION_ERROR", "idempotency_key 至少 8 个字符");
    const key = `${scope}:${body.idempotency_key}`;
    const fingerprint = idempotencyFingerprint(body);
    const existing = this.idempotency.get(key);
    if (existing) {
      if (existing.fingerprint !== fingerprint) throw new ServiceError("IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同请求", 409);
      return clone(existing.result);
    }
    const result = operation();
    this.idempotency.set(key, { fingerprint, result: clone(result) });
    return result;
  }

  approve(body = {}) {
    if (!body.case_id || !body.approver_id) throw new ServiceError("VALIDATION_ERROR", "case_id 与 approver_id 必填");
    return this.withIdempotency(`approve:${body.case_id}`, body, () => {
      const snapshot = this.buildSnapshot(body.case_id);
      const promise = snapshot.customerState.promises.raw;
      const at = new Date().toISOString();
      const deadline = promise?.deadline ?? addHours(at, 24);
      const nextCheck = body.human_edits?.next_check_at ?? addHours(at, 2);
      const runtime = clone(snapshot.runtime);
      runtime.version = (runtime.version ?? 1) + 1;
      runtime.case_status = "IN_FULFILLMENT";
      runtime.commitment_status = "ACTIVE";
      runtime.open_obligation = {
        obligation_type: "REPLACEMENT_FULFILLMENT",
        status: "ON_TRACK",
        accountable_side: "BRAND",
        executor: body.human_edits?.executor ?? "WAREHOUSE",
        deadline,
        next_check_at: nextCheck,
        milestone: "AWAITING_CARRIER_PICKUP",
        resolution_condition: "REPLACEMENT_DELIVERED",
      };
      runtime.service_progress_receipt = {
        receipt_id: `receipt_${body.case_id}_${runtime.version}`,
        status: "ACTIVE",
        received_evidence: snapshot.caseInput.evidence_images.map((item) => item.file_name),
        brand_action: "品牌正在核查并推进换货履约",
        latest_update_at: at,
        next_update_by: nextCheck,
        consumer_action_required: false,
        recovery_if_missed: body.human_edits?.recovery_if_missed ?? "若未按时更新，系统将升级主管并生成主动通知草稿。",
      };
      runtime.audit_trail = [...(runtime.audit_trail ?? []), { at, actor: body.approver_id, action: "RESOLUTION_APPROVED", changed_fields: Object.keys(body.human_edits ?? {}).concat(["open_obligation", "service_progress_receipt"]), request_id: requestId() }];
      this.runtime.set(body.case_id, runtime);
      const updated = this.buildSnapshot(body.case_id);
      return { case_id: body.case_id, approved_at: at, approved_resolution: body.human_edits ?? {}, accountability_state: updated.accountabilityState, customer_state: updated.customerState };
    });
  }

  shipment(body = {}) {
    if (!body.case_id || !body.event_type || !body.event_time) throw new ServiceError("SCHEMA_INVALID", "case_id、event_type 与 event_time 必填");
    return this.withIdempotency(`shipment:${body.case_id}`, body, () => {
      const snapshot = this.buildSnapshot(body.case_id);
      const runtime = clone(snapshot.runtime);
      if (!runtime.open_obligation) throw new ServiceError("INVALID_EVENT_TRANSITION", "请先批准解决路径并创建履约责任", 409);
      const milestone = runtime.open_obligation.milestone;
      if (body.event_type === "SHIPMENT_DELIVERED" && milestone !== "IN_TRANSIT") throw new ServiceError("INVALID_EVENT_TRANSITION", "未揽收的责任不能直接标记送达", 409);
      if (body.event_type === "SHIPMENT_PICKED_UP" && milestone !== "AWAITING_CARRIER_PICKUP") throw new ServiceError("INVALID_EVENT_TRANSITION", "只有待揽收状态可以接收揽收事件", 409);
      const deadlinePassed = new Date(body.event_time) > new Date(runtime.open_obligation.deadline);
      let action;
      if (body.event_type === "SHIPMENT_PICKED_UP") {
        runtime.open_obligation.milestone = "IN_TRANSIT";
        runtime.open_obligation.executor = "LOGISTICS_PROVIDER";
        runtime.case_status = "IN_FULFILLMENT";
        action = "SHIPMENT_PICKED_UP";
      } else if (body.event_type === "SHIPMENT_NOT_PICKED_UP") {
        runtime.open_obligation.status = deadlinePassed ? "AT_RISK" : "ON_TRACK";
        runtime.case_status = deadlinePassed ? "AT_RISK" : "IN_FULFILLMENT";
        runtime.commitment_status = deadlinePassed ? "AT_RISK" : "ACTIVE";
        runtime.service_progress_receipt.status = deadlinePassed ? "AT_RISK" : "ACTIVE";
        action = "SHIPMENT_NOT_PICKED_UP";
      } else {
        runtime.open_obligation.status = "COMPLETED";
        runtime.open_obligation.milestone = "DELIVERED";
        runtime.case_status = "RESOLVED";
        runtime.commitment_status = "COMPLETED";
        runtime.service_progress_receipt.status = "COMPLETED";
        runtime.service_progress_receipt.brand_action = "换货商品已送达，服务责任已完成";
        action = "SHIPMENT_DELIVERED";
      }
      runtime.service_progress_receipt.latest_update_at = body.event_time;
      runtime.audit_trail = [...(runtime.audit_trail ?? []), { at: body.event_time, actor: "SYSTEM", action, changed_fields: ["case_status", "open_obligation", "service_progress_receipt"], request_id: requestId() }];
      runtime.version = (runtime.version ?? 1) + 1;
      this.runtime.set(body.case_id, runtime);
      const updated = this.buildSnapshot(body.case_id, { evaluationTime: body.event_time });
      return {
        case_id: body.case_id,
        accountability_state: updated.accountabilityState,
        customer_state: updated.customerState,
        follow_up_candidate: body.event_type === "SHIPMENT_NOT_PICKED_UP" ? { type: "WAREHOUSE_FOLLOW_UP", priority: deadlinePassed ? "URGENT" : "HIGH" } : null,
        escalation_candidate: deadlinePassed ? { type: "SUPERVISOR_ESCALATION", reason: "PROMISE_OVERDUE" } : null,
        proactive_notification_draft: deadlinePassed ? { text: `换货仍未揽收，品牌已升级处理；下次更新时间 ${runtime.open_obligation.next_check_at}`, commits_next_update_at: runtime.open_obligation.next_check_at, requires_human_approval: true, channel: "ORIGINAL_CHAT" } : null,
      };
    });
  }

  riskCases() {
    return [...this.fixtures.keys()].map((caseId) => {
      const analysis = this.analyze({ case_id: caseId });
      const state = analysis.customer_state;
      return {
        case_id: caseId,
        title: analysis.title,
        consumer: analysis.accountability_state.experience_gap_diagnosis.consumer_expression.slice(0, 18),
        product: state.facts.product,
        risk: state.risk,
        emotion: state.emotion,
        effort: state.effort,
        promise: state.promises,
        resolution: state.resolution,
        next_best_action: state.actions.next_best_action,
      };
    }).sort((a, b) => b.risk.score - a.risk.score);
  }
}
