
import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path

import requests
from redis import Redis
from minio import Minio

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_SERVER_PORT", "6379"))
MINIO_HOST = os.getenv("MINIO_HOST", "localhost:9000")
MINIO_USER = os.getenv("MINIO_USER", "rootuser")
MINIO_PASSWORD = os.getenv("MINIO_PASSWORD", "rootpass123")

QUEUE_KEY = "toWorkers"

redis_client = Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    socket_timeout=None,
    decode_responses=True,
    socket_connect_timeout=10,
    health_check_interval=30
)

minio_client = Minio(
    MINIO_HOST,
    access_key=MINIO_USER,
    secret_key=MINIO_PASSWORD,
    secure=False
)


def log_info(message):
    print(f"WORKER: {message}", flush=True)
    redis_client.lpush("logging", f"WORKER: {message}")


def process_job(job):
    songhash = job["songhash"]
    model = job.get("model", "htdemucs")

    if model != "htdemucs":
        raise ValueError(f"Unsupported model: {model}")

    log_info(f"Processing {songhash}")

    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        input_file = temp_path / f"{songhash}.mp3"
        output_dir = temp_path / "output"

        # Retrieve original MP3 from RustFS
        minio_client.fget_object(
            "queue",
            f"{songhash}.mp3",
            str(input_file)
        )

        # Run Demucs music separation
        command = [
            sys.executable,
            "-m",
            "demucs.separate",
            "--mp3",
            "-n",
            model,
            "--out",
            str(output_dir),
            str(input_file)
        ]

        subprocess.run(command, check=True)

        stems_dir = output_dir / model / songhash

        for part in ["bass", "drums", "vocals", "other"]:
            file_path = stems_dir / f"{part}.mp3"

            if not file_path.exists():
                raise FileNotFoundError(str(file_path))

            # Upload separated track to RustFS
            minio_client.fput_object(
                "output",
                f"{songhash}-{part}.mp3",
                str(file_path),
                content_type="audio/mpeg"
            )

            log_info(f"Uploaded {part}.mp3")

    log_info(f"Completed {songhash}")

    # Callback is optional
    callback = job.get("callback")

    if isinstance(callback, dict) and callback.get("url"):
        try:
            requests.post(
                callback["url"],
                json=callback.get("data", {}),
                timeout=10
            )
        except requests.RequestException as error:
            log_info(f"Callback failed: {error}")


def main():
    log_info("Worker started")

    while True:
        try:
            result = redis_client.blpop(QUEUE_KEY, timeout=0)

            if result is None:
                continue

            _, message = result
            job = json.loads(message)

            process_job(job)

        except Exception as error:
            log_info(f"Worker error: {error}")


if __name__ == "__main__":
    main()
