"""Read-only Gate6 image evidence, separate from chat requests and demo billing."""
from collections import Counter
import json
import re

IMAGE_MODELS = frozenset({"wan2.6-image", "wan2.7-image", "wan2.7-image-pro", "qwen-image-3.0", "qwen-image-3.0-pro"})
TABLES = ("gate6_image_policy", "gate6_images", "gate6_image_downloads", "gate6_image_violations", "gate6_http_events")


def read_image_tables(connection):
    present = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result = {"present_tables": sorted(set(TABLES) & present)}
    for table in TABLES:
        # Names come exclusively from the fixed local tuple, never a file/CLI field.
        result[table] = [dict(r) for r in connection.execute("SELECT * FROM " + table)] if table in present else []
    result["identity_requests"] = [dict(r) for r in connection.execute("SELECT * FROM gate6_identity_request")] if "gate6_identity_request" in present else []
    result["identity_inputs"] = [dict(r) for r in connection.execute("SELECT * FROM gate6_identity_inputs")] if "gate6_identity_inputs" in present else []
    result["identity_phase"] = [dict(r) for r in connection.execute("SELECT * FROM gate6_phase")] if "gate6_phase" in present else []
    return result


def identity_request_evidence(rows, physical, *, expected_label=None):
    if not rows:
        return {"status": "not_covered", "reason": "No fixed identity vision request recorded"}
    if len(rows) != 1 or rows[0].get("id") != 1:
        return {"status": "failed", "reason": "Identity vision request is not unique"}
    call_id = rows[0].get("call_id")
    matched = [r for r in physical if r.get("id") == call_id]
    if len(matched) != 1:
        return {"status": "failed", "reason": "Identity request has no unique physical call", "call_id": call_id}
    call = matched[0]
    passed = call.get("kind") == "vision" and call.get("model") == "qwen3.7-plus" and call.get("status") == "success"
    if expected_label is not None:
        passed = passed and bool(expected_label) and call.get("label") == expected_label
    return {"status": "passed" if passed else "failed", "call_id": call_id,
        "audit_label": call.get("label"), "expected_audit_label": expected_label,
        "model": call.get("model"), "kind": call.get("kind"), "physical_status": call.get("status"),
        "meaning": "One dedicated guarded vision call; attachment completeness and identity judgment still require the identity archive."}


