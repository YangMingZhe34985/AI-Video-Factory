"""Evaluation-only default answers with stable v3 action identity and evidence."""
from copy import deepcopy
from hashlib import sha256
import json


def default_answer_payload(run_id, card_id, *, v3=True):
    if not all(isinstance(value, str) and value for value in (run_id, card_id)):
        raise ValueError("Default answers require a Run and card identity")
    payload = {"action": "answer", "card_id": card_id, "use_defaults": True}
    if v3:
        identity = json.dumps([run_id, card_id], ensure_ascii=False, separators=(",", ":"))
        payload["request_key"] = "eval-default-answer:" + sha256(identity.encode("utf-8")).hexdigest()
    return payload


def answer_defaults(client, run_id, card_id, notes, *, v3=True):
    """Send once; a rejected answer remains evidence and never advances the test."""
    payload = default_answer_payload(run_id, card_id, v3=v3)
    response = client.post(f"/api/agent/runs/{run_id}/actions", json=payload)
    accepted = response.status_code in (200, 202)
    evidence = {"answered_with_defaults": response.status_code, "card_id": card_id,
                "accepted": accepted}
    if "request_key" in payload:
        evidence["request_key"] = payload["request_key"]
    if not accepted:
        body = response.get_json(silent=True)
        evidence["error"] = deepcopy(body.get("error")) if isinstance(body, dict) and "error" in body else {
            "code": "UNEXPECTED_API_RESPONSE", "content_type": response.content_type}
    notes.append(evidence)
    return accepted
