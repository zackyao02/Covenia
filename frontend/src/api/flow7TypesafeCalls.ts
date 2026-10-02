/**
 * Typesafe API call snippets generated from:
 * /Users/zly/Desktop/哦来源/GitHub目前已有文件/generated_test_sets/flow_test_7_cases
 *
 * The source workbook uses Chinese column names. This module keeps only the
 * normalized Covenia API payloads and checks them with TypeScript `satisfies`.
 */
import type {
  AnalyzeCaseRequest,
  ApiResult,
  ApproveResolutionRequest,
  ApproveResolutionResponse,
  CaseInput,
  CoveniaApi,
  DecisionResult,
  EvaluateActionRequest,
  ObligationExecutor,
  PreparedAction,
  ShipmentEventRequest,
  ShipmentEventResponse,
} from "./contracts";

export interface Flow7RunResult {
  sampleId: string;
  analyze: Awaited<ReturnType<CoveniaApi["analyzeCase"]>>;
  decision: Awaited<ReturnType<CoveniaApi["evaluateAction"]>> | ApiResult<DecisionResult>;
  approval?: ApiResult<ApproveResolutionResponse>;
  shipment?: ApiResult<ShipmentEventResponse>;
}

function toObligationExecutor(
  executor: DecisionResult["resolution_path"]["executor"],
): ObligationExecutor | undefined {
  if (
    executor === "BRAND" ||
    executor === "WAREHOUSE" ||
    executor === "LOGISTICS_PROVIDER"
  ) {
    return executor;
  }
  return undefined;
}

async function approveIfNeeded(
  api: CoveniaApi,
  sampleId: string,
  decision: DecisionResult,
): Promise<ApiResult<ApproveResolutionResponse> | undefined> {
  if (!decision.resolution_path.requires_human_approval) return undefined;
  const executor = toObligationExecutor(decision.resolution_path.executor);

  const approveRequest = {
    case_id: sampleId,
    candidate_type: decision.resolution_path.candidate_type,
    approver_id: "FLOW7_AGENT",
    idempotency_key: `flow7-approve-${sampleId}`,
    human_edits: executor ? { executor } : {},
  } satisfies ApproveResolutionRequest;

  return api.approveResolution(approveRequest);
}

async function simulateShipmentIfUseful(
  api: CoveniaApi,
  sampleId: string,
  approval: ApiResult<ApproveResolutionResponse> | undefined,
): Promise<ApiResult<ShipmentEventResponse> | undefined> {
  if (!approval?.data?.accountability_state.open_obligation) return undefined;

  const shipmentRequest = {
    case_id: sampleId,
    event_id: `FLOW7_SHIPMENT_${sampleId}`,
    event_type: "SHIPMENT_PICKED_UP",
    event_time: "2026-05-20T10:00:00+08:00",
    idempotency_key: `flow7-shipment-${sampleId}`,
  } satisfies ShipmentEventRequest;

  return api.pushShipmentEvent(shipmentRequest);
}

async function runFlow7Case(
  api: CoveniaApi,
  sampleId: string,
  caseInput: CaseInput,
  preparedAction: PreparedAction,
): Promise<Flow7RunResult> {
  const analyzeRequest = {
    case_id: sampleId,
    challenge_mode: true,
    case_input: caseInput,
    evaluation_time: caseInput.evaluation_time,
  } satisfies AnalyzeCaseRequest;

  const analyzeResult = await api.analyzeCase(analyzeRequest);

  const evaluateRequest = {
    case_id: sampleId,
    prepared_action: preparedAction,
    challenge_mode: true,
    evaluation_time: caseInput.evaluation_time,
  } satisfies EvaluateActionRequest;

  const decisionResult = await api.evaluateAction(evaluateRequest);
  const approval = decisionResult.data
    ? await approveIfNeeded(api, sampleId, decisionResult.data)
    : undefined;
  const shipment = await simulateShipmentIfUseful(api, sampleId, approval);

  return { sampleId, analyze: analyzeResult, decision: decisionResult, approval, shipment };
}

