import analyzeExample from "./api/examples/01-analyze-case.json";
import type { CaseInput, PreparedAction } from "./api/contracts";

const heroInput = analyzeExample.case_input_fixture as unknown as CaseInput;

export interface DemoCase {
  id: string;
  shortId: string;
  title: string;
  preview: string;
  time: string;
  unread?: number;
  expectedDecision: "INTERVENE" | "ALLOW" | "HUMAN_REVIEW";
  sourceLabel: string;
  input: CaseInput;
  preparedAction: PreparedAction;
  composerText: string;
}

const heroScope = {
  order_id: heroInput.order.order_id,
  fulfillment_item_id: heroInput.current_issue.fulfillment_item_id,
  sku_id: heroInput.current_issue.sku_id,
  issue_type: heroInput.current_issue.issue_type,
};

const giftCase: CaseInput = {
  ...heroInput,
  case_id: "DEMO_002",
  evaluation_time: "2026-05-05T11:00:00+08:00",
  data_provenance: {
    ...heroInput.data_provenance,
    augmentation_notes: ["赠品损坏图片为团队构建的范围变化测试"],
  },
  conversation: [
    {
      message_id: "DEMO_AUG_MSG_002",
      timestamp: "2026-05-05T10:58:00+08:00",
      speaker: "CONSUMER",
      text: "刚才发的是赠品面膜外盒压坏的照片，粉底液泵头也按不出来，这是另一件商品。",
      source_kind: "DEMO_AUGMENTATION",
    },
  ],
  service_tickets: [],
  evidence_images: [
    {
      evidence_id: "S00001_GIFT_IMG",
      file_name: "s00001-gift-evidence.jpg",
      submitted_at: "2026-05-05T10:55:00+08:00",
      declared_view_type: "PACKAGE_CONTEXT",
      source_kind: "TEAM_SYNTHETIC_AUGMENTATION",
      source_message_id: "DEMO_AUG_IMG_GIFT",
      competition_reference_path: null,
    },
  ],
};

const blurredCase: CaseInput = {
  ...heroInput,
  case_id: "DEMO_003",
  evaluation_time: "2026-05-05T11:00:00+08:00",
  data_provenance: {
    ...heroInput.data_provenance,
    augmentation_notes: ["模糊泵头图片为团队构建的不确定性测试"],
  },
  conversation: [
    {
      message_id: "DEMO_AUG_MSG_003",
      timestamp: "2026-05-05T10:58:00+08:00",
      speaker: "CONSUMER",
      text: "粉底液泵头按不出来，我拍了照片，但手机没有对上焦。",
      source_kind: "DEMO_AUGMENTATION",
    },
  ],
  service_tickets: [],
  evidence_images: [
    {
      evidence_id: "S00001_BLURRED_IMG",
      file_name: "s00001-blurred-pump.jpg",
      submitted_at: "2026-05-05T10:59:00+08:00",
      declared_view_type: "ISSUE_DETAIL",
      source_kind: "TEAM_SYNTHETIC_AUGMENTATION",
      source_message_id: "DEMO_AUG_IMG_BLURRED",
      competition_reference_path: null,
    },
  ],
};

export const demoCases: DemoCase[] = [
  {
    id: "DEMO_001",
    shortId: "S00001",
    title: "林小满",
    preview: "换货到底有没有发？",
    time: "10:45",
    unread: 1,
    expectedDecision: "INTERVENE",
    sourceLabel: "主案例",
    input: heroInput,
    preparedAction: {
      action_id: "ACT_001",
      action_type: "ASK_EVIDENCE",
      requested_scope: heroScope,
      requires_human_approval: false,
    },
    composerText: "麻烦再上传一下粉底液泵头破损的照片，我们重新核实。",
  },
  {
    id: "DEMO_002",
    shortId: "范围变化",
    title: "赠品与正装",
    preview: "这是另一件商品",
    time: "10:58",
    expectedDecision: "ALLOW",
    sourceLabel: "挑战案例",
    input: giftCase,
    preparedAction: {
      action_id: "ACT_002",
      action_type: "ASK_EVIDENCE",
      requested_scope: heroScope,
      requires_human_approval: false,
    },
    composerText: "请补充一张正装粉底液泵头的近照。",
  },
  {
    id: "DEMO_003",
    shortId: "图片模糊",
    title: "需要人工判断",
    preview: "手机没有对上焦",
    time: "10:58",
    expectedDecision: "HUMAN_REVIEW",
    sourceLabel: "挑战案例",
    input: blurredCase,
    preparedAction: {
      action_id: "ACT_003",
      action_type: "ASK_EVIDENCE",
      requested_scope: heroScope,
      requires_human_approval: false,
    },
    composerText: "麻烦重新拍一张清晰的泵头照片。",
  },
];

export const decisionLabels = {
  INTERVENE: {
    eyebrow: "发送已暂停",
    title: "别让消费者再做一次",
    compact: "已拦截重复索证",
  },
  ALLOW: {
    eyebrow: "可以继续",
    title: "当前范围需要新证据",
    compact: "范围变化，合理索证",
  },
  HUMAN_REVIEW: {
    eyebrow: "等待人工确认",
    title: "事实不足，暂不自动判断",
    compact: "已转人工复核",
  },
} as const;

export function formatClock(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
