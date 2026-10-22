"""Independent c7 Plan geometry audit. Standard library; no compiler or I/O."""
from collections import defaultdict
from fractions import Fraction
import re

_SIZE = re.compile(r"^([1-9][0-9]{0,4})\*([1-9][0-9]{0,4})$")
_REF = re.compile(r"^([a-z0-9_]{1,40})\.([A-Za-z0-9_]{1,80})$")
_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4"}


def _size(value, *, canvas=False):
    match = _SIZE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return None
    width, height = map(int, match.groups())
    if canvas and (width % 2 or height % 2 or width > 8192 or height > 8192):
        return None
    return width, height


def _reference(value):
    if isinstance(value, dict) and set(value) == {"ref"} and isinstance(value["ref"], str):
        match = _REF.fullmatch(value["ref"])
        return match.groups() if match else None
    return None


def _key(value):
    ref = _reference(value)
    if ref:
        return ".".join(ref)
    if isinstance(value, str):
        return "artifact:" + value
    if isinstance(value, dict) and set(value) == {"artifact"} and isinstance(value["artifact"], str):
        return "artifact:" + value["artifact"]
    return None


def inspect_aspect_chain(plan, brief, measured_artifacts=None, *, expected="16:9"):
    """Audit archived c7 output-chain intent, never provider quality or media bytes.

    Optional dimensions must be independently measured, Run-scoped evidence;
    this function never treats authored Plan metadata or prompts as measurement.
    c7 requires a complete composition and matching final QC. Missing evidence
    remains not_covered; explicit conflicts fail. No aliases are normalized.
    """
    audit = _Audit(plan, brief, measured_artifacts or {}, expected)
    return audit.run()