// 1. FLOW7_01 · 补发 · 补发-漏发赠品
export const flow701CaseInput = {
  "case_id": "FLOW7_01",
  "data_provenance": {
    "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
    "source_session_id": "S00035",
    "augmentation_notes": [
      "FLOW7 sampled case normalized for typesafe API feasibility test",
      "source_ticket_sheet=补发换货工单",
      "sample_category=补发"
    ]
  },
  "evaluation_time": "2026-05-06T15:02:16+08:00",
  "conversation": [
    {
      "message_id": "72830760688119.PNM",
      "timestamp": "2026-05-06T14:52:11+08:00",
      "speaker": "CONSUMER",
      "text": "你好，我收到货了，但是说好的赠品测试修护精华小样5ml呢？没看到啊",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "86811279439898.PNM",
      "timestamp": "2026-05-06T14:55:01+08:00",
      "speaker": "AGENT",
      "text": "好的亲，马上为您查询，请稍等1-2分钟哦",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "88678098044389.PNM",
      "timestamp": "2026-05-06T14:55:33+08:00",
      "speaker": "AGENT",
      "text": "亲，查到您的订单确实包含赠品测试修护精华小样5ml，实在抱歉是仓库漏发了！这边马上给您登记补发",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "12503850924596.PNM",
      "timestamp": "2026-05-06T14:56:30+08:00",
      "speaker": "CONSUMER",
      "text": "亲，就是冲着赠品买的，可别再漏了啊",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "53736578475189.PNM",
      "timestamp": "2026-05-06T14:59:10+08:00",
      "speaker": "AGENT",
      "text": "已为您创建补发工单，48小时内发出，发货后单号同步给您，这次仓库会重点核对的，请您放心~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "91761172411389.PNM",
      "timestamp": "2026-05-06T15:00:05+08:00",
      "speaker": "CONSUMER",
      "text": "行，那等着了，谢谢",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "98932250393326.PNM",
      "timestamp": "2026-05-06T15:02:16+08:00",
      "speaker": "AGENT",
      "text": "后续有任何问题随时找欣欣哦，祝您使用愉快哈~",
      "source_kind": "COMPETITION_MOCK"
    }
  ],
  "order": {
    "order_id": "6920420870390416560",
    "channel": "TIANCHI_MOCK_QIANNIU",
    "items": [
      {
        "fulfillment_item_id": "6920420870390416560-XL10153",
        "sku_id": "XL10153",
        "product_name": "测试水润保湿眼霜15ml",
        "batch_code": null,
        "item_role": "PRIMARY"
      }
    ],
    "original_logistics_number": "SF1643040082892"
  },
  "service_tickets": [
    {
      "ticket_id": "BH652810902299",
      "ticket_type": "REPLACEMENT",
      "status": "已完结",
      "assignee_id": "G001",
      "executor_name": "测试供应链华东仓",
      "replacement_logistics_number": "773700160226927",
      "created_at": "2026-05-06T15:07:11+08:00",
      "completed_at": "2026-05-06T19:07:11+08:00",
      "source_sheet": "补发换货工单"
    }
  ],
  "evidence_images": [],
  "current_issue": {
    "fulfillment_item_id": "6920420870390416560-XL10153",
    "sku_id": "XL10153",
    "issue_type": "PACKAGE_DAMAGE",
    "affected_component": "UNKNOWN"
  },
  "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1"
} satisfies CaseInput;
export const flow701PreparedAction = {
  "action_id": "FLOW7_01_ACTION_001",
  "action_type": "CHECK_REPLACEMENT_PROGRESS",
  "requested_scope": {
    "order_id": "6920420870390416560",
    "fulfillment_item_id": "6920420870390416560-XL10153",
    "sku_id": "XL10153",
    "issue_type": "PACKAGE_DAMAGE"
  },
  "requires_human_approval": false
} satisfies PreparedAction;
export async function runFlow701(api: CoveniaApi): Promise<Flow7RunResult> {
  return runFlow7Case(api, "FLOW7_01", flow701CaseInput, flow701PreparedAction);
}

