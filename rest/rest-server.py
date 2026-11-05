
import os
import io
import json
import base64
import hashlib

from flask import Flask, request, jsonify, send_file
from redis import Redis
from minio import Minio
from minio.error import S3Error

app = Flask(__name__)

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
    decode_responses=True
)

minio_client = Minio(
    MINIO_HOST,
    access_key=MINIO_USER,
    secret_key=MINIO_PASSWORD,
    secure=False
)


def log_info(message):
    print(f"REST: {message}", flush=True)
    redis_client.lpush("logging", f"REST: {message}")


@app.route("/", methods=["GET"])
def home():
    return "<h1>Music Separation Server</h1>", 200


@app.route("/apiv1/separate", methods=["POST"])
def separate():
    data = request.get_json(silent=True)

    if not isinstance(data, dict) or "mp3" not in data:
        return jsonify({"error": "Missing mp3 data"}), 400

    try:
        mp3_bytes = base64.b64decode(
            data["mp3"], validate=True
        )
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid base64 data"}), 400

    if not mp3_bytes:
        return jsonify({"error": "Empty MP3"}), 400

    songhash = hashlib.sha256(mp3_bytes).hexdigest()

    minio_client.put_object(
        "queue",
        f"{songhash}.mp3",
        io.BytesIO(mp3_bytes),
        length=len(mp3_bytes),
        content_type="audio/mpeg"
    )

    job = {
        "songhash": songhash,
        "model": data.get("model", "htdemucs"),
        "callback": data.get("callback")
    }

    redis_client.lpush(QUEUE_KEY, json.dumps(job))

    log_info(f"Enqueued {songhash}")

    return jsonify({
        "hash": songhash,
        "reason": "Song enqueued for separation"
    }), 200


@app.route("/apiv1/queue", methods=["GET"])
@app.route("/apiv1/queue/", methods=["GET"])
def get_queue():
    jobs = redis_client.lrange(QUEUE_KEY, 0, -1)
    hashes = []

    for job in jobs:
        try:
            hashes.append(json.loads(job)["songhash"])
        except (ValueError, KeyError, TypeError):
            hashes.append(job)

    return jsonify({"queue": hashes}), 200


@app.route("/apiv1/track/<songhash>/<track>", methods=["GET"])
def get_track(songhash, track):
    if track == "base.mp3":
        track = "bass.mp3"

    valid_tracks = [
        "bass.mp3",
        "vocals.mp3",
        "drums.mp3",
        "other.mp3"
    ]

    if track not in valid_tracks:
        return jsonify({"error": "Invalid track"}), 400

    object_name = f"{songhash}-{track}"

    try:
        obj = minio_client.get_object("output", object_name)
        try:
            content = obj.read()
        finally:
            obj.close()
            obj.release_conn()

        return send_file(
            io.BytesIO(content),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=track
        )

    except S3Error as error:
        if error.code in ("NoSuchKey", "NoSuchObject"):
            return jsonify({"error": "Track not found"}), 404
        raise


@app.route(
    "/apiv1/remove/<songhash>/<track>",
    methods=["GET", "DELETE"]
)
def remove_track(songhash, track):
    if track == "base.mp3":
        track = "bass.mp3"

    valid_tracks = [
        "bass.mp3",
        "vocals.mp3",
        "drums.mp3",
        "other.mp3"
    ]

    if track not in valid_tracks:
        return jsonify({"error": "Invalid track"}), 400

    object_name = f"{songhash}-{track}"

    try:
        minio_client.stat_object("output", object_name)
    except S3Error as error:
        if error.code in ("NoSuchKey", "NoSuchObject"):
            return jsonify({"error": "Track not found"}), 404
        raise

    minio_client.remove_object("output", object_name)

    log_info(f"Removed {object_name}")

    return jsonify({
        "removed": object_name
    }), 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )
