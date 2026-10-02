"""Conservative keyword review for consumer-facing reply drafts."""
import re


def assess_draft(text: str) -> dict:
    t = re.sub(r"\s+", "", text).lower()
    clauses = re.split(r"[，。；;！!？?]|但|不过|然而|同时|另外|并请", t)
    evidence = any(
        re.search(r"(请|麻烦|烦请|需要您|请您).{0,20}(提供|补充|上传|发送|拍摄|提交).{0,20}(照片|图片|凭证|证据|材料|近照)", clause)
        and not re.search(r"(无需|不需要|不用|不必|不再|无需再|不用再).{0,16}(提供|补充|上传|发送|拍摄|提交|重复)", clause)
        for clause in clauses
    )
    progress = bool(re.search(r"(主动更新|反馈进展|告知进度|跟进进度|查询.{0,8}进度|帮您.{0,6}查询|核查.{0,12}进度|核实.{0,12}进度|查询.{0,8}状态|核实.{0,8}状态)", t))
    close = bool(re.search(r"(关闭工单|结案|问题已解决|本次服务已完成)", t))
    timed_update = bool(re.search(r"今天|明天|\d{1,2}[:：点时]|\d+小时内|\d+天内|\d+个工作日内", t) and re.search(r"更新|告知|反馈|联系", t))
    commitment = bool(re.search(r"(保证|承诺|一定会|确保|最晚|之前.{0,4}(送达|发出|完成)|.{0,12}(会|将).{0,12}(换货|退款|补发|送达))", t)) or timed_update
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