// 2. FLOW7_02 · 换货 · 换货-错发色号
export const flow702CaseInput = {
  "case_id": "FLOW7_02",
  "data_provenance": {
    "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
    "source_session_id": "S00004",
    "augmentation_notes": [
      "FLOW7 sampled case normalized for typesafe API feasibility test",
      "source_ticket_sheet=补发换货工单",
      "sample_category=换货"
    ]
  },
  "evaluation_time": "2026-05-05T11:59:21+08:00",
  "conversation": [
    {
      "message_id": "32171230124098.PNM",
      "timestamp": "2026-05-05T11:53:20+08:00",
      "speaker": "CONSUMER",
      "text": "开什么玩笑，我买的#01赤茶红，发来个#05枫叶红，色差也太大了，这我没法用",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "92208255883627.PNM",
      "timestamp": "2026-05-05T11:54:08+08:00",
      "speaker": "AGENT",
      "text": "非常抱歉亲！麻烦您拍一下收到商品的底标色号照片，测试客服马上为您核实处理呢~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "73787673079790.PNM",
      "timestamp": "2026-05-05T11:55:11+08:00",
      "speaker": "CONSUMER",
      "text": "图发你了，底标写的就是#05枫叶红",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "71878455163266.PNM",
      "timestamp": "2026-05-05T11:55:57+08:00",
      "speaker": "AGENT",
      "text": "确认是仓库发错色号了，实在抱歉！给您两个方案：①直接换货，先给您发#01赤茶红，收到后把错发的寄回（运费我们承担）；②如果您愿意留下#05枫叶红，补偿您30元。您选哪个？",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "15906241685198.PNM",
      "timestamp": "2026-05-05T11:56:29+08:00",
      "speaker": "CONSUMER",
      "text": "emmm，那还是换吧，#05枫叶红不适合我",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "45892272353688.PNM",
      "timestamp": "2026-05-05T11:58:55+08:00",
      "speaker": "AGENT",
      "text": "好的亲，换货工单已创建，今天为您发出#01赤茶红，包裹里附退货面单，您把#05枫叶红原样放进去交给快递员就行，全程不用您花一分钱~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "87403395200892.PNM",
      "timestamp": "2026-05-05T11:59:21+08:00",
      "speaker": "CONSUMER",
      "text": "行，操作挺方便，那等新的到了我就寄回",
      "source_kind": "COMPETITION_MOCK"
    }
  ],
  "order": {
    "order_id": "6920906372438643491",
    "channel": "TIANCHI_MOCK_QIANNIU",
    "items": [
      {
        "fulfillment_item_id": "6920906372438643491-XC30101",
        "sku_id": "XC30101",
        "product_name": "测试丝绒唇釉 #01赤茶红",
        "batch_code": null,
        "item_role": "PRIMARY"
      }
    ],
    "original_logistics_number": "463435373928579"
  },
  "service_tickets": [
    {
      "ticket_id": "BH699081699885",
      "ticket_type": "REPLACEMENT",
      "status": "已完结",
      "assignee_id": "A03",
      "executor_name": "测试供应链华东仓",
      "replacement_logistics_number": "773788296066113",
      "created_at": "2026-05-05T12:40:20+08:00",
      "completed_at": "2026-05-05T16:28:20+08:00",
      "source_sheet": "补发换货工单"
    }
  ],
  "evidence_images": [],
  "current_issue": {
    "fulfillment_item_id": "6920906372438643491-XC30101",
    "sku_id": "XC30101",
    "issue_type": "PACKAGE_DAMAGE",
    "affected_component": "UNKNOWN"
  },
  "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1"
} satisfies CaseInput;
export const flow702PreparedAction = {
  "action_id": "FLOW7_02_ACTION_001",
  "action_type": "CHECK_REPLACEMENT_PROGRESS",
  "requested_scope": {
    "order_id": "6920906372438643491",
    "fulfillment_item_id": "6920906372438643491-XC30101",
    "sku_id": "XC30101",
    "issue_type": "PACKAGE_DAMAGE"
  },
  "requires_human_approval": false
} satisfies PreparedAction;
export async function runFlow702(api: CoveniaApi): Promise<Flow7RunResult> {
  return runFlow7Case(api, "FLOW7_02", flow702CaseInput, flow702PreparedAction);
}

