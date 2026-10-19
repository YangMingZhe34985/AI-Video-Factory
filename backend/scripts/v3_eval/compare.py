import json
from pathlib import Path

import tempfile
HERE = Path(tempfile.gettempdir()) / "cinecrew_v3_eval" / "results"
V2 = Path(tempfile.gettempdir()) / "cinecrew_v2_eval" / "results"
CASES = ["c1_portrait", "c2_clip", "c3_story", "c4_vague", "c5_novel", "c6_constraint"]
print(f"{'case':14} | {'v3 status':22} {'s':>6} {'llm':>4} {'cr':>6} {'deleg':16} {'nodes':>5} | {'v2 status':20} {'s':>6} {'llm':>4} {'cr':>6}")
for case in CASES:
    v3 = json.loads((HERE / f"result_{case}.json").read_text(encoding="utf-8"))
    v2p = V2 / f"v2_result_{case}.json"
    v2 = json.loads(v2p.read_text(encoding="utf-8")) if v2p.exists() else None
    llm3 = v3["ledger_by_tool"].get("agent_llm_turn", {}).get("calls", 0)
    agents = "+".join(d["agent"][:4] for d in v3["delegations"])
    line = f"{case:14} | {v3['status']:22} {v3['elapsed_sec']:6} {llm3:4} {v3['spent_total']:6.2f} {agents:16} {len(v3['plan_nodes']):5} |"
    if v2:
        llm2 = sum(v["calls"] for k, v in v2["ledger_by_tool"].items() if k.startswith("agent_") or k in {"write_shot_prompts", "analyze_image"})
        line += f" {v2['status']:20} {v2['elapsed_sec']:6} {llm2:4} {v2['spent_total']:6.2f}"
    print(line)
print()
for case in CASES:
    v2p = V2 / f"v2_result_{case}.json"
    if v2p.exists():
        v2 = json.loads(v2p.read_text(encoding="utf-8"))
        print("v2", case, "tools:", {k: v["calls"] for k, v in v2["ledger_by_tool"].items()}, "| q:", v2.get("pending_questions"), "| err:", v2.get("error"))
        print("   plan:", (v2.get("raw_plan") or "")[:700])
