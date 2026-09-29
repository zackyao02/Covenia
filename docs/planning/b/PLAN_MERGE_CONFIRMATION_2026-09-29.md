# 计划合并依据确认与续跑上限裁定

日期：2026-09-29（Asia/Shanghai）。角色：主规划。性质：计划合并交接材料，不是合并回执、产品补签、独立验收结果或任务启动授权。

三项确认：本次所指的绝对隔离 venv、条件性锁文件追加、只读计划重载，是本任务中用户已明确授权、尚未集成的治理修订；X-A-FIXTURES 历史交接正文保留并标注“已完成 / ACCEPTED”；X-A-MAPPING 由集成协调者补做既有接收的登记回执，审查方独立复核，不要求产品负责人重新补签。

本轮只新增本文件与 `RESUME_RECEIPT.template.json`。两份 MASTER_PLAN.md / batches.json、审查方依据表、批准原文、业务代码、依赖、运行台账及历史回执均不改动；不执行提交、合并、推送或续跑。

## 1. 环境治理的授权性质

授权依据是本任务中的用户明确指令，而非仅凭文件存在推定：

- 要求所有批次使用本批隔离 venv 的绝对解释器路径，禁止裸用 Python；新增第三方依赖“只增不改 + 钉版本 + 留证”；交付前运行 pip check。
- 要求每个调度周期开始重新计算 plan_sha256，不一致即重载；状态写入失败不得阻止只读重载。

因此，这三项及其实现所必需的条件性文件互斥，可作为“已授权未集成”的计划规则合入，不是未批准草案。以工作区 §5.5、§5.3-11、environment_policy、plan_reload 及各批配套命令/条件锁为来源；不能据此宣称调度器已实现或独立验收已通过。

这不是给 PRODUCT-FREEZE 或 b-decisions.json 追加批准，也不为来源不明的其他条款概括补签。不追填批准日期、签名或历史批准记录。只读重载允许更新内存视图，不授权在无法可靠记录派发/锁/次数时继续派发。

## 2. X-A-FIXTURES：保留历史，纠正当前状态

合并时，§4.1 标注“已完成 / ACCEPTED（2026-09-13，原接收记录：产品负责人）”，保留 D07/T01 的原交接范围、三处变更和历史条件；将“仍为 MISSING、等待交付”等语句明确标成当时状态，不再作为当前阻塞。

依据：集成提交 `78f7754233ed430254043f8548ccb2e08eebbd13` 中的 `reports/batches/X-A-FIXTURES/GATE_ACCEPTANCE_RECEIPT.json`。本次在 HEAD `69d78e88c5c2ee0f7cd25c7a04c0eaa8223d0f51` 读取提交 blob，确认 1950 B、SHA256 `8A6371CBA6B651C45D252FA6D4B77C96D61F04740A46A603C75FA3CE7DE11CE9`。

