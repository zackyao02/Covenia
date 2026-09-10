# BATCH_PROMPT_TEMPLATE

把本模板的变量填完整后，投递到一个全新 Codex 对话。每次只投递一个 Batch；此模板不会自动创建/启动任务。模型设为 gpt-5.6-terra，reasoning effort 设为 max。

## 调度者填写（不得保留占位符）

- REPO_ROOT：{{目标仓库绝对路径；不是本次审查临时目录}}
- TARGET_BATCH_ID：{{BATCH-xx}}
- INTEGRATION_BRANCH：integration/covenia-b
- INTEGRATION_SHA：{{所有依赖已验收且已集成的确切 SHA}}
- EXECUTION_BRANCH / WORKTREE：{{本批独立分支与绝对工作树路径}}
- CONTRACT_VERSION：{{契约锁版本；01/02 可为基线冻结 SHA}}
- PLAN_SHA256：{{本次 MASTER_PLAN.md 与 batches.json 哈希}}
- DEPENDENCY_RECEIPTS：{{直接依赖的实现报告、独立 PASS、集成 SHA 与集成后复测证据}}
- EXTERNAL_GATE_RECEIPTS：{{本 Batch 所需外部门 ACCEPTED 记录；无则明确 []}}
- RUN_DIR：{{本批独占运行目录绝对路径，默认 reports/batches/BATCH-xx/runtime}}
- RESOURCE_LOCKS：{{已取得的模型/HTTP设备锁；不需要则 []}}
- BACKEND_BASE_URL / C_BASE_URL：{{HTTP/live批必填；普通模块填 NOT_REQUIRED}}
- MODEL/IMAGE ENV MANIFEST：{{已脱敏环境清单路径；秘密仅在环境变量}}
- CURRENT_BATCH_PACKAGE：读取 MASTER_PLAN.md 对应完整包与 batches.json 对应条目；两者不一致即停止请协调者修计划。

## 给执行者的任务

你是 Covenia B 线单批执行程序。只完成 TARGET_BATCH_ID 的一个明确结果，不开发整个后端，不顺手做下一批。该 Batch 的目标、依赖、输入、白名单、测试命令、验收标准、输出、回滚与负责人以计划为准。任何更高优先级指令仍须遵守。

### 1. 开始前的只读检查

1. 核对 REPO_ROOT、git rev-parse --show-toplevel、git status --short、当前 branch/HEAD；读取适用 AGENTS.md。保存初始状态，不 reset、stash 或清理用户改动。
2. 确认 INTEGRATION_SHA 与本工作树基线正确；所有依赖 code commits 在该基线祖先链里，依赖产物文件/hash、独立 PASS、集成后复测均可读取。未验收分支和未提交代码不算依赖。
3. 先读取本 Batch 指定输入及所有直接依赖的交接，再按以下优先级检查规范：最新已批准 PRODUCT-FREEZE.md → docs/05-api-and-ui.md → schemas/ → docs/03-firewall-rules.md → docs/04-responsibility-loop.md → docs/08-idempotency-and-ordering.md → fixtures/ground-truth.json。
4. BATCH-01 的 proposed decisions 不等于 X-FREEZE。对外部批准必须核对负责人、原始批准来源、最终选择及文件版本，不得自己填写 APPROVED。
5. 检查 Batch 要求的命令是由哪个前置 Batch 提供。命令缺失/关键资产缺失/服务不可用不能标 PASS；缺失外部门仅阻塞当前相关工作，不虚构图片或标签。
6. 初始工作树有重叠改动时停止，保留用户内容；无关脏文件只读记录。不能擅自换错误基线求测试通过。

### 2. 实施边界

- 只修改 allowed_paths，forbidden_paths 优先；未列路径一律不改。本批报告目录可写，但 VERIFICATION_REPORT.json 仅独立验收者写。
- B 不代改 frontend/；A 的 Excel/图片/GT/原始 fixtures 只读。公共 Schema/ports 变化仅对应所有权 Batch 可做且需重验消费者。
- 仅四个业务接口，绝不新增查询、重置、通知或分配接口；没有生产系统接入、自动退款赔偿补发、医疗诊断、BI 或新售后场景。
- AI 仅候选事实；由服务端验证来源、编译承诺、聚合证据、构建责任、执行统一规则。不得按 S00001、DEMO_001、DEMO_002、DEMO_003 或图片文件名写分支。案例 ID 可在数据目录/测试中作为映射键，不得进入规则、状态构建器、Prompt 捷径。
- 不把已标注 GT、最终证据/责任/激活/规则结论送模型；不把 C mockApi/示例响应移植为后端事实。
- 不用关闭 PII、放宽 Schema、取消时序、删掉测试或无标识缓存来换绿灯。保持单事务幂等与既有人工/事件历史。
- 测试数据/模型调用必须使用本批 RUN_DIR 与资源锁；不共享 SQLite、端口或同一可变 Demo 案件。无授权不购买算力、读取无关秘密、push 或操作 PR。
- 预计执行超过 6 小时、需要共享文件变更或出现新语义选择时，交回主规划拆批/裁决；不在本对话默默扩围。若缺的是纯实施细节，作保守选择并记报告。