def image_evidence(raw, ledger, profile):
    rows, policies = raw["gate6_images"], raw["gate6_image_policy"]
    downloads, violations = raw["gate6_image_downloads"], raw["gate6_image_violations"]
    events = raw["gate6_http_events"]
    issues = []
    def issue(code, **fields):
        issues.append({"code": code, **fields})
    if profile["name"] == "V12":
        if rows or downloads or events or policies or violations:
            issue("UNEXPECTED_REAL_IMAGE_EVIDENCE_IN_MOCK_ROUND")
        return {"status": "failed" if issues else "passed", "coverage": "not_required",
            "requested_image_units": 0 if not rows else None, "image_post_attempts": 0 if not rows else None,
            "actual_images_known_sum": 0 if not rows else None, "downloaded_images": len(downloads),
            "real_invocation_ids": [], "unattributed_invocation_ids": [], "rows": rows,
            "downloads": downloads, "violations": violations, "http_events": events, "diagnostics": issues}
    if set(raw["present_tables"]) != set(TABLES):
        return {"status": "not_covered", "coverage": "not_covered", "reason": "Gate6 image audit schema not yet present",
            "requested_image_units": None, "image_post_attempts": None, "actual_images_known_sum": None,
            "downloaded_images": None, "real_invocation_ids": [],
            "unattributed_invocation_ids": [r["invocation_id"] for r in ledger if r["tool_name"] == "generate_image" and r["status"] != "rejected"],
            "rows": rows, "downloads": downloads, "violations": violations, "http_events": events, "diagnostics": issues}
    manifest, limit = {}, None
    if len(policies) != 1 or policies[0].get("id") != 1:
        issue("INVALID_IMAGE_POLICY")
    else:
        policy = policies[0]
        try:
            manifest = json.loads(policy["manifest"])
        except (KeyError, TypeError, ValueError):
            issue("INVALID_IMAGE_MANIFEST")
        limit = policy.get("image_limit")
        if type(limit) is not int or not 0 <= limit <= profile["marker"]["real_image_limit"]:
            issue("IMAGE_LIMIT_OUTSIDE_PROFILE")
    selected = manifest.get("nodes", []) if isinstance(manifest, dict) else []
    valid_manifest = (isinstance(selected, list) and len(selected) == 4 and all(isinstance(n, dict) for n in selected)
        and len({n.get("node_id") for n in selected if isinstance(n.get("node_id"), str)}) == 4
        and Counter(n.get("kind") for n in selected) == {"cast": 2, "keyframe": 2}
        and all(n.get("model") in IMAGE_MODELS and type(n.get("n")) is int and n["n"] == 1 for n in selected))
    if not valid_manifest:
        issue("INVALID_IMAGE_SELECTION")
    by_node = {n["node_id"]: n for n in selected if isinstance(n, dict) and isinstance(n.get("node_id"), str)} if isinstance(selected, list) else {}
    by_id = {r.get("id"): r for r in rows}
    if len(by_id) != len(rows):
        issue("DUPLICATE_IMAGE_RESERVATION")
    invocation = {r["invocation_id"]: r for r in ledger}
    real_ids, unmapped, unknown_ids = set(), [], set()
    requested = actual = 0
    posts = sum(r.get("transport_started") is not None for r in rows)
    missing_output = []
    for row in rows:
        ident = row.get("id")
        selected_node = by_node.get(row.get("node_id"))
        if not selected_node or row.get("model") != selected_node.get("model"):
            issue("IMAGE_NODE_OR_MODEL_OUTSIDE_SELECTION", reservation_id=ident)
        if type(row.get("requested")) is not int or row["requested"] != 1:
            issue("INVALID_RESERVED_IMAGE_UNITS", reservation_id=ident)
        else:
            requested += row["requested"]
        amount = row.get("actual_images")
        if type(amount) is int and amount >= 0:
            actual += amount
            if amount > 1 or row.get("status") == "success" and amount != 1:
                issue("IMAGE_RESPONSE_COUNT_MISMATCH", reservation_id=ident)
        else:
            missing_output.append(ident)
        if row.get("status") not in {"success", "http_error"}:
            issue("UNSETTLED_IMAGE_ATTEMPT", reservation_id=ident)
        if row.get("status") == "success" and row.get("transport_started") is None:
            issue("SUCCESS_WITHOUT_IMAGE_TRANSPORT", reservation_id=ident)
        iid = row.get("invocation_id")
        linked = invocation.get(iid)
        if (not isinstance(iid, str) or not linked or linked["tool_name"] != "generate_image"
                or linked["budget_scope"] != manifest.get("run_id")):
            unmapped.append(ident)
        else:
            real_ids.add(iid)
    if unmapped:
        issue("UNMAPPED_IMAGE_INVOCATIONS", reservation_ids=unmapped)
        unknown_ids = {r["invocation_id"] for r in ledger if r["tool_name"] == "generate_image"
            and r["budget_scope"] == manifest.get("run_id") and r["invocation_id"] not in real_ids}
    if missing_output:
        issue("MISSING_IMAGE_OUTPUT_COUNT", reservation_ids=missing_output)
    for event in events:
        if event.get("status") in {"unknown", "reserved", "running"} or event.get("finished") is None:
            issue("UNSETTLED_MEDIA_HTTP_EVENT", event_id=event.get("id"))
        if event.get("reservation_id") is not None and event["reservation_id"] not in by_id:
            issue("ORPHAN_MEDIA_HTTP_EVENT", event_id=event.get("id"))
    if type(limit) is int and (requested > limit or actual > limit):
        issue("IMAGE_LIMIT_EXCEEDED")
    if violations:
        issue("RECORDED_IMAGE_GUARD_VIOLATION")
    complete_nodes = set()
    for download in downloads:
        row = by_id.get(download.get("reservation_id"), {})
        if (row.get("status") != "success" or row.get("actual_images") != 1
                or download.get("url_hash") != row.get("output_url_hash")
                or not isinstance(download.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", download["sha256"])
                or type(download.get("bytes")) is not int or download["bytes"] <= 0):
            issue("INVALID_IMAGE_DOWNLOAD_EVIDENCE", reservation_id=download.get("reservation_id"))
        else:
            complete_nodes.add(row.get("node_id"))
    # This proves recorded completed downloads, not visual identity or pixel quality.
    covered = valid_manifest and complete_nodes == set(by_node) and not issues
    return {"status": "failed" if issues else "passed", "coverage": "passed" if covered else "not_covered",
        "image_limit": limit, "manifest": manifest, "requested_image_units": requested,
        "image_post_attempts": posts, "actual_images_known_sum": actual, "actual_images_missing_ids": missing_output,
        "downloaded_images": len(downloads), "completed_node_ids": sorted(complete_nodes),
        "real_invocation_ids": sorted(real_ids), "unattributed_invocation_ids": sorted(unknown_ids),
        "unmapped_reservation_ids": unmapped, "rows": rows, "downloads": downloads,
        "violations": violations, "http_events": events, "diagnostics": issues,
        "limitations": ["POST attempts, reserved image units, returned images and completed download records are separate counts.",
            "Downloaded hashes are server audit records; this read-only report does not reopen media or grade identity.",
            "Provider retries can share one logical invocation; demo credits count that invocation once, not actual provider charges."]}


def identity_archive_evidence(records, image_audit, vision, ledger, *, display_audit=None):
    """Join one fixed archive to durable evidence; appearance remains human-reviewed."""
    result={"status":"not_covered","archives":records,"semantic_status":"needs_review","diagnostics":[]}
    if not records:
        return result
    def issue(code): result["diagnostics"].append({"code":code})
    if len(records)!=1:
        issue("IDENTITY_ARCHIVE_COUNT_MISMATCH")
    record=records[0]
    data=record.get("data") or {}
    manifest=image_audit.get("manifest") or {}
    rid=manifest.get("run_id")
    if (not isinstance(rid,str) or data.get("run_id")!=rid or data.get("round")!="V13-Gate6"
            or data.get("phase")!="identity_sample" or data.get("audit_label")!="04-identity:"+rid
            or data.get("manifest")!=manifest):
        issue("IDENTITY_ARCHIVE_BINDING_MISMATCH")
    identity=data.get("identity") or {}
    receipt=identity.get("tool_receipt") or {}
    rows=[r for r in ledger if r.get("budget_scope")==rid and r.get("tool_name")=="gate6_identity_review"]
    output={}
    if (len(rows)!=1 or receipt.get("tool")!="gate6_identity_review" or receipt.get("replayed") is not False
            or receipt.get("status")!="success" or rows[0].get("status")!="success"
            or receipt.get("invocation_id")!=rows[0].get("invocation_id")):
        issue("IDENTITY_LOGICAL_RECEIPT_MISMATCH")
    else:
        try:
            stored=rows[0].get("output_payload")
            output=json.loads(stored) if isinstance(stored,str) else stored
        except (TypeError,ValueError): output=None
        if not isinstance(output,dict) or output!=receipt.get("output"):
            issue("IDENTITY_OUTPUT_RECEIPT_MISMATCH"); output={}
    selected=manifest.get("nodes") or []
    images=identity.get("images") or []
    reservations={r.get("id"):r for r in image_audit.get("rows",[])}
    downloads={r.get("reservation_id"):r for r in image_audit.get("downloads",[])}
    if not isinstance(images,list) or len(images)!=4 or len(selected)!=4:
        issue("IDENTITY_IMAGE_BATCH_MISMATCH")
    else:
        for image,node in zip(images,selected):
            reservation=reservations.get(image.get("reservation_id"),{}) if isinstance(image,dict) else {}
            downloaded=downloads.get(image.get("reservation_id"),{}) if isinstance(image,dict) else {}
            if (not isinstance(image,dict) or image.get("node_id")!=node.get("node_id")
                    or image.get("kind")!=node.get("kind") or image.get("model")!=node.get("model")
                    or image.get("invocation_id")!=reservation.get("invocation_id")
                    or reservation.get("node_id")!=node.get("node_id")
                    or image.get("sha256")!=downloaded.get("sha256") or not downloaded
                    or not isinstance(image.get("artifact_id"),str) or not image["artifact_id"]):
                issue("IDENTITY_IMAGE_BATCH_MISMATCH");break
    display_audit=display_audit or {}
    input_rows=display_audit.get("identity_inputs") or []
    phase_rows=display_audit.get("identity_phase") or []
    supplied=identity.get("display_inputs")
    proof={"status":"failed","original_hashes":[image.get("sha256") for image in images if isinstance(image,dict)],
        "display_inputs":supplied,"meaning":"Original downloads remain unchanged; only the four recorded display copies enter vision."}
    display_ok=False
    try:
        fixed={"format":"JPEG","max_edge":1024,"quality":85,"subsampling":2,"optimize":False,
            "resample":"LANCZOS","alpha_background":"#FFFFFF","crop":False,"enhance":False}
        stored=json.loads(input_rows[0]["records"]) if len(input_rows)==1 and input_rows[0].get("id")==1 else None
        phase=phase_rows[0] if len(phase_rows)==1 and phase_rows[0].get("id")==1 else {}
        hashes=json.loads(phase.get("identity_hashes") or "null")
        display_ok=(isinstance(supplied,list) and len(supplied)==4 and stored==supplied
            and phase.get("phase")=="complete" and hashes==[d.get("sha256") for d in supplied])
        total=0
        for image,display in zip(images,supplied or []):
            transform=display.get("transform") or {}
            download=downloads.get(image.get("reservation_id"),{})
            size=display.get("size")
            total+=display.get("bytes",0)
            display_ok=display_ok and (display.get("source_sha256")==image.get("sha256")
                and display.get("source_bytes")==download.get("bytes")
                and isinstance(display.get("sha256"),str) and re.fullmatch(r"[0-9a-f]{64}",display["sha256"]) is not None
                and type(display.get("bytes")) is int and 0<display["bytes"]<=512*1024
                and isinstance(size,list) and len(size)==2 and all(type(v) is int and 0<v<=1024 for v in size)
                and all(transform.get(k)==v and type(transform.get(k)) is type(v) for k,v in fixed.items())
                and type(transform.get("exif_orientation_applied")) is bool and isinstance(transform.get("pillow_version"),str)
                and bool(transform["pillow_version"]) and set(transform)==set(fixed)|{"exif_orientation_applied","pillow_version"})
        display_ok=display_ok and total<=2*1024*1024 and len(images)==4
        proof["vision_hashes"]=hashes
    except (TypeError,ValueError,KeyError,AttributeError):
        display_ok=False
    if not display_ok:
        issue("IDENTITY_DISPLAY_INPUT_BINDING_MISMATCH")
    proof["status"]="passed" if display_ok else "failed"
    result["display_input_evidence"]=proof
    if vision.get("status")!="passed" or image_audit.get("coverage")!="passed":
        issue("IDENTITY_PHYSICAL_EVIDENCE_INCOMPLETE")
    result.update(status="failed" if result["diagnostics"] or data.get("status")!="passed" else "passed",
        run_id=rid,archive_status=data.get("status"),tool_invocation_id=receipt.get("invocation_id"),
        comparisons=output.get("comparisons",[]),limitations=output.get("limitations"),
        meaning="Archive/receipt/image transport binding only; verdict wording and actual identity need independent review.")
    return result
