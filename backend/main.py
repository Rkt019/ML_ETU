import json
import os
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from services.compare import compare_sequences


VIDEO_CONFIGS = {
    "up-down": {
        "video":  "reference/up-down.mp4",
        "json":   "reference/up-down.json",
        "label":  "Up-Down Head Movements",
        "icon":   "↕",
        "desc":   "Nod your head up and down",
    },
    "right-left": {
        "video":  "reference/right-left.mp4",
        "json":   "reference/right-left.json",
        "label":  "Right-Left Head Movements",
        "icon":   "↔",
        "desc":   "Turn your head right and left",
    },
}

_LEGACY_JSON = "reference/reference.json"

REFERENCE_DATA: Dict[str, Dict] = {}

for _vt, _cfg in VIDEO_CONFIGS.items():
    _path = _cfg["json"]
    if os.path.exists(_path):
        with open(_path) as f:
            REFERENCE_DATA[_vt] = json.load(f)
        print(f"[main] ✓ Loaded reference: {_path}")
    elif _vt == "up-down" and os.path.exists(_LEGACY_JSON):
        with open(_LEGACY_JSON) as f:
            REFERENCE_DATA[_vt] = json.load(f)
        print(f"[main] ✓ Loaded legacy reference for up-down: {_LEGACY_JSON}")
    else:
        print(f"[main] ⚠  Reference JSON not found for '{_vt}': {_path}")
        print(f"[main]    → Run: python services/extract_reference.py --video {_cfg['video']} --output {_path}")

if not REFERENCE_DATA:
    raise RuntimeError(
        "No reference JSON found. Run extract_reference.py for at least one video type.\n"
        "  python services/extract_reference.py --video reference/up-down.mp4 --output reference/up-down.json\n"
        "  python services/extract_reference.py --video reference/right-left.mp4 --output reference/right-left.json"
    )

SESSIONS: Dict[str, Dict] = {}

app = FastAPI(title="Dance Assessment POC", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://olab-poc.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PoseFrame(BaseModel):
    session_id: str
    time:       float
    yaw:        float
    pitch:      float
    roll:       float
    visible:    bool = True


class StartSessionRequest(BaseModel):
    video_type: str = "up-down"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "available_videos": list(REFERENCE_DATA.keys()),
    }


@app.get("/videos")
def list_videos():
    result = []
    for vt, cfg in VIDEO_CONFIGS.items():
        ref = REFERENCE_DATA.get(vt)
        result.append({
            "video_type":  vt,
            "label":       cfg["label"],
            "icon":        cfg["icon"],
            "desc":        cfg["desc"],
            "available":   vt in REFERENCE_DATA,
            "has_video":   os.path.exists(cfg["video"]),
            "duration":    ref.get("duration") if ref else None,
            "keyframes":   len(ref["sequence"]) if ref else 0,
        })
    return result


@app.get("/reference_info")
def reference_info(video_type: str = "up-down"):
    if video_type not in REFERENCE_DATA:
        available = list(REFERENCE_DATA.keys())
        raise HTTPException(
            status_code=404,
            detail=(
                f"Reference data for '{video_type}' not found. "
                f"Available: {available}. "
                f"Run: python services/extract_reference.py "
                f"--video reference/{video_type}.mp4 "
                f"--output reference/{video_type}.json"
            ),
        )
    data = REFERENCE_DATA[video_type]
    cfg  = VIDEO_CONFIGS[video_type]
    return {
        "video_type": video_type,
        "label":      cfg["label"],
        "duration":   data.get("duration"),
        "movements":  data.get("movements", 3),
        "fps":        data.get("fps", 1.0),
        "keyframes":  len(data["sequence"]),
    }


@app.post("/start_session")
def start_session(body: StartSessionRequest):
    video_type = body.video_type
    if video_type not in REFERENCE_DATA:
        raise HTTPException(
            status_code=404,
            detail=f"No reference data for '{video_type}'. "
                   f"Run extract_reference.py first."
        )
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {"video_type": video_type, "frames": []}
    return {"session_id": session_id, "video_type": video_type}


@app.post("/submit_pose")
def submit_pose(payload: PoseFrame):
    if payload.session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    SESSIONS[payload.session_id]["frames"].append({
        "time":    payload.time,
        "yaw":     payload.yaw,
        "pitch":   payload.pitch,
        "roll":    payload.roll,
        "visible": payload.visible,
    })
    count = len(SESSIONS[payload.session_id]["frames"])
    return {"received": True, "count": count}


@app.post("/finish_session/{session_id}")
def finish_session(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")

    session          = SESSIONS.pop(session_id)
    video_type       = session["video_type"]
    student_sequence = session["frames"]

    if len(student_sequence) < 3:
        return JSONResponse(status_code=422, content={
            "error":           "Too few frames captured. Make sure your face is visible to the camera.",
            "frames_captured": len(student_sequence),
        })

    visible_count    = sum(1 for f in student_sequence if f.get("visible", True))
    face_visible_pct = round(visible_count / len(student_sequence) * 100, 1)

    reference_sequence = REFERENCE_DATA[video_type]["sequence"]
    result = compare_sequences(reference_sequence, student_sequence, video_type=video_type)
    result["face_visible_pct"] = face_visible_pct
    result["video_type"]       = video_type
    return result


@app.delete("/session/{session_id}")
def cancel_session(session_id: str):
    SESSIONS.pop(session_id, None)
    return {"cancelled": True}


@app.get("/video/teacher/{video_type}")
def get_teacher_video(video_type: str):
    if video_type not in VIDEO_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Unknown video type: '{video_type}'")
    path = VIDEO_CONFIGS[video_type]["video"]
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail=f"Video file not found: {path}. "
                   f"Make sure {path} exists in the reference/ folder."
        )
    return FileResponse(path, media_type="video/mp4")


@app.get("/video/teacher")
def get_teacher_video_legacy():
    return get_teacher_video("up-down")
