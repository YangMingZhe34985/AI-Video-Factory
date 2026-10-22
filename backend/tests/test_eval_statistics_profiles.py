"""Versioned statistics regressions use synthetic SQLite and fixed JSON only."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.v3_eval.eval_statistics import checked_work, ledger_metrics, summarize, planning_audit_label, main, plan_evidence
from scripts.v3_eval.image_evidence import image_evidence, identity_request_evidence, identity_archive_evidence, TABLES
from scripts.v3_eval.round_profiles import round_profile
from tests import test_eval_statistics as legacy


def image_fixture():
    manifest = {"run_id": "agent_images", "plan_version": 1, "plan_hash": "a" * 64,
        "nodes": [{"node_id": f"n{i}", "kind": "cast" if i < 2 else "keyframe", "model": "qwen-image-3.0",
                   "node_hash": "b" * 64, "n": 1} for i in range(4)]}
    rows = [{"id": i+1, "attempt_key": f"attempt{i}", "node_id": f"n{i}", "model": "qwen-image-3.0",
        "requested": 1, "status": "success", "actual_images": 1, "transport_started": 100+i,
        "invocation_id": f"image{i}", "output_url_hash": str(i)*64} for i in range(4)]
    raw = {"present_tables": list(TABLES), "gate6_image_policy": [{"id": 1, "manifest": json.dumps(manifest), "image_limit": 6}],
        "gate6_images": rows, "gate6_image_downloads": [{"reservation_id": i+1, "url_hash": str(i)*64,
            "sha256": "c"*64, "bytes": 100, "completed_at": 200+i} for i in range(4)],
        "gate6_image_violations": [], "gate6_http_events": []}
    ledger = [{"invocation_id": f"image{i}", "budget_scope": "agent_images", "tool_name": "generate_image",
        "status": "success", "estimated_cost": 2} for i in range(4)]
    return raw, ledger


class ProfileAndImageTests(unittest.TestCase):
    def test_profiles_keep_historical_and_current_limits_separate(self):
        old, new = round_profile("V12"), round_profile("V13")
        self.assertEqual((old["marker"]["call_limit"], old["marker"]["real_image_limit"], old["input_token_limit"]), (150, 0, 60000))
        self.assertEqual((new["marker"]["call_limit"], new["marker"]["real_image_limit"], new["input_token_limit"]), (120, 6, 80000))
        self.assertEqual(new["expected"], {"c3_story": 2, "c7_complete_story": 1})
        old["marker"]["call_limit"] = 999
        self.assertEqual(round_profile("V12")["marker"]["call_limit"], 150)
        for bad in (None, "V11", {}, "v13"):
            with self.assertRaises(ValueError):
                round_profile(bad)

    def test_current_marker_is_not_allowed_to_relabel_historical_directory(self):
        fixture = legacy.StatisticsTests("test_dedup_phase_boundary_and_totals")
        fixture.setUp()
        (fixture.work / "v13-round.json").write_text(json.dumps(round_profile("V13")["marker"]), encoding="utf-8")
        with self.assertRaises(ValueError):
            checked_work(fixture.work, "V13")
        self.assertEqual(checked_work(fixture.work, "V12"), fixture.work)

    def test_known_physical_over_limit_fails_even_with_a_rejected_logical_row(self):
        fixture = legacy.StatisticsTests("test_dedup_phase_boundary_and_totals")
        fixture.setUp()
        with sqlite3.connect(fixture.work / "real_call_audit.sqlite") as db:
            db.execute("UPDATE calls SET input_tokens=68541 WHERE id=1")
        with sqlite3.connect(fixture.work / "eval.db") as db:
            db.execute("UPDATE tool_invocations SET output_payload=? WHERE invocation_id='turn1'", (json.dumps({"usage":{"prompt_tokens":68541,"completion_tokens":20}}),))
            db.execute("INSERT INTO tool_invocations VALUES(6,'refused','agent_test','agent_llm_turn','rejected','director',1,0,'{}','BUDGET_EXCEEDED','preflight')")
        archive=deepcopy(fixture.archive)
        archive["metrics"]["turns"].append({"invocation_id":"refused"})
        archive["metrics"]["llm"].update(calls=2, input_tokens_sum=68541)
        fixture.write("result_c3_story_agent_test.json", archive)
        fixture.write("result_c3_story.json", archive)
        case=summarize(fixture.work, "V12")["planning"][0]
        target=next(item for item in case["goals"] if "60000" in item["name"])
        self.assertEqual(target["status"], "failed")
        self.assertEqual(target["evidence"]["input_tokens_max"], 68541)

    def test_resume_success_does_not_erase_original_failed_archive(self):
        fixture = legacy.StatisticsTests("test_dedup_phase_boundary_and_totals")
        fixture.setUp()
        first={"scenario":"V12-story-agent_test", "run_id":"agent_test", "status":"failed",
               "acceptance":{"safe_control_flow":False, "outcome":"scope_failure"}}
        resumed={"scenario":"V12-story-resume07-agent_test", "run_id":"agent_test", "status":"passed",
                 "acceptance":{"safe_control_flow":True, "outcome":"resumed_story_scope_and_origin_passed"}}
        fixture.write("hybrid_V12-story-agent_test_agent_test.json", first)
        fixture.write("hybrid_V12-story-resume07-agent_test_agent_test.json", resumed)
        path=fixture.work/"results/hybrid_V12-story-agent_test_agent_test.json"
        original=sha256(path.read_bytes()).hexdigest()
        result=summarize(fixture.work, "V12")
        self.assertEqual(next(g for g in result["required_coverage"] if "审核B" in g["name"])["status"], "passed")
        self.assertEqual(next(h for h in result["hybrid"] if h["label"]==first["scenario"])["coverage"], "failed")
        self.assertEqual(sha256(path.read_bytes()).hexdigest(), original)

    def test_real_image_reserved_returned_downloaded_and_credits_are_separate(self):
        raw, ledger=image_fixture()
        retry = {**raw["gate6_images"][0], "id": 5, "attempt_key": "retry", "retry_of": 1}
        raw["gate6_images"][0].update(status="http_error", actual_images=0)
        raw["gate6_images"].append(retry)
        raw["gate6_image_downloads"][0]["reservation_id"] = 5
        audit=image_evidence(raw, ledger, round_profile("V13"))
        self.assertEqual(audit["status"], "passed")
        self.assertEqual((audit["requested_image_units"], audit["image_post_attempts"], audit["actual_images_known_sum"], audit["downloaded_images"]), (5,5,4,4))
        ledger += [{"invocation_id":"mock_video", "budget_scope":"agent_images", "tool_name":"animate_shot", "status":"success", "estimated_cost":10}]
        totals=ledger_metrics(ledger, audit)
        self.assertEqual(totals["real_image_demo_credits"], 8)
        self.assertEqual(totals["mock_media_demo_credits"], 10)
        self.assertEqual(totals["accounted_demo_credits"], 18)

    def test_unmapped_real_image_is_not_falsely_called_mock(self):
        raw, ledger=image_fixture()
        raw["gate6_images"][0]["invocation_id"] = None
        audit=image_evidence(raw, ledger, round_profile("V13"))
        totals=ledger_metrics(ledger, audit)
        self.assertEqual(audit["status"], "failed")
        self.assertEqual(totals["real_image_demo_credits"], 6)
        self.assertEqual(totals["unattributed_media_demo_credits"], 2)
        self.assertEqual(totals["mock_media_demo_credits"], 0)

    def test_image_audit_missing_is_unknown_not_zero(self):
        raw, ledger=image_fixture()
        raw["present_tables"]=[]
        audit=image_evidence(raw, ledger, round_profile("V13"))
        self.assertEqual(audit["status"], "not_covered")
        self.assertIsNone(audit["image_post_attempts"])
        self.assertEqual(ledger_metrics(ledger, audit)["unattributed_media_demo_credits"], 8)

    def test_overproduction_unknown_attempt_and_incomplete_download_cannot_pass(self):
        raw, ledger=image_fixture()
        for changed in ("overproduce", "unknown", "download"):
            fixture=deepcopy(raw)
            if changed=="overproduce":
                fixture["gate6_images"][0]["actual_images"]=2
            elif changed=="unknown":
                fixture["gate6_images"][0]["status"]="unknown"
            else:
                fixture["gate6_image_downloads"][0]["sha256"]="not verified"
            result=image_evidence(fixture, ledger, round_profile("V13"))
            self.assertEqual(result["status"], "failed")
            self.assertNotEqual(result["coverage"], "passed")

    def test_returned_urls_are_not_completed_downloads_or_visual_identity(self):
        raw, ledger=image_fixture()
        raw["gate6_image_downloads"]=[]
        result=image_evidence(raw, ledger, round_profile("V13"))
        self.assertEqual(result["actual_images_known_sum"], 4)
        self.assertEqual(result["downloaded_images"], 0)
        self.assertEqual(result["coverage"], "not_covered")

    def test_historical_zero_image_round_rejects_new_real_image_evidence(self):
        raw, ledger=image_fixture()
        self.assertEqual(image_evidence(raw, ledger, round_profile("V12"))["status"], "failed")

    def test_v13_summary_reads_separate_image_audit_and_preserves_historical_profile(self):
        old = legacy.StatisticsTests("test_dedup_phase_boundary_and_totals")
        old.setUp()
        work=Path(tempfile.mkdtemp(prefix="cinecrew-v13-stat-fixture-", dir=old.work.parent))
        for filename in ("eval.db", "real_call_audit.sqlite"):
            shutil.copyfile(old.work/filename, work/filename)
        shutil.copytree(old.work/"results", work/"results")
        (work/"v13-round.json").write_text(json.dumps(round_profile("V13")["marker"]), encoding="utf-8")
        for name in ("result_c3_story.json", "result_c3_story_agent_test.json"):
            archive=json.loads((work/"results"/name).read_text(encoding="utf-8"))
            archive.update(audit_label="01-c3-1:agent_test", phase="planning")
            (work/"results"/name).write_text(json.dumps(archive),encoding="utf-8")
        raw, media_ledger=image_fixture()
        manifest=json.loads(raw["gate6_image_policy"][0]["manifest"])
        manifest["run_id"]="agent_test"
        raw["gate6_image_policy"][0]["manifest"]=json.dumps(manifest)
        with sqlite3.connect(work/"real_call_audit.sqlite") as db:
            db.execute("UPDATE limits SET max_calls=120")
            db.execute("UPDATE calls SET label='01-c3-1:agent_test' WHERE id IN (1,2)")
            for table in TABLES:
                records=raw[table]
                fields=sorted({key for row in records for key in row}) or ["id"]
                db.execute("CREATE TABLE "+table+" ("+",".join(fields)+")")
                for row in records:
                    db.execute("INSERT INTO "+table+" ("+",".join(fields)+") VALUES ("+",".join("?" for _ in fields)+")", tuple(row.get(key) for key in fields))
            db.execute("CREATE TABLE gate6_identity_request(id INTEGER,call_id INTEGER)")
            db.execute("INSERT INTO gate6_identity_request VALUES(1,4)")
            db.execute("INSERT INTO calls VALUES(4,'04-identity:agent_test','vision','qwen3.7-plus','success',50,6)")
        with sqlite3.connect(work/"eval.db") as db:
            db.execute("INSERT INTO tool_invocations VALUES(10,'identity1','agent_test','gate6_identity_review','success','producer',1,0.5,?,NULL,NULL)", (json.dumps({"usage":{"prompt_tokens":50,"completion_tokens":6}}),))
            for i,row in enumerate(media_ledger):
                db.execute("INSERT INTO tool_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?)",(6+i,row["invocation_id"],"agent_test","generate_image","success","production",1,2,"{}",None,None))
        before={name:sha256((work/name).read_bytes()).hexdigest() for name in ("eval.db","real_call_audit.sqlite")}
        result=summarize(work,"V13")
        self.assertEqual(result["profile"]["name"], "V13")
        self.assertEqual(result["physical_audit"]["attempts"], 4)
        self.assertEqual(result["physical_audit"]["call_limit"], 120)
        self.assertEqual(result["safety"]["status"], "passed")
        self.assertEqual(result["safety"]["real_media_calls_observed"], 4)
        self.assertEqual(result["real_images"]["downloaded_images"], 4)
        self.assertEqual(result["totals"]["real_image_demo_credits"], 8)
        self.assertEqual(result["totals"]["mock_media_demo_credits"], 8)
        self.assertEqual(result["totals"]["accounted_demo_credits"], 19.6)
        self.assertEqual(result["identity_vision"]["status"], "passed")
        self.assertEqual(result["planning"][0]["metrics"]["vision"]["calls"], 1)
        self.assertTrue(result["planning"][0]["physical_slice_verified"])
        self.assertEqual(result["reconciliation"]["status"], "passed")
        self.assertFalse(any("审核B" in g["name"] or "c1_portrait" in g["name"] for g in result["required_coverage"]))
        self.assertTrue(any("80000" in g["name"] for g in result["planning"][0]["goals"]))
        self.assertEqual(before,{name:sha256((work/name).read_bytes()).hexdigest() for name in before})
        self.assertEqual(summarize(old.work,"V12")["physical_audit"]["call_limit"],150)

    def test_identity_call_requires_unique_dedicated_successful_vision(self):
        call={"id":7,"kind":"vision","model":"qwen3.7-plus","status":"success"}
        self.assertEqual(identity_request_evidence([], [call])["status"], "not_covered")
        self.assertEqual(identity_request_evidence([{"id":1,"call_id":7}], [call])["status"], "passed")
        for rows,calls in [([{"id":1,"call_id":7}], [{**call,"kind":"text"}]),
            ([{"id":1,"call_id":7}], [{**call,"status":"unknown"}]),
            ([{"id":1,"call_id":8}], [call]),
            ([{"id":1,"call_id":7},{"id":2,"call_id":7}], [call])]:
            self.assertEqual(identity_request_evidence(rows,calls)["status"], "failed")

    def test_fixed_planning_phase_is_not_inferred_from_case_or_identity_run(self):
        profile=round_profile("V13")
        data={"case":"c3_story","run_id":"agent_one","phase":"planning","audit_label":"01-c3-1:agent_one"}
        self.assertEqual(planning_audit_label(data,profile),"01-c3-1:agent_one")
        self.assertEqual(planning_audit_label({**data,"audit_label":"02-c3-2:agent_one"},profile),"02-c3-2:agent_one")
        for changes in ({"audit_label":None},{"audit_label":"c3_story:agent_one"},
                {"audit_label":"01-c3-1:agent_other"},{"audit_label":"04-identity:agent_one"},
                {"phase":"identity_sample"},{"audit_label":"03-c7:agent_one"}):
            self.assertIsNone(planning_audit_label({**data,**changes},profile))
        self.assertEqual(planning_audit_label(data,round_profile("V12")),"c3_story:agent_one")

    def test_identity_pointer_cannot_reuse_a_planning_vision_call(self):
        row={"id":7,"kind":"vision","model":"qwen3.7-plus","status":"success","label":"01-c3-1:agent_test"}
        pointer=[{"id":1,"call_id":7}]
        expected="04-identity:agent_test"
        self.assertEqual(identity_request_evidence(pointer,[row],expected_label=expected)["status"],"failed")
        self.assertEqual(identity_request_evidence(pointer,[{**row,"label":expected}],expected_label=expected)["status"],"passed")

    def test_cli_keeps_old_and_new_snapshots_immutable(self):
        fixture=legacy.StatisticsTests("test_dedup_phase_boundary_and_totals")
        fixture.setUp()
        old=fixture.work/"readonly-statistics"
        old.mkdir()
        (old/"v12-statistics.json").write_text("historical evidence",encoding="utf-8")
        argv=["eval_statistics.py","--work",str(fixture.work),"--profile","V12"]
        with patch("sys.argv",argv):
            main()
        target=fixture.work/"readonly-statistics-v2/v12-statistics.json"
        before=target.read_bytes()
        with patch("sys.argv",argv), self.assertRaises(FileExistsError):
            main()
        self.assertEqual(target.read_bytes(),before)
        self.assertEqual((old/"v12-statistics.json").read_text(encoding="utf-8"),"historical evidence")
        with patch("sys.argv",argv+["--snapshot-name","readonly-statistics-v2-final"]):
            main()
        self.assertTrue((fixture.work/"readonly-statistics-v2-final/v12-statistics.json").is_file())
        for value in ("../elsewhere","readonly-statistics","readonly-statistics-v2/escape"):
            with patch("sys.argv",argv+["--snapshot-name",value]), self.assertRaises(ValueError):
                main()

    def test_private_identity_tool_is_vision_not_other_cost_or_mock(self):
        rows=[{"invocation_id":"idv","budget_scope":"agent_images","tool_name":"gate6_identity_review",
            "status":"success","estimated_cost":0.7,"output_payload":json.dumps({"usage":{"prompt_tokens":40,"completion_tokens":4}})}]
        metrics=ledger_metrics(rows)
        self.assertEqual(metrics["vision"]["calls"],1)
        self.assertEqual(metrics["vision"]["input_tokens_known_sum"],40)
        self.assertEqual(metrics["all_model_usage"]["calls"],1)
        self.assertEqual(metrics["llm_demo_credits"],0.7)
        self.assertEqual(metrics["other_demo_credits"],0)
        self.assertEqual(metrics["mock_media_demo_credits"],0)

    def test_identity_archive_links_images_and_receipt_without_claiming_appearance(self):
        raw,ledger=image_fixture()
        evidence=image_evidence(raw,ledger,round_profile("V13"))
        output={"comparisons":[{"verdict":"inconsistent"}],"limitations":"Stub semantic result","usage":{"prompt_tokens":40,"completion_tokens":4}}
        ledger.append({"budget_scope":"agent_images","tool_name":"gate6_identity_review","invocation_id":"idv",
            "status":"success","output_payload":json.dumps(output)})
        images=[{"node_id":f"n{i}","kind":"cast" if i<2 else "keyframe","model":"qwen-image-3.0","invocation_id":f"image{i}",
            "reservation_id":i+1,"artifact_id":f"artifact{i}","sha256":"c"*64} for i in range(4)]
        data={"run_id":"agent_images","round":"V13-Gate6","phase":"identity_sample","audit_label":"04-identity:agent_images",
            "status":"passed","manifest":evidence["manifest"],"identity":{"images":images,"tool_receipt":{"tool":"gate6_identity_review",
            "invocation_id":"idv","replayed":False,"status":"success","output":output}}}
        display=[{"source_path":f"original{i}.png","source_sha256":"c"*64,"source_bytes":100,"source_size":[1024,1024],
            "path":f"display{i}.jpg","sha256":str(i+1)*64,"bytes":80,"size":[1024,1024],
            "transform":{"format":"JPEG","max_edge":1024,"quality":85,"subsampling":2,"optimize":False,
                "resample":"LANCZOS","alpha_background":"#FFFFFF","crop":False,"enhance":False,
                "exif_orientation_applied":False,"pillow_version":"stub"}} for i in range(4)]
        data["identity"]["display_inputs"]=display
        display_audit={"identity_inputs":[{"id":1,"records":json.dumps(display)}],
            "identity_phase":[{"id":1,"phase":"complete","identity_hashes":json.dumps([d["sha256"] for d in display])}]}
        records=[{"source":{"path":"fixed","sha256":"d"*64},"data":data}]
        result=identity_archive_evidence(records,evidence,{"status":"passed"},ledger,display_audit=display_audit)
        self.assertEqual(result["status"],"passed")
        self.assertEqual(result["semantic_status"],"needs_review")
        self.assertEqual(result["display_input_evidence"]["status"],"passed")
        self.assertNotEqual(result["display_input_evidence"]["original_hashes"],result["display_input_evidence"]["vision_hashes"])
        for field,value in (("quality",80),("crop",True)):
            changed=deepcopy(records);changed[0]["data"]["identity"]["display_inputs"][0]["transform"][field]=value
            self.assertEqual(identity_archive_evidence(changed,evidence,{"status":"passed"},ledger,display_audit=display_audit)["status"],"failed")
        altered=deepcopy(display_audit);altered["identity_phase"][0]["identity_hashes"]=json.dumps(["c"*64]*4)
        self.assertEqual(identity_archive_evidence(records,evidence,{"status":"passed"},ledger,display_audit=altered)["status"],"failed")
        self.assertEqual(identity_archive_evidence(records,evidence,{"status":"passed"},ledger)["status"],"failed")
        self.assertEqual(result["comparisons"][0]["verdict"],"inconsistent")
        for change in ("hash","order","receipt","label","duplicates","failed"):
            changed=deepcopy(records)
            if change=="hash":changed[0]["data"]["identity"]["images"][0]["sha256"]="e"*64
            if change=="order":changed[0]["data"]["identity"]["images"].reverse()
            if change=="receipt":changed[0]["data"]["identity"]["tool_receipt"]["output"]={}
            if change=="label":changed[0]["data"]["audit_label"]="03-c7:agent_images"
            if change=="duplicates":changed.append(deepcopy(changed[0]))
            if change=="failed":changed[0]["data"]["status"]="failed"
            self.assertEqual(identity_archive_evidence(changed,evidence,{"status":"passed"},ledger,display_audit=display_audit)["status"],"failed",change)
        self.assertEqual(identity_archive_evidence([],evidence,{"status":"passed"},ledger)["status"],"not_covered")

    def test_planned_delivery_seconds_are_separate_from_generated_and_billable_seconds(self):
        plan={"estimates":{"video_seconds":20},"nodes":[
            {"id":"shot","tool":"generate_video","params":{"duration":10},"characters":[]},
            {"id":"master","tool":"compose_video","inputs":{"video_artifact_ids":[{"ref":"shot.video"},{"ref":"shot.video"}]}}]}
        evidence=plan_evidence(plan)
        self.assertEqual(evidence["planned_delivery_video_seconds"],20)
        self.assertEqual(evidence["generated_video_seconds"],10)
        self.assertNotIn("estimated_billable_video_seconds",evidence)
        fixture=legacy.StatisticsTests("test_dedup_phase_boundary_and_totals");fixture.setUp()
        old=summarize(fixture.work,"V12")["planning"][0]["plan"]["duration_evidence_scope"]
        self.assertIn("historical version",old)
        self.assertIn("not probed",old)
