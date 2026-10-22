"""Independent positive/negative geometry fixtures; no application or I/O."""
from copy import deepcopy
import unittest

from scripts.v3_eval.aspect_evidence import inspect_aspect_chain


def fixture():
    nodes = [{"id": "actor_a", "tool": "generate_image", "params": {"n": 1, "size": "1024*1024"},
              "gate": "preview", "characters": ["alice"], "inputs": {"prompt": "a"}},
             {"id": "actor_b", "tool": "generate_image", "params": {"n": 1, "size": "1024*1024"},
              "gate": "preview", "characters": ["bob"], "inputs": {"prompt": "b"}}]
    for index in range(12):
        nodes += [{"id": f"kf_{index}", "tool": "generate_image", "params": {"size": "1280*720"},
                   "inputs": {"mode": "i2i", "reference_artifact_ids": [{"ref": "actor_a.image"}, {"ref": "actor_b.image"}]}},
                  {"id": f"shot_{index}", "tool": "animate_shot", "params": {"duration": 10},
                   "inputs": {"first_frame_artifact_id": {"ref": f"kf_{index}.image"}, "prompt": "16:9"}}]
    clips = [{"ref": f"shot_{i}.video"} for i in range(12)]
    target = {"target_aspect_ratio": "16:9", "target_size": "1280*720"}
    nodes += [{"id": "master", "tool": "compose_video", "inputs": {**target, "video_artifact_ids": clips}},
              {"id": "qc", "tool": "qc_video", "inputs": {**target, "artifact_id": {"ref": "master.artifact_id"}, "video_artifact_ids": clips}},
              {"id": "package", "tool": "package_story", "inputs": {"artifact_id": {"ref": "master.artifact_id"}}, "depends_on": ["qc"]}]
    plan = {"nodes": nodes, "character_references": {"alice": [{"ref": "actor_a.image"}], "bob": [{"ref": "actor_b.image"}]},
            "deliverables": [{"kind": "package", "node_id": "package", "output": "artifact_id"},
                             {"kind": "image", "node_id": "actor_a", "output": "images"},
                             {"kind": "image", "node_id": "actor_b", "output": "image"}]}
    return plan, {"deliverable": "video", "aspect_ratio": "16:9"}


def find(plan, node_id):
    return next(node for node in plan["nodes"] if node["id"] == node_id)


