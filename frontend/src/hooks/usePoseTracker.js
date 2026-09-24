/**
 * usePoseTracker.js — v2.0
 *
 * Changes from v1:
 *   - startTracking(videoType) now accepts a video type ('up-down' | 'right-left')
 *     and passes it to /start_session so the backend uses the correct reference.
 *
 * Coordinate system (same as extract_reference.py):
 *   yaw   = (nose.x - eye_mid_x) / eye_span
 *   pitch = (nose.y - eye_mid_y) / face_height
 *   roll  = atan2(right_eye.y - left_eye.y, right_eye.x - left_eye.x)
 */

import { useRef, useCallback, useState, useEffect } from 'react';
import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const SAMPLE_INTERVAL_MS = 167; // ~6 frames/sec — matches extract_reference.py's sample_rate=6,
                                 // so fast head turns aren't clipped below the true peak angle

const WASM_BASE = `${window.location.origin}/mediapipe/wasm`;

const MP_MODELS = [
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
  'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/face_landmarker.task',
];

// ---------------------------------------------------------------------------
// FaceLandmarker singleton
// ---------------------------------------------------------------------------
let _landmarkerPromise = null;

async function getLandmarker() {
  if (_landmarkerPromise) return _landmarkerPromise;

  _landmarkerPromise = (async () => {
    let lastErr;
    const vision = await FilesetResolver.forVisionTasks(WASM_BASE);

    for (const modelUrl of MP_MODELS) {
      try {
        const fl = await FaceLandmarker.createFromOptions(vision, {
          baseOptions: { modelAssetPath: modelUrl, delegate: 'GPU' },
          runningMode: 'VIDEO',
          numFaces: 1,
          outputFacialTransformationMatrixes: false,
        });
        console.log('[MP] FaceLandmarker ready. Model:', modelUrl);
        return fl;
      } catch (e) {
        console.warn('[MP] Model load failed:', modelUrl, e.message);
        lastErr = e;
      }
    }

    // Retry with CPU delegate if GPU/WebGL is unavailable
    for (const modelUrl of MP_MODELS) {
      try {
        const fl = await FaceLandmarker.createFromOptions(vision, {
          baseOptions: { modelAssetPath: modelUrl, delegate: 'CPU' },
          runningMode: 'VIDEO',
          numFaces: 1,
          outputFacialTransformationMatrixes: false,
        });
        console.log('[MP] FaceLandmarker ready (CPU fallback). Model:', modelUrl);
        return fl;
      } catch (e) {
        console.warn('[MP] CPU fallback failed:', modelUrl, e.message);
        lastErr = e;
      }
    }

    _landmarkerPromise = null;
    throw lastErr || new Error('FaceLandmarker init failed on all model URLs');
  })();

  return _landmarkerPromise;
}

// ---------------------------------------------------------------------------
// CORE: compute yaw/pitch/roll from landmarks — identical math to Python
// ---------------------------------------------------------------------------
function computePoseFromLandmarks(landmarks) {
  const nose     = landmarks[1];    // nose_tip
  const leftEye  = landmarks[33];   // left_eye_outer
  const rightEye = landmarks[263];  // right_eye_outer
  const chin     = landmarks[152];
  const forehead = landmarks[10];

  // YAW: nose horizontal offset from eye midpoint, normalized by eye span
  const eyeMidX = (leftEye.x + rightEye.x) / 2;
  const eyeSpan = Math.abs(rightEye.x - leftEye.x) || 0.001;
  const yaw     = (nose.x - eyeMidX) / eyeSpan;

  // PITCH: nose vertical offset from eye midpoint, normalized by face height
  const eyeMidY = (leftEye.y + rightEye.y) / 2;
  const faceH   = Math.abs(chin.y - forehead.y) || 0.001;
  const pitch   = (nose.y - eyeMidY) / faceH;

  // ROLL: eye line angle
  const dx   = rightEye.x - leftEye.x;
  const dy   = rightEye.y - leftEye.y;
  const roll = Math.atan2(dy, dx);

  return {
    yaw:   parseFloat(yaw.toFixed(6)),
    pitch: parseFloat(pitch.toFixed(6)),
    roll:  parseFloat(roll.toFixed(6)),
  };
}

// ---------------------------------------------------------------------------
// Detect pose from webcam frame
// ---------------------------------------------------------------------------
let _lastTime = -1;
let _lastPose = null;