### 3. 测试、复查与提交

1. 按实施步骤实现本批结果，并把指定测试命令真实跑完。测试/脚本属于当前 Batch 时必须先创建，不得仅在报告中列出“将运行”。
2. 报告每条命令的实际 cwd、解释器/依赖版本、退出码、耗时、测试数量及输出路径；关键 skip/xfail 不能算通过。
3. live 必须真实 Qwen+图像且禁用缓存；HTTP/e2e 必须实际访问服务。明确区分替身单测、真实推理、缓存灾备。API key、原始敏感信息不进入日志/报告。
4. 负控制：内层 mutant 必须在目标安全断言失败，外层驱动器检查预期失败并 exit 0；记录还原后的源码/环境 hash。任意崩溃不算验证成功。
5. 运行 git diff --check、复查 diff 与 allowed/forbidden 范围，检查新增依赖/配置是否属于本批。不顺手重构其他模块。
6. 精确 git add 本批文件，提交代码/测试并记录 code_commits；再写报告并提交报告。只提交当前 Batch，不推远程、不启动下一 Batch。若无法提交，报告 BLOCKED/PARTIAL 与原因，不声称“已提交”。

### 4. 必留交接产物

写入 reports/batches/{{TARGET_BATCH_ID}}/：

- IMPLEMENTATION_REPORT.json：下述结构；不是独立验收 PASS。
- IMPLEMENTATION_REPORT.md：简述完成、未完成、测试、风险、是否影响 Hero。
- commands.json：命令与退出码/耗时/证据文件对应。
- 本 Batch required_outputs 中实施方负责的其他产物、脱敏日志与 SHA256。
- 不写/覆盖 VERIFICATION_REPORT.json，不改 batches.json 的状态或依赖自解锁。

报告 code_commits 指向业务/测试提交，不包含报告自己的未知 SHA；报告提交 SHA 由协调者从 git 记录。纯规划/文档 Batch 也使用同一报告，按实际产物描述，不伪称业务实现。

```json
{
  "report_version": "1.0",
  "batch_id": "BATCH-xx",
  "result": "IMPLEMENTED",
  "repo_root": "<absolute path>",
  "branch": "<batch branch>",
  "base_integration_sha": "<sha>",
  "contract_version": "<version or baseline freeze sha>",
  "plan_sha256": "<hash>",
  "initial_worktree": [],
  "dependency_receipts": [
    {"batch_id": "BATCH-yy", "verdict": "PASS", "integration_sha": "<sha>", "artifact_hashes": {}}
  ],
  "external_gate_receipts": [],
  "code_commits": ["<sha>"],
  "changed_files": [],
  "scope_check": {"within_allowlist": true, "forbidden_changes": []},
  "acceptance_results": [
    {"criterion": "<exact criterion>", "status": "EVIDENCED", "evidence": ["<path>"]}
  ],
  "test_results": [
    {"command": "<actual command>", "cwd": "<absolute path>", "exit_code": 0, "duration_seconds": 0, "mode": "UNIT", "evidence": "<path>"}
  ],
  "artifacts": [
    {"path": "<repo-relative path>", "sha256": "<hash>", "classification": "REDACTED"}
  ],
  "model_runs": [],
  "not_completed": [],
  "risks": [],
  "rollback": {"code": "<precise revert plan>", "runtime_state": "<backup and recovery or NOT_APPLICABLE>"},
  "handoff": {"interfaces": [], "input_versions": {}, "reproduction": [], "remaining_gates": []},
  "next_batch_started": false
}
```

result 只能 IMPLEMENTED / PARTIAL / BLOCKED；缺测、未提交或关键门未满足不能填 IMPLEMENTED。test mode 用 UNIT / PROTOCOL_DOUBLE / LIVE / HTTP / E2E / MUTATION，不能把替身写 LIVE。acceptance status 为 EVIDENCED / NOT_MET / BLOCKED。
最终回答返回结构化 IMPLEMENTATION_REPORT 摘要、报告路径、提交 SHA、实际测试结果和剩余阻塞。不要自行开始下一批。

