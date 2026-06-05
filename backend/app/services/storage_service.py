import base64
import shutil
from pathlib import Path

from flask import current_app

from app.utils.files import ensure_dir, guess_mime_type, safe_filename, write_json
from app.utils.ids import file_sha256


MOCK_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class StorageService:
    @staticmethod
    def ensure_storage_dirs(config: dict | None = None) -> None:
        cfg = config or current_app.config
        for key in ("STORAGE_ROOT", "UPLOAD_FOLDER"):
            ensure_dir(cfg[key])
        for child in ("jobs", "templates", "artifacts"):
            ensure_dir(Path(cfg["STORAGE_ROOT"]) / child)

    @staticmethod
    def root() -> Path:
        return Path(current_app.config["STORAGE_ROOT"]).resolve()

    @staticmethod
    def relative_path(path: str | Path) -> str:
        target = Path(path).resolve()
        try:
            return target.relative_to(StorageService.root()).as_posix()
        except ValueError:
            return target.as_posix()

    @staticmethod
    def resolve(path: str | Path) -> Path:
        target = Path(path)
        if target.is_absolute():
            return target
        return (StorageService.root() / target).resolve()

    @staticmethod
    def job_dir(job_id: str, *parts: str) -> Path:
        return ensure_dir(StorageService.root() / "jobs" / job_id / Path(*parts))

    @staticmethod
    def append_job_log(job_id: str, log_type: str, entry: dict) -> None:
        """Append one JSONL entry to storage/jobs/{job_id}/logs/{log_type}.log.

        Failures in this method are silently swallowed so logging never breaks the main flow.
        log_type examples: "error", "i2i_sample"
        """
        import json
        from datetime import datetime, timezone
        log_dir = StorageService.job_dir(job_id, "logs")
        log_file = log_dir / f"{log_type}.log"
        stamped = {"ts": datetime.now(timezone.utc).isoformat(), **entry}
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(stamped, ensure_ascii=False) + "\n")

    @staticmethod
    def save_source_video(file_storage, job_id: str) -> dict:
        filename = safe_filename(file_storage.filename, fallback=f"{job_id}.mp4")
        target = ensure_dir(Path(current_app.config["UPLOAD_FOLDER"])) / f"{job_id}_{filename}"
        file_storage.save(target)
        return {
            "file_path": StorageService.relative_path(target),
            "file_name": filename,
            "source_hash": file_sha256(target),
            "size": target.stat().st_size,
        }

    @staticmethod
    def save_reference_upload(file_storage, job_id: str) -> dict:
        filename = safe_filename(file_storage.filename, fallback="reference.bin")
        target = StorageService.job_dir(job_id, "raw", "uploads") / filename
        file_storage.save(target)
        return {
            "file_path": StorageService.relative_path(target),
            "file_name": filename,
            "mime_type": guess_mime_type(target),
            "size": target.stat().st_size,
        }

    @staticmethod
    def write_job_json(job_id: str, relative_parts: list[str], payload: dict) -> str:
        target = StorageService.root() / "jobs" / job_id / Path(*relative_parts)
        write_json(target, payload)
        return StorageService.relative_path(target)

    @staticmethod
    def write_text_artifact(job_id: str, relative_parts: list[str], content: str) -> str:
        target = StorageService.root() / "jobs" / job_id / Path(*relative_parts)
        ensure_dir(target.parent)
        target.write_text(content, encoding="utf-8")
        return StorageService.relative_path(target)

    @staticmethod
    def write_binary_artifact(job_id: str, relative_parts: list[str], content: bytes) -> str:
        target = StorageService.root() / "jobs" / job_id / Path(*relative_parts)
        ensure_dir(target.parent)
        target.write_bytes(content)
        return StorageService.relative_path(target)

    @staticmethod
    def write_mock_video(job_id: str, relative_parts: list[str], label: str) -> str:
        content = f"Mock video artifact generated for {label}.\n".encode("utf-8")
        return StorageService.write_binary_artifact(job_id, relative_parts, content)

    @staticmethod
    def write_mock_png(job_id: str, relative_parts: list[str]) -> str:
        return StorageService.write_binary_artifact(job_id, relative_parts, MOCK_PNG_BYTES)

    @staticmethod
    def copy_into_job(job_id: str, source_path: str | Path, relative_parts: list[str]) -> str:
        source = Path(source_path)
        target = StorageService.root() / "jobs" / job_id / Path(*relative_parts)
        ensure_dir(target.parent)
        shutil.copy2(source, target)
        return StorageService.relative_path(target)