// 3. FLOW7_03 · 线下打款 · 售后期关闭退款
export const flow703CaseInput = {
  "case_id": "FLOW7_03",
  "data_provenance": {
    "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
    "source_session_id": "S00381",
    "augmentation_notes": [
      "FLOW7 sampled case normalized for typesafe API feasibility test",
      "source_ticket_sheet=线下打款工单",
      "sample_category=线下打款"
    ]
  },
  "evaluation_time": "2026-05-19T15:53:22+08:00",
  "conversation": [
    {
      "message_id": "13694977354478.PNM",
      "timestamp": "2026-05-19T15:44:33+08:00",
      "speaker": "CONSUMER",
      "text": "在吗，我的退货你们仓库都签收了，但售后单关闭了钱退不出来，急死我了呀",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "29182562564725.PNM",
      "timestamp": "2026-05-19T15:46:19+08:00",
      "speaker": "AGENT",
      "text": "好的亲，马上为您查询，请稍候1-2分钟哦",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "93578485614464.PNM",
      "timestamp": "2026-05-19T15:46:52+08:00",
      "speaker": "AGENT",
      "text": "亲别担心，查到您的退货已入库验收无误，只是平台售后期已过无法原路退款。这边走线下打款流程给您退，一分不会少的~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "97001141269602.PNM",
      "timestamp": "2026-05-19T15:47:42+08:00",
      "speaker": "CONSUMER",
      "text": "真的吗？那太好了，要什么信息你说哦",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "72730906445336.PNM",
      "timestamp": "2026-05-19T15:49:04+08:00",
      "speaker": "AGENT",
      "text": "提供下您的支付宝实名和账号就行，退款10元，审核通过后1-3个工作日到账",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "13900699709378.PNM",
      "timestamp": "2026-05-19T15:50:08+08:00",
      "speaker": "CONSUMER",
      "text": "发你了，谢谢谢谢",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "94464847131519.PNM",
      "timestamp": "2026-05-19T15:52:27+08:00",
      "speaker": "AGENT",
      "text": "已提交打款申请，请您留意支付宝到账通知，到账后麻烦回来跟测试客服说一声哦~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "28484931077464.PNM",
      "timestamp": "2026-05-19T15:53:22+08:00",
      "speaker": "CONSUMER",
      "text": "好的好的，谢谢你，帮大忙了",
      "source_kind": "COMPETITION_MOCK"
    }
  ],
  "order": {
    "order_id": "6920914776440905581",
    "channel": "TIANCHI_MOCK_QIANNIU",
    "items": [
      {
        "fulfillment_item_id": "6920914776440905581-XL23003",
        "sku_id": "XL23003",
        "product_name": "测试舒缓保湿喷雾300ml",
        "batch_code": null,
        "item_role": "PRIMARY"
      }
    ],
    "original_logistics_number": "773402274776732"
  },
  "service_tickets": [
    {
      "ticket_id": "HV1005604873",
      "ticket_type": "OFFLINE_PAYMENT",
      "status": "进行中",
      "assignee_id": "A03",
      "executor_name": null,
      "replacement_logistics_number": "773495659147765",
      "created_at": "2026-05-19T16:26:33+08:00",
      "completed_at": null,
      "source_sheet": "线下打款工单"
    }
  ],
  "evidence_images": [
    {
      "evidence_id": "FLOW7_03_IMG_01",
      "file_name": "S00381_06.jpg",
      "submitted_at": "2026-05-19T15:50:08+08:00",
      "declared_view_type": "OTHER",
      "source_kind": "TEAM_SYNTHETIC_AUGMENTATION",
      "source_message_id": "13900699709378.PNM",
      "competition_reference_path": "mock_images/refund_screenshot/S00381_06.jpg"
    }
  ],
  "current_issue": {
    "fulfillment_item_id": "6920914776440905581-XL23003",
    "sku_id": "XL23003",
    "issue_type": "PACKAGE_DAMAGE",
    "affected_component": "UNKNOWN"
  },
  "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1"
} satisfies CaseInput;
export const flow703PreparedAction = {
  "action_id": "FLOW7_03_ACTION_001",
  "action_type": "CREATE_FOLLOW_UP_TASK",
  "requested_scope": {
    "order_id": "6920914776440905581",
    "fulfillment_item_id": "6920914776440905581-XL23003",
    "sku_id": "XL23003",
    "issue_type": "PACKAGE_DAMAGE"
  },
  "requires_human_approval": true
} satisfies PreparedAction;
export async function runFlow703(api: CoveniaApi): Promise<Flow7RunResult> {
  return runFlow7Case(api, "FLOW7_03", flow703CaseInput, flow703PreparedAction);
}

