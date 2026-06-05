# -*- coding: utf-8 -*-
"""
Wan2.7 Image -> HappyHorse I2V workflow (REST HTTP)

Workflow:
1) Use wan2.7-image / wan2.7-image-pro to generate a first-frame image from text.
2) Use happyhorse-1.0-i2v to generate video from the first frame + prompt.

Notes:
- This script keeps the generated first frame as reusable asset/cover in output dirs.
- Supports both modes for wan2.7:
  - t2i: no reference_images passed.
  - i2i: pass reference_images (local path / http(s) / oss://).

Enhanced features (style aligned with video_generate_wan2.6-r2v.py):
- Separate prompt roots for first-frame image prompt and video prompt
  while sharing the same (series_name, template_name).
- HTTP create/poll flow with requests retry.
- Output layout:
  ./Results/<series>/<template>/<run_id>/ and ./Results/<series>/<template>/latest/
- Resume support for i2v polling with existing task_id.
- Auto download generated first frame and final video with retry.

Dependencies: pip install requests
"""

import os
import json
import time
import shutil
from pathlib import Path
from typing import Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# -------------------------
# Config
# -------------------------
API_KEY = os.getenv("DASHSCOPE_API_KEY")
assert API_KEY, "No API-key provided. Please set DASHSCOPE_API_KEY."

# Beijing endpoint by default:
# https://dashscope.aliyuncs.com/api/v1
# Singapore endpoint:
# https://dashscope-intl.aliyuncs.com/api/v1
BASE_URL = "https://dashscope.aliyuncs.com/api/v1"

WAN27_SYNC_URL = f"{BASE_URL}/services/aigc/multimodal-generation/generation"
HAPPYHORSE_CREATE_URL = f"{BASE_URL}/services/aigc/video-generation/video-synthesis"
TASK_URL_TPL = f"{BASE_URL}/tasks/{{task_id}}"

# IMPORTANT:
# Two prompt roots are intentionally different.
# - PROMPTS_ROOT_WAN27_IMAGE: prompt for wan2.7 image generation.
# - PROMPTS_ROOT_HAPPYHORSE_I2V: prompt for happyhorse image-to-video.
PROMPTS_ROOT_WAN27_IMAGE = Path("./Prompts/Wan2.7_Image")
PROMPTS_ROOT_HAPPYHORSE_I2V = Path("./Prompts/Wan2.6_I2V")

RESULTS_ROOT = Path("./Results/New")
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}
SUPPORTED_WAN27_MODELS = {"wan2.7-image", "wan2.7-image-pro"}
SUPPORTED_HAPPYHORSE_MODELS = {"happyhorse-1.0-i2v"}


# -------------------------
# HTTP Session with Retry
# -------------------------
def build_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = build_session()


# -------------------------
# Helpers
# -------------------------
def safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in s)


def normalize_to_path(p: Union[str, Path]) -> Path:
    if isinstance(p, Path):
        return p.expanduser().resolve()
    s = str(p).strip()
    if s.startswith("file://"):
        s2 = s.replace("file://", "", 1)
        if os.name == "nt" and s2.startswith("/") and len(s2) > 3 and s2[2] == ":":
            s2 = s2[1:]
        return Path(s2).expanduser().resolve()
    return Path(s).expanduser().resolve()


def is_remote_url(s: str) -> bool:
    v = s.strip().lower()
    return v.startswith("http://") or v.startswith("https://") or v.startswith("oss://")


def normalize_reference_inputs(
    reference_images: Optional[
        Union[str, Path, list[Union[str, Path]], tuple[Union[str, Path], ...]]
    ]
) -> list[Union[str, Path]]:
    if reference_images is None:
        return []
    if isinstance(reference_images, (str, Path)):
        one = str(reference_images).strip()
        return [] if not one else [reference_images]
    if isinstance(reference_images, (list, tuple)):
        cleaned = []
        for one in reference_images:
            if one is None:
                continue
            if isinstance(one, Path):
                cleaned.append(one)
                continue
            s = str(one).strip()
            if s:
                cleaned.append(one)
        return cleaned
    raise TypeError("reference_images must be None / str / Path / list / tuple.")