该回执只关闭 X-A-FIXTURES，不替代任何 Batch 的独立验收/集成，不扩大到图片注入对照、Ground Truth 或留出集门。全部 34 个 B 批次继续禁止修改 fixtures/**。

## 3. X-A-MAPPING：依据表遗漏了既有接收链

“没有同名 GATE_ACCEPTANCE_RECEIPT.json”属实；“只有三份文件存在、没有接收依据”不成立。本次找到并核对：

1. `reports/batches/X-A-MAPPING/ARCHIVE_REPORT.json` 已随 `90c83590ad4955e24d6d859c1281b42f53686785` 集成，明确记载 gate_status=ACCEPTED、delivery_owner=产品负责人、delivery_date=2026-09-13。
2. 外部协调回执 `C:/Users/WONG Tsun Ming/covenia-orchestration/runs/covenia-b-20260910-01/integration-receipts/X-A-MAPPING.json` 记载该集成提交、原始 blob 哈希及 SUCCESS。
3. `reports/batches/BATCH-05/VERIFICATION_REPORT.json` 的 external_gate_checks 已独立核验此门并给 PASS，且明确指出计划中的 MISSING 是登记滞后。该报告随 `dbedd4e9f985911cc89b140d1a129586a09fbdf4` 集成；BATCH-05 集成回执另有烟测证据。
4. 本次重新计算当前提交的 data-mapping.json 原始 blob：74175 B，SHA256 `8D76EEAD5757D5618B57107B3725FCF5543D96F0C9FECF6EDEA5FDDD210B5538`，与既有接收链相同。本次只核对记录和字节，未冒充重跑 BATCH-05。

裁定：合并时可将 X-A-MAPPING 的登记纠正为 ACCEPTED，依据是上述既有接收、独立核验及集成证据，不是文件大小/存在性。cases-manifest 与 images-manifest 各有自己的门，不能用三文件入库相互替代验收。

补登记职责：

- 集成协调者出具 `reports/batches/X-A-MAPPING/GATE_ACCEPTANCE_RECEIPT.json`，性质为“既有接收的协调登记”，由真实登记者填写 recorded_by / recorded_at；审查方独立核对证据与字段。
- 引用 source_acceptance_record、source_acceptance_date、integration_commit、独立报告及原始 blob 哈希；保留历史报告中的 delivery_owner 原字段，不把它改称新的 accepted_by 签名。
- 若模板要求 accepted_by，只能引用可核实的原始批准来源；不能为了补齐格式直接填“产品负责人”。产品负责人 Zack 只对新发现冲突或新增范围作新裁定，不重复批准本门，不倒签日期。
- 这是协调者的规划/登记工作，不交给任意编号 B 批次越权完成，也不改变 BATCH-05 已有实现、独立验收和集成记录。本轮尚未签发该回执。

## 4. 对合并依据表的三处必要修正

### 4.1 A2：工作区并非没有逐批验证命令

本次解析两份 batches.json：工作区 343 条 acceptance_commands，集成版 142 条；两边全部 34 批均有命令。统一解释器前缀后，集成版只有 4 条安装/构建命令未逐字匹配工作区，对应工作区增加的 --no-deps、--no-build-isolation、--no-isolation 环境约束。

合并口径：保留仓库既有测试对象、参数、检查目标和后续已验收修订；统一采用工作区绝对 venv、导入预检、锁定安装及 pip check，不用仓库旧命令覆盖治理条款。不能用“工作区没有命令”作为删掉其命令的理由。

### 4.2 V4：增量是语义不丢失，不是 diff 删除行数为零

状态纠正、解释器替换和历史标注会产生必要的替换行；git show --stat 不能证明无语义损失。V4 应检查完整差异与结构化对照，确认既有有效规则、测试目标、权限和历史证据未丢失，只有已列明的纠正与增补。

同理，allowed_paths 是严格超集不意味着无条件写权限。依赖锁继续受条件性独占锁与只增不改约束；BATCH-01 的批准归档仅可原样复制，同哈希为 NO_OP；BATCH-11 的 docs/02-ai-extraction.md 仅限本批候选抽取/Prompt 文档同步，不允许修改产品冻结、最终决策权或其他规范。

### 4.3 forbidden_paths 也有漂移，不能只合允许清单

本次静态自检最初假设两边都已显式禁止 fixtures/**，被 BATCH-01 的比对失败纠正。随后全量核对确认：工作区 34/34 批均含该通配禁止项，仓库版 0/34 含该通配项，后者仍列出 ground-truth.json、demo-cases.json 等具体禁止文件。全部34批的禁止清单差异均为工作区多 fixtures/**，仓库独有禁止项为0。

这不表示仓库版授权了修改其他夹具（允许清单仍约束写入），但证明“仅 allowed_paths 存在实质漂移”不完整。合并时须把工作区完整 fixtures/** 禁令一并带入所有批次，不能只保留部分文件禁令；不修改任何夹具或改变 A/B 职责。

## 5. 合并后独立检查的确定口径

| 检查 | 口径 |
| --- | --- |
| V1 | 34 个 ID 与 depends_on 逐项不变；本次只读预检查为 34/34 相同，不冒充合并后结果。 |
| V2 | 两份计划及实际派发包的 allowed_paths 对齐到本次列明的增量集合；31 个标准批、BATCH-01、BATCH-11、BATCH-02 的差异与依据表一致，仓库独有项为 0；同时核对全部34批 forbidden_paths，合入工作区 fixtures/** 禁令，保留条件锁和职责限制。 |
| V3 | X-FREEZE=ACCEPTED 引用原批准；X-A-FIXTURES=ACCEPTED 引用门回执；X-A-MAPPING=ACCEPTED 引用本文件第3节的既有接收链/补登记；X-A-IMAGES 保留原 ACCEPTED 与 injection_pairs=NOT_STARTED 等未完成子项，不扩张接收范围。 |
| V4 | 完整 diff + 结构化语义对照证明保留两边有效内容；不要求机械的零删除行，不以 --stat 代替复核。 |

X-FREEZE 本次提交 blob SHA256 仍为 `3ACAD4A113EB595BCED29025AF884A4C5EA2835E90E38D0E897298F91DB371DA`。准确称谓为“13 条裁决记录：8 APPROVED + 5 COVERED_BY_FREEZE，另有 T01”，不是13项新批准。批准原文字节不变。

合并后由协调者记录真实提交及两文件各自的 Git blob SHA256，审查方独立复算；明确唯一执行计划来源并检查派发包，不使用 CRLF 工作副本 hash 代替提交 blob。本轮没有合并后 plan_sha256，不能将当前旧提交 hash 冒充新值。

## 6. BATCH-08 / BATCH-09：达到 2/2 后转人工

选择 **(b) 转人工决断**，不提高上限，不开放第三次自动续跑。

已读取两张 `BATCH-08-RESUME-20260929.json` / `BATCH-09-RESUME-20260929.json`：resume_attempt_in_batch=2、resume_limit_per_batch=2；两者均写明禁止第三次自动续跑。它们同时记载 pending_init、额度恢复时间 NOT_OBSERVABLE，不能由此推断任务已成功恢复或当前已再次中断。

若再次中断或第二次续跑确认不能推进：

1. 保留原工作树、未提交内容、历史回执与累计次数；不通过重启、换线程、换阶段或重载计划清零。
2. 转人工决断队列，由 Zack 或有可核实授权的具名委托人决定等待、止损或一次性人工恢复。不能自动生成该授权。
3. 一次性人工恢复须记录额度恢复/可用性证据、原任务已停止及无并发实例、当前计划/依赖/工作树/锁复核、同任务同阶段同目标/写路径，以及可持久化的唯一派发记录；授权只消费一次。仅有“稍后重试”或 pending_init 不构成额度恢复证据。
4. 人工恢复另记 MANUAL_ONE_TIME，不提高自动上限、不覆盖历史次数，不消费或重置产品缺陷修复计数；产品测试失败仍走原修复门，不能伪装额度中断。
5. 状态不可写仍可只读重载计划，但不得无记账恢复执行。保留 auto_start_next_batch=false，不能借本裁定开启新批。

配套规划模板为 `docs/planning/b/RESUME_RECEIPT.template.json`。所有证据与人名默认空值，dispatch_permitted=false；不是可执行授权，不修改两张已有回执。本轮未部署调度器行为、未发起恢复调用。

## 7. 本轮验证与恢复边界

只读检查覆盖：集成 HEAD/工作树、34批依赖与允许/禁止权限差异、命令清单、批准及门产物的提交 blob 哈希、X-A-MAPPING 接收链、08/09 续跑回执。新模板通过 JSON 解析与默认不派发检查；两份计划及原批准文件哈希未变。检查不把当前已知的 forbidden_paths 漂移伪装成一致；没有运行或重新验收业务测试。

若后续独立复核发现本裁定的依据不成立，仅阻塞受影响的合并项/派发，不改写历史批准、回执或测试结果。修订本规划材料须保留变更出处；本轮没有代码或运行状态需要回滚。
