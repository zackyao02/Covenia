import type {
  AnalyzeCaseRequest,
  AnalyzeCaseResponse,
  ApiResult,
  ApproveResolutionRequest,
  ApproveResolutionResponse,
  CoveniaApi,
  EvaluateActionRequest,
  EvaluateActionResponse,
  ShipmentEventRequest,
  ShipmentEventResponse,
  CustomerState,
  PriorityState,
} from "./contracts";
import { mockApi } from "../mockApi";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

async function get<T>(path: string): Promise<ApiResult<T>> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  const requestId = crypto.randomUUID();
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      headers: { "X-Request-Id": requestId },
      signal: controller.signal,
    });
    return await response.json() as ApiResult<T>;
  } catch {
    return {
      data: null,
      error: { code: "INTERNAL_ERROR", message: "暂时无法读取案件，请重试。", retryable: true },
      request_id: requestId,
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

async function post<TRequest, TResponse>(
  path: string,
  body: TRequest,
  options: { timeoutMs: number; idempotent?: boolean },
): Promise<ApiResult<TResponse>> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs);
  const requestId = crypto.randomUUID();

  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "X-Request-Id": requestId,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const result = (await response.json()) as ApiResult<TResponse>;
    return result;
  } catch (error) {
    return {
      data: null,
      error: {
        code: error instanceof DOMException && error.name === "AbortError"
          ? "MODEL_UNAVAILABLE"
          : "INTERNAL_ERROR",
        message: error instanceof DOMException && error.name === "AbortError"
          ? "请求超时，请稍后重试。"
          : "暂时无法连接服务，请检查网络后重试。",
        retryable: true,
      },
      request_id: requestId,
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

export const httpApi: CoveniaApi = {
  getCustomerState(caseId: string) {
    return get<CustomerState>(`/api/customer-state/${encodeURIComponent(caseId)}`);
  },
  getPriority() {
    return get<PriorityState[]>("/api/priority");
  },
  analyzeCase(input: AnalyzeCaseRequest) {
    return post<AnalyzeCaseRequest, AnalyzeCaseResponse>("/api/cases/analyze", input, {
      timeoutMs: 20_000,
    });
  },
  evaluateAction(input: EvaluateActionRequest) {
    return post<EvaluateActionRequest, EvaluateActionResponse>("/api/actions/evaluate", input, {
      timeoutMs: 10_000,
    });
  },
  approveResolution(input: ApproveResolutionRequest) {
    return post<ApproveResolutionRequest, ApproveResolutionResponse>("/api/resolutions/approve", input, {
      timeoutMs: 10_000,
      idempotent: true,
    });
  },
  pushShipmentEvent(input: ShipmentEventRequest) {
    return post<ShipmentEventRequest, ShipmentEventResponse>("/api/events/shipment", input, {
      timeoutMs: 10_000,
      idempotent: true,
    });
  },
};

export const api: CoveniaApi = import.meta.env.VITE_API_MODE === "http" ? httpApi : mockApi;
