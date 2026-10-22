"""Evidence-bound investigation experiments; no new target, policy or recursive dispatch."""


def recommendation(run, store, owner):
    if run.get("created_by") != owner or run.get("test_kind") != "SYSTEM":
        return {"status": "UNAVAILABLE", "reason": "본인이 실행한 제조업 시험만 연결합니다."}
    batch = store.get_batch(run["qa_batch_id"], owner) if run.get("qa_batch_id") else None
    if run.get("qa_parent_run_id") or (batch and batch.get("source_run_id")):
        return {
            "status": "UNAVAILABLE",
            "reason": "추가 조사 실험에서 다음 실험을 연쇄 생성하지 않습니다.",
        }
    if batch and batch["status"] in {"RUNNING", "WAITING_APPROVAL", "STOPPING"}:
        return {"status": "WAITING", "reason": "원래 실험 계획이 종료된 뒤 추가 실험을 제안합니다."}
    if (
        run.get("status") not in {"COMPLETED", "ERROR"}
        or run.get("investigation", {}).get("status") == "RUNNING"
    ):
        return {"status": "WAITING", "reason": "현재 실행과 조사가 끝난 뒤 제안합니다."}
    findings = [c for c in run.get("checks", []) if c["verdict"] != "PASS"]
    if not findings:
        return {
            "status": "NOT_REQUIRED",
            "reason": "현재 검사에서 추가 조사할 위반·관측 부족이 없습니다.",
        }
    plan_id = run.get("manifest", {}).get("qa_plan_id")
    plan = store.get_plan(plan_id, owner) if plan_id else None
    if not plan or plan.get("design", {}).get("version") not in {"3.0.0", "4.0.0"}:
        return {
            "status": "UNAVAILABLE",
            "reason": "근거와 반복 기준이 저장된 시험을 먼저 설계해 주세요.",
        }
    case_id = run["manifest"].get("qa_case_id")
    case = next((c for c in plan["cases"] if c["case_id"] == case_id), None)
    control_id = (case or {}).get("evaluation_strategy", {}).get("control_case_id")
    control = next((c for c in plan["cases"] if c["case_id"] == control_id), None)
    if not case or not control or any(c["execution"]["status"] != "READY" for c in (case, control)):
        return {
            "status": "UNAVAILABLE",
            "reason": "같은 입력으로 비교할 정상 대조 연결이 없습니다.",
        }
    report = run.get("investigation", {}).get("report") or {}
    return {
        "status": "READY",
        "method": "CODE_GROUNDED_INVESTIGATION",
        "source_run_id": run["run_id"],
        "plan_id": plan_id,
        "case_ids": [case_id],
        "systems": [run["system_id"]],
        "max_runs": 2,
        "question": "같은 업무 입력에서 정상 조건과 위험 조건의 결과가 달라지는가?",
        "reason": (
            "조사 기록과 미충족 검사를 바탕으로 정상 대조 1회와 원래 위험 조건 1회를 제안합니다."
        ),
        "evidence_ids": sorted({e for c in findings for e in c.get("evidence_ids", [])}),
        "rule_ids": sorted({c["rule_id"] for c in findings}),
        "investigator_suggested_tests": report.get("retest_scenario_ids", []),
        "control_case_id": control_id,
        "changes": "대조 시험에서만 오류·거절·업무 위험 조건을 제거합니다.",
        "requires_human_approval": True,
        "recursive_execution": False,
        "batch_id": run.get("follow_up_batch_id"),
    }
