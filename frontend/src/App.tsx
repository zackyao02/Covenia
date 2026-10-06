import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MutableRefObject } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Clock3,
  Headphones,
  Loader2,
  Menu,
  MessageCircleMore,
  MoreHorizontal,
  PackageCheck,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Store,
  Truck,
  UserRoundCheck,
  X,
} from "lucide-react";
import type {
  AccountabilityState,
  ApproveResolutionRequest,
  Decision,
  DecisionResult,
  ExtractedJourney,
  PreparedAction,
  ServiceProgressReceipt,
  ShipmentEventType,
  DemoServiceEventType,
  EvaluateActionRequest,
  FollowUpCandidate,
  SupervisorEscalationCandidate,
  RuntimeMetrics,
  CustomerState,
  ConversationMessage,
  PriorityState,
  DemoClockStep,
} from "./api/contracts";
import { api } from "./api/client";
import { RetryIdentityStore } from "./api/retryIdentity";
import { decisionLabels, demoCases, formatClock, formatServiceDateTime, type DemoCase } from "./demoData";
import { simulateConsumerReply } from "./consumerSimulator";
import { canRefreshSuggestedDraft, replySuggestionsFor, type ReplySuggestion } from "./replySuggestions";
import { configureMockMode, type MockMode } from "./mockApi";

type PluginPhase = "overview" | "decision" | "resolution" | "approved";

interface AddedMessage {
  id: string;
  kind: "agent" | "consumer" | "receipt" | "status";
  text?: string;
  receipt?: ServiceProgressReceipt;
  time: string;
}

interface StoredDemoSession {
  messages: AddedMessage[];
  draft: string;
  phase: PluginPhase;
  accountability?: AccountabilityState | null;
  followUpCandidate?: FollowUpCandidate | null;
  supervisorCandidate?: SupervisorEscalationCandidate | null;
  simulationTime?: string;
  consumerTurn: number;
  replySuggestions: ReplySuggestion[];
  customerState: CustomerState | null;
  simulationEnded: boolean;
}

const DEMO_SESSION_KEY = "covenia-demo-sessions-v1";

function readDemoSessions(): Record<string, StoredDemoSession> {
  try {
    const value = localStorage.getItem(DEMO_SESSION_KEY);
    return value ? JSON.parse(value) as Record<string, StoredDemoSession> : {};
  } catch {
    return {};
  }
}

function writeDemoSession(caseId: string, session: StoredDemoSession) {
  try {
    const sessions = readDemoSessions();
    sessions[caseId] = session;
    localStorage.setItem(DEMO_SESSION_KEY, JSON.stringify(sessions));
  } catch {
    // Keep the demo usable when browser storage is unavailable.
  }
}

function removeDemoSession(caseId: string) {
  try {
    const sessions = readDemoSessions();
    delete sessions[caseId];
    localStorage.setItem(DEMO_SESSION_KEY, JSON.stringify(sessions));
  } catch {
    // Keep the current page usable when browser storage is unavailable.
  }
}

type StoryCardKey = "story" | "emotion" | "evidence" | "journey" | "promise" | "action";

interface StoryCard {
  key: StoryCardKey;
  eyebrow: string;
  title: string;
  body: string;
  tags: string[];
  focusTitle: string;
  focusPoints: Array<{ label: string; text: string }>;
  knownEvidence?: string[];
  missingEvidence?: string[];
  doNotAsk?: string[];
}

const decisionIcon = {
  INTERVENE: ShieldCheck,
  ALLOW: CheckCircle2,
  HUMAN_REVIEW: UserRoundCheck,
};

function buildEvaluateRequest(
  demoCase: DemoCase,
  preparedAction = demoCase.preparedAction,
  currentState: AccountabilityState | null = null,
): EvaluateActionRequest {
  const base: EvaluateActionRequest = {
    case_id: demoCase.id,
    prepared_action: preparedAction,
    evaluation_time: demoCase.input.evaluation_time,
  };
  if (demoCase.id === "DEMO_002" && currentState?.evidence_status !== "VALID") {
    const giftItem = demoCase.input.order.items.find((item) => item.item_role === "GIFT");
    if (!giftItem) return base;
    return {
      ...base,
      challenge_mode: true,
      challenge_overrides: {
        requested_scope: {
          ...preparedAction.requested_scope!,
          fulfillment_item_id: giftItem.fulfillment_item_id,
          sku_id: giftItem.sku_id,
        },
      },
    };
  }
  if (demoCase.id === "DEMO_003") return { ...base, challenge_mode: true };
  return base;
}

function initialKnownFacts(caseId: string) {
  if (caseId === "DEMO_002") {
    return [
      "消费者反映复颜精华瓶口有裂痕",
      "刚才收到的是赠品面膜外盒照片",
      "精华破损处的照片仍待补充",
    ];
  }
  if (caseId === "DEMO_003") {
    return [
      "消费者描述使用防晒乳后脸部泛红",
      "当前没有可供系统自动判断的完整依据",
      "需人工核实，不自动推断原因",
    ];
  }
  return [
    "粉底液正装 · XC33003",
    "泵头损坏图片已提交并确认",
    "换货单已创建 · 承诺 48 小时发出",
  ];
}

function prohibitedCopy(caseId: string) {
  if (caseId === "DEMO_002") {
    return "不要把赠品面膜照片当作精华瓶口证据";
  }
  if (caseId === "DEMO_003") {
    return "不要自动判断不适原因，也不要建议继续使用";
  }
  return "不要再次索取相同的破损图片";
}

function toShanghaiDateTimeInput(isoTime: string) {
  return new Date(new Date(isoTime).getTime() + 8 * 60 * 60 * 1000).toISOString().slice(0, 16);
}

function fromShanghaiDateTimeInput(localTime: string) {
  return new Date(`${localTime}:00+08:00`).toISOString();
}