// 4. FLOW7_04 · 物流 · 已收-货物短少(少件)
export const flow704CaseInput = {
  "case_id": "FLOW7_04",
  "data_provenance": {
    "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
    "source_session_id": "S00023",
    "augmentation_notes": [
      "FLOW7 sampled case normalized for typesafe API feasibility test",
      "source_ticket_sheet=物流工单",
      "sample_category=物流"
    ]
  },
  "evaluation_time": "2026-05-05T21:42:03+08:00",
  "conversation": [
    {
      "message_id": "93591189567742.PNM",
      "timestamp": "2026-05-05T21:35:16+08:00",
      "speaker": "CONSUMER",
      "text": "在吗，包裹到了但里面少了眼影盘，箱子也没破，咋回事",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "16134049045620.PNM",
      "timestamp": "2026-05-05T21:36:55+08:00",
      "speaker": "AGENT",
      "text": "收到，这边立刻为您核实，稍等一下下~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "11547736210894.PNM",
      "timestamp": "2026-05-05T21:37:24+08:00",
      "speaker": "AGENT",
      "text": "亲，麻烦您拍一下外箱面单和内件全貌照片哈，这边同步仓库核对出库重量记录~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "64956040246937.PNM",
      "timestamp": "2026-05-05T21:38:10+08:00",
      "speaker": "CONSUMER",
      "text": "emmm，图发你了，麻烦快点处理，等着用的",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "93072451988400.PNM",
      "timestamp": "2026-05-05T21:39:23+08:00",
      "speaker": "AGENT",
      "text": "收到亲，已登记少件工单，仓库正在复核出库录像，24小时内给您结果；若确认漏发，立即补发缺少商品~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "46955161163524.PNM",
      "timestamp": "2026-05-05T21:40:07+08:00",
      "speaker": "CONSUMER",
      "text": "行吧，等你们消息，麻烦了",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "72915827691981.PNM",
      "timestamp": "2026-05-05T21:41:16+08:00",
      "speaker": "AGENT",
      "text": "亲亲，仓库已核实为分拣遗漏，非常抱歉！缺少的眼影盘今天加急补发，顺丰到付…不对，是顺丰包邮直发您家哦哦~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "15152352129545.PNM",
      "timestamp": "2026-05-05T21:42:03+08:00",
      "speaker": "CONSUMER",
      "text": "哈哈行，你这客服还挺逗，等着了",
      "source_kind": "COMPETITION_MOCK"
    }
  ],
  "order": {
    "order_id": "6920381227503627930",
    "channel": "TIANCHI_MOCK_QIANNIU",
    "items": [
      {
        "fulfillment_item_id": "6920381227503627930-XC30903",
        "sku_id": "XC30903",
        "product_name": "测试九色眼影盘 #03落日大地",
        "batch_code": null,
        "item_role": "PRIMARY"
      }
    ],
    "original_logistics_number": "463478499903000"
  },
  "service_tickets": [
    {
      "ticket_id": "WL698348054",
      "ticket_type": "LOGISTICS",
      "status": "工单组处理",
      "assignee_id": "G002",
      "executor_name": "测试美妆分销中心",
      "replacement_logistics_number": "463478499903000",
      "created_at": "2026-05-05T22:00:16+08:00",
      "completed_at": null,
      "source_sheet": "物流工单"
    }
  ],
  "evidence_images": [
    {
      "evidence_id": "FLOW7_04_IMG_01",
      "file_name": "S00023_04.jpg",
      "submitted_at": "2026-05-05T21:38:10+08:00",
      "declared_view_type": "PACKAGE_CONTEXT",
      "source_kind": "TEAM_SYNTHETIC_AUGMENTATION",
      "source_message_id": "64956040246937.PNM",
      "competition_reference_path": "mock_images/short_item/S00023_04.jpg"
    }
  ],
  "current_issue": {
    "fulfillment_item_id": "6920381227503627930-XC30903",
    "sku_id": "XC30903",
    "issue_type": "LOGISTICS_STALLED",
    "affected_component": "OUTER_PACKAGE"
  },
  "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1"
} satisfies CaseInput;
export const flow704PreparedAction = {
  "action_id": "FLOW7_04_ACTION_001",
  "action_type": "CHECK_REPLACEMENT_PROGRESS",
  "requested_scope": {
    "order_id": "6920381227503627930",
    "fulfillment_item_id": "6920381227503627930-XC30903",
    "sku_id": "XC30903",
    "issue_type": "LOGISTICS_STALLED"
  },
  "requires_human_approval": false
} satisfies PreparedAction;
export async function runFlow704(api: CoveniaApi): Promise<Flow7RunResult> {
  return runFlow7Case(api, "FLOW7_04", flow704CaseInput, flow704PreparedAction);
}

