# Dance Movement Assessment — POC

Head-movement comparison system: students mirror a teacher video and receive a similarity score calculated with **Dynamic Time Warping (DTW)** on Yaw / Pitch / Roll angles.

---

## Quick Start

### 1 · Backend

```bash
cd backend
pip install -r requirements.txt

# One-time extraction (already done if reference.json exists)
python services/extract_reference.py \
  --video reference/teacher.mp4 \
  --output reference/reference.json

# Start server
uvicorn main:app --reload --port 8000
```

### 2 · Frontend

```bash
cd frontend
npm install
npm start          # http://localhost:3000
```

---

## Project Structure

```
dance-poc/
│
├── start_backend.sh          ← one command to run backend
├── start_frontend.sh         ← one command to run frontend
│
├── backend/
│   ├── main.py               ← FastAPI app (all routes)
│   ├── requirements.txt
│   │
│   ├── reference/
│   │   ├── teacher.mp4       ← teacher reference video (place here)
│   │   └── reference.json    ← auto-generated head pose sequence
│   │
│   └── services/
│       ├── extract_reference.py  ← one-time video → JSON
│       └── compare.py            ← DTW comparison + scoring
│
└── frontend/
    ├── package.json
    └── src/
        ├── App.jsx                   ← main app (3 screens)
        ├── index.js / index.css
        ├── hooks/
        │   └── usePoseTracker.js     ← webcam + pose + API calls
        └── components/
            ├── ScoreRing.jsx         ← animated SVG score ring
            └── ResultScreen.jsx      ← results layout
```

---

## System Flow

```
                ┌─────────────────────┐
                │  teacher.mp4        │  (stored once)
                └────────┬────────────┘
                         │  extract_reference.py
                         ▼
                ┌─────────────────────┐
                │  reference.json     │  {frame, yaw, pitch, roll}
                └─────────────────────┘


      ┌─── Student opens browser ────────────────────────────┐
      │                                                       │
      │  IDLE SCREEN        →  enter name, click Start       │
      │                                                       │
      │  ASSESS SCREEN                                        │
      │    ┌──────────────────┐   ┌──────────────────┐       │
      │    │  Teacher Video   │   │  Live Webcam     │       │
      │    │  (plays once)    │   │  (mirrored)      │       │
      │    └──────────────────┘   └────────┬─────────┘       │
      │                                    │                   │
      │                             every 1 second            │
      │                                    ▼                   │
      │                          POST /submit_pose            │
      │                          {yaw, pitch, roll}           │
      │                                                       │
      │  When video ends → POST /finish_session/{id}         │
      │                                                       │
      │  RESULT SCREEN                                        │
      │    Overall Score + per-axis rings + feedback         │
      └───────────────────────────────────────────────────────┘
```

---

## API Endpoints

| Method | Route                        | Description                           |
|--------|------------------------------|---------------------------------------|
| GET    | `/health`                    | Liveness check                        |
| GET    | `/reference_info`            | Teacher video metadata                |
| GET    | `/video/teacher`             | Stream teacher.mp4                    |
| POST   | `/start_session`             | Create session → `{session_id}`       |
| POST   | `/submit_pose`               | Send one pose frame                   |
| POST   | `/submit_face_box`           | Send face bbox → server computes pose |
| POST   | `/finish_session/{id}`       | Compare + return score                |
| DELETE | `/session/{id}`              | Cancel session                        |

---

## Scoring Algorithm

### Head Pose Extraction
From a face bounding box, 6 approximate 2D landmarks are derived.
`cv2.solvePnP` maps them to a 3D face model to extract:

- **Yaw**   — left / right rotation  
- **Pitch** — up / down tilt  
- **Roll**  — side head tilt  

### DTW Comparison

```
DTW distance = sum of |teacher[i] - student[j]|
               along the optimal warp path, normalised by path length
```

DTW is time-elastic: it allows the student to be slightly ahead or behind and still score well.

### Scoring

```python
similarity = max(0, 1 - dtw_distance / MAX_EXPECTED_DISTANCE)
score_pct  = similarity * 100

overall = 0.55 * yaw_score
        + 0.30 * pitch_score
        + 0.15 * roll_score
```

Yaw is weighted highest because left-right turns are the most visible head movement in dance.

---

## Adding a New Teacher Video

```bash
# 1. Copy your video
cp my_new_dance.mp4 backend/reference/teacher.mp4

# 2. Re-extract reference
python backend/services/extract_reference.py \
  --video backend/reference/teacher.mp4 \
  --output backend/reference/reference.json

# 3. Restart backend — done!
```

---

## Future Upgrades

| Feature               | How to add                                      |
|-----------------------|-------------------------------------------------|
| Full-body tracking    | Add MediaPipe Pose to extract 33 body keypoints |
| Higher accuracy pose  | Use `@mediapipe/tasks-vision` WASM in browser   |
| Multiple teachers     | Store multiple reference JSONs, add selector    |
| Leaderboard           | Add DB (SQLite → PostgreSQL)                    |
| AI scoring model      | Collect teacher + student data, train Siamese   |

---

## Tech Stack

| Layer      | Technology                  |
|------------|-----------------------------|
| Frontend   | React 18                    |
| Backend    | FastAPI + Uvicorn           |
| Video      | HTML5 `<video>`             |
| Face       | OpenCV Haar cascade         |
| Head pose  | solvePnP (Yaw/Pitch/Roll)   |
| Comparison | DTW (pure Python)           |
| Storage    | JSON (POC)                  |
