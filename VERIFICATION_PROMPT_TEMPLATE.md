# VERIFICATION_PROMPT_TEMPLATE

由独立的全新 Codex 对话执行；不要在实现对话里让实现者给自己 PASS。模型可采用 gpt-5.6-terra / max，与执行者同型号不影响“独立对话、独立证据”的要求。

## 调度者填写

- REPO_ROOT：{{目标仓库绝对路径}}
- TARGET_BATCH_ID：{{BATCH-xx}}
- BASE_SHA：{{实施前已验收集成基线}}
- IMPLEMENTATION_COMMITS：{{本批确切代码/测试提交列表}}
- REVIEW_SHA：{{待验收的固定提交}}
- CONTRACT_VERSION / PLAN_SHA256：{{契约版本与计划哈希}}
- IMPLEMENTATION_REPORT：{{报告绝对路径}}
- DEPENDENCY_RECEIPTS / EXTERNAL_GATE_RECEIPTS：{{可读取的前置 PASS/ACCEPTED 与集成回执}}
- VERIFY_RUN_DIR：{{独立验收运行目录，不共用实现者 DB/缓存}}
- RESOURCE_LOCKS / BASE_URLS / MODEL_MANIFEST：{{当前批需要的独占资源与已脱敏环境}}
- OUTPUT：reports/batches/{{TARGET_BATCH_ID}}/VERIFICATION_REPORT.json

## 你的任务与权限

只验收 TARGET_BATCH_ID，不实现新功能、不修实现代码、不改变产品范围。不要相信实现报告中的完成声明、测试计数、图片来源或 PASS；它们只是查证线索。
代码、Schema、配置、锁文件、原始数据、GT 和 C UI 只读。可在本批验收输出目录写报告/脱敏证据，在隔离临时环境运行测试；不得覆盖 IMPLEMENTATION_REPORT，不修改根 QA-ACCEPTANCE.md/历史 Claude 文件或调度状态。

### 1. 固定基线并查证差异

1. 检查 git status --short、HEAD/branch、适用 AGENTS.md 和所有输入路径。验证 REVIEW_SHA 存在、BASE_SHA 是正确基线、本批代码提交准确；不检查一个仍在被实现者修改的工作树。
2. 阅读 MASTER_PLAN 当前批完整包、batches.json 对应条目、指定输入、最新批准冻结与契约锁、依赖的独立报告及集成回执。未合并正式契约不能被旧 main 覆盖。
3. 使用 git diff --name-status BASE_SHA REVIEW_SHA 和逐文件 diff 查验真实修改。若 REVIEW_SHA 额外包含其他批/外部门提交，分离审查本批 commit 集并记录准确树差异，不能漏审或把他人的文件判成当前批成果。
4. 对每个路径核对 allowed_paths/forbidden_paths；全仓格式化、改依赖/配置、改 GT、改前端、写第五接口、重写批准记录均需对应授权，否则 FAIL。
5. 实现者报告引用的产物必须实存、hash相符、与 REVIEW_SHA 对应。缺失“据称已通过”的测试/脚本或核心逻辑是 FAIL；缺外部服务/资产是 BLOCKED，分别记录。

### 2. 独立验证

- 阅读实现代码及新增测试，确认断言真的验证业务，不能只快照复制固定 JSON/导入 expected 作为 actual。
- 从隔离环境按锁文件安装，运行该 Batch 所有 acceptance_commands 和 git diff --check，保存完整退出码/脱敏输出。不要只复述实现者日志。
- 检查测试的关键 skip/xfail、被吞异常、恒真断言与硬编码 fixture；先审计脚本会写哪些运行路径，禁止对共享 DB/源文件做破坏测试。
- 针对本批目标加入只读/临时探针复核边界：同 ID 改事实、换随机 ID 不改事实、来源假冒、PII 旁路、缓存标识、并发重放、倒序事件等。探针不要求永久改代码；发现缺口给最小修复清单。
- live 检查真实模型身份/revision、实际图片 bytes/hash、无缓存、usage/latency 和脱敏；http/e2e 检查真实网络四端点和 UI 状态，拒绝以 Mock 或观察覆盖代替真实图像因果测试。
- 验证负控制确实触发目标断言：关闭 PII 必须被抓到，移除缓存角标必须被抓到；测试环境还原。异常来自模型不可用/语法错误不是有效负控制证据。
- 检查模型不决定最终责任/激活/证据/规则、规则优先级与抑制列表、命令来源与下游交接的完整性。
- 检查回滚是否仅针对本批提交与明确备份，不能删源数据/强制改分支；代码回滚不能冒充撤销人审事实。

### 3. 裁定

- PASS：本批每条验收标准有独立证据；所有要求测试成功，无越界；真实资源门已满足且输入/契约/代码版本匹配；交接与回滚完整。
- FAIL：发现可复现缺陷、缺实现/测试/产物、违反范围、安全或规范、伪装证据。即使另外还有外部阻塞，也先报告已证实的 FAIL。
- BLOCKED：仅因缺批准/图片/模型/环境/独占资源等外部条件不能判定，且没有已证实应判 FAIL 的实现缺陷。列明已做检查，不扩大为全项目失败。
- 不使用“有条件 PASS”跨过关键门。PASS 不是集成许可的全部：协调者仍须合并准确提交并在集成 SHA 复跑受影响检查，写集成回执才可放行下游。

FAIL 必须给最小修复清单：准确文件/行或模块、复现步骤、期望/实际、需要增加的断言、责任 Batch。修复若超出当前白名单，标记所属 Batch 与负责人，不直接代改或扩大实现范围。
BLOCKED 给解除条件及 owner，不伪造临时批准或替身结果。

### 4. 输出格式

只写当前 OUTPUT 及同目录 verification-evidence/；不更改计划状态。报告自己的提交由协调者保存，不能为了填 PASS 擅自 merge/push。

```json
{
  "report_version": "1.0",
  "batch_id": "BATCH-xx",
  "verdict": "PASS",
  "reviewed_base_sha": "<sha>",
  "reviewed_sha": "<sha>",
  "reviewed_code_commits": ["<sha>"],
  "contract_version": "<version>",
  "plan_sha256": "<hash>",
  "verified_at": "<ISO date-time>",
  "independent_context": true,
  "environment": {"python": "<version>", "node": "<version or NOT_REQUIRED>", "run_dir": "<absolute path>"},
  "dependency_checks": [],
  "external_gate_checks": [],
  "scope_audit": {"passed": true, "changed_files": [], "violations": []},
  "criteria": [
    {"criterion": "<exact criterion>", "result": "PASS", "evidence": ["<path>"]}
  ],
  "commands": [
    {"command": "<actual>", "cwd": "<absolute path>", "exit_code": 0, "mode": "UNIT", "output": "<path>"}
  ],
  "artifact_hashes": {},
  "negative_controls": [],
  "findings": [],
  "minimal_fix_list": [],
  "blockers": [],
  "recheck_commands": [],
  "rollback_review": {"passed": true, "notes": ""},
  "code_modified": false,
  "next_batch_started": false
}
```

不得照抄示例 PASS 或空 findings；填写本次实际结果。最终回答先给 PASS/FAIL/BLOCKED，再列证据路径、审查 SHA、测试摘要；FAIL 给最小修复清单，BLOCKED 给解除条件。不自行启动下一 Batch。

