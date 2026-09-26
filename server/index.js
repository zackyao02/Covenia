import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CoveniaService, ServiceError } from "./service.js";
import { requestId } from "./domain.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(__dirname, "../web");
const port = Number(process.env.PORT ?? 4173);
const host = process.env.HOST ?? "127.0.0.1";
const service = new CoveniaService();
const monitorIntervalMs = Number(process.env.MONITOR_INTERVAL_MS ?? 10_000);
const deadlineMonitor = setInterval(() => service.monitorPromiseDeadlines(), monitorIntervalMs);
deadlineMonitor.unref();

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function envelope(data, error, id = requestId()) {
  return { data, error, request_id: id };
}

function sendJson(response, status, payload) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  response.end(JSON.stringify(payload));
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 1_000_000) throw new ServiceError("REQUEST_TOO_LARGE", "请求体超过 1MB", 413);
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new ServiceError("SCHEMA_INVALID", "请求体不是有效 JSON");
  }
}

function serveStatic(requestPath, response) {
  const requested = requestPath === "/" ? "/index.html" : requestPath;
  const filePath = path.resolve(webRoot, `.${requested}`);
  if (!filePath.startsWith(webRoot)) return false;
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) return false;
  response.writeHead(200, {
    "content-type": mimeTypes[path.extname(filePath)] ?? "application/octet-stream",
    "cache-control": "no-cache",
  });
  fs.createReadStream(filePath).pipe(response);
  return true;
}

const server = http.createServer(async (request, response) => {
  const id = requestId();
  const url = new URL(request.url, `http://${request.headers.host ?? "localhost"}`);
  try {
    if (request.method === "GET" && url.pathname === "/api/health") {
      return sendJson(response, 200, envelope({ status: "ok", service: "covenia-v1.1", now: new Date().toISOString() }, null, id));
    }
    if (request.method === "GET" && url.pathname === "/api/risk/cases") {
      const cases = service.riskCases();
      return sendJson(response, 200, envelope({ cases, summary: {
        total: cases.length,
        critical: cases.filter((item) => item.risk.level === "CRITICAL").length,
        high: cases.filter((item) => item.risk.level === "HIGH").length,
        overdue: cases.filter((item) => item.promise.active.some((promise) => promise.status === "AT_RISK")).length,
        average_effort: Math.round(cases.reduce((sum, item) => sum + item.effort.score, 0) / Math.max(1, cases.length)),
      } }, null, id));
    }
    if (request.method === "GET" && url.pathname === "/api/emerging-issues") {
      return sendJson(response, 200, envelope(service.emergingIssues(), null, id));
    }
    if (request.method === "GET" && url.pathname === "/api/monitor/deadlines") {
      return sendJson(response, 200, envelope(service.deadlineMonitoringStatus(), null, id));
    }
    if (request.method === "GET" && url.pathname === "/api/jev/status") {
      return sendJson(response, 200, envelope(service.jevClient.status(), null, id));
    }
    const routes = new Map([
      ["/api/cases/analyze", (body) => service.analyze(body)],
      ["/api/jev/cases/analyze", (body) => service.analyzeWithJev(body)],
      ["/api/actions/evaluate", (body) => service.evaluate(body)],
      ["/api/resolutions/approve", (body) => service.approve(body)],
      ["/api/events/shipment", (body) => service.shipment(body)],
      ["/api/monitor/deadlines/run", (body) => service.monitorPromiseDeadlines(body.now)],
    ]);
    if (request.method === "POST" && routes.has(url.pathname)) {
      const body = await readJson(request);
      const data = await routes.get(url.pathname)(body);
      return sendJson(response, 200, envelope(data, null, id));
    }
    if (request.method === "GET" && serveStatic(url.pathname, response)) return;
    sendJson(response, 404, envelope(null, { code: "NOT_FOUND", message: "资源不存在", retryable: false }, id));
  } catch (error) {
    const known = error instanceof ServiceError;
    const status = known ? error.status : 500;
    if (!known) console.error(`[${id}]`, error);
    sendJson(response, status, envelope(null, {
      code: known ? error.code : "INTERNAL_ERROR",
      message: known ? error.message : "服务暂时不可用",
      retryable: known ? error.retryable : true,
    }, id));
  }
});

server.listen(port, host, () => {
  const displayHost = host === "0.0.0.0" ? "<server-ip>" : host;
  console.log(`Covenia is running at http://${displayHost}:${port}`);
});

export { server, service };