def make_run_id(root_dir: Path) -> str:
    base = time.strftime("%Y%m%d_%H%M%S")
    run_id = base
    suffix = 2
    while (root_dir / run_id).exists():
        run_id = f"{base}_{suffix:02d}"
        suffix += 1
    return run_id


def dump_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def dump_json_to_dirs(obj, dirs: list[Path], filename: str) -> None:
    for directory in dirs:
        dump_json(obj, directory / filename)


def write_text_to_dirs(text: str, dirs: list[Path], filename: str) -> None:
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_text(text, encoding="utf-8")


def load_prompt(prompt_root: Path, series_name: str, template_name: str) -> str:
    prompt_path = prompt_root / series_name / f"{template_name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def save_task_meta(path: Path, data: dict) -> None:
    dump_json(data, path)


def load_task_meta(path: Path) -> Optional[dict]:
    return load_json(path)


def copy_local_sources_to_dirs(local_sources: dict[str, Path], dirs: list[Path]) -> None:
    for directory in dirs:
        source_dir = directory / "source_inputs"
        if source_dir.exists():
            shutil.rmtree(source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)

        for tag, source_path in local_sources.items():
            if not source_path.exists():
                raise FileNotFoundError(f"Local file not found: {source_path}")
            suffix = source_path.suffix or ""
            target_name = f"{tag}{suffix}"
            shutil.copy2(source_path, source_dir / target_name)


def download_file(url: str, save_path: Path, timeout: int = 600, max_attempts: int = 5) -> None:
    save_path.parent.mkdir(parents=True, exist_ok=True)

    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            with SESSION.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                tmp_path = save_path.with_suffix(save_path.suffix + ".part")
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                tmp_path.replace(save_path)
                return
        except Exception as e:
            last_err = e
            print(f"[download] attempt {attempt}/{max_attempts} failed: {e}")
            if attempt < max_attempts:
                time.sleep(min(3 * attempt, 15))

    raise RuntimeError(f"Download failed after {max_attempts} attempts: {last_err}")