// 5. FLOW7_05 · 不良反应 · 额头发红、起小颗粒疹子，伴瘙痒（买家自述）
export const flow705CaseInput = {
  "case_id": "FLOW7_05",
  "data_provenance": {
    "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
    "source_session_id": "S00079",
    "augmentation_notes": [
      "FLOW7 sampled case normalized for typesafe API feasibility test",
      "source_ticket_sheet=不良反应工单",
      "sample_category=不良反应"
    ]
  },
  "evaluation_time": "2026-05-08T17:51:19+08:00",
  "conversation": [
    {
      "message_id": "41444390778681.PNM",
      "timestamp": "2026-05-08T17:38:49+08:00",
      "speaker": "CONSUMER",
      "text": "在吗？急！昨晚用了洁面乳，今早额头又红又痒，是不是过敏了！",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "47470037906197.PNM",
      "timestamp": "2026-05-08T17:41:25+08:00",
      "speaker": "AGENT",
      "text": "亲先别慌，测试客服帮您登记核实。请先立即停用产品，用清水洁面，暂时不要叠加其他护肤品哦。方便说下您用后多久出现不适的吗？",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "35971309387809.PNM",
      "timestamp": "2026-05-08T17:42:31+08:00",
      "speaker": "CONSUMER",
      "text": "当晚就有点刺，第二天更明显了",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "38391373397485.PNM",
      "timestamp": "2026-05-08T17:44:38+08:00",
      "speaker": "AGENT",
      "text": "了解~再确认几个信息哈：您的年龄和肤质？使用前皮肤状态如何？最近一周有没有用新的其他产品或做医美项目？",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "34384356061340.PNM",
      "timestamp": "2026-05-08T17:45:26+08:00",
      "speaker": "CONSUMER",
      "text": "那个，31岁，油性肌肤，之前皮肤挺稳定的，最近没换别的东西也没做医美，急",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "89667551938341.PNM",
      "timestamp": "2026-05-08T17:47:22+08:00",
      "speaker": "AGENT",
      "text": "收到亲。目前建议：停用+温和清洁+做好保湿，一般轻度敏感2-3天可自行缓解；若持续加重或范围扩大请及时就医。这边已为您登记不良反应记录单，专员会在24小时内回访跟进~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "51186872059789.PNM",
      "timestamp": "2026-05-08T17:48:23+08:00",
      "speaker": "CONSUMER",
      "text": "需要退货吗？剩下大半瓶呢",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "72548600652653.PNM",
      "timestamp": "2026-05-08T17:50:13+08:00",
      "speaker": "AGENT",
      "text": "建议皮肤完全恢复后先做耳后测试，若仍不适就不要继续使用了~商品可以走\"使用不适\"退货退款，运费我们承担，稍后专员回访时一并为您办理~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "20122123699603.PNM",
      "timestamp": "2026-05-08T17:50:40+08:00",
      "speaker": "CONSUMER",
      "text": "好的，那我先停用观察，谢谢哦",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "43612810666181.PNM",
      "timestamp": "2026-05-08T17:51:19+08:00",
      "speaker": "AGENT",
      "text": "嗯嗯，祝您皮肤快快恢复，有任何变化随时联系测试客服~",
      "source_kind": "COMPETITION_MOCK"
    }
  ],
  "order": {
    "order_id": "6920676929380273867",
    "channel": "TIANCHI_MOCK_QIANNIU",
    "items": [
      {
        "fulfillment_item_id": "6920676929380273867-XL21205",
        "sku_id": "XL21205",
        "product_name": "测试温和氨基酸洁面乳120ml",
        "batch_code": "26B12",
        "item_role": "PRIMARY"
      }
    ],
    "original_logistics_number": "YT7611027129564"
  },
  "service_tickets": [
    {
      "ticket_id": "BLFY28579679",
      "ticket_type": "ADVERSE_REACTION",
      "status": "已完结",
      "assignee_id": "A05",
      "executor_name": null,
      "replacement_logistics_number": null,
      "created_at": "2026-05-08T18:04:49+08:00",
      "completed_at": "2026-05-08T23:08:49+08:00",
      "source_sheet": "不良反应工单"
    }
  ],
  "evidence_images": [],
  "current_issue": {
    "fulfillment_item_id": "6920676929380273867-XL21205",
    "sku_id": "XL21205",
    "issue_type": "ADVERSE_REACTION",
    "affected_component": "UNKNOWN"
  },
  "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1"
} satisfies CaseInput;
export const flow705PreparedAction = {
  "action_id": "FLOW7_05_ACTION_001",
  "action_type": "ASK_EVIDENCE",
  "requested_scope": {
    "order_id": "6920676929380273867",
    "fulfillment_item_id": "6920676929380273867-XL21205",
    "sku_id": "XL21205",
    "issue_type": "ADVERSE_REACTION"
  },
  "requires_human_approval": true
} satisfies PreparedAction;
export async function runFlow705(api: CoveniaApi): Promise<Flow7RunResult> {
  return runFlow7Case(api, "FLOW7_05", flow705CaseInput, flow705PreparedAction);
}