function useCountdown(target?: string, referenceTime?: string) {
  if (!target) return { label: "未设置", overdue: false };
  const simulatedNow = referenceTime ? Date.parse(referenceTime) : Date.now();
  const difference = new Date(target).getTime() - simulatedNow;
  const absoluteSeconds = Math.max(0, Math.floor(Math.abs(difference) / 1000));
  const hours = Math.floor(absoluteSeconds / 3600);
  const minutes = Math.floor((absoluteSeconds % 3600) / 60);
  const seconds = absoluteSeconds % 60;
  const label = `${hours.toString().padStart(2, "0")}:${minutes
    .toString()
    .padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  return { label, overdue: difference < 0 };
}

function nextShipmentEventTime(serviceClock: string | undefined, receiptUpdatedAt: string | undefined, fallback: string) {
  const latest = Math.max(Date.parse(serviceClock ?? fallback), Date.parse(receiptUpdatedAt ?? fallback), Date.parse(fallback));
  return new Date(latest + 60_000).toISOString();
}

function App() {
  const retryIdentities = useRef(new RetryIdentityStore());
  const [selectedId, setSelectedId] = useState("DEMO_001");
  const [accountability, setAccountability] = useState<AccountabilityState | null>(null);
  const [journey, setJourney] = useState<ExtractedJourney | null>(null);
  const [decision, setDecision] = useState<DecisionResult | null>(null);
  const [phase, setPhase] = useState<PluginPhase>("overview");
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [approvalReply, setApprovalReply] = useState("");
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [extraMessages, setExtraMessages] = useState<AddedMessage[]>([]);
  const [blockedDraftText, setBlockedDraftText] = useState<string | null>(null);
  const [blockedDraftReason, setBlockedDraftReason] = useState<string | null>(null);
  const [simulationEnded, setSimulationEnded] = useState(false);
  const [consumerTyping, setConsumerTyping] = useState(false);
  const [consumerStatePending, setConsumerStatePending] = useState(false);
  const [consumerAnalysisError, setConsumerAnalysisError] = useState(false);
  const [replySuggestions, setReplySuggestions] = useState<ReplySuggestion[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [cachedResult, setCachedResult] = useState(false);
  const [runtimeMetrics, setRuntimeMetrics] = useState<RuntimeMetrics | null>(null);
  const [customerState, setCustomerState] = useState<CustomerState | null>(null);
  const [priorityStates, setPriorityStates] = useState<PriorityState[]>([]);
  const [priorityError, setPriorityError] = useState<string | null>(null);
  const [executor, setExecutor] = useState("WAREHOUSE");
  const [nextCheckAt, setNextCheckAt] = useState("");
  const sendSequence = useRef(0);
  const prioritySequence = useRef(0);
  const caseGeneration = useRef(0);
  const draftRef = useRef(draft);
  const accountabilityRef = useRef(accountability);
  accountabilityRef.current = accountability;
  const suggestedDraftRef = useRef<string | null>(null);
  const pendingDraftRef = useRef<string | null>(null);
  const consumerTimer = useRef<number | null>(null);
  const consumerTurn = useRef(0);
  const consumerAnalysisSequence = useRef(0);
  const extraMessagesRef = useRef<AddedMessage[]>([]);
  const [simulationTime, setSimulationTime] = useState(demoCases[0].input.evaluation_time);
  const [clockStepPending, setClockStepPending] = useState<DemoClockStep | null>(null);
  const [clockEventSummary, setClockEventSummary] = useState<string | null>(null);
  const [clockNotificationDraft, setClockNotificationDraft] = useState<string | null>(null);
  const [clockDeadlineStatus, setClockDeadlineStatus] = useState<string | null>(null);
  const [hydratedSessionCase, setHydratedSessionCase] = useState<string | null>(null);

  useEffect(() => { draftRef.current = draft; }, [draft]);
  useEffect(() => { extraMessagesRef.current = extraMessages; }, [extraMessages]);
  const [followUpCandidate, setFollowUpCandidate] = useState<FollowUpCandidate | null>(null);
  const [supervisorCandidate, setSupervisorCandidate] = useState<SupervisorEscalationCandidate | null>(null);
  const [mockMode, setMockMode] = useState<MockMode>("normal");
  const [reloadKey, setReloadKey] = useState(0);

  const selectedCase = useMemo(
    () => demoCases.find((item) => item.id === selectedId) ?? demoCases[0],
    [selectedId],
  );

  useEffect(() => {
    let active = true;
    async function loadCase() {
      if (consumerTimer.current !== null) window.clearTimeout(consumerTimer.current);
      consumerTimer.current = null;
      consumerTurn.current = 0;
      consumerAnalysisSequence.current += 1;
      extraMessagesRef.current = [];
      setHydratedSessionCase(null);
      setLoading(true);
      setLoadError(null);
      setCachedResult(false);
      setRuntimeMetrics(null);
      setCustomerState(null);
      setSimulationTime(selectedCase.input.evaluation_time);
      setClockStepPending(null);
      setClockEventSummary(null);
      setClockNotificationDraft(null);
      setClockDeadlineStatus(null);
      setFollowUpCandidate(null);
      setSupervisorCandidate(null);
      setAccountability(null);
      setJourney(null);
      setDecision(null);
      setPhase("overview");
      setDetailsOpen(false);
      setExtraMessages([]);
      setReplySuggestions([]);
      setConsumerTyping(false);
      setConsumerStatePending(false);
      setConsumerAnalysisError(false);
      setBlockedDraftText(null);
      setSimulationEnded(false);
      let storedSession: StoredDemoSession | undefined = readDemoSessions()[selectedCase.id];
      suggestedDraftRef.current = null;
      setDraft(storedSession?.draft ?? selectedCase.composerText);
      if (storedSession) {
        setFollowUpCandidate(storedSession.followUpCandidate ?? null);
        setSupervisorCandidate(storedSession.supervisorCandidate ?? null);
        setSimulationTime(storedSession.simulationTime ?? selectedCase.input.evaluation_time);
      }

      const result = await api.analyzeCase({
        case_id: selectedCase.id,
        evaluation_time: selectedCase.input.evaluation_time,
        ...(selectedCase.id !== "DEMO_001"
          ? { challenge_mode: true, case_input: selectedCase.input }
          : {}),
      });
      if (!active) return;
      if (result.error) {
        setLoadError(result.error.message);
        setLoading(false);
        return;
      }
      setCachedResult(result.data.model_metadata.cached_result === true);
      setRuntimeMetrics(result.data.runtime_metrics);
      const hasApprovedReview = result.data.accountability_state.audit_trail.some((event) => event.action === "RESOLUTION_APPROVED");
      const backendHasSavedResolution = Boolean(result.data.accountability_state.open_obligation || hasApprovedReview || result.data.accountability_state.demo_service_event);
      if (storedSession?.phase === "approved" && !backendHasSavedResolution) {
        removeDemoSession(selectedCase.id);
        storedSession = undefined;
        setDraft(selectedCase.composerText);
        setFollowUpCandidate(null);
        setSupervisorCandidate(null);
        setSimulationTime(selectedCase.input.evaluation_time);
        setToast("本地服务已重新开始，会话已恢复初始状态");
      }
      const restoredAccountability = result.data.accountability_state;
      setAccountability(restoredAccountability);
      setJourney(result.data.extracted_journey);
      setCustomerState(result.data.customer_state ?? null);
      if (storedSession) {
        extraMessagesRef.current = storedSession.messages;
        setExtraMessages(storedSession.messages);
        setSimulationEnded(storedSession.simulationEnded);
        consumerTurn.current = storedSession.consumerTurn;
        const restoredCustomerState = result.data.customer_state ?? null;
        const latestConsumerText = [...storedSession.messages].reverse().find((item) => item.kind === "consumer")?.text;
        if (latestConsumerText) {
          const refreshedSuggestions = replySuggestionsFor(
            selectedCase.id,
            restoredCustomerState,
            latestConsumerText,
            nextUpdateTimeLabel(restoredAccountability),
            restoredAccountability.demo_service_event ?? null,
            restoredAccountability.open_obligation,
          );
          setReplySuggestions(refreshedSuggestions);
          const draftWasAutomatic = storedSession.replySuggestions.some((item) => item.text === storedSession.draft);
          if (draftWasAutomatic && refreshedSuggestions[0]) {
            suggestedDraftRef.current = refreshedSuggestions[0].text;
            setDraft(refreshedSuggestions[0].text);
          }
        } else {
          setReplySuggestions(storedSession.replySuggestions);
        }
      }
      void refreshPriority();

      const restoredAsApproved = backendHasSavedResolution;
      const shouldRestoreDecision = selectedCase.id !== "DEMO_001" || Boolean(storedSession && storedSession.phase !== "overview") || hasApprovedReview;
      if (shouldRestoreDecision) {
        const restoreAction: PreparedAction = selectedCase.id === "DEMO_001" && storedSession?.phase === "resolution"
          ? { ...selectedCase.preparedAction, action_id: `RESTORE_${Date.now()}`, action_type: "CHECK_REPLACEMENT_PROGRESS", requires_human_approval: true }
          : selectedCase.preparedAction;
        const evaluated = await api.evaluateAction(buildEvaluateRequest(selectedCase, restoreAction, restoredAccountability));
        if (!active) return;
        if (evaluated.error) {
          setLoadError(evaluated.error.message);
          setLoading(false);
          return;
        }
        setDecision(evaluated.data);
        setRuntimeMetrics(evaluated.data.runtime_metrics);
      }
      if (restoredAsApproved) setPhase("approved");
      else setPhase(storedSession?.phase ?? (selectedCase.id !== "DEMO_001" ? "decision" : "overview"));
      setLoading(false);
      setHydratedSessionCase(selectedCase.id);
    }
    void loadCase();
    return () => {
      active = false;
    };
  }, [selectedCase, reloadKey]);

  useEffect(() => {
    if (loading || hydratedSessionCase !== selectedId) return;
    writeDemoSession(selectedId, {
      messages: extraMessages,
      draft,
      phase,
      accountability,
      followUpCandidate,
      supervisorCandidate,
      simulationTime,
      consumerTurn: consumerTurn.current,
      replySuggestions,
      customerState,
      simulationEnded,
    });
  }, [selectedId, hydratedSessionCase, loading, extraMessages, draft, phase, accountability, followUpCandidate, supervisorCandidate, simulationTime, replySuggestions, customerState, simulationEnded]);

  useEffect(() => () => {
    if (consumerTimer.current !== null) window.clearTimeout(consumerTimer.current);
  }, []);

  async function refreshPriority() {
    const sequence = ++prioritySequence.current;
    const result = await api.getPriority();
    if (sequence !== prioritySequence.current) return;
    if (result.error) { setPriorityError(result.error.message); return; }
    setPriorityError(null);
    setPriorityStates(result.data);
  }

  useEffect(() => { void refreshPriority(); }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function nextUpdateTimeLabel(source: AccountabilityState | null = accountability) {
    const value = source?.service_progress_receipt?.next_update_by
      ?? source?.open_obligation?.next_check_at
      ?? source?.open_obligation?.deadline
      ?? source?.active_commitments[0]?.deadline;
    return value ? formatServiceDateTime(value) : null;
  }

  async function evaluateAction(action?: PreparedAction, draftReply?: string) {
    if (!accountability) return null;
    const generation = caseGeneration.current;
    const caseId = selectedCase.id;
    setActing(true);
    const reviewedAction = action ?? (selectedCase.id === "DEMO_002" && accountability.evidence_status === "VALID"
      ? { ...selectedCase.preparedAction, action_type: "CHECK_REPLACEMENT_PROGRESS" as const }
      : selectedCase.preparedAction);
    const result = await api.evaluateAction({ ...buildEvaluateRequest(selectedCase, reviewedAction, accountability), ...(draftReply === undefined ? {} : { draft_reply: draftReply }) });
    if (generation !== caseGeneration.current || caseId !== selectedId) return null;
    setActing(false);
    if (result.error) {
      if (result.error.code === "P0_PROHIBITED_ACTION" && draftReply !== undefined) {
        setBlockedDraftText(draftReply);
        setBlockedDraftReason(result.error.message);
      }
      setToast(result.error.message);
      return null;
    }
    setDecision(result.data);
    setRuntimeMetrics(result.data.runtime_metrics);
    void refreshPriority();
    return result.data;
  }

  async function handleAttemptSend() {
    if (!draft.trim() || acting || consumerTyping) return;
    if (loading || !accountability) {
      setToast("服务分析尚未就绪，请等待分析完成或重新分析后检查回复");
      return;
    }

    const submittedDraft = draftRef.current;
    const caseId = selectedCase.id;
    const sequence = ++sendSequence.current;
    const result = await evaluateAction(undefined, submittedDraft);
    if (sequence !== sendSequence.current || caseId !== selectedId) return;
    if (!result) return;
    const assessment = result.draft_assessment;
    if (result.decision === "INTERVENE") {
      setPhase("decision");
      setBlockedDraftText(submittedDraft);
      setBlockedDraftReason(result.reason);
      setReplySuggestions(replySuggestionsFor(caseId, customerState, submittedDraft, nextUpdateTimeLabel(), accountability?.demo_service_event ?? null, accountability?.open_obligation));
      setToast("消息已暂停，未发送给消费者");
    } else if (result.decision === "ALLOW" && assessment && !assessment.requires_confirmation) {
      setBlockedDraftText(null);
      setBlockedDraftReason(null);
      setPhase(accountabilityRef.current?.open_obligation ? "approved" : "decision");
      setExtraMessages((items) => [
        ...items,
        { id: `MSG_${crypto.randomUUID()}`, kind: "agent", text: assessment.evaluated_text, time: "本地记录" },
      ]);
      queueConsumerReply(caseId, assessment.evaluated_text);
      setReplySuggestions([]);
      if (draftRef.current === submittedDraft) setDraft("");
      setToast("回复已记录在本地；千牛发送尚未接入");
    } else if (assessment) {
      setPhase("decision");
      setBlockedDraftText(null);
      setBlockedDraftReason(null);
      setApprovalReply(assessment.evaluated_text);
      pendingDraftRef.current = submittedDraft;
      setExecutor(accountability?.open_obligation?.milestone === "IN_TRANSIT" ? "LOGISTICS_PROVIDER" : result.resolution_path.executor);
      const suggested = result.resolution_path.compiled_service_responsibility?.next_check_at ?? accountability?.service_progress_receipt?.next_update_by ?? accountability?.open_obligation?.next_check_at ?? accountability?.open_obligation?.deadline;
      setNextCheckAt(suggested ? toShanghaiDateTimeInput(suggested) : "");
      setApprovalOpen(true);
      setToast(assessment.explanation || "草稿需要人工确认");
    } else {
      setPhase("decision");
      setToast("草稿评估未确认可发送，请人工确认后再处理");
    }
  }

  function queueConsumerReply(caseId: string, agentReply: string) {
    const generation = caseGeneration.current;
    const reply = simulateConsumerReply(caseId, agentReply, consumerTurn.current);
    if (reply === null) {
      setSimulationEnded(true);
      setToast("顾客暂未进一步回复；可继续处理当前服务事项");
      return;
    }
    consumerTurn.current += 1;
    setSimulationEnded(false);
    if (consumerTimer.current !== null) window.clearTimeout(consumerTimer.current);
    setConsumerTyping(true);
    consumerTimer.current = window.setTimeout(() => {
      consumerTimer.current = null;
      if (generation !== caseGeneration.current || caseId !== selectedId) return;
      const nextMessages: AddedMessage[] = [...extraMessagesRef.current, {
        id: `CONSUMER_${crypto.randomUUID()}`,
        kind: "consumer",
        text: reply,
        time: "本地模拟顾客",
      }];
      extraMessagesRef.current = nextMessages;
      setExtraMessages(nextMessages);
      setConsumerTyping(false);
      setConsumerStatePending(true);
      setConsumerAnalysisError(false);
      setCustomerState(null);
      const latestAccountability = accountabilityRef.current;
      const initialOptions = replySuggestionsFor(caseId, null, reply, nextUpdateTimeLabel(latestAccountability), latestAccountability?.demo_service_event ?? null, latestAccountability?.open_obligation);
      setReplySuggestions(initialOptions);
      const priorSuggestion = suggestedDraftRef.current;
      if (canRefreshSuggestedDraft(draftRef.current, priorSuggestion)) {
        suggestedDraftRef.current = initialOptions[0].text;
        setDraft(initialOptions[0].text);
      }
      const sequence = ++consumerAnalysisSequence.current;
      const baseTime = Date.parse(selectedCase.input.evaluation_time);
      const messages: ConversationMessage[] = nextMessages
        .filter((item) => (item.kind === "agent" || item.kind === "consumer") && item.text)
        .map((item, index) => ({
          message_id: `DEMO_CHAT_${item.id}`,
          timestamp: new Date(baseTime + (index + 1) * 60_000).toISOString(),
          speaker: item.kind === "agent" ? "AGENT" as const : "CONSUMER" as const,
          text: item.text!,
          source_kind: "DEMO_AUGMENTATION" as const,
        }));
      void api.refreshDemoCustomerState({ case_id: caseId, challenge_mode: true, messages }).then((result) => {
        if (generation !== caseGeneration.current || caseId !== selectedId || sequence !== consumerAnalysisSequence.current) return;
        setConsumerStatePending(false);
        if (result.error) {
          setConsumerAnalysisError(true);
          return;
        }
        setCustomerState(result.data);
        const currentAccountability = accountabilityRef.current;
        const updatedOptions = replySuggestionsFor(caseId, result.data, reply, nextUpdateTimeLabel(currentAccountability), currentAccountability?.demo_service_event ?? null, currentAccountability?.open_obligation);
        setReplySuggestions(updatedOptions);
        if (suggestedDraftRef.current === initialOptions[0].text && draftRef.current === initialOptions[0].text) {
          suggestedDraftRef.current = updatedOptions[0].text;
          setDraft(updatedOptions[0].text);
        }
      });
    }, 1100);
  }

  async function handleQueryProgress() {
    const queryAction: PreparedAction = {
      ...selectedCase.preparedAction,
      action_id: `CHECK_${Date.now()}`,
      action_type: "CHECK_REPLACEMENT_PROGRESS",
      requires_human_approval: true,
    };
    // 查询补发进度必须按当前动作重新评估，不能复用上一次“发送消息”的判断。
    const result = await evaluateAction(queryAction);
    if (!result) return;
    setPhase("resolution");
    setApprovalReply(result.resolution_path.consumer_reply_draft);
    setToast("已找到现有换货工单和待处理节点");
  }

  async function handleGenerateReply() {
    const result = decision ?? (await evaluateAction());
    if (!result) return;
    if (result.decision === "ALLOW") {
      setDraft(result.resolution_path.consumer_reply_draft);
      setToast("精准索证草稿已放入输入框；发送前仍需评估");
      return;
    }
    if (result.decision === "HUMAN_REVIEW") {
      if (extraMessages.some((message) => message.id.startsWith("REVIEW_"))) {
        setToast("待人工复核；当前版本未连接任务创建服务");
        return;
      }
      setDraft(result.resolution_path.consumer_reply_draft);
      setToast("需要人工证据复核；已准备安抚回复");
      return;
    }
    setPhase("resolution");
    setDraft(result.resolution_path.consumer_reply_draft);
    setApprovalReply(result.resolution_path.consumer_reply_draft);
    setToast("解决回复已放入输入框；确认后会本地记录");
  }

  function handleSelectCase(caseId: string) {
    // 案例切换后的分析是异步的；先同步清除旧决策，避免旧案例短暂影响新案例的操作路径。
    setSelectedId(caseId);
    if (consumerTimer.current !== null) window.clearTimeout(consumerTimer.current);
    consumerTimer.current = null;
    consumerTurn.current = 0;
    consumerAnalysisSequence.current += 1;
    extraMessagesRef.current = [];
    setConsumerTyping(false);
    caseGeneration.current += 1;
    sendSequence.current += 1;
    setApprovalOpen(false);
    setApprovalError(null);
    pendingDraftRef.current = null;
    setActing(false);
    setDecision(null);
    setPhase("overview");
    setLoading(true);
    setRuntimeMetrics(null);
  }

  async function handleApprove() {
    if (!decision) return;
    if (decision.resolution_path.creates_obligation && !nextCheckAt) {
      setApprovalError("请先选择下次更新时间。");
      return;
    }
    const generation = caseGeneration.current;
    const caseId = selectedCase.id;
    const identityScope = `approve-${caseId}`;
    const humanEdits = {
      ...(decision.resolution_path.creates_obligation ? { executor: executor as ApproveResolutionRequest["human_edits"]["executor"] } : {}),
      ...(decision.resolution_path.creates_obligation && nextCheckAt ? { next_check_at: fromShanghaiDateTimeInput(nextCheckAt) } : {}),
      consumer_reply: approvalReply,
    };
    const identity = retryIdentities.current.get(identityScope, {
      case_id: caseId,
      candidate_type: decision.resolution_path.candidate_type,
      approver_id: "AGENT_ZHOU",
      human_edits: humanEdits,
    });
    setActing(true);
    const input: ApproveResolutionRequest = {
      case_id: selectedCase.id,
      candidate_type: decision.resolution_path.candidate_type,
      approver_id: "AGENT_ZHOU",
      idempotency_key: identity.idempotencyKey,
      human_edits: humanEdits,
    };
    const result = await api.approveResolution(input);
    if (generation !== caseGeneration.current || caseId !== selectedId) return;
    setActing(false);
    if (result.error) {
      setApprovalError(result.error.code === "P0_PROHIBITED_ACTION"
        ? "这条回复包含重复索证或提前结案内容，没有保存。请修改回复后重试。"
        : result.error.message);
      setToast(result.error.message);
      return;
    }
    retryIdentities.current.clear(identityScope);
    setApprovalError(null);
    accountabilityRef.current = result.data.accountability_state;
    setAccountability(result.data.accountability_state);
    setReplySuggestions([]);
    setPhase("approved");
    setApprovalOpen(false);
    if (pendingDraftRef.current === null || draftRef.current === pendingDraftRef.current) setDraft("");
    pendingDraftRef.current = null;
    const receipt = result.data.accountability_state.service_progress_receipt;
    setExtraMessages((items) => [...items,
      {
        id: `AGENT_${Date.now()}`,
        kind: "agent",
        text: result.data.approved_resolution.consumer_reply_draft,
        time: "本地记录",
      },
      ...(receipt
        ? [
            {
              id: `RECEIPT_${Date.now()}`,
              kind: "receipt" as const,
              receipt,
              time: "现在",
            },
          ]
        : []),
    ]);
    await refreshPriority();
    if (generation !== caseGeneration.current || caseId !== selectedId) return;
    const currentState = await api.getCustomerState(caseId);
    if (generation !== caseGeneration.current || caseId !== selectedId) return;
    if (!currentState.error) setCustomerState(currentState.data);
    queueConsumerReply(caseId, result.data.approved_resolution.consumer_reply_draft);
    setToast("解决路径已确认并本地记录回复；千牛发送尚未接入");
  }

  async function handleShipment(eventType: ShipmentEventType) {
    if (!accountability) return;
    const generation = caseGeneration.current;
    const caseId = selectedCase.id;
    setActing(true);
    const eventTime = nextShipmentEventTime(
      customerState?.service_clock ?? simulationTime,
      accountability.service_progress_receipt?.latest_update_at,
      simulationTime,
    );
    const identityScope = `shipment-${caseId}-${eventType}`;
    const identity = retryIdentities.current.get(identityScope, {
      case_id: caseId,
      event_type: eventType,
      event_time: eventTime,
    }, true);
    const result = await api.pushShipmentEvent({
      case_id: selectedCase.id,
      event_id: identity.eventId!,
      event_type: eventType,
      event_time: eventTime,
      idempotency_key: identity.idempotencyKey,
    });
    if (generation !== caseGeneration.current || caseId !== selectedId) return;
    setActing(false);
    if (result.error) {
      setToast(result.error.message);
      return;
    }
    retryIdentities.current.clear(identityScope);
    setSimulationTime(eventTime);
    accountabilityRef.current = result.data.accountability_state;
    setAccountability(result.data.accountability_state);
    const latestConsumer = [...extraMessagesRef.current].reverse().find((item) => item.kind === "consumer")?.text ?? "";
    const updatedOptions = replySuggestionsFor(caseId, customerState, latestConsumer, nextUpdateTimeLabel(result.data.accountability_state), null, result.data.accountability_state.open_obligation);
    setReplySuggestions(updatedOptions);
    if (canRefreshSuggestedDraft(draftRef.current, suggestedDraftRef.current)) {
      suggestedDraftRef.current = updatedOptions[0].text;
      setDraft(updatedOptions[0].text);
    }
    await refreshPriority();
    if (generation !== caseGeneration.current || caseId !== selectedId) return;
    const currentState = await api.getCustomerState(caseId);
    if (generation !== caseGeneration.current || caseId !== selectedId) return;
    if (!currentState.error) setCustomerState(currentState.data);
    setFollowUpCandidate(result.data.follow_up_candidate);
    setSupervisorCandidate(result.data.supervisor_escalation_candidate);
    const receipt = result.data.accountability_state.service_progress_receipt;
    if (receipt) {
      setExtraMessages((items) => [
        ...items.map((item) => item.kind === "receipt" ? { ...item, receipt, time: "现在" } : item),
        {
          id: `STATUS_${Date.now()}`,
          kind: "status",
          text: result.data.proactive_notification_draft?.text ?? receipt.brand_action,
          receipt,
          time: "现在",
        },
      ]);
    }
    setToast(
      eventType === "SHIPMENT_PICKED_UP"
        ? "物流已揽收，服务责任继续跟踪"
        : eventType === "SHIPMENT_DELIVERED"
          ? "换货件已送达，服务责任已闭环"
          : "责任已升级，催办与主动通知已生成",
    );
  }

  async function handleAdvanceDemoClock(step: DemoClockStep) {
    const obligation = accountability?.open_obligation;
    if (selectedCase.id !== "DEMO_001" || phase !== "approved" || !obligation || obligation.milestone !== "AWAITING_CARRIER_PICKUP" || !accountability?.service_progress_receipt) return;
    const generation = caseGeneration.current;
    const caseId = selectedCase.id;
    const identityScope = `demo-clock-${caseId}-${step}`;
    const identity = retryIdentities.current.get(identityScope, { case_id: caseId, step });
    setActing(true);
    const result = await api.advanceDemoClock({
      case_id: caseId,
      step,
      idempotency_key: identity.idempotencyKey,
    });
    if (generation !== caseGeneration.current || caseId !== selectedId) return;
    setActing(false);
    if (result.error) {
      setToast(result.error.message);
      return;
    }
    retryIdentities.current.clear(identityScope);

    const updated = result.data.accountability_state;
    accountabilityRef.current = updated;
    setAccountability(updated);
    setSimulationTime(result.data.service_clock);
    setCustomerState((previous) => result.data.customer_state ?? (previous ? {
      ...previous,
      service_clock: result.data.service_clock,
      promises: { ...previous.promises, deadline_state: result.data.deadline_state },
    } : null));
    setPriorityStates(result.data.priority_states);
    setPriorityError(null);
    setFollowUpCandidate(result.data.follow_up_candidate);
    setSupervisorCandidate(result.data.supervisor_escalation_candidate);
    setClockEventSummary(result.data.event_summary);
    setClockNotificationDraft(result.data.proactive_notification_draft?.text ?? null);
    setClockDeadlineStatus(result.data.deadline_state.status);
    setClockStepPending(null);
    const latestConsumer = [...extraMessagesRef.current].reverse().find((item) => item.kind === "consumer")?.text ?? "";
    const options = replySuggestionsFor(caseId, result.data.customer_state, latestConsumer, nextUpdateTimeLabel(updated), null, updated.open_obligation);
    setReplySuggestions(options);
    if (canRefreshSuggestedDraft(draftRef.current, suggestedDraftRef.current)) {
      suggestedDraftRef.current = options[0]?.text ?? null;
      if (options[0]) setDraft(options[0].text);
    }
    setToast(result.data.event_summary);
  }

  async function handleDemoServiceEvent(eventType: DemoServiceEventType) {
    if (selectedCase.id !== "DEMO_002" && selectedCase.id !== "DEMO_003") return;
    const generation = caseGeneration.current;
    const caseId = selectedCase.id;
    const identityScope = `demo-service-${caseId}-${eventType}`;
    const identity = retryIdentities.current.get(identityScope, { case_id: caseId, event_type: eventType });
    setActing(true);
    const result = await api.pushDemoServiceEvent({
      case_id: caseId,
      event_type: eventType,
      idempotency_key: identity.idempotencyKey,
    });
    if (generation !== caseGeneration.current || caseId !== selectedId) return;
    setActing(false);
    if (result.error) { setToast(result.error.message); return; }
    retryIdentities.current.clear(identityScope);
    const updated = result.data.accountability_state;
    accountabilityRef.current = updated;
    setAccountability(updated);
    setPhase("approved");
    const latestConsumer = [...extraMessagesRef.current].reverse().find((item) => item.kind === "consumer")?.text ?? "";
    const options = replySuggestionsFor(caseId, customerState, latestConsumer, nextUpdateTimeLabel(updated), eventType);
    setReplySuggestions(options);
    if (canRefreshSuggestedDraft(draftRef.current, suggestedDraftRef.current)) {
      suggestedDraftRef.current = options[0].text;
      setDraft(options[0].text);
    }
    setExtraMessages((items) => [...items, {
      id: `SERVICE_${crypto.randomUUID()}`,
      kind: "status",
      text: result.data.event_summary,
      time: "本地模拟事件",
    }]);
    await refreshPriority();
    setToast(result.data.event_summary);
  }

  function handleRetry() {
    setReloadKey((value) => value + 1);
  }

  function handleMockModeChange(mode: MockMode) {
    configureMockMode(mode);
    setMockMode(mode);
    setReloadKey((value) => value + 1);
  }

  async function handleResetSession() {
    const caseId = selectedCase.id;
    const generation = ++caseGeneration.current;
    if (consumerTimer.current !== null) window.clearTimeout(consumerTimer.current);
    consumerTimer.current = null;
    consumerAnalysisSequence.current += 1;
    sendSequence.current += 1;
    setHydratedSessionCase(null);
    setActing(true);
    const result = await api.resetDemoSession(caseId);
    if (generation !== caseGeneration.current || caseId !== selectedId) return;
    setActing(false);
    if (result.error) {
      setHydratedSessionCase(caseId);
      setToast(result.error.message);
      return;
    }
    removeDemoSession(caseId);
    consumerTurn.current = 0;
    extraMessagesRef.current = [];
    setHydratedSessionCase(null);
    setToast("本会话已重置，可以重新演示");
    setReloadKey((value) => value + 1);
  }

  return (
    <div className="app-shell">
      <TopBar />
      <main className="workbench">
        <ConversationRail
          cases={demoCases.map((item) => {
            if (item.id !== selectedId || !extraMessages.length) return item;
            const latest = [...extraMessages].reverse().find((message) => message.kind === "consumer" || message.kind === "agent");
            if (!latest?.text) return item;
            const latestIsConsumer = latest.kind === "consumer";
            return { ...item, preview: latest.text, time: latest.time, unread: latestIsConsumer ? 1 : 0 };
          })}
          selectedId={selectedId}
          onSelect={handleSelectCase}
        />
        <ChatWorkspace
          key={`${selectedId}-${reloadKey}`}
          demoCase={selectedCase}
          draft={draft}
          setDraft={setDraft}
          onSend={handleAttemptSend}
          acting={acting || loading}
          phase={phase}
          addedMessages={extraMessages}
          currentReceipt={accountability?.service_progress_receipt ?? null}
          blockedDraftText={blockedDraftText}
          blockedDraftReason={blockedDraftReason}
          onDraftChange={(value) => {
            if (value !== suggestedDraftRef.current) suggestedDraftRef.current = null;
            setDraft(value);
            if (value !== blockedDraftText) {
              setBlockedDraftText(null);
              setBlockedDraftReason(null);
            }
          }}
          onUseSafeReply={() => {
            const latestConsumer = [...extraMessages].reverse().find((item) => item.kind === "consumer")?.text ?? "";
            const currentOptions = replySuggestions.length
              ? replySuggestions
              : replySuggestionsFor(
                  selectedId,
                  customerState,
                  latestConsumer,
                  nextUpdateTimeLabel(),
                  accountability?.demo_service_event ?? null,
                  accountability?.open_obligation,
                );
            const currentDraft = draftRef.current.trim();
            const safeReply = currentOptions.find((item) => item.text.trim() && item.text.trim() !== currentDraft)?.text
              ?? (decision?.resolution_path.consumer_reply_draft.trim() !== currentDraft ? decision?.resolution_path.consumer_reply_draft : undefined);
            if (!safeReply?.trim() || safeReply.trim() === currentDraft) {
              setToast("暂时没有不同的安全回复，请修改草稿后重新检查");
              return;
            }
            setReplySuggestions(currentOptions);
            suggestedDraftRef.current = safeReply;
            setDraft(safeReply);
            setBlockedDraftText(null);
            setBlockedDraftReason(null);
            setToast("已替换为安全回复，请核对后再发送");
          }}
          simulationEnded={simulationEnded}
          consumerTyping={consumerTyping}
          replySuggestions={replySuggestions}
          suggestionSource={customerState?.decision_advisory?.source === "JEV" && customerState.decision_advisory.jev_call.succeeded ? "JEV 情绪辅助" : "服务规则"}
          onResetSession={handleResetSession}
        />
        <CoveniaPlugin
          demoCase={selectedCase}
          selectedId={selectedId}
          onSelectCase={handleSelectCase}
          accountability={accountability}
          journey={journey}
          decision={decision}
          phase={phase}
          loading={loading}
          acting={acting}
          detailsOpen={detailsOpen}
          onToggleDetails={() => setDetailsOpen((value) => !value)}
          onQuery={handleQueryProgress}
          onGenerate={handleGenerateReply}
          onApprove={() => {
            if (decision) {
              setApprovalError(null);
              setApprovalReply(decision.resolution_path.consumer_reply_draft);
              setExecutor(accountability?.open_obligation?.milestone === "IN_TRANSIT" ? "LOGISTICS_PROVIDER" : decision.resolution_path.executor);
              const suggested = decision.resolution_path.compiled_service_responsibility?.next_check_at ?? accountability?.service_progress_receipt?.next_update_by ?? accountability?.open_obligation?.next_check_at ?? accountability?.open_obligation?.deadline;
              setNextCheckAt(suggested ? toShanghaiDateTimeInput(suggested) : "");
            }
            // The composer may still contain a blocked draft. Approval starts from the rule-safe reply.
            setApprovalReply(decision?.resolution_path.consumer_reply_draft || "");
            pendingDraftRef.current = null;
            setApprovalOpen(true);
          }}
          onShipment={handleShipment}
          onAdvanceDemoClock={handleAdvanceDemoClock}
          extraMessages={extraMessages}
          clockStepPending={clockStepPending}
          onClockStepPendingChange={setClockStepPending}
          clockEventSummary={clockEventSummary}
          clockNotificationDraft={clockNotificationDraft}
          clockDeadlineStatus={clockDeadlineStatus}
          onUseClockNotificationDraft={(text) => {
            suggestedDraftRef.current = null;
            setDraft(text);
            setToast("已放入客服草稿；发送前仍需检查并确认");
          }}
          onDemoServiceEvent={handleDemoServiceEvent}
          runtimeMetrics={runtimeMetrics}
          customerState={customerState}
          consumerStatePending={consumerStatePending}
          consumerAnalysisError={consumerAnalysisError}
          simulationTime={simulationTime}
          priorityStates={priorityStates}
          priorityError={priorityError}
          onRetryPriority={refreshPriority}
          followUpCandidate={followUpCandidate}
          supervisorCandidate={supervisorCandidate}
          loadError={loadError}
          cachedResult={cachedResult}
          mockMode={mockMode}
          onRetry={handleRetry}
          onMockModeChange={handleMockModeChange}
          reviewSubmitted={extraMessages.some((message) => message.id.startsWith("REVIEW_"))}
          hasLocalReply={extraMessages.some((message) => message.kind === "agent")}
        />
      </main>
      {approvalOpen && decision ? (
        <ApprovalDialog
          decision={decision}
          hasExistingObligation={Boolean(accountability?.open_obligation)}
          fixedExecutor={accountability?.open_obligation?.milestone === "IN_TRANSIT"}
          reply={approvalReply}
          setReply={(value) => { setApprovalReply(value); setApprovalError(null); }}
          executor={executor}
          setExecutor={(value) => { setExecutor(value); setApprovalError(null); }}
          nextCheckAt={nextCheckAt}
          setNextCheckAt={(value) => { setNextCheckAt(value); setApprovalError(null); }}
          acting={acting}
          error={approvalError}
          onClose={() => setApprovalOpen(false)}
          onConfirm={handleApprove}
        />
      ) : null}
      {toast ? (
        <div className="toast" role="status">
          <CheckCircle2 size={17} />
          {toast}
        </div>
      ) : null}
    </div>
  );
}

function TopBar() {
  return (
    <header className="topbar">
      <div className="brand-mark" aria-label="千牛工作台">
        <span className="qianniu-logo"><img src="/brand/qianniu-demo-mark.svg" alt="" /></span>
        <span>千牛工作台</span>
        <span className="topbar-divider" />
        <span className="shop-name">美妆官方旗舰店</span>
      </div>
      <div className="topbar-actions">
        <span className="online-pill"><span /> 在线接待中</span>
        <div className="agent-avatar">周</div>
      </div>
    </header>
  );
}

function ConversationRail({
  cases,
  selectedId,
  onSelect,
}: {
  cases: DemoCase[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [showUnread, setShowUnread] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && window.innerWidth > 1050) {
        event.preventDefault();
        searchRef.current?.focus();
      } else if (event.key === "Escape" && document.activeElement === searchRef.current) {
        setQuery("");
        searchRef.current?.blur();
      }
    };
    document.addEventListener("keydown", handleShortcut);
    return () => document.removeEventListener("keydown", handleShortcut);
  }, []);
  const unreadCount = cases.filter((item) => item.unread).length;
  const visibleCases = cases.filter((item) => {
    const matchesQuery = `${item.title} ${item.preview} ${item.id}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
    return matchesQuery && (!showUnread || Boolean(item.unread));
  });
  return (
    <aside className="conversation-rail">
      <div className="rail-nav" aria-hidden="true">
        <span className="rail-icon active"><MessageCircleMore size={19} /></span>
        <span className="rail-icon"><ClipboardCheck size={19} /></span>
        <span className="rail-icon"><Store size={19} /></span>
        <div className="rail-spacer" />
        <span className="rail-icon"><Menu size={19} /></span>
      </div>
      <div className="sessions-panel">
        <div className="sessions-heading">
          <div>
            <span className="section-kicker">接待中心</span>
            <h2>进行中的会话</h2>
          </div>
        </div>
        <label className="search-box">
          <Search size={15} />
          <input ref={searchRef} aria-label="搜索会话" placeholder="搜索消费者或订单" value={query} onChange={(event) => setQuery(event.target.value)} />
          <kbd className="search-shortcut">Ctrl K</kbd>
        </label>
        <div className="session-filter">
          <button className={!showUnread ? "active" : ""} onClick={() => setShowUnread(false)} aria-pressed={!showUnread}>全部 <span>{cases.length}</span></button>
          <button className={showUnread ? "active" : ""} onClick={() => setShowUnread(true)} aria-pressed={showUnread}>未回复 <span>{unreadCount}</span></button>
        </div>
        <div className="session-list">
          {visibleCases.map((item) => (
            <button
              className={`session-item ${item.id === selectedId ? "selected" : ""}`}
              key={item.id}
              onClick={() => onSelect(item.id)}
              aria-current={item.id === selectedId ? "true" : undefined}
            >
              <div className={`customer-avatar avatar-${cases.findIndex((candidate) => candidate.id === item.id) + 1}`}>
                {item.title.slice(0, 1)}
                <span className="channel-dot" />
              </div>
              <div className="session-copy">
                <div className="session-line">
                  <strong>{item.title}</strong>
                  <time>{item.time}</time>
                </div>
                <div className="session-preview">
                  <span>{item.preview}</span>
                  {item.unread ? <b>{item.unread}</b> : null}
                </div>
                <div className="case-tag-row">
                  <span>{item.sourceLabel}</span>
                </div>
              </div>
            </button>
          ))}
          {visibleCases.length === 0 ? <p className="session-empty">没有符合条件的会话</p> : null}
        </div>
      </div>
    </aside>
  );
}