class AspectTests(unittest.TestCase):
    def test_twelve_shot_chain_and_square_cast_exemption(self):
        plan, brief = fixture()
        before = deepcopy((plan, brief))
        result = inspect_aspect_chain(plan, brief)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["required_image_nodes"]), 12)
        self.assertEqual(len(result["required_video_nodes"]), 12)
        self.assertEqual(result["exempt_auxiliary_cast_nodes"], ["actor_a", "actor_b"])
        self.assertEqual(result["compose_nodes"], ["master"])
        self.assertEqual(result["qc_nodes"], ["qc"])
        self.assertEqual((plan, brief), before)
        self.assertIn("actual_pixels_SAR_provider_quality_not_assessed", result["assessment"])

    def test_wrong_frame_size_fails_despite_prompt_and_video_ratio(self):
        plan, brief = fixture()
        find(plan, "kf_0")["params"]["size"] = "1024*1024"
        find(plan, "shot_0")["params"]["ratio"] = "16:9"
        result = inspect_aspect_chain(plan, brief)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(c["node_id"] == "kf_0" and c["code"] == "ASPECT_MISMATCH" for c in result["checks"]))

    def test_explicit_wrong_video_ratio_is_not_overridden_by_good_frame(self):
        plan, brief = fixture()
        find(plan, "shot_0")["params"]["ratio"] = "9:16"
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "failed")

    def test_cast_used_as_first_or_last_frame_loses_exemption(self):
        for field in ("first_frame_artifact_id", "last_frame_artifact_id"):
            with self.subTest(field=field):
                plan, brief = fixture()
                find(plan, "shot_0")["inputs"][field] = {"ref": "actor_a.image"}
                result = inspect_aspect_chain(plan, brief)
                self.assertEqual(result["status"], "failed")
                self.assertIn("actor_a", result["required_image_nodes"])
                self.assertNotIn("actor_a", result["exempt_auxiliary_cast_nodes"])

    def test_selector_requires_every_candidate(self):
        plan, brief = fixture()
        plan["nodes"].append({"id": "pick", "tool": "select_image", "inputs": {
            "candidate_artifact_ids": [{"ref": "kf_0.image"}, {"ref": "kf_1.image"}]}})
        find(plan, "shot_0")["inputs"]["first_frame_artifact_id"] = {"ref": "pick.image"}
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "passed")
        find(plan, "kf_1")["params"]["size"] = "720*1280"
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "failed")

    def test_dependencies_and_free_text_cannot_prove_geometry(self):
        plan, brief = fixture()
        shot = find(plan, "shot_0")
        shot["inputs"] = {"prompt": "16:9, use kf_0"}
        shot["depends_on"] = ["kf_0"]
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "not_covered")

    def test_missing_brief_or_size_never_passes(self):
        plan, brief = fixture()
        self.assertEqual(inspect_aspect_chain(plan, {})["status"], "not_covered")
        find(plan, "kf_0")["params"].pop("size")
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "not_covered")

    def test_canvas_requires_exact_legal_even_pixels(self):
        for size in ("1366*768", "16*9", "16384*9216", "1280x720"):
            with self.subTest(size=size):
                plan, brief = fixture()
                find(plan, "master")["inputs"]["target_size"] = size
                self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "failed")

    def test_qc_must_match_same_master_and_canvas(self):
        plan, brief = fixture()
        find(plan, "qc")["inputs"]["target_size"] = "1920*1080"
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "failed")
        find(plan, "qc")["inputs"]["artifact_id"] = {"ref": "other.artifact_id"}
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "not_covered")

    def test_cast_label_without_catalog_is_not_exempt(self):
        plan, brief = fixture()
        plan["character_references"] = {}
        find(plan, "actor_a")["stage"] = "cast_reference"
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "failed")

    def test_shared_catalog_root_is_not_exempt(self):
        plan, brief = fixture()
        plan["character_references"]["bob"] = [{"ref": "actor_a.image"}]
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "failed")

    def test_t2v_r2v_transform_use_output_ratio_not_reference_geometry(self):
        for tool, extra in (("generate_video", {"mode": "t2v"}),
                            ("generate_video", {"mode": "r2v", "reference_artifact_ids": [{"ref": "actor_a.image"}]}),
                            ("transform_video", {"operation": "reference", "media": [{"type": "reference_image", "artifact_id": {"ref": "actor_a.image"}}]})):
            with self.subTest(tool=tool, extra=extra):
                plan, brief = fixture()
                shot = find(plan, "shot_0")
                shot.update(tool=tool, inputs=extra)
                shot["params"]["ratio"] = "16:9"
                self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "passed")
                shot["params"].pop("ratio")
                self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "not_covered")

    def test_artifact_dimensions_require_independent_verified_evidence(self):
        plan, brief = fixture()
        find(plan, "shot_0")["inputs"]["first_frame_artifact_id"] = {"artifact": "uploaded"}
        plan["input_artifact_metadata"] = {"uploaded": {"verified": True, "width": 1280, "height": 720}}
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "not_covered")
        evidence = {"uploaded": {"verified": True, "width": 1280, "height": 720}}
        self.assertEqual(inspect_aspect_chain(plan, brief, evidence)["status"], "passed")
        evidence["uploaded"]["width"] = 720
        self.assertEqual(inspect_aspect_chain(plan, brief, evidence)["status"], "failed")

    def test_wrong_output_alias_and_missing_node_never_pass(self):
        for reference in ("kf_0.picture", "missing.image"):
            plan, brief = fixture()
            find(plan, "shot_0")["inputs"]["first_frame_artifact_id"] = {"ref": reference}
            self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "not_covered")

    def test_unknown_and_cyclic_chain_do_not_recurse_forever(self):
        plan, brief = fixture()
        find(plan, "kf_0").update(tool="extract_frame", inputs={"video_artifact_id": {"ref": "shot_0.video"}})
        find(plan, "shot_0")["inputs"]["first_frame_artifact_id"] = {"ref": "kf_0.artifact_id"}
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "failed")

    def test_extract_frame_uses_its_video_data_source(self):
        plan, brief = fixture()
        plan["nodes"].append({"id": "source_clip", "tool": "generate_video", "inputs": {"mode": "t2v"}, "params": {"ratio": "16:9"}})
        find(plan, "kf_0").update(tool="extract_frame", inputs={"video_artifact_id": {"ref": "source_clip.video"}})
        find(plan, "shot_0")["inputs"]["first_frame_artifact_id"] = {"ref": "kf_0.artifact_id"}
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "passed")
        find(plan, "source_clip")["params"]["ratio"] = "9:16"
        self.assertEqual(inspect_aspect_chain(plan, brief)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