def upload_local_file_get_oss_url(
    api_key: str,
    model_name: str,
    file_path: Union[str, Path],
) -> str:
    local_path = normalize_to_path(file_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    policy_resp = SESSION.get(
        f"{BASE_URL}/uploads",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        params={"action": "getPolicy", "model": model_name},
        timeout=60,
    )
    policy_resp.raise_for_status()
    p = policy_resp.json()["data"]

    file_name = local_path.name
    key = f"{p['upload_dir']}/{file_name}"
    with open(local_path, "rb") as f:
        files = {
            "OSSAccessKeyId": (None, p["oss_access_key_id"]),
            "Signature": (None, p["signature"]),
            "policy": (None, p["policy"]),
            "x-oss-object-acl": (None, p["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, p["x_oss_forbid_overwrite"]),
            "key": (None, key),
            "success_action_status": (None, "200"),
            "file": (file_name, f),
        }
        up_resp = SESSION.post(p["upload_host"], files=files, timeout=300)
        up_resp.raise_for_status()

    bucket = p.get("bucket") or p.get("oss_bucket") or p.get("bucket_name")
    if bucket:
        return f"oss://{bucket}/{key}"
    return f"oss://{key}"


def resolve_input_to_url(
    *,
    api_key: str,
    model: str,
    input_value: Union[str, Path],
    input_name: str,
) -> tuple[str, Optional[Path]]:
    raw = str(input_value).strip()
    if is_remote_url(raw):
        return raw, None

    local_path = normalize_to_path(input_value)
    if local_path.is_dir():
        raise ValueError(f"{input_name} is a directory, expected an image file: {local_path}")
    oss_url = upload_local_file_get_oss_url(api_key, model, local_path)
    print(f"[upload] {input_name}: {oss_url}")
    return oss_url, local_path


def resolve_reference_image_urls(
    *,
    api_key: str,
    model: str,
    reference_images: list[Union[str, Path]],
) -> tuple[list[str], dict[str, Path]]:
    urls = []
    local_sources = {}
    for idx, one in enumerate(reference_images, start=1):
        url, local_path = resolve_input_to_url(
            api_key=api_key,
            model=model,
            input_value=one,
            input_name=f"wan27_ref_{idx}",
        )
        urls.append(url)
        if local_path is not None:
            local_sources[f"wan27_ref_{idx:02d}"] = local_path
    return urls, local_sources


def build_wan27_content(reference_urls: list[str], prompt_text: str) -> list[dict]:
    content = []
    for one_url in reference_urls:
        content.append({"image": one_url})
    content.append({"text": prompt_text})
    return content


def copy_first_frame_to_latest(run_dir: Path, latest_dir: Path) -> None:
    src = run_dir / "first_frame.png"
    if src.exists():
        latest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, latest_dir / "first_frame.png")


def extract_first_frame_url(image_data: dict) -> Optional[str]:
    output = image_data.get("output", {})
    choices = output.get("choices")
    if not isinstance(choices, list):
        return None
    for choice in choices:
        message = choice.get("message", {})
        content_list = message.get("content", [])
        if not isinstance(content_list, list):
            continue
        for one in content_list:
            if isinstance(one, dict) and one.get("type") == "image" and one.get("image"):
                return one["image"]
            if isinstance(one, dict) and one.get("image"):
                return one["image"]
    return None


def extract_video_url(task_data: dict) -> Optional[str]:
    output = task_data.get("output", {})
    if output.get("video_url"):
        return output["video_url"]
    results = output.get("results", {})
    if isinstance(results, dict):
        return results.get("video_url")
    return None


# -------------------------
# Task polling
# -------------------------
def poll_task_until_done(
    *,
    api_key: str,
    task_id: str,
    latest_dir: Path,
    run_dir: Path,
    poll_interval_sec: int = 3,
    max_consecutive_errors: int = 20,
) -> dict:
    headers_get = {"Authorization": f"Bearer {api_key}"}
    consecutive_errors = 0
    last_data = None
    state_dirs = [latest_dir, run_dir]

    while True:
        try:
            r = SESSION.get(TASK_URL_TPL.format(task_id=task_id), headers=headers_get, timeout=60)
            r.raise_for_status()
            last_data = r.json()
            dump_json_to_dirs(last_data, state_dirs, "response.json")

            status = last_data["output"]["task_status"]
            print("status:", status)

            meta = load_task_meta(latest_dir / "task_meta.json") or load_task_meta(run_dir / "task_meta.json") or {}
            meta["task_id"] = task_id
            meta["status"] = status
            meta["updated_at"] = int(time.time())
            dump_json_to_dirs(meta, state_dirs, "task_meta.json")

            consecutive_errors = 0

            if status == "SUCCEEDED":
                return last_data

            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                output = last_data.get("output", {})
                code = output.get("code")
                message = output.get("message")
                raise RuntimeError(
                    f"Task ended with {status}, code={code}, message={message}. "
                    f"See {latest_dir / 'response.json'}"
                )

            time.sleep(poll_interval_sec)

        except Exception as e:
            consecutive_errors += 1
            print(f"[poll] consecutive error {consecutive_errors}/{max_consecutive_errors}: {e}")

            if consecutive_errors >= max_consecutive_errors:
                raise RuntimeError(
                    f"Polling failed too many times continuously. "
                    f"You can rerun the script to resume with existing task_id={task_id}."
                ) from e

            time.sleep(min(poll_interval_sec * consecutive_errors, 30))


# -------------------------
# Step 1: Generate first frame with wan2.7-image
# -------------------------
def create_first_frame_image(
    *,
    api_key: str,
    model: str,
    image_prompt_text: str,
    reference_image_urls: list[str],
    size: str,
    n: int,
    watermark: bool,
    thinking_mode: Optional[bool],
    state_dirs: list[Path],
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-OssResourceResolve": "enable",
    }

    payload = {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": build_wan27_content(reference_image_urls, image_prompt_text),
                }
            ]
        },
        "parameters": {
            "size": size,
            "n": n,
            "watermark": watermark,
        },
    }
    if thinking_mode is not None:
        payload["parameters"]["thinking_mode"] = thinking_mode

    dump_json_to_dirs(payload, state_dirs, "wan27_request_payload.json")

    resp = SESSION.post(WAN27_SYNC_URL, headers=headers, json=payload, timeout=180)

    try:
        image_data = resp.json()
    except Exception:
        image_data = {"text": resp.text}

    dump_json_to_dirs(image_data, state_dirs, "wan27_response.json")

    if resp.status_code >= 400:
        err_code = image_data.get("code")
        err_msg = image_data.get("message")
        raise RuntimeError(
            f"Wan2.7 image call failed: HTTP {resp.status_code}, code={err_code}, message={err_msg}. "
            f"See {state_dirs[0] / 'wan27_response.json'}"
        )

    return image_data


