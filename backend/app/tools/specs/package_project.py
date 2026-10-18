from pydantic import BaseModel, ConfigDict, Field

from app.api import AppError
from app.services.job_package_service import JobPackageService
from app.services.job_service import JobService
from app.tools.permissions import PRODUCTION, SYSTEM, WRITE
from app.tools.spec import ToolContext, ToolSpec

TERMINAL_STATUSES = {"success", "partial_success", "failed", "cancelled"}


class PackageProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_ids: list[str] = Field(min_length=1, max_length=20)


class PackageRef(BaseModel):
    job_id: str
    artifact_id: str
    download_url: str
    package_status: str
    included_counts: dict


class PackageError(BaseModel):
    job_id: str
    code: str
    message: str


class PackageProjectOutput(BaseModel):
    packages: list[PackageRef]
    errors: list[PackageError]


def run(data: PackageProjectInput, ctx: ToolContext):
    packages, errors = [], []
    for job_id in dict.fromkeys(data.job_ids):
        try:
            job = JobService.get_job(job_id)
            if job.status not in TERMINAL_STATUSES:
                raise AppError("JOB_NOT_FINISHED", f"Job is still {job.status}", 409)
            result = JobPackageService.create_or_refresh(job)
        except AppError as error:
            errors.append(PackageError(job_id=job_id, code=error.code, message=error.message))
            continue
        packages.append(
            PackageRef(
                job_id=job_id,
                artifact_id=result["artifact"]["artifact_id"],
                download_url=result["download_url"],
                package_status=result["package_status"],
                included_counts=result["included_counts"],
            )
        )
    if not packages:
        raise AppError(
            "NO_PACKABLE_CONTENT",
            "None of the requested jobs could be packaged",
            400,
            payload={"errors": [error.model_dump() for error in errors]},
        )
    return PackageProjectOutput(packages=packages, errors=errors)


SPEC = ToolSpec(
    name="package_project",
    description=(
        "Export finished jobs as downloadable ZIP packages (videos, images, prompts, manifest), "
        "one package per job. Does not stitch shots into a single video."
    ),
    input_model=PackageProjectInput,
    output_model=PackageProjectOutput,
    handler=run,
    permission=WRITE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}),
    timeout_sec=120,
    # Packages must reflect the latest job state, so repeated calls re-run.
    dedupe=False,
    max_retries=0,
)