class _Audit:
    def __init__(self, plan, brief, measured, expected):
        if expected not in _RATIOS:
            raise ValueError("Expected ratio must be a known contract value")
        self.plan = plan if isinstance(plan, dict) else {}
        self.brief = brief if isinstance(brief, dict) else {}
        self.measured, self.expected = measured, expected
        self.ratio = Fraction(*map(int, expected.split(":")))
        self.checks, self.seen_checks = [], set()
        self.images, self.videos, self.compositions, self.qcs = set(), set(), set(), set()
        self.auxiliary_cast, self.master_refs, self.edges = set(), {}, []
        self.memo, self.visiting, self.geometry = {}, set(), {}
        self.nodes = {}
        for node in self.plan.get("nodes", []):
            if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                self.add(None, "nodes", "failed", "INVALID_NODE")
                continue
            if node["id"] in self.nodes:
                self.add(node["id"], "id", "failed", "DUPLICATE_NODE")
            self.nodes[node["id"]] = node
        users = defaultdict(set)
        for character, values in (self.plan.get("character_references") or {}).items():
            for value in values if isinstance(values, list) else []:
                ref = _reference(value)
                if ref and ref[1] == "image":
                    users[ref[0]].add(character)
        self.cast = {nid for nid, owners in users.items() if len(owners) == 1
            and (node := self.nodes.get(nid, {})).get("tool") == "generate_image"
            and node.get("params", {}).get("n", 1) == 1 and node.get("gate") == "preview"
            and node.get("characters") == list(owners)}

    def add(self, node_id, field, status, code, **evidence):
        identity = (node_id, field, status, code)
        if identity not in self.seen_checks:
            self.checks.append({"node_id": node_id, "field": field, "status": status,
                                "code": code, **evidence})
            self.seen_checks.add(identity)
        return status == "passed"

    def dimensions(self, node_id, field, value, *, canvas=False):
        dims = _size(value, canvas=canvas)
        if dims is None:
            self.add(node_id, field, "not_covered" if value is None else "failed",
                     "MISSING_SIZE_EVIDENCE" if value is None else "INVALID_SIZE")
            return None
        if Fraction(*dims) != self.ratio:
            self.add(node_id, field, "failed", "ASPECT_MISMATCH", width=dims[0], height=dims[1], expected=self.expected)
            return None
        self.add(node_id, field, "passed", "EXACT_SIZE_RATIO", width=dims[0], height=dims[1])
        return dims

    def target(self, node):
        nid, inputs = node["id"], node.get("inputs") or {}
        ratio = inputs.get("target_aspect_ratio")
        ok = self.add(nid, "inputs.target_aspect_ratio",
                      "not_covered" if ratio is None else "passed" if ratio == self.expected else "failed",
                      "CANVAS_TARGET_RATIO", expected=self.expected)
        dims = self.dimensions(nid, "inputs.target_size", inputs.get("target_size"), canvas=True)
        if ok and dims:
            self.geometry[nid] = dims
            return True
        return False

    def artifact(self, value, owner, field):
        ident = value if isinstance(value, str) else value.get("artifact") if isinstance(value, dict) and set(value) == {"artifact"} else None
        info = self.measured.get(ident) if isinstance(ident, str) else None
        if not isinstance(info, dict) or info.get("verified") is not True:
            return self.add(owner, field, "not_covered", "MEASURED_ARTIFACT_REQUIRED")
        width, height = info.get("width"), info.get("height")
        if type(width) is not int or type(height) is not int or min(width, height) <= 0:
            return self.add(owner, field, "not_covered", "MEASURED_SIZE_MISSING")
        return self.dimensions(owner, field, f"{width}*{height}") is not None

    def media(self, value, kind, owner, field):
        if isinstance(value, list):
            if not value:
                return self.add(owner, field, "not_covered", "EMPTY_MEDIA_INPUT")
            outcomes = [self.media(item, kind, owner, f"{field}[{index}]") for index, item in enumerate(value)]
            return all(outcomes)
        ref = _reference(value)
        if not ref:
            return self.artifact(value, owner, field)
        nid, output = ref
        self.edges.append({"from": owner, "field": field, "to": nid, "output": output, "kind": kind})
        node = self.nodes.get(nid)
        if node is None:
            return self.add(owner, field, "not_covered", "REFERENCED_NODE_MISSING")
        marker = (nid, output, kind)
        if marker in self.visiting:
            return self.add(nid, field, "failed", "MEDIA_REFERENCE_CYCLE")
        if marker in self.memo:
            return self.memo[marker]
        self.visiting.add(marker)
        inputs, params, tool = node.get("inputs") or {}, node.get("params") or {}, node.get("tool")
        ok = False
        if kind == "image" and tool == "generate_image" and output in {"image", "images"}:
            self.images.add(nid)
            dims = self.dimensions(nid, "params.size", params.get("size"))
            ok = dims is not None
            if dims:
                self.geometry[nid] = dims
            if params.get("ratio") is not None and params["ratio"] != self.expected:
                ok = self.add(nid, "params.ratio", "failed", "ASPECT_MISMATCH", expected=self.expected)
        elif kind == "image" and tool == "select_image" and output == "image":
            candidates = inputs.get("candidate_artifact_ids")
            ok = self.media(candidates, "image", nid, "inputs.candidate_artifact_ids")
            if candidates is None:
                ok = False
        elif kind == "image" and tool == "extract_frame" and output == "artifact_id":
            ok = self.media(inputs.get("video_artifact_id"), "video", nid, "inputs.video_artifact_id")
        elif kind == "video" and tool == "compose_video" and output in {"artifact_id", "compressed_artifact_id"}:
            self.compositions.add(nid)
            target_ok = self.target(node)
            sources_ok = self.media(inputs.get("video_artifact_ids"), "video", nid, "inputs.video_artifact_ids")
            ok = target_ok and sources_ok
        elif kind == "video" and tool == "retain_video_segment" and output == "artifact_id":
            ok = self.media(inputs.get("video_artifact_id"), "video", nid, "inputs.video_artifact_id")
        elif kind == "video" and tool in {"animate_shot", "generate_video", "transform_video"} and output == "video":
            self.videos.add(nid)
            ratio_value, size_value = params.get("ratio"), params.get("size")
            ratio_proof = False
            ok = True
            if ratio_value is not None:
                ratio_proof = self.add(nid, "params.ratio", "passed" if ratio_value == self.expected else "failed",
                                       "VIDEO_RATIO", expected=self.expected)
                ok = ok and ratio_proof
            if size_value is not None:
                dims = self.dimensions(nid, "params.size", size_value)
                ok = ok and dims is not None
                ratio_proof = ratio_proof or dims is not None
                if dims:
                    self.geometry[nid] = dims
            i2v = tool == "animate_shot" or tool == "generate_video" and inputs.get("mode") == "i2v"
            frame_results = []
            if i2v:
                frame_results.append(self.media(inputs.get("first_frame_artifact_id"), "image", nid, "inputs.first_frame_artifact_id"))
            elif inputs.get("first_frame_artifact_id") is not None:
                frame_results.append(self.media(inputs["first_frame_artifact_id"], "image", nid, "inputs.first_frame_artifact_id"))
            if inputs.get("last_frame_artifact_id") is not None:
                frame_results.append(self.media(inputs["last_frame_artifact_id"], "image", nid, "inputs.last_frame_artifact_id"))
            if frame_results:
                ok = ok and all(frame_results)
                ratio_proof = ratio_proof or i2v and all(frame_results)
            if not ratio_proof:
                self.add(nid, "params.ratio", "not_covered", "VIDEO_RATIO_OR_I2V_FRAME_PROOF_REQUIRED")
                ok = False
            # r2v/transform references and generate_image reference images are
            # identity/content evidence, not an output-aspect proof.
        else:
            ok = self.add(nid, "outputs." + output, "not_covered", "OUTPUT_GEOMETRY_UNSUPPORTED")
        self.visiting.remove(marker)
        self.memo[marker] = ok
        return ok

    def run(self):
        ratio = self.brief.get("aspect_ratio")
        self.add(None, "brief.aspect_ratio", "not_covered" if ratio is None else "passed" if ratio == self.expected else "failed",
                 "BRIEF_EXPLICIT_RATIO", expected=self.expected)
        targets = self.plan.get("deliverables") or []
        if not self.nodes or not targets:
            self.add(None, "deliverables", "not_covered", "PLAN_DELIVERY_MISSING")
        for target in targets:
            nid, output, kind = target.get("node_id"), target.get("output"), target.get("kind")
            node = self.nodes.get(nid, {})
            value = {"ref": f"{nid}.{output}"}
            if kind == "image":
                if self.brief.get("deliverable") == "video" and nid in self.cast:
                    self.auxiliary_cast.add(nid)
                else:
                    self.media(value, "image", "deliverable", "image")
            elif kind == "video":
                self.master_refs[_key(value)] = value
                self.media(value, "video", "deliverable", "video")
            elif kind == "package" and node.get("tool") == "package_story" and output == "artifact_id":
                for field in ("artifact_id", "compressed_artifact_id"):
                    source = (node.get("inputs") or {}).get(field)
                    if source is not None:
                        self.master_refs[_key(source)] = source
                        self.media(source, "video", nid, "inputs." + field)
            else:
                self.add(nid, "deliverables", "not_covered", "DELIVERY_GEOMETRY_UNSUPPORTED")
        primary = {key: value for key, value in self.master_refs.items() if key is not None and not key.endswith(".compressed_artifact_id")}
        for master, source in primary.items():
            matches = [node for node in self.nodes.values() if node.get("tool") == "qc_video"
                       and _key((node.get("inputs") or {}).get("artifact_id")) == master]
            if not matches:
                self.add(None, "qc_video", "not_covered", "MATCHING_MASTER_QC_MISSING")
            for qc in matches:
                nid = qc["id"]
                self.qcs.add(nid)
                self.target(qc)
                ref = _reference(source)
                source_size = self.geometry.get(ref[0]) if ref else None
                qc_size = self.geometry.get(nid)
                self.add(nid, "inputs.target_size", "not_covered" if source_size is None or qc_size is None
                         else "passed" if source_size == qc_size else "failed", "QC_MATCHES_MASTER_CANVAS")
        if not self.compositions:
            self.add(None, "compose_video", "not_covered", "C7_COMPOSITION_NOT_COVERED")
        if not self.qcs:
            self.add(None, "qc_video", "not_covered", "C7_FINAL_QC_NOT_COVERED")
        statuses = {item["status"] for item in self.checks}
        status = "failed" if "failed" in statuses else "not_covered" if "not_covered" in statuses else "passed"
        if ratio is None or self.brief.get("deliverable") not in {"video", "image"}:
            # Without the persisted brief even the auxiliary-cast exemption
            # cannot be established; do not label conditional findings final.
            status = "not_covered"
        return {"status": status, "expected_ratio": self.expected, "checks": self.checks,
                "required_image_nodes": sorted(self.images), "required_video_nodes": sorted(self.videos),
                "compose_nodes": sorted(self.compositions), "qc_nodes": sorted(self.qcs),
                "structural_cast_nodes": sorted(self.cast),
                "exempt_auxiliary_cast_nodes": sorted(self.auxiliary_cast - self.images),
                "reference_only_cast_nodes": sorted(self.cast - self.images),
                "media_edges": self.edges,
                "assessment": "archived_plan_intent_only; actual_pixels_SAR_provider_quality_not_assessed"}
