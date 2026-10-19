"""Print each archived V10a attempt and the quantitative targets (no network)."""
import json
import os
import tempfile
from pathlib import Path
import sqlite3

from metrics import history_issues


def summarize(directory):
    rows = []
    connection = sqlite3.connect((directory.parent / "eval.db").as_uri() + "?mode=ro", uri=True)
    for path in sorted(directory.glob("result_*_agent_*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        metrics = row["metrics"]
        states = [json.loads(item[0]) for item in connection.execute(
            "SELECT state FROM agent_delegations WHERE run_id=?", (row["run_id"],))]
        history = history_issues(states)
        rows.append({"case": row["case"], "run_id": row["run_id"], "status": row["status"],
                     "seconds": row["elapsed_sec"], "llm": metrics["llm"], "vision": metrics["vision"],
                     "credits": row["spent_total"], "agents": [d["agent"] for d in row["delegations"]],
                     "nodes": row["plan_metrics"]["node_count"], "choice": row["plan_metrics"]["choice_count"],
                     "animation_uses_selection": row["plan_metrics"]["animation_uses_selection"],
                     "compile_codes": sorted(set(metrics["compile_issue_codes"] + history["history_compile_issue_codes"])),
                     "tool_failures": history["tool_failures"],
                     "final_compile_codes": row["final_compile_issue_codes"], "error": row["error"]})
    connection.close()
    return rows


if __name__ == "__main__":
    work = Path(os.environ.get("EVAL_WORK_DIR") or Path(tempfile.gettempdir()) / "cinecrew-v10")
    print(json.dumps(summarize(work / "results"), ensure_ascii=False, indent=2))
