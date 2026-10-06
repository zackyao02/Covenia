"""Conservative keyword review for consumer-facing reply drafts."""
import re


def contains_unsupported_fulfillment_guarantee(text: str) -> bool:
    """Block promises of an outcome, while allowing checks on existing orders."""
    t = re.sub(r"\s+", "", text).lower()
    outcome = r"(?:换货|补发|重新发货|退款|退货|送达|到货|寄出)"
    guarantee = r"(?:保证|承诺|一定|确保|最晚)"
    direct_action = r"(?:安排|办理|直接)?" + outcome
    for clause in re.split(r"[，。；;！!？?]|但|不过|然而", t):
        clause = re.sub(r"(?:不能|无法|不敢|不会|不作|不做|不)(?:向您)?(?:保证|承诺|确保).{0,12}" + outcome, "", clause)
        clause = re.sub(r"(?:不会|不能|无法|不)(?:为您)?" + direct_action, "", clause)
        if (
            re.search(guarantee + r".{0,10}" + outcome, clause)
            or re.search(outcome + r".{0,10}" + guarantee, clause)
            or re.search(r"(?:会|将)(?:在(?:今天|明天|\d+小时内|\d+天内))?(?:为您)?" + direct_action, clause)
            or re.search(r"(?:会为您|将为您)" + direct_action, clause)
        ):
            return True
    return False


def reply_conflict_with_state(state: dict, text: str) -> str | None:
    """Block requests for evidence already on file and completion claims ahead of facts."""
    t = re.sub(r"\s+", "", text).lower()
    clauses = re.split(r"[，。；;！!？?]|但|不过|然而|同时|另外", t)
    negative = r"(?:不需要|无需|不用|不必|不再|不要|请勿|不会|不能|无法|尚未|还没|未|没|别)"
    if state.get("evidence_status") == "VALID":
        evidence_terms = r"(?:照片|图片|凭证|证据|材料|近照)"
        repeat_request = r"(?:再|重新|再次|重复|补充|补拍|重传|再发|再拍|重新上传|重新发送|再次提交|再提交|补交|补发).{0,12}" + evidence_terms
        reverse_request = evidence_terms + r".{0,10}(?:重传|再发|补发|重新上传|再拍|重复提交|重新提交)"
        for clause in clauses:
            if re.search(repeat_request, clause) or re.search(reverse_request, clause):
                if not re.search(negative + r".{0,12}(?:再|重新|再次|重复|补充|补拍|重传|再发|再拍|上传|发送|提交|提供|拍)", clause):
                    return "当前材料已经收到，不能要求消费者重复提交。"

    obligation = state.get("open_obligation") or {}
    delivered = obligation.get("status") == "COMPLETED" or obligation.get("milestone") == "DELIVERED" or state.get("case_status") in ("RESOLVED", "CLOSED")
    has_open_service = bool(obligation or state.get("active_commitments")) and not delivered
    if has_open_service:
        fulfillment_claim = r"(?:换货件|补发件|包裹|快递|商品|物流).{0,12}(?:已经|已|成功)?(?:送达|送到|到货|签收|收到了)"
        resolution_claim = r"(?:问题|服务|本次处理).{0,8}(?:已经|已)?(?:解决|完成)|(?:不用|无需|不必).{0,5}再跟进"
        for clause in clauses:
            if re.search(r"(?:吗|么|没有|呢|是否)$", clause):
                continue
            if re.search(fulfillment_claim, clause) and not re.search(negative + r".{0,10}(?:送达|送到|到货|签收)", clause):
                return "当前履约记录尚未显示送达，不能声称换货件已经送达。"
            if re.search(resolution_claim, clause) and not re.search(negative + r".{0,10}(?:解决|完成|跟进)", clause):
                return "当前仍有服务事项待处理，不能把问题表述为已解决。"
    return None


def assess_draft(text: str) -> dict:
    t = re.sub(r"\s+", "", text).lower()
    clauses = re.split(r"[，。；;！!？?]|但|不过|然而|同时|另外|并请", t)
    evidence = any(
        re.search(r"(请|麻烦|烦请|需要您|请您|您只要|只需|只要).{0,20}(提供|补充|补|上传|发送|拍摄|拍|提交).{0,20}(照片|图片|凭证|证据|材料|近照)", clause)
        and not re.search(r"(无需|不需要|不用|不必|不再|无需再|不用再).{0,16}(提供|补充|补|上传|发送|拍摄|拍|提交|重复)", clause)
        for clause in clauses
    )
    progress = bool(re.search(r"(主动更新|反馈进展|告知进度|跟进进度|查询.{0,8}进度|帮您.{0,6}查询|核查.{0,12}进度|核实.{0,12}进度|查询.{0,8}状态|核实.{0,8}状态|核实.{0,16}揽收)", t))
    close = any(
        re.search(r"(关闭工单|结案|问题已解决|本次服务已完成)", clause)
        and not re.search(r"(?:不|未|尚未|不能|不会|暂不|不要).{0,6}(?:关闭工单|结案|解决|完成)", clause)
        for clause in clauses
    )
    timed_update = bool(re.search(r"今天|明天|\d{1,2}[:：点时]|\d+小时内|\d+天内|\d+个工作日内", t) and re.search(r"更新|告知|反馈|联系", t))
    commitment = contains_unsupported_fulfillment_guarantee(text) or bool(
        re.search(r"(?:我|我们|品牌).{0,6}(?:会|将).{0,8}(?:在|于).{0,8}(?:更新|告知|反馈|联系)", t)
    ) or timed_update
    hits = [evidence, progress, close, commitment]
    names = ["EVIDENCE_REQUEST", "PROGRESS_UPDATE", "CLOSE_CASE", "NEW_COMMITMENT"]
    found = [name for name, hit in zip(names, hits) if hit]
    if len(found) == 1:
        kind = found[0]
        confirmation = kind in ("NEW_COMMITMENT", "CLOSE_CASE")
        explanation = "关键词规则识别到单一回复类别；请结合上下文核验。"
    elif not found:
        kind, confirmation = "UNCLASSIFIED", True
        explanation = "未匹配到明确类别，需人工确认。"
    else:
        kind, confirmation = "UNCLASSIFIED", True
        explanation = "回复包含多个类别或意图不明确，需人工确认。"
    detected = [name for name, hit in zip(names, hits) if hit]
    return {"kind": kind, "requires_confirmation": confirmation, "explanation": explanation, "evaluated_text": text, "_detected_actions": detected}
