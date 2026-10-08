import json
import os
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from services.compare import compare_sequences
from services.hand_compare import load_templates, public_template, score_frame, summarize_attempt
from services.rhythm import rhythm_score


VIDEO_CONFIGS = {
    "up-down": {
        "video":  "reference/up-down.mp4",
        "json":   "reference/up-down.json",
        "beats":  "reference/up-down_beats.json",
        "label":  "Up-Down Head Movements",
        "icon":   "↕",
        "desc":   "Nod your head up and down",
    },
    "right-left": {
        "video":  "reference/right-left.mp4",
        "json":   "reference/right-left.json",
        "beats":  "reference/right-left_beats.json",
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

BEATS_DATA: Dict[str, Dict] = {}

for _vt, _cfg in VIDEO_CONFIGS.items():
    if os.path.exists(_cfg["beats"]):
        with open(_cfg["beats"]) as f:
            BEATS_DATA[_vt] = json.load(f)
        print(f"[main] ✓ Loaded beats: {_cfg['beats']} ({BEATS_DATA[_vt]['tempo_bpm']} BPM)")
    else:
        print(f"[main] ⚠  Beats not found for '{_vt}' — rhythm scoring off. "
              f"Run: python services/extract_beats.py")

if not REFERENCE_DATA:
    raise RuntimeError(
        "No reference JSON found. Run extract_reference.py for at least one video type.\n"
        "  python services/extract_reference.py --video reference/up-down.mp4 --output reference/up-down.json\n"
        "  python services/extract_reference.py --video reference/right-left.mp4 --output reference/right-left.json"
    )

SESSIONS: Dict[str, Dict] = {}

HASTA_VIDEO = "reference/Wrist.mp4"
HASTA_SEGMENTS_JSON = "reference/asamyuta_hasta_segments.json"
HASTA_TEMPLATES_JSON = "reference/asamyuta_hasta_templates.json"
HASTA_SAMPLE_INTERVAL = 0.167  # seconds between webcam samples, matches the frontend

HASTA_TEMPLATES = load_templates(HASTA_TEMPLATES_JSON)
HASTA_SEGMENTS: Dict[str, Dict] = {}
if os.path.exists(HASTA_SEGMENTS_JSON):
    with open(HASTA_SEGMENTS_JSON) as f:
        HASTA_SEGMENTS = {s["name"]: s for s in json.load(f)["segments"]}

if HASTA_TEMPLATES:
    print(f"[main] ✓ Loaded {len(HASTA_TEMPLATES)} hasta templates: {HASTA_TEMPLATES_JSON}")
else:
    print(f"[main] ⚠  Hasta templates not found: {HASTA_TEMPLATES_JSON}")
    print("[main]    → Run: python services/extract_hand_reference.py")

HAND_SESSIONS: Dict[str, Dict] = {}

app = FastAPI(title="Dance Assessment POC", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    # allow_origins=["https://olab-poc-nine.vercel.app"],
    allow_origins=[
    "https://olab-poc.vercel.app",
    "https://olab-poc-git-main-rk1019.vercel.app",
    "http://localhost:3000",
],
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
    data  = REFERENCE_DATA[video_type]
    cfg   = VIDEO_CONFIGS[video_type]
    beats = BEATS_DATA.get(video_type)
    return {
        "video_type":  video_type,
        "label":       cfg["label"],
        "duration":    data.get("duration"),
        "movements":   data.get("movements", 3),
        "fps":         data.get("fps", 1.0),
        "keyframes":   len(data["sequence"]),
        "tempo_bpm":   beats["tempo_bpm"] if beats else None,
        "beat_period": beats["beat_period"] if beats else None,
        "beats":       beats["beats"] if beats else [],
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

    rhythm = rhythm_score(reference_sequence, student_sequence, video_type, BEATS_DATA.get(video_type))
    if rhythm and result.get("grade") != "Error":
        result["feedback"] = result["feedback"] + rhythm.pop("rhythm_feedback")
        result.update(rhythm)
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


# ── Hasta (hand gesture / mudra) practice ─────────────────────────────────────

class HandFrame(BaseModel):
    session_id:      str
    time:            float
    visible:         bool = True
    handedness:      Optional[str] = None
    landmarks_world: Optional[List[List[float]]] = None


class StartHandSessionRequest(BaseModel):
    mudra: str


def _require_hasta_templates():
    if not HASTA_TEMPLATES:
        raise HTTPException(
            status_code=404,
            detail=f"Hasta templates not found ({HASTA_TEMPLATES_JSON}). "
                   f"Run: python services/extract_hand_reference.py",
        )


@app.get("/hasta/mudras")
def list_mudras():
    _require_hasta_templates()
    result = []
    for t in sorted(HASTA_TEMPLATES.values(), key=lambda t: t["id"]):
        seg = HASTA_SEGMENTS.get(t["name"], {})
        result.append({
            "id":         t["id"],
            "name":       t["name"],
            "display":    t["display"],
            "meaning":    t["meaning"],
            "start":      seg.get("start"),
            "end":        seg.get("end"),
            "hold_start": t["hold"]["start"],
            "hold_end":   t["hold"]["end"],
        })
    return result


@app.get("/hasta/template/{mudra}")
def get_mudra_template(mudra: str):
    _require_hasta_templates()
    if mudra not in HASTA_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Unknown mudra: '{mudra}'")
    return public_template(HASTA_TEMPLATES[mudra])


@app.get("/video/hasta")
def get_hasta_video():
    if not os.path.exists(HASTA_VIDEO):
        raise HTTPException(status_code=404, detail=f"Video file not found: {HASTA_VIDEO}")
    return FileResponse(HASTA_VIDEO, media_type="video/mp4")


@app.post("/hasta/start_session")
def start_hand_session(body: StartHandSessionRequest):
    _require_hasta_templates()
    if body.mudra not in HASTA_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Unknown mudra: '{body.mudra}'")
    session_id = str(uuid.uuid4())
    HAND_SESSIONS[session_id] = {"mudra": body.mudra, "frames": []}
    return {"session_id": session_id, "mudra": body.mudra}


@app.post("/hasta/submit_frame")
def submit_hand_frame(payload: HandFrame):
    session = HAND_SESSIONS.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if payload.visible and (not payload.landmarks_world or len(payload.landmarks_world) != 21
                            or any(len(p) != 3 for p in payload.landmarks_world)):
        raise HTTPException(status_code=422, detail="landmarks_world must be 21 points of [x, y, z]")

    template = HASTA_TEMPLATES[session["mudra"]]
    live, norm = score_frame(payload.model_dump(), template, HASTA_TEMPLATES)
    session["frames"].append({
        "time":    payload.time,
        "visible": live["visible"],
        "score":   live["score"],
        "norm":    norm,
    })
    return {**live, "count": len(session["frames"])}


@app.post("/hasta/finish_session/{session_id}")
def finish_hand_session(session_id: str):
    session = HAND_SESSIONS.pop(session_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    frames = session["frames"]
    if len(frames) < 3:
        return JSONResponse(status_code=422, content={
            "error":           "Too few frames captured. Keep the camera on a little longer.",
            "frames_captured": len(frames),
        })

    template = HASTA_TEMPLATES[session["mudra"]]
    result = summarize_attempt(template, frames, HASTA_TEMPLATES, HASTA_SAMPLE_INTERVAL)
    if result is None:
        return JSONResponse(status_code=422, content={
            "error":           "No hand was detected. Hold your hand up in front of the camera.",
            "frames_captured": len(frames),
        })
    return result


@app.delete("/hasta/session/{session_id}")
def cancel_hand_session(session_id: str):
    HAND_SESSIONS.pop(session_id, None)
    return {"cancelled": True}