// 6. FLOW7_06 · 售后退货-异常 · 协商一致退款
export const flow706CaseInput = {
  "case_id": "FLOW7_06",
  "data_provenance": {
    "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
    "source_session_id": "S00076",
    "augmentation_notes": [
      "FLOW7 sampled case normalized for typesafe API feasibility test",
      "source_ticket_sheet=售后退货工单",
      "sample_category=售后退货-异常"
    ]
  },
  "evaluation_time": "2026-05-08T16:00:06+08:00",
  "conversation": [
    {
      "message_id": "87876031612223.PNM",
      "timestamp": "2026-05-08T15:52:30+08:00",
      "speaker": "CONSUMER",
      "text": "我在专柜对比了，你们发的粉底液膏体颜色不一样，质地也稀，是不是给我发的假货？！哦",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "62747503042360.PNM",
      "timestamp": "2026-05-08T15:52:56+08:00",
      "speaker": "AGENT",
      "text": "亲请放心，官方旗舰店所有商品与专柜同源，绝无假货。不同批次间原料存在合理差异~您可以刮开防伪码验证，也可以把批次号发我帮您查~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "92900836378476.PNM",
      "timestamp": "2026-05-08T15:53:44+08:00",
      "speaker": "CONSUMER",
      "text": "批次号26A27，你查！查不出来我就去平台举报，急",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "99981856230927.PNM",
      "timestamp": "2026-05-08T15:56:02+08:00",
      "speaker": "AGENT",
      "text": "查到批次26A27为今年3月正常生产批次，质检报告可以发您。当然，如果您仍不放心，完全支持退货退款，运费我们承担，绝不让您勉强使用哈~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "12231567697227.PNM",
      "timestamp": "2026-05-08T15:57:05+08:00",
      "speaker": "CONSUMER",
      "text": "行，那退吧，报告也发我一份，我自己看",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "44823773515997.PNM",
      "timestamp": "2026-05-08T15:57:33+08:00",
      "speaker": "AGENT",
      "text": "好的亲，退货申请这边直接给您通过，质检报告已发送。仓库签收后当天退款~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "72152884051374.PNM",
      "timestamp": "2026-05-08T15:58:07+08:00",
      "speaker": "CONSUMER",
      "text": "收到，处理挺痛快，就是希望品控上点心",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "37234694467079.PNM",
      "timestamp": "2026-05-08T15:59:09+08:00",
      "speaker": "AGENT",
      "text": "好的亲，还有其他可以帮您的吗？祝您生活愉快~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "69182903606382.PNM",
      "timestamp": "2026-05-08T16:00:06+08:00",
      "speaker": "SYSTEM",
      "text": "【测试积分】您已累计2860积分，可在积分商城兑换小样好礼，快来看看~",
      "source_kind": "COMPETITION_MOCK"
    }
  ],
  "order": {
    "order_id": "6920527885849331832",
    "channel": "TIANCHI_MOCK_QIANNIU",
    "items": [
      {
        "fulfillment_item_id": "6920527885849331832-XC33003",
        "sku_id": "XC33003",
        "product_name": "测试轻透粉底液30ml #N02自然色",
        "batch_code": null,
        "item_role": "PRIMARY"
      }
    ],
    "original_logistics_number": "773766140701841"
  },
  "service_tickets": [
    {
      "ticket_id": "KOC2531140",
      "ticket_type": "RETURN",
      "status": "已完结",
      "assignee_id": "G001",
      "executor_name": null,
      "replacement_logistics_number": "463489998443198",
      "created_at": "2026-05-08T16:03:30+08:00",
      "completed_at": "2026-05-08T21:36:30+08:00",
      "source_sheet": "售后退货工单"
    }
  ],
  "evidence_images": [],
  "current_issue": {
    "fulfillment_item_id": "6920527885849331832-XC33003",
    "sku_id": "XC33003",
    "issue_type": "PACKAGE_DAMAGE",
    "affected_component": "UNKNOWN"
  },
  "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1"
} satisfies CaseInput;
export const flow706PreparedAction = {
  "action_id": "FLOW7_06_ACTION_001",
  "action_type": "CREATE_FOLLOW_UP_TASK",
  "requested_scope": {
    "order_id": "6920527885849331832",
    "fulfillment_item_id": "6920527885849331832-XC33003",
    "sku_id": "XC33003",
    "issue_type": "PACKAGE_DAMAGE"
  },
  "requires_human_approval": true
} satisfies PreparedAction;
export async function runFlow706(api: CoveniaApi): Promise<Flow7RunResult> {
  return runFlow7Case(api, "FLOW7_06", flow706CaseInput, flow706PreparedAction);
}

// 7. FLOW7_07 · 售后退货-正常 · 使用后不适
export const flow707CaseInput = {
  "case_id": "FLOW7_07",
  "data_provenance": {
    "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
    "source_session_id": "S00068",
    "augmentation_notes": [
      "FLOW7 sampled case normalized for typesafe API feasibility test",
      "source_ticket_sheet=售后退货工单",
      "sample_category=售后退货-正常"
    ]
  },
  "evaluation_time": "2026-05-08T09:53:29+08:00",
  "conversation": [
    {
      "message_id": "32013046520247.PNM",
      "timestamp": "2026-05-08T09:46:24+08:00",
      "speaker": "CONSUMER",
      "text": "在吗，这个卸妆水我用着不太舒服，脸有点紧绷刺刺的，不严重但不想用了，能退不，麻烦了",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "78730973295874.PNM",
      "timestamp": "2026-05-08T09:47:18+08:00",
      "speaker": "AGENT",
      "text": "亲，先关心下您的皮肤状况：现在还有不适感吗？建议先停用观察哦",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "75299706461063.PNM",
      "timestamp": "2026-05-08T09:48:07+08:00",
      "speaker": "CONSUMER",
      "text": "在吗，停了就没事了，就是不适合我，退货吧啊",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "42679395699902.PNM",
      "timestamp": "2026-05-08T09:50:52+08:00",
      "speaker": "AGENT",
      "text": "好的亲，虽然商品已开封，考虑到是使用不适，咱家支持退货的~您申请退货退款选\"与商品描述不符-使用后不适\"，剩余商品寄回即可，运费我们承担~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "65629514156248.PNM",
      "timestamp": "2026-05-08T09:51:31+08:00",
      "speaker": "CONSUMER",
      "text": "行，那我今天寄，用不惯真的可惜了",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "43272052317531.PNM",
      "timestamp": "2026-05-08T09:52:47+08:00",
      "speaker": "AGENT",
      "text": "已为您秒审通过~仓库收到验收后1-3个工作日退款，感谢理解，也欢迎以后再来试试其他款呢~",
      "source_kind": "COMPETITION_MOCK"
    },
    {
      "message_id": "14544382911740.PNM",
      "timestamp": "2026-05-08T09:53:29+08:00",
      "speaker": "CONSUMER",
      "text": "行吧，谢谢啊",
      "source_kind": "COMPETITION_MOCK"
    }
  ],
  "order": {
    "order_id": "6920887080308099214",
    "channel": "TIANCHI_MOCK_QIANNIU",
    "items": [
      {
        "fulfillment_item_id": "6920887080308099214-XL21204",
        "sku_id": "XL21204",
        "product_name": "测试净澈卸妆水300ml",
        "batch_code": null,
        "item_role": "PRIMARY"
      }
    ],
    "original_logistics_number": "463424126607914"
  },
  "service_tickets": [
    {
      "ticket_id": "KOC3556428",
      "ticket_type": "RETURN",
      "status": "已完结",
      "assignee_id": "B12",
      "executor_name": null,
      "replacement_logistics_number": "YT7639618554406",
      "created_at": "2026-05-08T10:17:24+08:00",
      "completed_at": "2026-05-08T12:48:24+08:00",
      "source_sheet": "售后退货工单"
    }
  ],
  "evidence_images": [],
  "current_issue": {
    "fulfillment_item_id": "6920887080308099214-XL21204",
    "sku_id": "XL21204",
    "issue_type": "PACKAGE_DAMAGE",
    "affected_component": "UNKNOWN"
  },
  "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1"
} satisfies CaseInput;
export const flow707PreparedAction = {
  "action_id": "FLOW7_07_ACTION_001",
  "action_type": "CREATE_FOLLOW_UP_TASK",
  "requested_scope": {
    "order_id": "6920887080308099214",
    "fulfillment_item_id": "6920887080308099214-XL21204",
    "sku_id": "XL21204",
    "issue_type": "PACKAGE_DAMAGE"
  },
  "requires_human_approval": true
} satisfies PreparedAction;
export async function runFlow707(api: CoveniaApi): Promise<Flow7RunResult> {
  return runFlow7Case(api, "FLOW7_07", flow707CaseInput, flow707PreparedAction);
}

export const flow7TypesafeRunners = [
  runFlow701,
  runFlow702,
  runFlow703,
  runFlow704,
  runFlow705,
  runFlow706,
  runFlow707,
] as const;
