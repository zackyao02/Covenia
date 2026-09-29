# 计划合并交接报告｜2026-09-29

状态：IMPLEMENTED / PENDING_INDEPENDENT_REVIEW。本报告由实现/协调登记方出具，不是独立 V1–V5 PASS，不授权解冻或派发。

## 交付范围

- 按 PLAN_MERGE_BASIS.md 第3版及主规划确认合并 MASTER_PLAN.md / batches.json，根目录与集成工作树同正文；仓库合并前基线 69d78e88c5c2ee0f7cd25c7a04c0eaa8223d0f51。
- 仓库 §5.1.1 两条常设规则完整保留；工作区 §5.5、绝对隔离venv、条件性锁追加/独占锁/失效保护、只读重载完整保留。
- 34批对象与合并前工作区 batches 数组相同：集合、depends_on、业务职责、允许/禁止路径、可执行命令、静态批状态均未变；每批含 fixtures/** 禁令。根目录与仓库计划同步为同一版本。
- X-FREEZE / X-A-FIXTURES / X-A-MAPPING / X-A-IMAGES 均登记 ACCEPTED；其他门与图片注入对照未完成子项不变。X-FREEZE原文仍为8 APPROVED + 5 COVERED_BY_FREEZE及T01，不增加批准。X-A-MAPPING仅依据既有接收链补登记，未填新的产品签名。
- §4.1 原交接正文完整保留，加“已完成 / ACCEPTED（2026-09-13）”及历史边界。旧“仍为MISSING”是历史描述，不是当前门状态。
- 未修改任何批准、夹具、业务代码、依赖锁、配置、运行状态、历史验收/集成回执；未推送、未开启或续跑任何Batch。未部署任何调度器能力。

## 命令并集及原文追溯

全量JSON口径为工作区343条、仓库142条，共485条来源记录；“77”保留为审查方依据表的原统计，不冒充JSON总数。COMMAND_UNION.json保存每条原文、批次、来源序号、环境适配规则及可执行列表位置。适配后142条仓库命令全部已有对应项，执行并集为343条，不因重复来源额外执行同一检查。

只适配已批准的绝对venv解释器与4条锁定安装/构建参数，未删除测试目标或验证职责。MASTER与JSON的34批可执行清单一致。不要执行来源映射中的旧裸命令。

MASTER第12节保留123条原仓库历史措辞/命令，只读、非执行；当前规则以第0–11节和batches.json为准。该存档使原文可追溯，但不能仅凭文字存在判定语义无损，独立审查仍须核对完整diff、当前规则与逐条映射。WORKSPACE_MASTER_PLAN.before.md / WORKSPACE_batches.before.json是工作区合并前文本快照；仓库原文从合并前commit读取。

## 自检证据

SELFCHECK.json：实现方最终静态自检25/25；PowerShell解析343/343；隔离venv最长路径156字符；pip check退出0；git diff --check退出0。包括两源DAG、完整batch对象、权限、命令来源覆盖/Markdown一致性、5.1.1/5.5正文、4.1历史保留、门接收链、批准字节不变等检查。未运行后端业务测试，未声称编号Batch通过验收。

首次镜像字节断言因根目录LF/工作树CRLF返回失败；已更正为正文一致校验，提交后另核对raw Git blob。未修改core.autocrlf；没有把工作副本hash登记成plan_sha256。SELFCHECK.json保留原因、检查脚本和执行命令，独立审查不得仅相信此报告。

## 独立审查与派发边界

审查方使用独立、短绝对VERIFY_RUN_DIR/venv，从根工作区运行既有 checks/verify_merge.py，指定 --repo work/repo2、--ref 本次真实提交SHA、--root 根工作区绝对路径；交付前同一绝对解释器运行 -m pip check。审查方检查器及 .plan-merge-baseline.json 均未修改。

复核V1–V5及完整diff，分别从本次提交内MASTER_PLAN.md / batches.json的原始blob字节计算SHA256并登记。提交号与提交blob哈希由最终交接消息/只读提交核验回执给出，避免在决定自身SHA的文件中伪造自引用提交号。

只有独立PASS与新hash登记完成后，协调者才可解除14/17/18的计划漂移阻塞。auto_start_next_batch仍为false，既有授权/依赖/锁仍须检查。此前scheduler-index.json / scheduler-packages含旧hash/行号，本次未更新或使用它们；协调者必须在派发前从已接收新计划重新生成或核对派发包，不可继续按旧包执行。此项不是运行态解冻已完成的声明。

## 失败恢复

独立复核FAIL时仅修本次规划合并差异并重新提交，保留批准、门接收及各Batch既有证据。需要撤销时由协调者在检查后继消费者后revert本次确切规划提交；根目录文本可据before快照恢复供核对，但旧登记不得覆盖真实接收事实。不得reset用户工作树、删除运行数据或清空续跑次数；未接收的旧/新计划均不得借回滚自动派发。

本次补登记路径：reports/batches/X-A-MAPPING/GATE_ACCEPTANCE_RECEIPT.json。recorded_by为真实的本次Codex协调登记者，历史delivery_owner按原字段引用，不改称新的accepted_by。
