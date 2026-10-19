import json
import sys
from pathlib import Path

import tempfile
HERE = Path(tempfile.gettempdir()) / "cinecrew_v3_eval" / "results"
V2 = Path(tempfile.gettempdir()) / "cinecrew_v2_eval" / "results"
for case in sys.argv[1:]:
    r = json.loads((HERE / f"result_{case}.json").read_text(encoding="utf-8"))
    print("=" * 20, case, r["status"], f"{r['elapsed_sec']}s", "spent", r["spent_total"], "experimental", r.get("experimental"))
    print("questions:", r.get("pending_questions"), "notes:", r.get("notes"))
    for d in r["delegations"]:
        print(f"  deleg#{d['id']} parent={d['parent']} {d['agent']} {d['status']} llm={d['llm_calls']} limit={d['credits_limit']} out={d['output_kind']} err={json.dumps(d['error'], ensure_ascii=False)[:160] if d['error'] else ''}")
        print("     task:", d["task"][:150])
    print("ledger:", json.dumps({k: (v["calls"], round(v["credits"], 2), v["statuses"]) for k, v in r["ledger_by_tool"].items()}, ensure_ascii=False))
    print("seq:", " ".join(s.split(":", 1)[0][0] + ":" + (s.rsplit(":", 1)[1] or "llm") for s in r["tool_sequence"]))
    print("plan:", r.get("plan_title"), "| deliverables:", json.dumps(r.get("deliverables"), ensure_ascii=False))
    for n in r["plan_nodes"]:
        print(f"   - {n['id']} {n['tool']} model={n['model']} dur={n['duration']} gate={n['gate']} deps={n['deps']}")
        if n["prompt"]:
            print("       prompt:", n["prompt"][:120])
    est = r.get("estimates") or {}
    print("estimate total:", est.get("total_credits", est.get("total")), "| issues:", r.get("plan_issues"), "| error:", r.get("error"))