# -------------------------
# Step 2: Create happyhorse i2v task
# -------------------------
def create_happyhorse_i2v_task(
    *,
    api_key: str,
    model: str,
    video_prompt_text: str,
    first_frame_url: str,
    resolution: str,
    duration: int,
    watermark: bool,
    seed: Optional[int],
    state_dirs: list[Path],
    base_meta: dict,
) -> str:
    headers_create = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    params = {
        "resolution": resolution,
        "duration": duration,
        "watermark": watermark,
    }
    if seed is not None:
        params["seed"] = seed

    payload = {
        "model": model,
        "input": {
            "prompt": video_prompt_text,
            "media": [
                {
                    "type": "first_frame",
                    "url": first_frame_url,
                }
            ],
        },
        "parameters": params,
    }
    dump_json_to_dirs(payload, state_dirs, "happyhorse_request_payload.json")

    resp = SESSION.post(HAPPYHORSE_CREATE_URL, headers=headers_create, json=payload, timeout=60)

    try:
        create_data = resp.json()
    except Exception:
        create_data = {"text": resp.text}

    dump_json_to_dirs(create_data, state_dirs, "response.json")

    if resp.status_code >= 400:
        err_code = create_data.get("code")
        err_msg = create_data.get("message")
        raise RuntimeError(
            f"HappyHorse create failed: HTTP {resp.status_code}, code={err_code}, message={err_msg}. "
            f"See {state_dirs[0] / 'response.json'}"
        )

    task_id = create_data["output"]["task_id"]
    request_id = create_data.get("request_id")

    meta = dict(base_meta)
    meta.update({
        "task_id": task_id,
        "request_id": request_id,
        "happyhorse_model": model,
        "created_at": int(time.time()),
        "status": "SUBMITTED",
    })
    dump_json_to_dirs(meta, state_dirs, "task_meta.json")

    print("task_id:", task_id)
    if request_id:
        print("request_id:", request_id)

    return task_id