function ChatWorkspace({
  demoCase,
  draft,
  setDraft,
  onDraftChange,
  onSend,
  acting,
  phase,
  addedMessages,
  currentReceipt,
  blockedDraftText,
  blockedDraftReason,
  onUseSafeReply,
  simulationEnded,
  consumerTyping,
  replySuggestions,
  suggestionSource,
  onResetSession,
}: {
  demoCase: DemoCase;
  draft: string;
  setDraft: (value: string) => void;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  acting: boolean;
  phase: PluginPhase;
  addedMessages: AddedMessage[];
  currentReceipt: ServiceProgressReceipt | null;
  blockedDraftText: string | null;
  blockedDraftReason: string | null;
  onUseSafeReply: () => void;
  simulationEnded: boolean;
  consumerTyping: boolean;
  replySuggestions: ReplySuggestion[];
  suggestionSource: string;
  onResetSession: () => void;
}) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const messagesRef = useRef<HTMLDivElement>(null);
  const resetDialogRef = useRef<HTMLElement>(null);
  const resetTriggerRef = useRef<HTMLButtonElement>(null);
  const currentItem = demoCase.input.order.items.find((item) => item.sku_id === demoCase.input.current_issue.sku_id);
  const productName = (currentItem?.product_name ?? "商品").replace(/^测试/, "").replace(" #", " · ");
  const historicalMessages = demoCase.input.conversation.slice(0, -1);
  const todayMessages = demoCase.input.conversation.slice(-1);
  const latestCustomerQuestion = [...addedMessages].reverse().find((message) => message.kind === "consumer")?.text
    ?? [...demoCase.input.conversation].reverse().find((message) => message.speaker === "CONSUMER")?.text;
  const historyStart = historicalMessages[0]?.timestamp;
  const historyEnd = historicalMessages[historicalMessages.length - 1]?.timestamp;
  const memoryMilestones = demoCase.id === "DEMO_001"
    ? historicalMessages.filter((message) => message.speaker === "CONSUMER" || message.text.includes("换货单")).slice(0, 3)
    : historicalMessages.slice(-3);

  useEffect(() => {
    setHistoryOpen(false);
  }, [demoCase.id]);

  useEffect(() => {
    if (!resetConfirmOpen) return;
    const dialog = resetDialogRef.current;
    dialog?.querySelector<HTMLElement>("button:not(:disabled)")?.focus();
    const trigger = resetTriggerRef.current;
    return () => trigger?.focus();
  }, [resetConfirmOpen]);

  function trapDialogKeys(event: ReactKeyboardEvent<HTMLElement>, onClose: () => void) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const dialog = event.currentTarget;
    const stops = [...dialog.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex='-1'])")]
      .filter((node) => node.getClientRects().length > 0);
    if (!stops.length) { event.preventDefault(); return; }
    const first = stops[0];
    const last = stops[stops.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  }

  useEffect(() => {
    if (addedMessages.length || consumerTyping) {
      messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [addedMessages.length, consumerTyping]);

  const renderConversationMessage = (message: DemoCase["input"]["conversation"][number], index: number, scope: "history" | "today") => (
    <div
      key={message.message_id}
      className={`message-row ${message.speaker === "AGENT" ? "agent" : "consumer"}`}
    >
      {message.speaker === "CONSUMER" ? (
        <div className="message-avatar">{demoCase.title.slice(0, 1)}</div>
      ) : null}
      <div className="message-stack">
        <div className="message-bubble">{message.text}</div>
        {demoCase.id === "DEMO_001" && scope === "history" && index === 2 ? <EvidenceGallery /> : null}
        {demoCase.evidenceVariant === "gift" && demoCase.input.evidence_images.some((evidence) => evidence.source_message_id === message.message_id) ? (
          <EvidenceGallery variant={demoCase.evidenceVariant} />
        ) : null}
        <time>{formatClock(message.timestamp)}</time>
      </div>
      {message.speaker === "AGENT" ? <div className="message-avatar agent-avatar-chat">周</div> : null}
    </div>
  );

  return (
    <section className={`chat-workspace${replySuggestions.length ? " has-reply-suggestions" : ""}`}>
      <header className="chat-header">
        <div>
          <div className="chat-title-row">
            <h1>{demoCase.title}</h1>
            <span className="buyer-badge">消费者</span>
          </div>
          <p>订单 {demoCase.input.order.order_id} · 天猫</p>
        </div>
        <div className="chat-header-actions">
          <button onClick={() => setHistoryOpen((value) => !value)} aria-expanded={historyOpen}><Clock3 size={16} /> 服务记录</button>
          <button ref={resetTriggerRef} className="session-reset-button" onClick={() => setResetConfirmOpen(true)} disabled={acting} title="重置当前演示会话"><RefreshCw size={14} /><span>重置会话</span></button>
        </div>
      </header>
      <div className="context-strip">
        <div className="product-thumb">
          {demoCase.productImage ? <img src={demoCase.productImage} alt={demoCase.productImageIsSynthetic ? "AI生成的演示商品示意图，不代表真实包装" : `${productName}商品图`} /> : <span className="product-thumb-placeholder">{demoCase.productShortLabel}</span>}
        </div>
        <div>
          <strong>{productName}</strong>
          <p>SKU {currentItem?.sku_id ?? demoCase.input.current_issue.sku_id}{demoCase.productImageIsSynthetic ? " · AI 生成演示图" : ""}</p>
        </div>
        <div className="context-price">{demoCase.productPrice}</div>
      </div>
      <div className="messages story-messages" key={demoCase.id} ref={messagesRef}>
        {latestCustomerQuestion ? <div className="current-need-callout"><span>消费者当前最关心</span><strong>“{latestCustomerQuestion}”</strong></div> : null}
        {historicalMessages.length > 0 ? (
          <section className="history-summary-card">
            <div>
              <span>沟通快照 / {historicalMessages.length} 条记录</span>
              <strong>此前已经发生</strong>
              <p>{historyStart ? formatClock(historyStart) : "此前"}–{historyEnd ? formatClock(historyEnd) : "现在"} · 当前会话沟通记录</p>
            </div>
            <button type="button" onClick={() => setHistoryOpen((value) => !value)} aria-expanded={historyOpen}>
              {historyOpen ? "收起完整对话" : "查看完整对话"}
            </button>
            {!historyOpen ? (
              <ol className="history-milestones">
                {memoryMilestones.slice(-2).map((message) => (
                  <li key={message.message_id}>
                    <time>{formatClock(message.timestamp)}</time>
                    <span>{message.text}</span>
                  </li>
                ))}
              </ol>
            ) : null}
            {!historyOpen && (demoCase.id === "DEMO_001" || demoCase.evidenceVariant === "gift") ? (
              <button type="button" className="history-evidence-preview" onClick={() => setHistoryOpen(true)} aria-label={demoCase.evidenceVariant === "gift" ? "查看已经收到的赠品照片" : "查看已经收到的泵头照片"}>
                <img src={demoCase.evidenceVariant === "gift" ? "/evidence/s00001-gift-evidence.jpg" : "/evidence/s00001-product-overview.jpg"} alt={demoCase.evidenceVariant === "gift" ? "已收到的赠品面膜照片" : "已收到的泵头损坏照片"} />
                <span><small>已收到的图片证据</small><strong>{demoCase.evidenceVariant === "gift" ? "赠品面膜外盒照片" : "泵头损坏照片"}</strong><em>查看原始对话与图片</em></span>
                <ChevronRight size={16} />
              </button>
            ) : null}
          </section>
        ) : null}
        {historyOpen ? (
          <div className="history-thread">
            {historicalMessages.map((message, index) => renderConversationMessage(message, index, "history"))}
          </div>
        ) : null}
        <div className="message-day"><span>最新消息</span></div>
        {todayMessages.map((message, index) => renderConversationMessage(message, index, "today"))}
        {addedMessages.map((message) => {
          if (message.kind === "consumer") {
            return (
              <div className="message-row consumer" key={message.id}>
                <div className="message-avatar">{demoCase.title.slice(0, 1)}</div>
                <div className="message-stack">
                  <div className="message-bubble">{message.text}</div>
                  <time>{message.time}</time>
                </div>
              </div>
            );
          }
          if (message.kind === "receipt" && message.receipt) {
            return <ReceiptMessage key={message.id} receipt={currentReceipt ?? message.receipt} />;
          }
          if (message.kind === "status") {
            return (
              <div className="system-update" key={message.id}>
                <span><Sparkles size={13} /> Covenia 主动更新</span>
                <p>{message.text}</p>
              </div>
            );
          }
          return (
            <div className="message-row agent" key={message.id}>
              <div className="message-stack">
                <div className="message-bubble">{message.text}</div>
                <time>{message.time}</time>
              </div>
              <div className="message-avatar agent-avatar-chat">周</div>
            </div>
          );
        })}
        {consumerTyping ? (
          <div className="message-row consumer" role="status" aria-label="模拟顾客正在输入">
            <div className="message-avatar">{demoCase.title.slice(0, 1)}</div>
            <div className="message-stack">
              <div className="message-bubble consumer-typing"><span /><span /><span /></div>
              <time>本地模拟顾客正在输入</time>
            </div>
          </div>
        ) : null}
        {simulationEnded ? (
          <div className="simulation-end-notice" role="status">
            <strong>本案例的顾客对话已演示完</strong>
            <span>你仍可继续查看服务责任和处理结果；这是预设演示对话，不代表真实消费者在线回复。</span>
          </div>
        ) : null}
      </div>
      <div className="composer">
        {blockedDraftText ? (
          <div className="blocked-draft-notice" role="alert">
            <div><strong>这条回复已拦截，未发给消费者</strong><span>{blockedDraftReason ?? "请根据已有材料和当前履约状态修改回复。"}</span></div>
            <button type="button" onClick={onUseSafeReply}>换成安全回复</button>
          </div>
        ) : null}
        {replySuggestions.length ? (
          <div className="reply-suggestion-strip" aria-label="推荐回复">
            <span><Sparkles size={13} /> 推荐回复 <small>{suggestionSource}</small></span>
            <div>
              {replySuggestions.map((option) => (
                <button key={option.id} type="button" className={draft === option.text ? "selected" : ""} onClick={() => onDraftChange(option.text)} aria-pressed={draft === option.text}>
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <div className="composer-tools">
          <span className="draft-label">回复草稿</span>
          <span className="send-check"><CheckCircle2 size={14} /> 回复前检查</span>
        </div>
        <textarea
          aria-label="客服回复内容"
          value={draft}
          onChange={(event) => {
            onDraftChange(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (!acting && !consumerTyping && draft.trim()) onSend();
            }
          }}
          placeholder="输入回复内容…"
        />
        <div className="composer-footer">
          <span>按 Enter 发送 · Shift + Enter 换行</span>
          <button className="send-button" onClick={onSend} disabled={acting || consumerTyping || !draft.trim()}>
            {acting ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
            检查回复
          </button>
        </div>
      </div>
      {resetConfirmOpen ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setResetConfirmOpen(false); }}>
          <section ref={resetDialogRef} className="approval-dialog reset-session-dialog" role="alertdialog" aria-modal="true" aria-labelledby="reset-session-title" aria-describedby="reset-session-description" onKeyDown={(event) => trapDialogKeys(event, () => setResetConfirmOpen(false))}>
            <header>
              <div className="dialog-icon"><RefreshCw size={20} /></div>
              <div><span>当前案例</span><h2 id="reset-session-title">从头开始这段会话？</h2></div>
              <button type="button" onClick={() => setResetConfirmOpen(false)} aria-label="关闭重置确认"><X size={18} /></button>
            </header>
            <p id="reset-session-description" className="reset-session-description">会清除“{demoCase.title}”的模拟回复、顾客追问和履约进度，恢复初始案例。其他会话不受影响。</p>
            <footer>
              <button className="dialog-cancel" type="button" onClick={() => setResetConfirmOpen(false)}>暂不重置</button>
              <button className="dialog-confirm reset-session-confirm" type="button" onClick={() => { setResetConfirmOpen(false); onResetSession(); }}><RefreshCw size={15} />确认重置</button>
            </footer>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function EvidenceGallery({ variant = "hero" }: { variant?: "hero" | "gift" }) {
  if (variant === "gift") {
    return (
      <div className="evidence-grid single">
        <EvidenceCard fileName="s00001-gift-evidence.jpg" className="gift-evidence" label="赠品外盒" fallbackClass="mask-shape" />
      </div>
    );
  }
  return (
    <div className="evidence-grid">
      <EvidenceCard fileName="s00001-product-overview.jpg" className="overview-evidence" label="商品全貌" fallbackClass="bottle-shape" />
      <EvidenceCard fileName="s00001-pump-detail.jpg" className="detail-evidence" label="泵头破损" fallbackClass="pump-shape" />
      <EvidenceCard fileName="s00001-package-context.jpg" className="package-evidence" label="外包装" fallbackClass="box-shape" />
    </div>
  );
}

function EvidenceCard({
  fileName,
  className,
  label,
  fallbackClass,
}: {
  fileName: string;
  className: string;
  label: string;
  fallbackClass: string;
}) {
  const [imageAvailable, setImageAvailable] = useState(true);
  return (
    <div className={`evidence-card ${className}`}>
      {imageAvailable ? (
        <img
          src={`/evidence/${fileName}`}
          alt={label}
          onError={() => setImageAvailable(false)}
        />
      ) : (
        <span className={fallbackClass} />
      )}
      <small>{label}</small>
    </div>
  );
}

function ReceiptMessage({ receipt }: { receipt: ServiceProgressReceipt }) {
  return (
    <div className="receipt-message">
      <div className="receipt-message-head">
        <span><ShieldCheck size={15} /> 服务进度回执</span>
        <small>消费者可见</small>
      </div>
      <p><b>已收到</b> {receipt.received_evidence[0]}，无需再次提交</p>
      <p><b>正在处理</b> {receipt.brand_action}</p>
      <p><b>下次更新</b> {formatServiceDateTime(receipt.next_update_by)}</p>
      <div><Check size={14} /> 消费者当前无需操作</div>
    </div>
  );
}

function buildStoryCards(
  demoCase: DemoCase,
  accountability: AccountabilityState,
  journey: ExtractedJourney | null,
  decision: DecisionResult | null,
): StoryCard[] {
  const commitment = accountability.active_commitments[0];
  const evidenceCount = journey?.image_observations.length ?? demoCase.input.evidence_images.length;
  const knownEvidence = initialKnownFacts(demoCase.id);
  const missingEvidence =
    demoCase.expectedDecision === "INTERVENE"
      ? ["暂无待补充证据。"]
      : demoCase.expectedDecision === "ALLOW"
        ? ["只补当前范围缺失材料：复颜精华瓶口裂痕照片。不要重复索要赠品图片。"]
        : ["涉及使用不适，由人工谨慎核实；不自动推断原因，也不要求提交健康图片。"];
  const doNotAsk = [prohibitedCopy(demoCase.id)];
  const decisionText = decision
    ? decisionLabels[decision.decision].title
    : demoCase.expectedDecision === "ALLOW"
      ? "当前范围需要新证据"
      : demoCase.expectedDecision === "HUMAN_REVIEW"
        ? "事实不足，先人工复核"
        : "优先核查换货进度";

  if (demoCase.id === "DEMO_002") {
    return [
      {
        key: "emotion",
        eyebrow: "沟通状态",
        title: "她发过照片，却又被要求整单重传。",
        body: "系统核对后发现：照片对应赠品，不是破损的精华。",
        tags: ["只补当前缺口"],
        focusTitle: "商品范围",
        focusPoints: [
          { label: "顾虑", text: "消费者愿意补材料，但不想从头解释和重传订单。" },
          { label: "已收", text: "消费者已提交赠品面膜外盒照片。" },
          { label: "下一步", text: "只补精华瓶口的破损照片。" },
        ],
      },
      {
        key: "evidence",
        eyebrow: "已交材料",
        title: "当前证据不对应。",
        body: "面膜外盒照片不能用于判断精华瓶口。",
        tags: ["赠品照片已收", "精华照片待补"],
        focusTitle: "证据状态",
        focusPoints: [],
        knownEvidence,
        missingEvidence,
        doNotAsk,
      },
      {
        key: "journey",
        eyebrow: "当前问题",
        title: "转为核实精华瓶口。",
        body: "收到对应照片后再确认处理方式。",
        tags: ["复颜修护精华"],
        focusTitle: "服务旅程断点",
        focusPoints: [
          { label: "已知", text: "赠品外盒图片已经收到。" },
          { label: "发现", text: "当前诉求是精华瓶口裂痕，已收照片却对应赠品面膜。" },
          { label: "下一步", text: decision?.reason ?? "只请求当前范围缺失材料。" },
        ],
      },
      {
        key: "promise",
        eyebrow: "下一步",
        title: "等待补充精华照片。",
        body: "收到后再确认后续处理时间。",
        tags: ["暂未承诺"],
        focusTitle: "承诺状态",
        focusPoints: [
          { label: "状态", text: "还没有可执行服务承诺。" },
          { label: "条件", text: "需收到精华瓶口照片后再判断处理方案。" },
          { label: "边界", text: "不能把赠品照片当作精华破损证据。" },
        ],
      },
    ];
  }

  if (demoCase.id === "DEMO_003") {
    return [
      {
        key: "emotion",
        eyebrow: "沟通状态",
        title: "她需要有人先接住这件事。",
        body: "此前被要求上传面部照片；现在无需先拍照，转专人核实。",
        tags: ["人工复核", "谨慎处理"],
        focusTitle: "人工复核",
        focusPoints: [
          { label: "接收", text: "消费者描述使用防晒乳后脸部泛红。" },
          { label: "保护", text: "不要求上传面部照片；系统不诊断原因，也不建议继续使用。" },
          { label: "转交", text: "由人工核实，并给出后续联系安排。" },
        ],
      },
      {
        key: "evidence",
        eyebrow: "已交材料",
        title: "当前信息交由人工核实。",
        body: "不自动判断原因，也不要求消费者提交健康图片。",
        tags: ["需人工确认"],
        focusTitle: "证据状态",
        focusPoints: [],
        knownEvidence,
        missingEvidence,
        doNotAsk,
      },
      {
        key: "journey",
        eyebrow: "当前问题",
        title: "使用不适需要谨慎跟进。",
        body: "不适原因交由人工核实，避免自动下结论。",
        tags: ["需要复核"],
        focusTitle: "服务旅程断点",
        focusPoints: [
          { label: "已知", text: "消费者反馈使用防晒乳后脸部泛红。" },
          { label: "风险", text: "涉及身体不适，不能仅凭聊天内容自动判断原因。" },
          { label: "处理", text: decision?.reason ?? "转人工核实后再回复消费者。" },
        ],
      },
      {
        key: "promise",
        eyebrow: "下一步",
        title: "先由人工复核。",
        body: "复核后再回复是否需要补充材料。",
        tags: ["不自动索证"],
        focusTitle: "承诺状态",
        focusPoints: [
          { label: "状态", text: "还没有可执行服务承诺。" },
          { label: "条件", text: "人工复核确认责任后，再进入解决路径。" },
          { label: "体验", text: "复核前先安抚，不要求重复上传。" },
        ],
      },
    ];
  }

  return [
    {
      key: "story",
      eyebrow: "案件摘要",
      title: "她已交过照片，正在等换货进度。",
      body: "照片已收到 · 48 小时换货承诺待跟进",
      tags: ["已收到照片", "等待换货"],
      focusTitle: "发生了什么",
      focusPoints: [
        { label: "01", text: "消费者已说明粉底液泵头损坏。" },
        { label: "02", text: `已提交 ${evidenceCount} 张可追踪证据。` },
        { label: "03", text: "客服已承诺换货单 48 小时内发出。" },
      ],
    },
    {
      key: "emotion",
      eyebrow: "沟通状态",
      title: "再次追问换货进度。",
      body: "先回应进度，避免让她重复说明。",
      tags: ["多次沟通"],
      focusTitle: "为什么体验恶化",
      focusPoints: [
        { label: "承诺", text: commitment ? `${commitment.raw_text}，当前状态 ${commitment.status}。` : "已有服务承诺等待确认。" },
        { label: "打扰", text: "重复索证会让消费者感觉历史材料被忽略。" },
        { label: "等待", text: accountability.experience_gap_diagnosis.deterioration_cause },
      ],
    },
    {
      key: "evidence",
      eyebrow: "已交材料",
      title: `照片已收到（${evidenceCount}）`,
      body: "查看已收到的照片和仍缺的材料。",
      tags: [`${evidenceCount} 张照片`],
      focusTitle: "证据状态",
      focusPoints: [],
      knownEvidence,
      missingEvidence,
      doNotAsk,
    },
    {
      key: "journey",
      eyebrow: "服务进度",
      title: "换货进度待确认。",
      body: "已有换货工单，需核查物流状态。",
      tags: ["已有工单"],
      focusTitle: "服务旅程断点",
      focusPoints: [
        { label: "已完成", text: "消费者已经说明问题并提交图片。" },
        { label: "已形成", text: "客服已承诺 48 小时内发出换货。" },
        { label: "当前", text: "消费者再次进线追问是否发出。" },
      ],
    },
    {
      key: "promise",
      eyebrow: "服务承诺",
      title: commitment ? "48 小时内换货承诺" : "尚无有效承诺",
      body: commitment ? `截止 ${formatServiceDateTime(commitment.deadline)}，由店铺继续跟进。` : "确认责任后再建立服务承诺。",
      tags: [commitment?.status === "ACTIVE" ? "跟进中" : "待确认"],
      focusTitle: "承诺如何运行",
      focusPoints: [
        { label: "来源", text: commitment?.raw_text ?? "来自客服侧承诺与既有换货工单。" },
        { label: "责任", text: "消费者输入已完整，当前应由品牌侧跟进。" },
        { label: "完成", text: "不是建单即完成，必须追踪到换货商品送达。" },
      ],
    },
    {
      key: "action",
      eyebrow: "Next Best Action",
      title: decisionText,
      body: "先核查换货进度，再把可见进展回执给消费者。",
      tags: [decision?.decision ?? "READY", decision?.rule_id ?? "E1", "无需消费者操作"],
      focusTitle: "现在应该做什么",
      focusPoints: [
        { label: "做", text: "查询既有换货工单和物流揽收状态。" },
        { label: "不做", text: prohibitedCopy(demoCase.id) },
        { label: "回复", text: decision?.resolution_path.consumer_reply_draft ?? "告知证据已收到，正在核实换货进度。" },
      ],
    },
  ];
}

function StoryDeck({
  demoCase,
  accountability,
  journey,
  decision,
  phase,
  acting,
  loading,
  onQuery,
  onGenerate,
  onApprove,
  reviewSubmitted,
}: {
  demoCase: DemoCase;
  accountability: AccountabilityState;
  journey: ExtractedJourney | null;
  decision: DecisionResult | null;
  phase: PluginPhase;
  acting: boolean;
  loading: boolean;
  onQuery: () => void;
  onGenerate: () => void;
  onApprove: () => void;
  reviewSubmitted: boolean;
}) {
  const cards = useMemo(
    () => buildStoryCards(demoCase, accountability, journey, decision),
    [demoCase, accountability, journey, decision],
  );
  const [focusKey, setFocusKey] = useState<StoryCardKey | null>(null);
  const sliderRef = useRef<HTMLDivElement | null>(null);
  const entryCards = cards.filter((card) => ["emotion", "evidence", "journey", "promise"].includes(card.key));

  useEffect(() => {
    setFocusKey(null);
  }, [demoCase.id, phase]);

  const focusCard = focusKey ? cards.find((card) => card.key === focusKey) ?? null : null;
  const move = (direction: -1 | 1) => {
    const slider = sliderRef.current;
    const cardWidth = slider?.querySelector(".story-card")?.getBoundingClientRect().width ?? 220;
    slider?.scrollBy({ left: direction * (cardWidth + 10), behavior: "smooth" });
  };

  if (focusCard) {
    return (
      <section className="focus-view">
        <button className="focus-back" onClick={() => setFocusKey(null)} type="button">
          <ChevronLeft size={15} /> 返回 Customer Snapshot
        </button>
        <span className="story-eyebrow">{focusCard.eyebrow}</span>
        <h2>{focusCard.focusTitle}</h2>
        {focusCard.key === "evidence" ? (
          <div className="evidence-focus-grid">
            <section>
              <h3>已知证据</h3>
              {(focusCard.knownEvidence ?? []).map((item) => <p className="evidence-line known" key={item}>✓ {item}</p>)}
            </section>
            <section>
              <h3>待补充证据</h3>
              {(focusCard.missingEvidence ?? []).map((item) => <p className="evidence-line pending" key={item}>● {item}</p>)}
            </section>
            <section className="do-not-ask-chart">
              <h3>❌ 不要再问</h3>
              {(focusCard.doNotAsk ?? []).map((item) => <p className="evidence-line blocked" key={item}>❌ {item}</p>)}
            </section>
          </div>
        ) : (
          <div className="focus-points">
            {focusCard.focusPoints.map((point) => (
              <div key={point.label}>
                <span>{point.label}</span>
                <p>{point.text}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="story-deck">
      <div className="story-hero">
        <span>案件摘要</span>
        <h2>{cards[0].title}</h2>
        <p>{cards[0].body}</p>
        <div>
          {cards[0].tags.map((tag) => <small key={tag}>{tag}</small>)}
        </div>
      </div>

      <div className="card-carousel" aria-label="Customer state cards">
        <button className="carousel-nav" onClick={() => move(-1)} type="button" aria-label="上一张">
          <ChevronLeft size={18} />
        </button>
        <div className="story-card-strip" ref={sliderRef}>
          {entryCards.map((card) => (
            <button className={`story-card card-${card.key}`} key={card.key} onClick={() => setFocusKey(card.key)} type="button">
              <span>{card.eyebrow}</span>
              <strong>{card.title}</strong>
              <p>{card.body}</p>
              <em aria-label="查看详情"><ChevronRight size={13} /></em>
            </button>
          ))}
        </div>
        <button className="carousel-nav" onClick={() => move(1)} type="button" aria-label="下一张">
          <ChevronRight size={18} />
        </button>
      </div>

      <StoryActionPanel
        demoCase={demoCase}
        decision={decision}
        phase={phase}
        acting={acting}
        loading={loading}
        onQuery={onQuery}
        onGenerate={onGenerate}
        onApprove={onApprove}
        reviewSubmitted={reviewSubmitted}
      />
    </section>
  );
}

function StoryActionPanel({
  demoCase,
  decision,
  phase,
  acting,
  loading,
  onQuery,
  onGenerate,
  onApprove,
  reviewSubmitted,
}: {
  demoCase: DemoCase;
  decision: DecisionResult | null;
  phase: PluginPhase;
  acting: boolean;
  loading: boolean;
  onQuery: () => void;
  onGenerate: () => void;
  onApprove: () => void;
  reviewSubmitted: boolean;
}) {
  const decisionType = decision?.decision;
  const approvalLabel = decision?.resolution_path.candidate_type === "HUMAN_EVIDENCE_REVIEW"
    ? "确认转人工复核"
    : decision?.resolution_path.candidate_type === "ASK_CURRENT_SCOPE_EVIDENCE"
      ? "确认精准补证回复"
      : "确认责任与更新时间";
  return (
    <section className="story-action-panel" key={phase}>
      <span>{phase === "resolution" ? "等待人工确认" : "建议的下一步"}</span>
      <h3 aria-live="polite">{phase === "resolution" ? "确认处理安排" : decision?.resolution_path.candidate_type === "HUMAN_EVIDENCE_REVIEW" ? "先交人工核实" : decision?.resolution_path.candidate_type === "ASK_CURRENT_SCOPE_EVIDENCE" ? "只补充缺少的证据" : "跟进现有换货进度"}</h3>
      <p>{phase === "resolution" ? "确认后保存处理责任，并继续跟踪承诺。" : decision?.resolution_path.candidate_type === "HUMAN_EVIDENCE_REVIEW" ? "涉及使用不适，系统不自动判断原因，由专人谨慎核实。" : decision?.resolution_path.candidate_type === "ASK_CURRENT_SCOPE_EVIDENCE" ? "只询问本次商品范围内缺少的材料。" : "先查看本案例已记录的换货进度，再向消费者同步。"}</p>
      {phase === "resolution" ? (
        <button className="primary-action" onClick={onApprove} disabled={acting || loading}>
          <ClipboardCheck size={16} /> {approvalLabel} <ChevronRight size={16} />
        </button>
      ) : decision?.resolution_path.candidate_type === "ASK_CURRENT_SCOPE_EVIDENCE" ? (
        <button className="primary-action allow-action" onClick={onGenerate} disabled={acting}>
          准备补充证据回复 <ChevronRight size={16} />
        </button>
      ) : decisionType === "HUMAN_REVIEW" ? (
        <button className="primary-action review-action" onClick={onGenerate} disabled={acting || reviewSubmitted}>
          准备人工复核回复 <UserRoundCheck size={16} />
        </button>
      ) : (
        <div className="action-stack">
          <button className="primary-action" onClick={onQuery} disabled={acting}>
            {acting ? <Loader2 size={16} className="spin" /> : <Search size={16} />}
            查看已记录的换货进度 <ChevronRight size={16} />
          </button>
        </div>
      )}
    </section>
  );
}

function priorityScore(caseItem: DemoCase) {
  const base = caseItem.expectedDecision === "INTERVENE" ? 110 : caseItem.expectedDecision === "HUMAN_REVIEW" ? 86 : 72;
  const contactBoost = Math.min(caseItem.input.conversation.length * 4, 18);
  const evidenceBoost = Math.min(caseItem.input.evidence_images.length * 5, 15);
  const ticketBoost = caseItem.input.service_tickets.length ? 8 : 0;
  return base + contactBoost + evidenceBoost + ticketBoost;
}

function priorityBand(caseItem: DemoCase) {
  const score = priorityScore(caseItem);
  if (score >= 120) return "red";
  if (score >= 95) return "orange";
  return "yellow";
}

function priorityReasons(caseItem: DemoCase) {
  if (caseItem.expectedDecision === "INTERVENE") return ["承诺待兑现", "重复索证风险", "已有工单未闭环"];
  if (caseItem.expectedDecision === "HUMAN_REVIEW") return ["使用不适反馈", "需人工复核", "不自动判因"];
  return ["问题范围变化", "只补当前缺口", "避免重复材料"];
}

function PriorityQueue({
  selectedId,
  onSelectCase,
  states,
  error,
  onRetry,
}: {
  selectedId: string;
  onSelectCase: (caseId: string) => void;
  states: PriorityState[];
  error: string | null;
  onRetry: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ordered = useMemo(() => states.slice().sort((a, b) => a.rank - b.rank).map((state) => ({ state, item: demoCases.find((entry) => entry.id === state.case_id) })).filter((row): row is { state: PriorityState; item: DemoCase } => Boolean(row.item)), [states]);
  const currentIndex = Math.max(0, ordered.findIndex((item) => item.item.id === selectedId));
  const current = ordered[currentIndex] ?? ordered[0];
  const move = (direction: -1 | 1) => {
    if (!ordered.length) return;
    const nextIndex = (currentIndex + direction + ordered.length) % ordered.length;
    if (ordered[nextIndex]) onSelectCase(ordered[nextIndex].item.id);
  };

  useEffect(() => {
    if (!open) return;
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [open]);

  return (
    <section className="priority-queue-card">
      {error ? <div className="priority-load-error">待处理案件加载失败：{error} <button type="button" onClick={onRetry}>重试</button></div> : null}
      <div className="priority-queue-top">
        <button type="button" onClick={() => move(-1)} aria-label="上一位消费者"><ChevronLeft size={15} /></button>
        <div>
          <span>待跟进责任 · {ordered.length ? `${String(currentIndex + 1).padStart(2, "0")} / ${String(ordered.length).padStart(2, "0")}` : "—"}</span>
          <strong>{current?.item.title ?? "—"}</strong>
          <small className="queue-current-reason">{current?.state.queue_reasons?.[0] ?? ""}</small>
        </div>
        <button type="button" onClick={() => move(1)} aria-label="下一位消费者"><ChevronRight size={15} /></button>
        <button className="priority-toggle-button" type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls="priority-list">
          查看待跟进 <small>{ordered.length} 项责任</small>
        </button>
      </div>
      {open ? (
        <div className="priority-list-panel" id="priority-list">
          <div className="priority-list-head">
            <span>待跟进责任</span>
            <small>{error ? "加载失败" : "服务端优先级"}</small>
          </div>
          {error ? <p>{error} <button type="button" onClick={onRetry}>重试</button></p> : ordered.map(({ item, state }, index) => (
            <button
              type="button"
              className={`priority-list-item ${state.band.toLowerCase()} ${item.id === selectedId ? "selected" : ""}`}
              key={item.id}
              onClick={() => { onSelectCase(item.id); setOpen(false); }}
            >
              <b>{index + 1}</b>
              <strong>{item.title}</strong>
              <small>主要原因：{state.queue_reasons.slice(0, 2).map((reason) => reason.replace(/[。！!?？、，,\s]+$/u, "")).join("；")}</small>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function fusionRows(demoCase: DemoCase, journey: ExtractedJourney | null) {
  return [
    {
      label: "Conversation",
      count: demoCase.input.conversation.length,
      ids: demoCase.input.conversation.map((item) => item.message_id),
    },
    {
      label: "Image",
      count: journey?.image_observations.length ?? demoCase.input.evidence_images.length,
      ids: (journey?.image_observations ?? []).map((item) => item.evidence_id)
        .concat(journey ? [] : demoCase.input.evidence_images.map((item) => item.evidence_id)),
    },
    {
      label: "Order",
      count: 1,
      ids: [demoCase.input.order.order_id],
    },
    {
      label: "Ticket",
      count: demoCase.input.service_tickets.length,
      ids: demoCase.input.service_tickets.map((item) => item.ticket_id),
    },
  ];
}

function timelineRows(demoCase: DemoCase, accountability: AccountabilityState) {
  const firstMessage = demoCase.input.conversation[0];
  const firstEvidence = demoCase.input.evidence_images[0];
  const firstTicket = demoCase.input.service_tickets[0];
  const commitment = accountability.active_commitments[0];
  return [
    {
      time: firstMessage ? formatClock(firstMessage.timestamp) : "—",
      source: "CONVERSATION",
      title: "消费者说明当前诉求",
      detail: firstMessage?.message_id ?? "暂无消息 ID",
    },
    {
      time: firstEvidence ? formatClock(firstEvidence.submitted_at) : "—",
      source: "IMAGE",
      title: "证据进入可追踪状态",
      detail: firstEvidence?.evidence_id ?? "暂无图片证据",
    },
    {
      time: firstTicket ? formatClock(firstTicket.created_at) : "派生",
      source: "TICKET",
      title: firstTicket ? "已有服务工单" : "当前无已建工单",
      detail: firstTicket?.ticket_id ?? "仅使用当前案例上下文",
    },
    {
      time: commitment ? formatClock(commitment.deadline) : "待定",
      source: "PROMISE",
      title: commitment ? "承诺进入责任账本" : "尚未形成可执行承诺",
      detail: commitment?.raw_text ?? "需先完成人工确认或证据复核",
    },
  ];
}

function riskFactors(demoCase: DemoCase, accountability: AccountabilityState) {
  const score = priorityScore(demoCase);
  const factors = [
    {
      label: "Experience Risk",
      value: accountability.experience_risk,
      weight: accountability.experience_risk === "HIGH" ? "+40" : "+20",
      evidence: accountability.experience_gap_diagnosis.deterioration_cause,
    },
    {
      label: "Consumer Effort",
      value: `${demoCase.input.conversation.length} contacts`,
      weight: `+${Math.min(demoCase.input.conversation.length * 4, 18)}`,
      evidence: accountability.experience_gap_diagnosis.latent_need,
    },
    {
      label: "Promise",
      value: accountability.active_commitments[0]?.status ?? "NONE",
      weight: accountability.active_commitments.length ? "+8" : "+0",
      evidence: accountability.active_commitments[0]?.raw_text ?? "当前没有可执行服务承诺",
    },
  ];
  return { score, factors };
}

function V11Workspace({
  demoCase,
  selectedId,
  onSelectCase,
  accountability,
  journey,
  decision,
  phase,
}: {
  demoCase: DemoCase;
  selectedId: string;
  onSelectCase: (caseId: string) => void;
  accountability: AccountabilityState;
  journey: ExtractedJourney | null;
  decision: DecisionResult | null;
  phase: PluginPhase;
}) {
  const fusion = fusionRows(demoCase, journey);
  const timeline = timelineRows(demoCase, accountability);
  const { score, factors } = riskFactors(demoCase, accountability);
  const effortScore = Math.min(100, 38 + demoCase.input.conversation.length * 9 + demoCase.input.evidence_images.length * 7);
  const hasCompleteFusion = fusion.every((item) => item.count > 0);
  const orderedCases = useMemo(() => [...demoCases].sort((a, b) => priorityScore(b) - priorityScore(a)), []);
  const commitment = accountability.active_commitments[0];
  const deadlineStatus =
    phase === "approved"
      ? accountability.case_status === "AT_RISK"
        ? "AT_RISK"
        : accountability.case_status === "RESOLVED"
          ? "CLOSED"
          : "SCHEDULED"
      : commitment
        ? "READY_AFTER_APPROVAL"
        : "NO_ACTIVE_PROMISE";
  const emergingSignals = demoCases.filter((item) => item.input.current_issue.issue_type === demoCase.input.current_issue.issue_type).length;
  const coreItems = [
    { label: "Experience Ledger", value: accountability.case_status },
    { label: "Evidence", value: accountability.evidence_status },
    { label: "Promise", value: commitment?.status ?? "NONE" },
    { label: "Firewall", value: decision?.decision ?? "READY" },
    { label: "Resolution", value: phase === "approved" ? "RUNNING" : "DRAFT" },
  ];
  const extensionItems = [
    {
      id: "Intent",
      title: "Current Intent",
      status: journey?.journey_understanding.cooperation_willingness ?? "UNKNOWN",
      text: journey?.journey_understanding.consumer_intent ?? accountability.experience_gap_diagnosis.consumer_expression,
    },
    {
      id: "Emotion",
      title: "Emotion / Trend",
      status: journey?.journey_understanding.cooperation_willingness ?? "UNKNOWN",
      text: journey?.journey_understanding.experience_expression ?? "等待抽取情绪表达与原因。",
    },
    {
      id: "Effort",
      title: "Consumer Effort",
      status: `${effortScore}/100`,
      text: accountability.experience_gap_diagnosis.latent_need,
    },
    {
      id: "Risk",
      title: "Risk State",
      status: `${score}`,
      text: "单个消费者服务风险；不把情绪推断写入风险分。",
    },
    {
      id: "Decision",
      title: "Decision",
      status: decision?.decision ?? "READY",
      text: decision?.reason ?? "先评估动作，避免把责任倒流给消费者。",
    },
    {
      id: "Deadline",
      title: "Deadline State",
      status: deadlineStatus,
      text: commitment ? `${commitment.raw_text} · ${formatClock(commitment.deadline)} 前` : "暂无可监控承诺。",
    },
  ];

  return (
    <section className="v11-workspace" aria-label="V1.1 新版工作区">
      <div className="v11-workspace-head">
        <div>
          <span>V1.1 Workspace</span>
          <h2>连续服务新版工作区</h2>
          <p>BC Core 不破坏；新增能力按 Customer Extension、Operational State、Model Governance 分层展示。</p>
        </div>
        <b>新版区</b>
      </div>

      <div className="v11-layer-label">BC Core · 不破坏</div>
      <div className="v11-core-strip">
        {coreItems.map((item) => (
          <div key={item.label}>
            <span>{item.label}</span>
            <b>{item.value}</b>
          </div>
        ))}
      </div>

      <div className="v11-layer-label">Customer Extension · 新增</div>
      <div className="v11-capability-grid">
        {extensionItems.map((item) => (
          <article className="v11-capability-card" key={item.id}>
            <div><span>{item.id}</span><b>{item.status}</b></div>
            <strong>{item.title}</strong>
            <p>{item.text}</p>
          </article>
        ))}
      </div>

      <section className="v11-fusion-card">
        <div className="v11-card-title">
          <span>Multi-source Fusion</span>
          <small>{hasCompleteFusion ? "COMPLETE · 100%" : "PARTIAL · 待补齐"}</small>
        </div>
        <div className="fusion-source-grid">
          {fusion.map((item) => (
            <div key={item.label} title={item.ids.join(" / ") || "暂无来源 ID"}>
              <b>{item.count}</b>
              <span>{item.label}</span>
            </div>
          ))}
        </div>
        <p className="fusion-link-line">Conversation → Order → Image → Ticket 均保留来源 ID；冲突时先进入人工复核。</p>
      </section>

      <section className="v11-two-column">
        <div className="v11-card">
          <div className="v11-card-title"><span>Journey Timeline</span><small>来源可追溯</small></div>
          <div className="v11-timeline">
            {timeline.map((item) => (
              <div key={`${item.source}-${item.title}`}>
                <b>{item.time}</b>
                <span>{item.source}</span>
                <p>{item.title}<small>{item.detail}</small></p>
              </div>
            ))}
          </div>
        </div>
        <div className="v11-card">
          <div className="v11-card-title"><span>Handoff Package</span><small>人工可接手</small></div>
          <ul className="handoff-list">
            <li>当前诉求：{journey?.journey_understanding.consumer_intent ?? "等待恢复"}</li>
            <li>已知事实：{initialKnownFacts(demoCase.id).slice(0, 2).join("；")}</li>
            <li>不要再问：{prohibitedCopy(demoCase.id)}</li>
            <li>建议动作：{decision?.resolution_path.task_prefill.summary ?? "先查询既有责任状态"}</li>
          </ul>
        </div>
      </section>

      <div className="v11-layer-label">Aggregate / Operational State · 独立</div>
      <section className="v11-risk-card">
        <div className="v11-card-title">
          <span>Risk Radar</span>
          <small>运营分流 · 非预测</small>
        </div>
        <div className="risk-score-row">
          <b>{score}</b>
          <div>
            {factors.map((factor) => (
              <p key={factor.label}><span>{factor.weight}</span>{factor.label} · {factor.value}</p>
            ))}
          </div>
        </div>
        <div className="risk-list-mini">
          {orderedCases.map((item, index) => (
            <button
              type="button"
              key={item.id}
              className={item.id === selectedId ? "selected" : ""}
              onClick={() => onSelectCase(item.id)}
            >
              <b>{index + 1}</b>
              <span>{item.title}</span>
              <small>{priorityScore(item)}</small>
            </button>
          ))}
        </div>
        <p className="risk-footnote">情绪只用于沟通语气；分数来自等待、承诺、重复沟通和工单状态。</p>
      </section>

      <section className="v11-monitor-row">
        <div>
          <span>Priority Queue</span>
          <strong>{orderedCases.findIndex((item) => item.id === selectedId) + 1}/{orderedCases.length}</strong>
          <p>按 Risk、Deadline、等待和人工复核需求排序；只决定先处理谁。</p>
        </div>
        <div>
          <span>Emerging Issue</span>
          <strong>{emergingSignals >= 3 ? "CANDIDATE" : "WATCHING"}</strong>
          <p>{emergingSignals} 个同类案例信号；样例数据仅供参考，不代表实际风险趋势。</p>
        </div>
      </section>

      <div className="v11-layer-label">Model Governance · 独立</div>
      <section className="v11-governance-row">
        <div><span>JEV Decision</span><b>Typed choices only</b></div>
        <div><span>Confidence</span><b>解释，不直接动作</b></div>
        <div><span>Threshold</span><b>低于阈值回退</b></div>
        <div><span>Fallback / Audit</span><b>Human Review + log</b></div>
      </section>
    </section>
  );
}

function CoveniaPlugin({
  demoCase,
  selectedId,
  onSelectCase,
  accountability,
  journey,
  decision,
  phase,
  loading,
  acting,
  detailsOpen,
  onToggleDetails,
  onQuery,
  onGenerate,
  onApprove,
  onShipment,
  onAdvanceDemoClock,
  extraMessages,
  clockStepPending,
  onClockStepPendingChange,
  clockEventSummary,
  clockNotificationDraft,
  clockDeadlineStatus,
  onUseClockNotificationDraft,
  onDemoServiceEvent,
  runtimeMetrics,
  customerState,
  consumerStatePending,
  consumerAnalysisError,
  simulationTime,
  priorityStates,
  priorityError,
  onRetryPriority,
  followUpCandidate,
  supervisorCandidate,
  loadError,
  cachedResult,
  mockMode,
  onRetry,
  onMockModeChange,
  reviewSubmitted,
  hasLocalReply,
}: {
  demoCase: DemoCase;
  selectedId: string;
  onSelectCase: (caseId: string) => void;
  accountability: AccountabilityState | null;
  journey: ExtractedJourney | null;
  decision: DecisionResult | null;
  phase: PluginPhase;
  loading: boolean;
  acting: boolean;
  detailsOpen: boolean;
  onToggleDetails: () => void;
  onQuery: () => void;
  onGenerate: () => void;
  onApprove: () => void;
  onShipment: (event: ShipmentEventType) => void;
  onAdvanceDemoClock: (step: DemoClockStep) => void;
  extraMessages: AddedMessage[];
  clockStepPending: DemoClockStep | null;
  onClockStepPendingChange: (step: DemoClockStep | null) => void;
  clockEventSummary: string | null;
  clockNotificationDraft: string | null;
  clockDeadlineStatus: string | null;
  onUseClockNotificationDraft: (text: string) => void;
  onDemoServiceEvent: (event: DemoServiceEventType) => void;
  runtimeMetrics: RuntimeMetrics | null;
  customerState: CustomerState | null;
  consumerStatePending: boolean;
  consumerAnalysisError: boolean;
  simulationTime: string;
  priorityStates: PriorityState[];
  priorityError: string | null;
  onRetryPriority: () => void;
  followUpCandidate: FollowUpCandidate | null;
  supervisorCandidate: SupervisorEscalationCandidate | null;
  loadError: string | null;
  cachedResult: boolean;
  mockMode: MockMode;
  onRetry: () => void;
  onMockModeChange: (mode: MockMode) => void;
  reviewSubmitted: boolean;
  hasLocalReply: boolean;
}) {
  const decisionType = decision?.decision;
  const detailsRef = useRef<HTMLDivElement>(null);
  const [evidencePreview, setEvidencePreview] = useState<{ fileName: string; label: string } | null>(null);
  const evidenceTriggerRef = useRef<HTMLButtonElement | null>(null);
  const evidenceCloseRef = useRef<HTMLButtonElement | null>(null);
  const handoffTriggerRef = useRef<HTMLButtonElement | null>(null);
  const handoffDialogRef = useRef<HTMLDivElement | null>(null);
  const [handoffOpen, setHandoffOpen] = useState(false);
  useEffect(() => { setEvidencePreview(null); }, [selectedId]);
  useEffect(() => {
    if (!evidencePreview) return;
    const handlePreviewKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setEvidencePreview(null);
      if (event.key === "Tab") { event.preventDefault(); evidenceCloseRef.current?.focus(); }
    };
    window.addEventListener("keydown", handlePreviewKey);
    return () => {
      window.removeEventListener("keydown", handlePreviewKey);
      evidenceTriggerRef.current?.focus();
    };
  }, [evidencePreview]);
  useEffect(() => {
    if (!handoffOpen) return;
    const dialog = handoffDialogRef.current;
    (dialog?.querySelector<HTMLElement>("button:not(:disabled)") ?? dialog)?.focus();
    const handleHandoffKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setHandoffOpen(false);
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const stops = [...dialog.querySelectorAll<HTMLElement>("button:not(:disabled), [href], [tabindex]:not([tabindex='-1'])")]
        .filter((node) => node.getClientRects().length > 0);
      if (!stops.length) { event.preventDefault(); return; }
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    window.addEventListener("keydown", handleHandoffKey);
    return () => {
      window.removeEventListener("keydown", handleHandoffKey);
      handoffTriggerRef.current?.focus();
    };
  }, [handoffOpen]);
  useEffect(() => {
    if (!detailsOpen) return;
    const frame = window.requestAnimationFrame(() => {
      detailsRef.current?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
        block: "nearest",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [detailsOpen]);
  if (loadError) {
    return (
      <aside className="plugin-panel">
        <PluginHeader mockMode={mockMode} onMockModeChange={onMockModeChange} />
        <div className="plugin-error">
          <div className="error-symbol"><AlertCircle size={22} /></div>
          <span>分析暂时没有完成</span>
          <h2>案例内容和客服草稿已保留</h2>
          <p>{loadError}</p>
          <button onClick={onRetry}><RefreshCw size={15} /> 重新分析</button>
          <small>可在右上角设置中切换服务响应状态</small>
        </div>
      </aside>
    );
  }
  if (loading || !accountability) {
    return (
      <aside className="plugin-panel">
        <PluginHeader mockMode={mockMode} onMockModeChange={onMockModeChange} />
        <div className="plugin-loading">
          <div className="loading-orbit"><img src="/brand/covenia-relay-glass-v5.png" alt="" /></div>
          <strong>正在恢复这次服务旅程</strong>
          <p>核对聊天、订单、图片和已有工单…</p>
          <div className="loading-lines"><span /><span /><span /></div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="plugin-panel">
      <PluginHeader mockMode={mockMode} onMockModeChange={onMockModeChange} />
      <div className="plugin-scroll">
        <button className="handoff-open-button" type="button" ref={handoffTriggerRef} onClick={() => setHandoffOpen(true)}>
          <ClipboardCheck size={15} /><span><b>交接摘要</b><small>已知情况、已做事项与下一步</small></span><ChevronRight size={15} />
        </button>
        {phase === "approved" && accountability.service_progress_receipt && accountability.open_obligation ? (
          <ProgressView
            accountability={accountability}
            serviceClock={customerState?.service_clock ?? simulationTime}
            deadline={accountability.open_obligation?.deadline}
            acting={acting}
            onShipment={onShipment}
            onAdvanceDemoClock={onAdvanceDemoClock}
            clockStepPending={clockStepPending}
            onClockStepPendingChange={onClockStepPendingChange}
            clockEventSummary={clockEventSummary}
            onUseClockNotificationDraft={onUseClockNotificationDraft}
            canAdvanceDemoClock={selectedId === "DEMO_001" && accountability.open_obligation.milestone === "AWAITING_CARRIER_PICKUP"}
            notificationDraft={clockNotificationDraft}
            clockDeadlineStatus={clockDeadlineStatus ?? customerState?.promises.deadline_state.status}
            queueRank={priorityStates.find((item) => item.case_id === selectedId)?.rank ?? null}
            queueReason={priorityStates.find((item) => item.case_id === selectedId)?.queue_reasons[0] ?? null}
            runtimeMetrics={runtimeMetrics}
            followUpCandidate={followUpCandidate}
            supervisorCandidate={supervisorCandidate}
          />
        ) : (
          <>
            {phase === "approved" && !accountability.open_obligation && !accountability.demo_service_event ? <div className="cached-notice"><CheckCircle2 size={14} /> 人工确认与回复已记录</div> : null}
            {cachedResult ? (
              <div className="cached-notice"><RefreshCw size={13} /> 当前使用缓存抽取结果，后续规则仍实时运行</div>
            ) : null}
            {consumerStatePending ? <div className="cached-notice"><MessageCircleMore size={13} /> 正在分析顾客新回复</div> : null}
            {consumerAnalysisError ? <div className="cached-notice"><AlertCircle size={13} /> 情绪分析暂不可用；回复建议仍按服务规则提供</div> : null}
            {(phase !== "approved" || !accountability.open_obligation) ? <>
                <div className="plugin-card-stack">
                  <PriorityQueue selectedId={selectedId} onSelectCase={onSelectCase} states={priorityStates} error={priorityError} onRetry={onRetryPriority} />
                  {(selectedId === "DEMO_002" && (hasLocalReply || Boolean(accountability.demo_service_event))) || (selectedId === "DEMO_003" && phase === "approved") ? (
                    <SideCaseActionPanel caseId={selectedId} accountability={accountability} acting={acting} onEvent={onDemoServiceEvent} />
                  ) : phase === "approved" && !accountability.open_obligation ? (
                    <section className="story-action-panel" aria-label="人工确认记录"><span>人工确认已记录</span><h3>回复已确认</h3><p>处理依据和回复已留在本次服务记录。</p></section>
                  ) : (
                    <StoryActionPanel
                      demoCase={demoCase}
                      decision={decision}
                      phase={phase}
                      acting={acting}
                      loading={loading}
                      onQuery={onQuery}
                      onGenerate={onGenerate}
                      onApprove={onApprove}
                      reviewSubmitted={reviewSubmitted}
                    />
                  )}
                  <JevInsightCard
                    state={customerState}
                    latestConsumerText={[...extraMessages].reverse().find((item) => item.kind === "consumer" && item.text)?.text
                      ?? [...demoCase.input.conversation].reverse().find((item) => item.speaker === "CONSUMER")?.text
                      ?? ""}
                  />
                  <section className="customer-facts" aria-label="本次服务依据">
                    <div className="fact-evidence" data-status={accountability.evidence_status}>
                      <div className="fact-evidence-copy">
                        <span><ShieldCheck size={15} /> 已收到的材料</span>
                        <b>{{ VALID: "材料已齐，别再重复索取", MISMATCHED: "材料与当前商品不一致", NEED_HUMAN_REVIEW: "当前信息需人工核实" }[accountability.evidence_status]}</b>
                        <small>{accountability.demo_service_event === "CURRENT_SCOPE_EVIDENCE_SUBMITTED"
                          ? "赠品照片已保留 · 瓶口近照已模拟登记（无原图）"
                          : demoCase.input.evidence_images.length ? `${demoCase.input.evidence_images.length} 张关联图片 · 对应当前案例` : "未提交图片 · 先由人工核实"}</small>
                      </div>
                      <div className="fact-evidence-gallery" aria-label="图片证据预览">
                        {demoCase.input.evidence_images.slice(0, 3).map((item) => {
                          const label = { PRODUCT_OVERVIEW: "商品", ISSUE_DETAIL: "问题", PACKAGE_CONTEXT: "包装", OTHER: "其他" }[item.declared_view_type];
                          return (
                            <button type="button" key={item.evidence_id} onClick={(event) => { evidenceTriggerRef.current = event.currentTarget; setEvidencePreview({ fileName: item.file_name, label }); }} aria-label={`查看${label}图片`}>
                              <EvidenceCard fileName={item.file_name} className="dossier-evidence" label={label} fallbackClass={item.declared_view_type === "PACKAGE_CONTEXT" ? "box-shape" : "bottle-shape"} />
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <div className="fact-owner"><span><UserRoundCheck size={14} /> 负责方</span><b>{accountability.accountable_side === "BRAND" ? "品牌跟进" : accountability.accountable_side === "CONSUMER" ? "消费者待补充" : "待人工确认"}</b></div>
                    <div className="fact-deadline"><span><Clock3 size={14} /> 下次更新</span><b>{accountability.service_progress_receipt?.next_update_by ? formatServiceDateTime(accountability.service_progress_receipt.next_update_by) : "待确认时间"}</b>{!accountability.service_progress_receipt && accountability.active_commitments[0]?.deadline ? <span>原承诺 {formatServiceDateTime(accountability.active_commitments[0].deadline)}</span> : null}</div>
                    <small>{customerState?.emotion.trend === "WORSENING" ? "可能需要优先安抚 · " : customerState?.emotion.trend === "UNKNOWN" ? "情绪待确认 · " : "沟通建议 · "}{customerState?.emotion.communication_guidance ?? "先确认已有材料，再说明下一步。"}</small>
                  </section>
                </div>
            </> : null}

            <button className="details-toggle" onClick={onToggleDetails} aria-expanded={detailsOpen} aria-controls="case-details">
              <span>判断依据与服务记录</span>
              <ChevronDown size={16} className={detailsOpen ? "rotated" : ""} />
            </button>
            {detailsOpen ? (
              <div id="case-details" className="case-details-content" ref={detailsRef}>
                {decision ? <DecisionBanner decision={decision} /> : null}
                <DiagnosisDetails accountability={accountability} journey={journey} />
                {customerState ? <details className="communication-sources"><summary>查看沟通依据</summary>{customerState.source_evidence.filter((item) => customerState.emotion.source_evidence_ids.includes(item.source_id)).slice(-3).map((item) => <p key={item.source_id}><small>{item.source_label} · {item.observed_at ? formatClock(item.observed_at) : ""}</small><br />{item.claim}</p>)}</details> : null}
                {runtimeMetrics ? <details className="technical-disclosure"><summary>技术运行信息</summary><RuntimeCostBar metrics={runtimeMetrics} /></details> : null}
              </div>
            ) : null}
          </>
        )}
      </div>
      {evidencePreview ? (
        <div className="evidence-lightbox-backdrop" onClick={() => setEvidencePreview(null)}>
          <section className="evidence-lightbox" role="dialog" aria-modal="true" aria-label={`${evidencePreview.label}图片预览`} onClick={(event) => event.stopPropagation()}>
            <div className="evidence-lightbox-head"><strong>{evidencePreview.label}图片</strong><button type="button" ref={evidenceCloseRef} autoFocus onClick={() => setEvidencePreview(null)}>关闭</button></div>
            <img src={`/evidence/${evidencePreview.fileName}`} alt={`${evidencePreview.label}图片`} />
            <small>已关联当前案例</small>
          </section>
        </div>
      ) : null}
      {handoffOpen ? <HandoffDialog
        refElement={handoffDialogRef}
        demoCase={demoCase}
        accountability={accountability}
        customerState={customerState}
        extraMessages={extraMessages}
        onClose={() => setHandoffOpen(false)}
      /> : null}
    </aside>
  );
}

function JevInsightCard({ state, latestConsumerText }: { state: CustomerState | null; latestConsumerText: string }) {
  const advisory = state?.decision_advisory ?? state?.decision?.decision_advisory;
  if (!state || !advisory) return null;

  const live = advisory.source === "JEV" && advisory.jev_call.succeeded;
  const worseningProbability = live && advisory.emotion.source === "JEV" && typeof advisory.emotion.probability === "number"
    ? Math.round(Math.max(0, Math.min(1, advisory.emotion.probability)) * 100)
    : null;
  const trendCopy = {
    WORSENING: "耐心可能正在下降",
    STABLE: "暂未发现明显恶化",
    IMPROVING: "表达可能有所缓和",
    UNKNOWN: "暂未形成稳定判断",
  }[advisory.emotion.trend];
  const communicationGuidance = state.emotion.communication_guidance || "先回应顾客当前顾虑，再说明有依据的下一步。";
  const citedEvidence = state.source_evidence
    .filter((item) => advisory.emotion.source === "JEV" && state.emotion.source_evidence_ids.includes(item.source_id))
    .slice(-2);

  return (
    <section className={`jev-insight-card${live ? " is-live" : " is-fallback"}`} aria-label="JEV 沟通状态辅助判断">
      <div className="jev-insight-topline">
        <div className="jev-brand-mark"><Sparkles size={16} /></div>
        <div className="jev-insight-title"><span>JEV 辅助</span><strong>沟通状态</strong></div>
        <span className="jev-status-pill">{live ? "未校准信号" : "规则兜底"}</span>
      </div>

      <div className="jev-insight-main">
        <div className="jev-emotion-copy">
          <small>近期沟通趋势</small>
          <h3>{live ? trendCopy : "当前无法确认情绪变化"}</h3>
        </div>
        {worseningProbability !== null ? (
          <div className="jev-probability" aria-label={`JEV 对当前对话的情绪恶化判断概率 ${worseningProbability}%，未校准`} title="这是模型针对当前对话的原始判断概率；未经本项目标注样本校准，不代表准确率。">
            <strong>{worseningProbability}<small>%</small></strong>
            <span>模型判断 · 非准确率</span>
          </div>
        ) : null}
      </div>

      <div className="jev-action-row">
        <div className="jev-action-icon"><CheckCircle2 size={15} /></div>
        <div><small>{live ? "回复侧重点" : "规则建议仍可使用"}</small><strong>{communicationGuidance}</strong></div>
      </div>

      {citedEvidence.length > 0 ? (
        <details className="jev-evidence-disclosure">
          <summary>查看本次分析输入（{citedEvidence.length} 段对话）</summary>
          <div className="jev-evidence-list" aria-label="情绪分析引用的对话">
            {citedEvidence.map((item) => {
              const normalize = (value: string) => value.replace(/[\s，。！？,.!?]/gu, "");
              const isCurrent = latestConsumerText && (normalize(item.claim).includes(normalize(latestConsumerText)) || normalize(latestConsumerText).includes(normalize(item.claim)));
              const messageScope = isCurrent ? "当前消息" : item.source_type === "CHAT" ? "此前消息" : item.source_label;
              return <p key={item.source_id}><span>{messageScope}<small>{item.observed_at ? formatClock(item.observed_at) : ""}</small></span>“{item.claim}”</p>;
            })}
          </div>
        </details>
      ) : null}

    </section>
  );
}

function PluginHeader({
  mockMode,
  onMockModeChange,
}: {
  mockMode: MockMode;
  onMockModeChange: (mode: MockMode) => void;
}) {
  const [open, setOpen] = useState(false);
  const modeOptions: Array<{ value: MockMode; label: string; note: string }> = [
    { value: "normal", label: "正常响应", note: "标准服务状态" },
    { value: "slow", label: "慢响应", note: "延迟返回结果" },
    { value: "cached", label: "缓存结果", note: "使用已有分析结果" },
    { value: "model_timeout", label: "模型超时", note: "返回可重试状态" },
    { value: "state_conflict", label: "状态冲突", note: "关键操作需要重试" },
  ];
  return (
    <header className="plugin-header">
      <div className="covenia-symbol"><img src="/brand/covenia-relay-glass-v5.png" alt="" /></div>
      <div>
        <strong>Covenia</strong>
        <small>记住承诺 · 跟到兑现</small>
      </div>
      {import.meta.env.VITE_API_MODE !== "http" ? (
        <button aria-label="插件设置" onClick={() => setOpen((value) => !value)}><MoreHorizontal size={18} /></button>
      ) : null}
      {open && import.meta.env.VITE_API_MODE !== "http" ? (
        <div className="demo-settings">
          <div><span>服务响应状态</span><small>仅影响当前工作台</small></div>
          {modeOptions.map((option) => (
            <button
              key={option.value}
              className={mockMode === option.value ? "active" : ""}
              onClick={() => {
                onMockModeChange(option.value);
                setOpen(false);
              }}
            >
              <span>{option.label}<small>{option.note}</small></span>
              {mockMode === option.value ? <Check size={14} /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </header>
  );
}

function DecisionBanner({ decision }: { decision: DecisionResult }) {
  const Icon = decisionIcon[decision.decision];
  const copy = decisionLabels[decision.decision];
  return (
    <div className={`decision-banner state-${decision.decision.toLowerCase()}`}>
      <div className="decision-icon"><Icon size={19} /></div>
      <div>
        <span>{copy.eyebrow}</span>
        <strong>{copy.title}</strong>
        <p>{decision.reason}</p>
      </div>
    </div>
  );
}

function ResolutionPreview({ decision, onApprove }: { decision: DecisionResult; onApprove: () => void }) {
  return (
    <section className="resolution-preview">
      <div className="resolution-head">
        <span><Sparkles size={15} /> 解决路径已准备</span>
        <small>需要人工确认</small>
      </div>
      <div className="route-line">
        <span className="route-node done"><Check size={12} /></span>
        <div><b>沿用已有换货单</b><small>{decision.resolution_path.task_prefill.existing_ticket_id}</small></div>
      </div>
      <div className="route-line">
        <span className="route-node"><PackageCheck size={12} /></span>
        <div><b>查询仓库与揽收状态</b><small>已有物流单号，不重复建单</small></div>
      </div>
      <div className="route-line">
        <span className="route-node"><MessageCircleMore size={12} /></span>
        <div><b>主动回复消费者</b><small>明确下次更新时间</small></div>
      </div>
      <button className="approve-inline" onClick={onApprove}>查看并确认 <ChevronRight size={15} /></button>
    </section>
  );
}

function DiagnosisDetails({ accountability, journey }: { accountability: AccountabilityState; journey: ExtractedJourney | null }) {
  return (
    <div className="diagnosis-details">
      <div><span>体验断层</span><p>{accountability.experience_gap_diagnosis.deterioration_cause}</p></div>
      <div><span>潜在需要</span><p>{accountability.experience_gap_diagnosis.latent_need}</p></div>
      <div><span>责任判断</span><p>{accountability.accountable_side === "BRAND" ? "消费者输入已完整，当前由品牌负责" : accountability.accountable_side === "CONSUMER" ? "当前范围仍需消费者补充输入" : "事实不足，等待人工确认"}</p></div>
      <div className="fact-chips">
        <span>证据 {{ VALID: "已核实", MISMATCHED: "需要补充", NEED_HUMAN_REVIEW: "待人工复核" }[accountability.evidence_status]}</span>
        <span>{journey?.image_observations.length ?? 0} 张图片</span>
        <span>{accountability.active_commitments.length} 条承诺</span>
      </div>
    </div>
  );
}

function AccountabilitySummary({ accountability }: { accountability: AccountabilityState }) {
  const commitment = accountability.active_commitments[0];
  return (
    <section className="accountability-summary">
      <div><span>案件状态</span><b>{{ WAITING_FOR_CONSUMER: "等待消费者回复", READY_FOR_BRAND: "等待品牌处理", ACTION_REVIEW: "待确认处理动作", IN_FULFILLMENT: "处理中", AT_RISK: "承诺有超时风险", RESOLVED: "已解决" }[accountability.case_status]}</b></div>
      {commitment ? <>
        <div><span>承诺原文</span><b>{commitment.raw_text}</b></div>
        <div><span>当前义务</span><b>{commitment.status} · {formatServiceDateTime(commitment.deadline)}</b></div>
        <div><span>执行方</span><b>{accountability.open_obligation?.executor ?? "待人工确认"}</b></div>
      </> : <div><span>当前义务</span><b>尚未激活</b></div>}
    </section>
  );
}

function RuntimeCostBar({ metrics }: { metrics: RuntimeMetrics }) {
  if (metrics.measurement_status === "NOT_MEASURED") {
    return <section className="runtime-cost-bar" aria-label="本次运行方式">
      <span>运行方式</span><b>本地数据模式</b><span>未调用图文模型，模型成本未计量</span>
    </section>;
  }
  return <section className="runtime-cost-bar" aria-label="本次运行成本">
    <span>本次运行</span><b>{(metrics.input_tokens ?? 0) + (metrics.output_tokens ?? 0)} tokens</b>
    <b>{metrics.inference_latency_ms ?? "—"} ms</b><b>规则替代 {metrics.rule_substitution_count ?? "—"}</b>
  </section>;
}

function SideCaseActionPanel({ caseId, accountability, acting, onEvent }: {
  caseId: "DEMO_002" | "DEMO_003";
  accountability: AccountabilityState;
  acting: boolean;
  onEvent: (event: DemoServiceEventType) => void;
}) {
  const event = accountability.demo_service_event;
  const isEvidence = caseId === "DEMO_002";
  const nextEvent: DemoServiceEventType | null = isEvidence
    ? event ? null : "CURRENT_SCOPE_EVIDENCE_SUBMITTED"
    : !event ? "SPECIALIST_ASSIGNED" : event === "SPECIALIST_ASSIGNED" ? "SPECIALIST_FOLLOWED_UP" : null;
  const title = isEvidence
    ? event ? "材料已齐，品牌继续核验" : "只等当前商品的一张照片"
    : event === "SPECIALIST_FOLLOWED_UP" ? "专人已反馈，品牌继续跟进"
      : event === "SPECIALIST_ASSIGNED" ? "售后专员已接手" : "等待售后专员接手";
  const description = accountability.service_progress_receipt?.brand_action
    ?? (isEvidence
      ? "已收到的赠品照片会保留；只需精华瓶口近照，不需要重传整单。"
      : "先记录使用反馈，暂停使用；无需先上传面部照片，也不自动判断原因。");
  const buttonText = nextEvent === "CURRENT_SCOPE_EVIDENCE_SUBMITTED" ? "模拟收到精华瓶口近照"
    : nextEvent === "SPECIALIST_ASSIGNED" ? "模拟售后专员接手" : "模拟专人主动回访";
  return <section className="sidecase-action-panel" aria-label="服务后续进度">
    <div className="sidecase-action-top"><span>{isEvidence ? "材料跟进" : "专人跟进"}</span><small>{event ? "品牌负责" : "待处理"}</small></div>
    <h3>{title}</h3>
    <p>{description}</p>
    {accountability.service_progress_receipt ? <div className="sidecase-action-facts"><span>{isEvidence ? "当前证据" : "接手人"}<b>{isEvidence ? "精华瓶口近照已收到" : accountability.demo_specialist ?? "售后专员"}</b></span><span>下次更新<b>{formatServiceDateTime(accountability.service_progress_receipt.next_update_by)}</b></span></div> : null}
    {nextEvent ? <button type="button" onClick={() => onEvent(nextEvent)} disabled={acting}><RefreshCw size={16} />{buttonText}<ChevronRight size={16} /></button> : null}
    <small className="sidecase-local-note">本地模拟进度，未连接真实材料上传或人工任务系统。</small>
  </section>;
}

function ProgressView({
  accountability,
  serviceClock,
  deadline,
  acting,
  onShipment,
  onAdvanceDemoClock,
  clockStepPending,
  onClockStepPendingChange,
  clockEventSummary,
  onUseClockNotificationDraft,
  canAdvanceDemoClock,
  notificationDraft,
  clockDeadlineStatus,
  queueRank,
  queueReason,
  runtimeMetrics,
  followUpCandidate,
  supervisorCandidate,
}: {
  accountability: AccountabilityState;
  serviceClock?: string;
  deadline?: string;
  acting: boolean;
  onShipment: (event: ShipmentEventType) => void;
  onAdvanceDemoClock: (step: DemoClockStep) => void;
  clockStepPending: DemoClockStep | null;
  onClockStepPendingChange: (step: DemoClockStep | null) => void;
  clockEventSummary: string | null;
  onUseClockNotificationDraft: (text: string) => void;
  canAdvanceDemoClock: boolean;
  notificationDraft: string | null;
  clockDeadlineStatus?: string;
  queueRank: number | null;
  queueReason: string | null;
  runtimeMetrics: RuntimeMetrics | null;
  followUpCandidate: FollowUpCandidate | null;
  supervisorCandidate: SupervisorEscalationCandidate | null;
}) {
  const receipt = accountability.service_progress_receipt!;
  const pickedUp = accountability.open_obligation?.milestone === "IN_TRANSIT" || accountability.open_obligation?.milestone === "DELIVERED";
  const delivered = accountability.open_obligation?.milestone === "DELIVERED";
  const atRisk = accountability.case_status === "AT_RISK";
  const countdown = useCountdown(deadline, serviceClock);
  const deadlineStatusLabel = clockDeadlineStatus === "NEAR_DUE" ? "临近承诺"
    : clockDeadlineStatus === "OVERDUE" ? "已逾期"
      : clockDeadlineStatus === "ESCALATED" ? "已升级"
        : clockDeadlineStatus === "CLOSED" ? "已关闭"
          : "按期处理中";
  const nearDueReached = ["NEAR_DUE", "OVERDUE", "ESCALATED", "CLOSED"].includes(clockDeadlineStatus ?? "");
  const overdueReached = ["OVERDUE", "ESCALATED", "CLOSED"].includes(clockDeadlineStatus ?? "");
  return (
    <div className="progress-view">
      <div className={`progress-hero ${pickedUp || delivered ? "on-track" : atRisk ? "at-risk" : ""}`}>
        <div className="progress-hero-top">
          <span className="progress-icon">{delivered ? <PackageCheck size={20} /> : pickedUp ? <Truck size={20} /> : <Clock3 size={20} />}</span>
          <div>
            <small>{delivered ? "服务责任已完成" : "服务责任正在运行"}</small>
            <h2>{delivered ? "换货件已送达" : pickedUp ? "换货件已揽收" : atRisk ? "承诺节点需要补救" : "等待物流揽收"}</h2>
          </div>
          <span className="status-word">{delivered ? "已闭环" : pickedUp ? "正常" : atRisk ? "有风险" : "进行中"}</span>
        </div>
        <p>{receipt.brand_action}</p>
        {!pickedUp && !delivered ? (
          <div className={`countdown-strip ${countdown.overdue ? "overdue" : ""}`}>
            <span>{countdown.overdue ? "承诺已超时" : "距承诺节点"}</span>
            <b>{countdown.label}</b>
            <small>{countdown.overdue ? "模拟时间已越过承诺节点" : "模拟时间固定，推进后触发检查"}</small>
          </div>
        ) : null}
        <div className="responsibility-line"><span /> <b>{delivered ? "换货送达已核验，责任闭环" : "品牌继续负责，直至换货商品送达"}</b></div>
      </div>

      <details className="receipt-card">
        <summary className="receipt-card-title"><span><ShieldCheck size={16} /> 服务进度回执</span><small>查看完整记录 <ChevronDown size={14} /></small></summary>
        <dl>
          <div><dt>已收到</dt><dd>{receipt.received_evidence[0]}，无需再次提交</dd></div>
          <div><dt>处理进度</dt><dd>{receipt.brand_action}</dd></div>
          <div><dt>下次更新</dt><dd>{formatServiceDateTime(receipt.next_update_by)}</dd></div>
          <div><dt>未完成时</dt><dd>{receipt.recovery_if_missed}</dd></div>
        </dl>
        <div className="no-action"><CheckCircle2 size={16} /> 消费者当前无需操作</div>
      </details>

      <section className="timeline-card">
        <div className="timeline-title"><span>责任进度</span><small>{delivered ? "已完成" : pickedUp ? "运输中" : "等待揽收"}</small></div>
        <div className="mini-timeline">
          <div className="complete"><span><Check size={11} /></span><small>工单创建</small></div>
          <i />
          <div className={pickedUp ? "complete" : atRisk ? "risk" : "current"}><span>{pickedUp ? <Check size={11} /> : "2"}</span><small>物流揽收</small></div>
          <i />
          <div className={delivered ? "complete" : ""}><span>{delivered ? <Check size={11} /> : "3"}</span><small>商品送达</small></div>
        </div>
        <p><AlertCircle size={14} /> 工单创建和物流单号生成都不等于问题已解决</p>
      </section>

      {canAdvanceDemoClock ? <section className="demo-clock-card" aria-label="模拟时间控制">
        <div className="demo-clock-heading"><span><Clock3 size={15} /> 模拟时间</span><b>{serviceClock ? formatServiceDateTime(serviceClock) : "待获取"}</b></div>
        <div className="demo-clock-state">
          <span>承诺节点 <b>{deadline ? formatServiceDateTime(deadline) : "待确认"}</b></span>
          <span>期限状态 <b>{clockDeadlineStatus ? deadlineStatusLabel : atRisk ? "已逾期" : "按期处理中"}</b></span>
          <span>队列 <b>{queueRank ? `第 ${queueRank} 位` : "待刷新"}</b></span>
        </div>
        {queueReason ? <small className="demo-clock-reason">当前排序原因：{queueReason}</small> : null}
        {clockEventSummary ? <p className="demo-clock-result" role="status">{clockEventSummary}</p> : null}
        {clockStepPending ? <div className="demo-clock-approval" role="group" aria-label="确认模拟时间推进">
          <p>将调用服务端期限检查并更新责任状态、待办排序和模拟时间。</p>
          <div><button type="button" className="clock-cancel" disabled={acting} onClick={() => onClockStepPendingChange(null)}>取消</button>
            <button type="button" className="clock-confirm" disabled={acting} onClick={() => onAdvanceDemoClock(clockStepPending)}>{acting ? "处理中…" : `确认推进至${clockStepPending === "NEAR_DUE" ? "到期前 10 分钟" : "逾期"}`}</button></div>
        </div> : <div className="demo-clock-actions">
          <button type="button" disabled={acting || nearDueReached} onClick={() => onClockStepPendingChange("NEAR_DUE")}>{nearDueReached ? "已推进至临近承诺" : "到期前 10 分钟"}</button>
          <button type="button" disabled={acting || overdueReached} onClick={() => onClockStepPendingChange("OVERDUE")}>{overdueReached ? "已推进至逾期" : "推进至逾期"}</button>
        </div>}
        {notificationDraft ? <div className="clock-notification-draft"><small>主动通知草稿 · 需客服确认</small><p>{notificationDraft}</p><button type="button" onClick={() => onUseClockNotificationDraft(notificationDraft)}>放入客服草稿</button></div> : null}
      </section> : null}

      <section className="shipment-simulator">
        <div className="simulator-title">
          <div><span>模拟物流进度</span><small>选择事件，观察责任如何变化</small></div>
        </div>
        <p className="simulation-disclosure">事件会更新本地责任账本、回执和聊天记录；不会连接真实仓库或物流。</p>
        <div className="shipment-buttons">
          <button
            className={pickedUp || delivered ? "selected" : ""}
            onClick={() => onShipment("SHIPMENT_PICKED_UP")}
            disabled={acting || pickedUp || delivered}
          ><Truck size={16} /><span><b>{pickedUp || delivered ? "已记录揽收" : "正常：已揽收"}</b><small>{pickedUp || delivered ? "责任继续跟到送达" : "按时推进履约"}</small></span></button>
          <button
            className={atRisk ? "selected risk-choice" : "risk-choice"}
            onClick={() => onShipment("SHIPMENT_NOT_PICKED_UP")}
            disabled={acting || pickedUp || delivered || atRisk}
          ><AlertTriangle size={16} /><span><b>{atRisk ? "已记录逾期风险" : "异常：仍未揽收"}</b><small>{atRisk ? "已生成催办与升级候选" : "推进到逾期并触发补救"}</small></span></button>
          <button
            className={delivered ? "selected" : ""}
            onClick={() => onShipment("SHIPMENT_DELIVERED")}
            disabled={acting || !pickedUp || delivered}
          ><PackageCheck size={16} /><span><b>{delivered ? "已记录送达" : "已送达"}</b><small>{delivered ? "责任已闭环" : "揽收后完成闭环"}</small></span></button>
        </div>
      </section>
      {followUpCandidate || supervisorCandidate ? <section className="supervisor-zone">
        <div className="timeline-title"><span>主管跟踪区</span><small>本地演示候选</small></div>
        {followUpCandidate ? <p>催办：{followUpCandidate.summary}</p> : <p>当前没有仓库催办候选</p>}
        {supervisorCandidate ? <p>升级：{supervisorCandidate.summary}</p> : <p>当前没有主管升级候选</p>}
      </section> : null}
      {runtimeMetrics ? <RuntimeCostBar metrics={runtimeMetrics} /> : null}
    </div>
  );
}

function HandoffDialog({
  refElement,
  demoCase,
  accountability,
  customerState,
  extraMessages,
  onClose,
}: {
  refElement: MutableRefObject<HTMLDivElement | null>;
  demoCase: DemoCase;
  accountability: AccountabilityState;
  customerState: CustomerState | null;
  extraMessages: AddedMessage[];
  onClose: () => void;
}) {
  const product = demoCase.input.order.items.find((item) => item.fulfillment_item_id === demoCase.input.current_issue.fulfillment_item_id);
  const issueLabel = demoCase.id === "DEMO_003" ? "使用后泛红、刺痛" : demoCase.id === "DEMO_002" ? "精华瓶口裂痕" : "粉底液泵头损坏与换货进度";
  const latestConsumer = [...extraMessages].reverse().find((item) => item.kind === "consumer" && item.text)?.text
    ?? [...demoCase.input.conversation].reverse().find((item) => item.speaker === "CONSUMER")?.text
    ?? "当前没有可显示的消费者原话。";
  const imageEvidence = demoCase.input.evidence_images;
  const knownEvidence = customerState?.evidence.known ?? (accountability.evidence_status === "VALID" ? ["当前问题所需材料已确认"] : []);
  const missingEvidence = customerState?.evidence.missing ?? (accountability.evidence_status === "MISMATCHED"
    ? ["当前商品对应的问题照片仍待补充"]
    : accountability.evidence_status === "NEED_HUMAN_REVIEW" ? ["需人工核实；无需先补充未确认的材料"] : []);
  const doNotAskAgain = customerState?.evidence.do_not_ask_again?.length
    ? customerState.evidence.do_not_ask_again
    : accountability.prohibited_actions.map((action) => ({
        ASK_SAME_EVIDENCE: "不要重复索取已收到的同一材料",
        ASK_REPEAT_EXPLANATION: "不要要求消费者重复说明已记录的问题",
        SHIFT_FOLLOW_UP_TO_CONSUMER: "不要把品牌跟进责任交给消费者",
        MAKE_UNTRACKABLE_PROMISE: "不要作出没有更新时间的承诺",
        CLOSE_BEFORE_RESOLUTION: "问题未解决前不要结案",
      }[action]));
  const auditLabels: Record<AccountabilityState["audit_trail"][number]["action"], string> = {
    ANALYZED: "已核对案件材料",
    RESOLUTION_APPROVED: "客服已确认服务安排",
    SHIPMENT_PICKED_UP: "已记录物流揽收",
    SHIPMENT_NOT_PICKED_UP: "已记录未揽收并触发跟进",
    SHIPMENT_DELIVERED: "已记录送达",
    CURRENT_SCOPE_EVIDENCE_SUBMITTED: "已记录当前问题所需材料",
    SPECIALIST_ASSIGNED: "已记录专人接手",
    SPECIALIST_FOLLOWED_UP: "已记录专人回访",
    PROMISE_DEADLINE_ESCALATED: "已记录承诺逾期升级",
    DEMO_CLOCK_NEAR_DUE: "已记录期限临近检查",
    DEMO_CLOCK_OVERDUE_ESCALATED: "已记录首次逾期升级",
    DEMO_CLOCK_OVERDUE_ALREADY_ESCALATED: "已检查逾期状态，升级已存在",
  };
  const priorActions = accountability.audit_trail.slice(-4).reverse();
  const nextUpdate = accountability.service_progress_receipt?.next_update_by
    ?? accountability.open_obligation?.next_check_at
    ?? accountability.open_obligation?.deadline;
  const nextAction = customerState?.actions.next_best_action
    ?? accountability.experience_gap_diagnosis.reply_strategy;
  const responsibleParty = accountability.accountable_side === "BRAND" ? "品牌" : accountability.accountable_side === "CONSUMER" ? "消费者" : "待人工确认";
  const executor = accountability.open_obligation?.executor === "WAREHOUSE" ? "仓库（演示责任方）"
    : accountability.open_obligation?.executor === "LOGISTICS_PROVIDER" ? "物流服务方（演示责任方）"
    : accountability.open_obligation?.executor === "BRAND" ? "品牌客服"
    : accountability.demo_specialist ?? "尚未记录具体执行人";

  return <div className="handoff-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={refElement} className="handoff-dialog" role="dialog" aria-modal="true" aria-labelledby="handoff-title" tabIndex={-1}>
      <header><div><small>当前案件 · {demoCase.shortId}</small><h2 id="handoff-title">交接摘要</h2></div><button type="button" onClick={onClose} aria-label="关闭交接摘要"><X size={18} /></button></header>
      <p className="handoff-issue"><b>{product?.product_name ?? "当前商品"}</b><span>{issueLabel}</span><q>{latestConsumer}</q></p>
      <div className="handoff-grid">
        <section><h3>已知情况与材料</h3>
          {knownEvidence.length ? <ul>{knownEvidence.map((fact, index) => <li key={`${fact}-${index}`}>{fact}</li>)}</ul> : <p>当前没有已确认的材料信息。</p>}
          {imageEvidence.length ? <div className="handoff-source-list"><b>关联图片来源</b>{imageEvidence.map((item) => <p key={item.evidence_id}>
            {item.source_kind === "TEAM_SYNTHETIC_AUGMENTATION" || item.source_kind === "TEAM_SYNTHETIC_RECREATION" ? "团队合成示意素材" : "案件关联图片"} · {item.declared_view_type === "PACKAGE_CONTEXT" ? "包装/赠品视角" : item.declared_view_type === "ISSUE_DETAIL" ? "问题细节" : item.declared_view_type === "PRODUCT_OVERVIEW" ? "商品整体" : "其他视角"} · {formatServiceDateTime(item.submitted_at)}
          </p>)}</div> : <small>当前案件没有关联图片。</small>}
        </section>
        <section><h3>仍缺材料</h3>{missingEvidence.length ? <ul>{missingEvidence.map((fact, index) => <li key={`${fact}-${index}`}>{fact}</li>)}</ul> : <p>没有待消费者补充的材料。</p>}</section>
        <section><h3>此前已做</h3>{priorActions.length ? <ul>{priorActions.map((item) => <li key={`${item.request_id}-${item.action}`}>{auditLabels[item.action]} · {formatServiceDateTime(item.at)}</li>)}</ul> : <p>当前服务账本尚无已记录的处理动作。</p>}
          {demoCase.input.service_tickets.length ? <small>关联工单：{demoCase.input.service_tickets.map((ticket) => ticket.ticket_id).join("、")}</small> : null}
        </section>
        <section><h3>责任与下一步</h3><p>责任方：{responsibleParty} · 执行方：{executor}</p><p>下一次更新：{nextUpdate ? formatServiceDateTime(nextUpdate) : "尚未约定"}</p><p>建议动作：{nextAction}</p></section>
      </div>
      <section className="handoff-do-not-ask"><h3>当前案件避免重复询问</h3><small>以下范围仅适用于已知的当前商品与问题。</small>
        {doNotAskAgain.length ? <ul>{doNotAskAgain.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : <p>尚无足够依据列出需要避免的问题。</p>}
      </section>
      <footer><small>摘要来自当前案件与服务记录；演示责任方不代表真实外部任务已分派。</small><button type="button" onClick={onClose}>完成</button></footer>
    </div>
  </div>;
}

function ApprovalDialog({
  decision,
  hasExistingObligation,
  fixedExecutor,
  reply,
  setReply,
  executor,
  setExecutor,
  nextCheckAt,
  setNextCheckAt,
  acting,
  error,
  onClose,
  onConfirm,
}: {
  decision: DecisionResult;
  hasExistingObligation: boolean;
  fixedExecutor: boolean;
  reply: string;
  setReply: (value: string) => void;
  executor: string;
  setExecutor: (value: string) => void;
  nextCheckAt: string;
  setNextCheckAt: (value: string) => void;
  acting: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef(document.activeElement as HTMLElement);
  useEffect(() => {
    const dialog = dialogRef.current;
    (dialog?.querySelector<HTMLElement>("textarea") ?? dialog?.querySelector<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled)"))?.focus();
    return () => restoreFocusRef.current?.focus();
  }, []);
  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !acting) {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const stops = [...dialog.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex='-1'])")]
      .filter((node) => node.getClientRects().length > 0);
    if (!stops.length) { event.preventDefault(); return; }
    const first = stops[0];
    const last = stops[stops.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  }
  const createsObligation = decision.resolution_path.creates_obligation;
  const confirmationTitle = decision.resolution_path.candidate_type === "HUMAN_EVIDENCE_REVIEW"
    ? "确认人工复核记录"
    : decision.resolution_path.candidate_type === "ASK_CURRENT_SCOPE_EVIDENCE"
      ? "确认索证回复"
      : createsObligation ? (hasExistingObligation ? "确认下一次跟进安排" : "确认服务责任安排") : "确认这条回复";
  const confirmationEffect = createsObligation
    ? (hasExistingObligation
      ? "确认后更新下次跟进时间并记录回复；已有物流进度与原承诺保持不变。回复不会发送到千牛。"
      : "确认后建立服务责任，并按约定时间持续跟进。回复仅记录在当前工作台，不会发送到千牛。")
    : (hasExistingObligation
      ? "确认后记录这条回复；既有服务责任继续跟进，不会发送到千牛。"
      : "确认后记录人工复核决定与回复，不会创建服务义务或发送到千牛。");
  return (
    <div className="modal-backdrop" role="presentation">
      <div ref={dialogRef} className="approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title" onKeyDown={handleKeyDown}>
        <header>
          <div className="dialog-icon"><img src="/brand/covenia-relay-glass-v5.png" alt="" /></div>
          <div><span>人工确认</span><h2 id="approval-title">{confirmationTitle}</h2></div>
          <button onClick={onClose} aria-label="关闭"><X size={19} /></button>
        </header>
        {createsObligation ? <div className="approval-grid">
          <label><span>责任方</span><div className="fixed-input"><ShieldCheck size={15} /> {decision.resolution_path.accountable_side === "BRAND" ? "品牌" : decision.resolution_path.accountable_side}</div></label>
          <label><span>执行方</span>{fixedExecutor
            ? <div className="fixed-input"><Truck size={15} /> 物流服务方 · 揽收后保持当前履约方</div>
            : <select value={executor} onChange={(event) => setExecutor(event.target.value)}><option value="WAREHOUSE">仓库</option><option value="BRAND">品牌客服</option><option value="LOGISTICS_PROVIDER">物流服务方</option></select>}
          </label>
          <label><span>下次更新时间</span><input className="fixed-input" type="datetime-local" required value={nextCheckAt} onChange={(event) => setNextCheckAt(event.target.value)} /></label>
          <label><span>完成条件</span><div className="fixed-input"><PackageCheck size={15} /> 换货商品送达</div></label>
        </div> : null}
        <label className="reply-editor">
          <span>消费者回复</span>
          <textarea autoFocus value={reply} onChange={(event) => setReply(event.target.value)} />
          <small>确认后，这段文字会保存为本次服务回复。</small>
        </label>
        <div className="approval-summary">
          <Sparkles size={16} />
          <p><b>确认后会发生什么</b><span>{confirmationEffect}</span></p>
        </div>
        {error ? <div className="approval-error" role="alert"><AlertTriangle size={15} /><span>{error}</span></div> : null}
        <footer>
          <button className="dialog-cancel" onClick={onClose}>返回修改</button>
          <button className="dialog-confirm" onClick={onConfirm} disabled={acting || !reply.trim() || (createsObligation && !nextCheckAt)}>
            {acting ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
            确认并记录回复
          </button>
        </footer>
      </div>
    </div>
  );
}

export default App;