async function detectPose(videoEl) {
  let landmarker;
  try { landmarker = await getLandmarker(); } catch { return null; }
  if (!videoEl || videoEl.readyState < 2) return null;

  const t = videoEl.currentTime;
  if (t === _lastTime) return _lastPose;
  _lastTime = t;

  let result;
  try { result = landmarker.detectForVideo(videoEl, performance.now()); }
  catch { return null; }

  if (!result?.faceLandmarks?.length) { _lastPose = null; return null; }

  const pose = computePoseFromLandmarks(result.faceLandmarks[0]);
  _lastPose = pose;
  return pose;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------
export function usePoseTracker() {
  const videoRef     = useRef(null);
  const streamRef    = useRef(null);
  const intervalRef  = useRef(null);
  const sessionIdRef = useRef(null);
  const countRef     = useRef(0);
  const maxFramesRef = useRef(Infinity); // caps sampling to the teacher clip's duration

  const [isTracking,  setIsTracking]  = useState(false);
  const [frameCount,  setFrameCount]  = useState(0);
  const [cameraError, setCameraError] = useState(null);
  const [streamReady, setStreamReady] = useState(false);
  const [mpStatus,    setMpStatus]    = useState('idle');

  // Pre-warm on mount
  useEffect(() => {
    setMpStatus('loading');
    getLandmarker()
      .then(() => setMpStatus('ready'))
      .catch(e => { console.warn('[MP] Unavailable:', e.message); setMpStatus('error'); });
  }, []);

  // Attach stream to <video>
  useEffect(() => {
    if (!streamReady) return;
    const vid    = videoRef.current;
    const stream = streamRef.current;
    if (!vid || !stream) return;
    vid.srcObject = stream;
    const onMeta = () => { vid.play().catch(() => {}); _startInterval(); };
    vid.addEventListener('loadedmetadata', onMeta, { once: true });
    if (vid.readyState >= 1) { vid.play().catch(() => {}); _startInterval(); }
    return () => vid.removeEventListener('loadedmetadata', onMeta);
  }, [streamReady]); // eslint-disable-line

  function _startInterval() {
    if (intervalRef.current) return;
    countRef.current = 0;

    intervalRef.current = setInterval(async () => {
      const vid = videoRef.current;
      const sid = sessionIdRef.current;
      if (!vid || !sid || vid.readyState < 2) return;

      if (countRef.current >= maxFramesRef.current) {
        // Reached the teacher clip's duration — stop sampling further
        // frames even if the caller hasn't called stopTracking() yet.
        clearInterval(intervalRef.current);
        intervalRef.current = null;
        return;
      }

      const rawPose = await detectPose(vid);
      const visible = !!rawPose;
      const pose    = rawPose || { yaw: 0, pitch: 0, roll: 0 };

      try {
        await fetch(`${API}/submit_pose`, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sid,
            time: parseFloat((countRef.current * SAMPLE_INTERVAL_MS / 1000).toFixed(3)),
            yaw:   pose.yaw,
            pitch: pose.pitch,
            roll:  pose.roll,
            visible,
          }),
        });
        countRef.current += 1;
        setFrameCount(countRef.current);
      } catch { /* network blip */ }
    }, SAMPLE_INTERVAL_MS);
  }

  /**
   * startTracking(videoType, durationSec)
   * @param {string} videoType   'up-down' | 'right-left'
   * @param {number} [durationSec]  teacher clip duration, used to cap the
   *   number of frames sampled so capture can never run past the reference
   *   clip (optional — if omitted, no cap is applied and the caller is
   *   expected to stop tracking when the teacher video ends, as before).
   */
  const startTracking = useCallback(async (videoType = 'up-down', durationSec) => {
    setCameraError(null);
    setFrameCount(0);
    setStreamReady(false);
    countRef.current = 0;
    maxFramesRef.current = (typeof durationSec === 'number' && durationSec > 0)
      // +2 frames of buffer for interval/scheduling jitter near the end of the clip
      ? Math.ceil((durationSec * 1000) / SAMPLE_INTERVAL_MS) + 2
      : Infinity;

    let sessionId;
    try {
      const res  = await fetch(`${API}/start_session`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_type: videoType }),
      });
      let data = {};
      try { data = await res.json(); } catch { /* non-JSON error body */ }
      if (!res.ok) {
        throw new Error(data.detail || `Backend error (${res.status}) starting session.`);
      }
      sessionId  = data.session_id;
      sessionIdRef.current = sessionId;
    } catch (err) {
      setCameraError(err.message || 'Cannot reach backend. Is the FastAPI server running?');
      return false;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      });
      streamRef.current = stream;
    } catch (err) {
      const msg = err.name === 'NotAllowedError'
        ? 'Camera permission denied. Allow access and retry.'
        : `Camera error: ${err.message}`;
      setCameraError(msg);
      await fetch(`${API}/session/${sessionId}`, { method: 'DELETE' }).catch(() => {});
      return false;
    }

    setIsTracking(true);
    setStreamReady(true);
    return true;
  }, []);

  const stopTracking = useCallback(async () => {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    if (streamRef.current)   { streamRef.current.getTracks().forEach(t => t.stop()); streamRef.current = null; }
    if (videoRef.current)    { videoRef.current.srcObject = null; }
    maxFramesRef.current = Infinity;
    setIsTracking(false);
    setStreamReady(false);

    const sid = sessionIdRef.current;
    if (!sid) return null;
    sessionIdRef.current = null;
    try {
      const res = await fetch(`${API}/finish_session/${sid}`, { method: 'POST' });
      return await res.json();
    } catch { return null; }
  }, []);

  return { videoRef, isTracking, frameCount, cameraError, mpStatus, startTracking, stopTracking };
}