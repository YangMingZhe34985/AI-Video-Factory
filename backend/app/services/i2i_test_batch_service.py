import random
from pathlib import Path

from flask import current_app

from app.api import AppError
from app.extensions import db
from app.models import Job, JobNodeRun
from app.services.artifact_service import ArtifactService
from app.services.event_service import EventService
from app.services.storage_service import StorageService


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
TEST_MODES = {"single_male", "single_female", "couple"}

# Maps the UI test mode to the model API shot_type enum.
# single_male / single_female -> single ; couple -> multi
MODE_TO_SHOT_TYPE = {
    "single_male": "single",
    "single_female": "single",
    "couple": "multi",
}


class I2ITestBatchService:
    @staticmethod
    def shot_type_for_mode(mode: str | None) -> str:
        """Convert a UI test mode into the model API shot_type enum value."""
        return MODE_TO_SHOT_TYPE.get(str(mode or "").strip(), "single")

    @staticmethod
    def prepare_batch(
        job: Job, node_run: JobNodeRun, node_config: dict | None = None
    ) -> dict:
        config = I2ITestBatchService.config_for_job(job, node_config=node_config)
        male_images = I2ITestBatchService._image_pool(config["male_dataset_dir"])
        female_images = I2ITestBatchService._image_pool(config["female_dataset_dir"])

        mode = config["mode"]
        if mode in {"single_male", "couple"} and not male_images:
            raise AppError(
                "DEPENDENCY_MISSING",
                f"No male test images found in {config['male_dataset_dir']}",
                400,
            )
        if mode in {"single_female", "couple"} and not female_images:
            raise AppError(
                "DEPENDENCY_MISSING",
                f"No female test images found in {config['female_dataset_dir']}",
                400,
            )

        rng = random.SystemRandom()
        items = []
        for index in range(1, config["test_count"] + 1):
            role_sources = I2ITestBatchService._select_sources(mode, male_images, female_images, rng)
            copied_sources = []
            for role, source_path in role_sources:
                copied = I2ITestBatchService._copy_source(job, index, role, source_path)
                artifact = ArtifactService.register_artifact(
                    job,
                    copied,
                    "i2i_test_source_image",
                    branch_key="i2i_test",
                    node_run=node_run,
                    metadata={
                        "test_index": index,
                        "role": role,
                        "source_dataset_path": str(source_path),
                    },
                )
                copied_sources.append(
                    {
                        "role": role,
                        "file_path": copied,
                        "artifact_id": artifact.artifact_id,
                        "source_dataset_path": str(source_path),
                    }
                )

            primary = next(
                (item for item in copied_sources if item["role"] == "female"),
                copied_sources[0],
            )
            items.append(
                {
                    "test_index": index,
                    "mode": mode,
                    "source_images": copied_sources,
                    "primary_role": primary["role"],
                    "primary_image": primary["file_path"],
                }
            )

        batch = {
            "mode": mode,
            "test_count": config["test_count"],
            "image_model": config["image_model"],
            "i2v_model": config["i2v_model"],
            "male_dataset_dir": config["male_dataset_dir"],
            "female_dataset_dir": config["female_dataset_dir"],
            "items": items,
        }
        batch_path = StorageService.write_job_json(
            job.job_id, ["raw", "i2i_test_batch.json"], batch
        )
        ArtifactService.register_artifact(
            job,
            batch_path,
            "i2i_test_batch",
            branch_key="i2i_test",
            node_run=node_run,
            metadata={"test_count": config["test_count"], "mode": mode},
        )
        job.config = {**(job.config or {}), "i2i_test_batch": batch}
        db.session.flush()
        EventService.record(
            job,
            "I2I_TEST_BATCH_PREPARED",
            message=f"I2I test batch prepared: {config['test_count']} item(s)",
            node_key=node_run.node_key,
            payload={"mode": mode, "test_count": config["test_count"]},
        )
        return batch

    @staticmethod
    def config_for_job(job: Job, node_config: dict | None = None) -> dict:
        job_config = job.config or {}
        node_i2i = dict((node_config or {}).get("i2i_test") or {})
        test_config = {**node_i2i, **dict(job_config.get("i2i_test") or {})}
        models = dict(job_config.get("models") or {})
        node_models = dict(job_config.get("node_models") or {})
        mode = str(test_config.get("mode") or "couple").strip()
        if mode not in TEST_MODES:
            raise AppError(
                "INVALID_INPUT",
                "i2i_test.mode must be one of: single_male, single_female, couple",
                400,
            )
        try:
            test_count = int(test_config.get("test_count") or 3)
        except (TypeError, ValueError):
            raise AppError("INVALID_INPUT", "i2i_test.test_count must be an integer", 400)
        if test_count < 1 or test_count > 20:
            raise AppError("INVALID_INPUT", "i2i_test.test_count must be between 1 and 20", 400)

        return {
            "enabled": bool(test_config.get("enabled", False)),
            "mode": mode,
            "test_count": test_count,
            "image_model": (
                test_config.get("image_model")
                or node_models.get("submit_i2i_test_image")
                or models.get("i2i_test_image")
                or current_app.config["DEFAULT_I2I_TEST_IMAGE_MODEL"]
            ),
            "i2v_model": (
                test_config.get("i2v_model")
                or node_models.get("submit_i2i_test_i2v")
                or models.get("i2i_test_i2v")
                or current_app.config["DEFAULT_I2I_TEST_I2V_MODEL"]
            ),
            "male_dataset_dir": str(
                test_config.get("male_dataset_dir")
                or current_app.config["I2I_TEST_MALE_DATASET_DIR"]
            ),
            "female_dataset_dir": str(
                test_config.get("female_dataset_dir")
                or current_app.config["I2I_TEST_FEMALE_DATASET_DIR"]
            ),
        }

    @staticmethod
    def _select_sources(mode: str, male_images: list[Path], female_images: list[Path], rng) -> list[tuple[str, Path]]:
        if mode == "single_male":
            return [("male", rng.choice(male_images))]
        if mode == "single_female":
            return [("female", rng.choice(female_images))]
        return [("male", rng.choice(male_images)), ("female", rng.choice(female_images))]

    @staticmethod
    def _image_pool(raw_dir: str) -> list[Path]:
        for directory in I2ITestBatchService._candidate_dataset_dirs(raw_dir):
            if directory.exists() and directory.is_dir():
                return sorted(
                    item.resolve()
                    for item in directory.iterdir()
                    if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
                )
        return []

    @staticmethod
    def _candidate_dataset_dirs(raw_dir: str) -> list[Path]:
        primary = I2ITestBatchService._resolve_dataset_dir(raw_dir)
        candidates = [primary]
        path = Path(raw_dir)
        parts = [part.lower() for part in path.parts]
        if len(parts) >= 3 and parts[0] == "storage" and parts[1] == "personas":
            fallback = (
                I2ITestBatchService._project_root()
                / "workspace"
                / "personas"
                / Path(*path.parts[2:])
            )
            if fallback.resolve() != primary.resolve():
                candidates.append(fallback.resolve())
        return candidates

    @staticmethod
    def _resolve_dataset_dir(raw_dir: str) -> Path:
        path = Path(raw_dir)
        if path.is_absolute():
            return path.resolve()
        if path.parts and path.parts[0].lower() == "workspace":
            return (I2ITestBatchService._project_root() / path).resolve()
        if path.parts and path.parts[0].lower() == "storage":
            return (StorageService.root().parent / path).resolve()
        return StorageService.resolve(path)

    @staticmethod
    def _project_root() -> Path:
        return Path(current_app.root_path).resolve().parents[1]

    @staticmethod
    def _copy_source(job: Job, test_index: int, role: str, source_path: Path) -> str:
        suffix = source_path.suffix.lower() or ".bin"
        return StorageService.copy_into_job(
            job.job_id,
            source_path,
            ["raw", "i2i_test_sources", f"test_{test_index:03d}_{role}{suffix}"],
        )
