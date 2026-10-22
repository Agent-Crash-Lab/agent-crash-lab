"""Opt-in local QA regression. Uses demo accounts; never bypasses approval or budget.

Run from repository root. --llm enables paid QA generation; reference targets are unchanged.
Full evidence is written under ignored artifacts/local-runs, never to Git.
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--types",
        nargs="+",
        choices=["PURCHASE", "PRODUCTION", "QUALITY"],
        default=["PURCHASE", "PRODUCTION", "QUALITY"],
    )
    parser.add_argument("--llm", action="store_true")
    parser.add_argument(
        "--approve", action="store_true", help="Use the configured demo approver"
    )
    parser.add_argument("--follow-up", action="store_true")
    args = parser.parse_args()
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key] = value.strip().strip('"').strip("'")
    base = "http://127.0.0.1:" + env.get("FRONTEND_PORT", "5173") + "/api"
    folder = ROOT / "artifacts/local-runs/qa-regression" / str(time.time_ns())
    folder.mkdir(parents=True)

    def api(path, body=None, token=None):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": "Bearer " + token} if token else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=190) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                code = json.load(exc).get("error", {}).get("code", "HTTP_ERROR")
            except (ValueError, AttributeError):
                code = "HTTP_ERROR"
            raise RuntimeError(f"{exc.code} {code}") from None

    password = env.get("DEMO_USER_PASSWORD", "crashlab")
    requester = api("/auth/login", {"user_id": "requester-01", "password": password})[
        "access_token"
    ]
    approver = (
        api("/auth/login", {"user_id": "approver-01", "password": password})[
            "access_token"
        ]
        if args.approve
        else None
    )

    def save(name, data):
        (folder / (name + ".json")).write_text(
            json.dumps(data, ensure_ascii=False, indent=2)
        )

    def wait_run(run_id):
        deadline = time.monotonic() + (90 if args.approve else 330)
        decided = False
        while time.monotonic() < deadline:
            run = api("/runs/" + run_id, token=requester)
            if run["status"] == "WAITING_APPROVAL" and approver and not decided:
                approval = run["approval_request"]
                decision = (
                    run["qa_case"]["simulation"]["approval_decision"] or "APPROVED"
                )
                prefix = "/qa" if run["manifest"].get("state_store") else ""
                api(
                    prefix + "/runs/" + run_id + "/approval",
                    {
                        **{
                            k: approval[k]
                            for k in ("approval_request_id", "payload_hash")
                        },
                        "decision": decision,
                    },
                    approver,
                )
                decided = True
            if (
                run["status"] in {"COMPLETED", "ERROR"}
                and run["investigation"]["status"] != "RUNNING"
            ):
                save(run_id, run)
                print(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "type": run["qa_report"]["target"]["type"],
                            "conclusion": run["qa_report"]["conclusion"],
                            "checks": run["summary"],
                            "measured": run["agent"].get("measured"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                return run
            time.sleep(0.15)
        raise TimeoutError(
            "Inspect existing run " + run_id + "; do not repeat ambiguous writes"
        )

    plans, runs, errors = [], [], []
    for kind in args.types:
        reference = api("/qa/target?target_type=" + kind, token=requester)
        try:
            plan = api(
                "/qa/design",
                {**reference, "generation_mode": "llm" if args.llm else "offline"},
                requester,
            )
        except RuntimeError as exc:
            errors.append({"type": kind, "error": str(exc)})
            print(json.dumps(errors[-1]), flush=True)
            continue
        plans.append(plan)
        save(kind + "-plan", plan)
        proposals = [c for c in plan["cases"] if c.get("design_basis")]
        print(
            json.dumps(
                {
                    "type": kind,
                    "plan_id": plan["plan_id"],
                    "proposals": len(proposals),
                    "ready": sum(
                        c["execution"]["status"] == "READY" for c in proposals
                    ),
                    "repair": {
                        k: plan["design"].get("repair", {}).get(k)
                        for k in ("attempts", "status")
                    },
                    "usage": plan["design"].get("llm_usage"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if not any(c["execution"]["status"] == "READY" for c in proposals):
            errors.append({"type": kind, "error": "NO_EXECUTABLE_PROPOSALS"})
        selected = set()
        for case in proposals:
            if case["execution"]["status"] != "READY":
                continue
            control = case.get("evaluation_strategy", {}).get("control_case_id")
            for case_id in (control, case["case_id"]):
                if not case_id or case_id in selected:
                    continue
                selected.add(case_id)
                started = api(
                    "/runs",
                    {"plan_id": plan["plan_id"], "case_id": case_id, "system_id": "B1"},
                    requester,
                )
                runs.append(wait_run(started["run_id"]))
    if args.follow_up:
        # B0 intentionally omits server idempotency in the local sandbox, to expose a finding.
        candidate = next(
            (
                (p, c)
                for p in plans
                for c in p["cases"]
                if c.get("design_basis")
                and c["execution"]["status"] == "READY"
                and c["simulation"].get("fault")
            ),
            None,
        )
        if candidate:
            plan, case = candidate
            source = wait_run(
                api(
                    "/runs",
                    {
                        "plan_id": plan["plan_id"],
                        "case_id": case["case_id"],
                        "system_id": "B0",
                    },
                    requester,
                )["run_id"]
            )
            runs.append(source)
            batch = api("/qa/runs/" + source["run_id"] + "/follow-up", {}, requester)
            again = api("/qa/runs/" + source["run_id"] + "/follow-up", {}, requester)
            assert batch["batch_id"] == again["batch_id"]
            deadline = time.monotonic() + 180
            seen = set()
            while batch["status"] in {"RUNNING", "WAITING_APPROVAL", "STOPPING"}:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Inspect existing batch " + batch["batch_id"])
                run_id = batch.get("active_run_id")
                if run_id and run_id not in seen:
                    seen.add(run_id)
                    runs.append(wait_run(run_id))
                time.sleep(0.15)
                batch = api("/qa/batches/" + batch["batch_id"], token=requester)
            save("follow-up", batch)
            assert (
                batch["source_run_id"] == source["run_id"] and len(batch["slots"]) == 2
            )
            print(
                json.dumps(
                    {
                        "follow_up_batch": batch["batch_id"],
                        "source_run_id": source["run_id"],
                        "status": batch["status"],
                        "slots": [s["status"] for s in batch["slots"]],
                    }
                ),
                flush=True,
            )
        else:
            errors.append(
                {"stage": "follow_up", "error": "NO_RESPONSE_LOSS_CASE_FOR_FOLLOW_UP"}
            )
    save(
        "summary",
        {
            "llm_generation": args.llm,
            "reference_target_mode": env.get("AGENT_MODEL_MODE", "offline"),
            "plan_ids": [p["plan_id"] for p in plans],
            "run_ids": [r["run_id"] for r in runs],
            "errors": errors,
        },
    )
    print("Evidence: " + str(folder), flush=True)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