# -------------------------
# Main workflow
# -------------------------
def wan27_image_then_happyhorse_i2v_generate(
    *,
    series_name: str,
    template_name: str,
    reference_images: Optional[
        Union[str, Path, list[Union[str, Path]], tuple[Union[str, Path], ...]]
    ] = None,
    wan27_model: str = "wan2.7-image-pro",
    wan27_size: str = "2K",
    wan27_n: int = 1,
    wan27_watermark: bool = False,
    wan27_thinking_mode: Optional[bool] = None,
    happyhorse_model: str = "happyhorse-1.0-i2v",
    resolution: str = "720P",
    duration: int = 5,
    happyhorse_watermark: bool = False,
    seed: Optional[int] = None,
    poll_interval_sec: int = 8,
    force_new_task: bool = False,
) -> Path:
    if wan27_model not in SUPPORTED_WAN27_MODELS:
        raise ValueError(f"Unsupported wan27_model: {wan27_model}")
    if happyhorse_model not in SUPPORTED_HAPPYHORSE_MODELS:
        raise ValueError(f"Unsupported happyhorse_model: {happyhorse_model}")
    if wan27_n < 1 or wan27_n > 4:
        raise ValueError("wan27_n must be in [1, 4].")
    if duration < 3 or duration > 15:
        raise ValueError("duration must be in [3, 15] for happyhorse-1.0-i2v.")
    if seed is not None and (seed < 0 or seed > 2147483647):
        raise ValueError("seed must be in [0, 2147483647].")

    image_prompt_text = load_prompt(PROMPTS_ROOT_WAN27_IMAGE, series_name, template_name)
    video_prompt_text = load_prompt(PROMPTS_ROOT_HAPPYHORSE_I2V, series_name, template_name)
    normalized_refs = normalize_reference_inputs(reference_images)

    root_dir = RESULTS_ROOT / safe_name(series_name) / safe_name(template_name)
    latest_dir = root_dir / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)

    task_meta_path = latest_dir / "task_meta.json"
    existing_meta = load_task_meta(task_meta_path) or {}
    existing_task_id = None if force_new_task else existing_meta.get("task_id")
    existing_status = None if force_new_task else existing_meta.get("status")

    run_dir = None
    if not force_new_task:
        existing_run_dir = existing_meta.get("run_dir")
        existing_run_id = existing_meta.get("run_id")
        if existing_run_dir:
            run_dir = Path(existing_run_dir)
        elif existing_run_id:
            run_dir = root_dir / existing_run_id

    existing_video_path = existing_meta.get("video_path")
    if existing_video_path:
        video_exists = Path(existing_video_path).exists()
    elif run_dir is not None:
        video_exists = (run_dir / "video.mp4").exists()
    else:
        video_exists = False

    should_resume = bool(
        existing_task_id
        and not force_new_task
        and (
            existing_status not in TERMINAL_STATUSES
            or (existing_status == "SUCCEEDED" and not video_exists)
        )
    )

    if should_resume:
        if run_dir is None:
            run_id = make_run_id(root_dir)
            run_dir = root_dir / run_id
        else:
            run_id = run_dir.name

        run_dir.mkdir(parents=True, exist_ok=True)
        state_dirs = [latest_dir, run_dir]

        write_text_to_dirs(image_prompt_text, state_dirs, "wan27_prompt_used.txt")
        write_text_to_dirs(video_prompt_text, state_dirs, "happyhorse_prompt_used.txt")

        existing_meta.update({
            "series_name": series_name,
            "template_name": template_name,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "latest_dir": str(latest_dir),
            "updated_at": int(time.time()),
        })
        dump_json_to_dirs(existing_meta, state_dirs, "task_meta.json")

        copy_first_frame_to_latest(run_dir, latest_dir)

        print(f"resume existing task: {existing_task_id}")
        final_data = poll_task_until_done(
            api_key=API_KEY,
            task_id=existing_task_id,
            latest_dir=latest_dir,
            run_dir=run_dir,
            poll_interval_sec=poll_interval_sec,
        )

    else:
        run_id = make_run_id(root_dir)
        run_dir = root_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        state_dirs = [latest_dir, run_dir]

        write_text_to_dirs(image_prompt_text, state_dirs, "wan27_prompt_used.txt")
        write_text_to_dirs(video_prompt_text, state_dirs, "happyhorse_prompt_used.txt")

        reference_urls, local_sources = resolve_reference_image_urls(
            api_key=API_KEY,
            model=wan27_model,
            reference_images=normalized_refs,
        )
        if local_sources:
            copy_local_sources_to_dirs(local_sources, state_dirs)
        wan27_generation_mode = "t2i" if not reference_urls else "i2i"
        print(f"[wan27] generation_mode={wan27_generation_mode}, refs={len(reference_urls)}")

        wan27_response = create_first_frame_image(
            api_key=API_KEY,
            model=wan27_model,
            image_prompt_text=image_prompt_text,
            reference_image_urls=reference_urls,
            size=wan27_size,
            n=wan27_n,
            watermark=wan27_watermark,
            thinking_mode=wan27_thinking_mode,
            state_dirs=state_dirs,
        )

        first_frame_url = extract_first_frame_url(wan27_response)
        if not first_frame_url:
            raise RuntimeError(f"Wan2.7 image succeeded but no image url. See {latest_dir / 'wan27_response.json'}")

        print("first_frame_url:", first_frame_url)
        first_frame_path = run_dir / "first_frame.png"
        print("downloading first frame ->", first_frame_path)
        download_file(first_frame_url, first_frame_path)
        copy_first_frame_to_latest(run_dir, latest_dir)

        base_meta = {
            "series_name": series_name,
            "template_name": template_name,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "latest_dir": str(latest_dir),
            "wan27_model": wan27_model,
            "wan27_size": wan27_size,
            "wan27_n": wan27_n,
            "wan27_watermark": wan27_watermark,
            "wan27_thinking_mode": wan27_thinking_mode,
            "wan27_generation_mode": wan27_generation_mode,
            "wan27_reference_urls": reference_urls,
            "first_frame_url": first_frame_url,
            "first_frame_path": str(first_frame_path),
            "happyhorse_model": happyhorse_model,
            "resolution": resolution,
            "duration": duration,
            "happyhorse_watermark": happyhorse_watermark,
            "seed": seed,
            "status": "PREPARING",
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
        dump_json_to_dirs(base_meta, state_dirs, "task_meta.json")

        task_id = create_happyhorse_i2v_task(
            api_key=API_KEY,
            model=happyhorse_model,
            video_prompt_text=video_prompt_text,
            first_frame_url=first_frame_url,
            resolution=resolution,
            duration=duration,
            watermark=happyhorse_watermark,
            seed=seed,
            state_dirs=state_dirs,
            base_meta=base_meta,
        )

        final_data = poll_task_until_done(
            api_key=API_KEY,
            task_id=task_id,
            latest_dir=latest_dir,
            run_dir=run_dir,
            poll_interval_sec=poll_interval_sec,
        )

    video_path = run_dir / "video.mp4"
    video_url = extract_video_url(final_data)
    if not video_url:
        raise RuntimeError(f"SUCCEEDED but no video_url. See {latest_dir / 'response.json'}")

    print("video_url:", video_url)
    meta = load_task_meta(task_meta_path) or {}
    meta["status"] = "DOWNLOADING"
    meta["video_url"] = video_url
    meta["video_path"] = str(video_path)
    meta["updated_at"] = int(time.time())
    dump_json_to_dirs(meta, [latest_dir, run_dir], "task_meta.json")

    if video_path.exists():
        print("video already exists:", video_path)
    else:
        print("downloading ->", video_path)
        download_file(video_url, video_path)
        print("done:", video_path)

    meta = load_task_meta(task_meta_path) or {}
    meta["status"] = "SUCCEEDED"
    meta["video_url"] = video_url
    meta["video_path"] = str(video_path)
    meta["run_dir"] = str(run_dir)
    meta["latest_dir"] = str(latest_dir)
    meta["finished_at"] = int(time.time())
    meta["updated_at"] = int(time.time())
    dump_json_to_dirs(meta, [latest_dir, run_dir], "task_meta.json")

    return run_dir


# -------------------------
# Example
# -------------------------
if __name__ == "__main__":
    series_name = "Sweet Couple"
    template_name = "tmp9"

    # Optional reference image(s) for wan2.7:
    # - None / []     => t2i (default)
    # - local/remote  => i2i
    reference_images = [
        r"E:\Desktop\实习工作\正式工作\Task8\精选测试图集\female\fm_81.jpg",
        r"E:\Desktop\实习工作\正式工作\Task8\精选测试图集\male\ml_61.jpg",
    ]
    # reference_images = [r"E:\path\to\ref1.jpg", r"E:\path\to\ref2.png"]

    # Prompt files are loaded from different roots but same series/template name:
    # - ./Prompts/Wan2.7_Image/<series_name>/<template_name>.md
    # - ./Prompts/Wan2.6_I2V/<series_name>/<template_name>.md
    wan27_image_then_happyhorse_i2v_generate(
        series_name=series_name,
        template_name=template_name,
        reference_images=reference_images,
        wan27_model="wan2.7-image-pro",          # wan2.7-image / wan2.7-image-pro
        wan27_size="1080*1920",
        wan27_n=1,
        wan27_watermark=False,
        wan27_thinking_mode=None,
        happyhorse_model="happyhorse-1.0-i2v",
        resolution="720P",
        duration=5,
        happyhorse_watermark=False,
        seed=None,
        poll_interval_sec=8,
        force_new_task=False,                # resume old task by default
    )
