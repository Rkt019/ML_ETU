/**
 * useHandTracker.js — webcam hand tracking for Hasta (mudra) practice
 *
 * Runs MediaPipe HandLandmarker in the browser ~6 times a second, draws the
 * 21 hand points on a canvas over the webcam, and sends the raw world
 * landmarks to the backend (/hasta/submit_frame). All scoring maths lives in
 * backend/services/hand_compare.py so it matches the teacher templates
 * exactly; each response carries the live score for that frame.
 */

import { useRef, useCallback, useState, useEffect } from 'react';
import { HandLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';
// const API = 'https://mletu-production.up.railway.app';

export const SAMPLE_INTERVAL_MS = 167; // ~6 frames/sec, same rate the teacher video was sampled at

const WASM_BASE = `${window.location.origin}/mediapipe/wasm`;
const HAND_MODEL =
  'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';

const HAND_EDGES = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20], [0, 17],
];

let _landmarkerPromise = null;

async function getHandLandmarker() {
  if (_landmarkerPromise) return _landmarkerPromise;

  _landmarkerPromise = (async () => {
    const vision = await FilesetResolver.forVisionTasks(WASM_BASE);
    let lastErr;
    for (const delegate of ['GPU', 'CPU']) {
      try {
        const hl = await HandLandmarker.createFromOptions(vision, {
          baseOptions: { modelAssetPath: HAND_MODEL, delegate },
          runningMode: 'VIDEO',
          numHands: 1,
        });
        console.log(`[MP] HandLandmarker ready (${delegate}).`);
        return hl;
      } catch (e) {
        console.warn(`[MP] HandLandmarker ${delegate} init failed:`, e.message);
        lastErr = e;
      }
    }
    _landmarkerPromise = null;
    throw lastErr || new Error('HandLandmarker init failed');
  })();

  return _landmarkerPromise;
}

function drawHand(canvas, video, points, color) {
  if (!canvas || !video) return;
  const w = video.videoWidth;
  const h = video.videoHeight;
  if (!w || !h) return;
  if (canvas.width !== w)  canvas.width = w;
  if (canvas.height !== h) canvas.height = h;

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, h);
  if (!points) return;

  ctx.strokeStyle = color;
  ctx.lineWidth = 4;
  for (const [a, b] of HAND_EDGES) {
    ctx.beginPath();
    ctx.moveTo(points[a].x * w, points[a].y * h);
    ctx.lineTo(points[b].x * w, points[b].y * h);
    ctx.stroke();
  }
  ctx.fillStyle = '#FFFDF8';
  for (const p of points) {
    ctx.beginPath();
    ctx.arc(p.x * w, p.y * h, 5, 0, 2 * Math.PI);
    ctx.fill();
  }
}

function scoreColor(score) {
  if (score >= 80) return '#2F9E73';
  if (score >= 50) return '#E5862D';
  return '#B23A3A';
}

export function useHandTracker() {
  const videoRef     = useRef(null);
  const canvasRef    = useRef(null);
  const streamRef    = useRef(null);
  const intervalRef  = useRef(null);
  const sessionIdRef = useRef(null);
  const startedAtRef = useRef(0);
  const busyRef      = useRef(false);
  const lastScoreRef = useRef(0);

  const [isTracking,  setIsTracking]  = useState(false);
  const [elapsed,     setElapsed]     = useState(0);
  const [live,        setLive]        = useState(null);
  const [cameraError, setCameraError] = useState(null);
  const [mpStatus,    setMpStatus]    = useState('idle');

  useEffect(() => {
    setMpStatus('loading');
    getHandLandmarker()
      .then(() => setMpStatus('ready'))
      .catch(e => { console.warn('[MP] Hand model unavailable:', e.message); setMpStatus('error'); });
  }, []);

  const tick = useCallback(async () => {
    if (busyRef.current) return;
    const vid = videoRef.current;
    const sid = sessionIdRef.current;
    if (!vid || !sid || vid.readyState < 2) return;

    busyRef.current = true;
    try {
      let hand = null;
      try {
        const landmarker = await getHandLandmarker();
        const res = landmarker.detectForVideo(vid, performance.now());
        if (res?.landmarks?.length) {
          hand = {
            image:      res.landmarks[0],
            world:      res.worldLandmarks[0].map(p => [p.x, p.y, p.z]),
            handedness: res.handednesses?.[0]?.[0]?.categoryName || null,
          };
        }
      } catch { /* model not ready or frame not decodable — treat as no hand */ }

      drawHand(canvasRef.current, vid, hand?.image, scoreColor(lastScoreRef.current));

      const time = (performance.now() - startedAtRef.current) / 1000;
      setElapsed(time);

      const r = await fetch(`${API}/hasta/submit_frame`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id:      sid,
          time:            parseFloat(time.toFixed(3)),
          visible:         !!hand,
          handedness:      hand?.handedness,
          landmarks_world: hand?.world,
        }),
      });
      if (r.ok && sessionIdRef.current === sid) {
        const data = await r.json();
        lastScoreRef.current = data.score || 0;
        setLive(data);
      }
    } catch { /* network blip — skip this frame */ }
    finally { busyRef.current = false; }
  }, []);

  const releaseCamera = useCallback(() => {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    if (streamRef.current)   { streamRef.current.getTracks().forEach(t => t.stop()); streamRef.current = null; }
    if (videoRef.current)    { videoRef.current.srcObject = null; }
    const canvas = canvasRef.current;
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  }, []);

  const startTracking = useCallback(async (mudra) => {
    setCameraError(null);
    setLive(null);
    setElapsed(0);
    lastScoreRef.current = 0;

    let sessionId;
    try {
      const res = await fetch(`${API}/hasta/start_session`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mudra }),
      });
      let data = {};
      try { data = await res.json(); } catch { /* non-JSON error body */ }
      if (!res.ok) throw new Error(data.detail || `Backend error (${res.status}) starting session.`);
      sessionId = data.session_id;
    } catch (err) {
      setCameraError(err.message || 'Cannot reach backend. Is the FastAPI server running?');
      return false;
    }

    try {
      streamRef.current = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      });
    } catch (err) {
      setCameraError(err.name === 'NotAllowedError'
        ? 'Camera permission denied. Allow access and retry.'
        : `Camera error: ${err.message}`);
      await fetch(`${API}/hasta/session/${sessionId}`, { method: 'DELETE' }).catch(() => {});
      return false;
    }

    const vid = videoRef.current;
    if (vid) {
      vid.srcObject = streamRef.current;
      await vid.play().catch(() => {});
    }
    sessionIdRef.current = sessionId;
    startedAtRef.current = performance.now();
    intervalRef.current  = setInterval(tick, SAMPLE_INTERVAL_MS);
    setIsTracking(true);
    return true;
  }, [tick]);

  const stopTracking = useCallback(async () => {
    releaseCamera();
    setIsTracking(false);

    const sid = sessionIdRef.current;
    if (!sid) return null;
    sessionIdRef.current = null;
    try {
      const res = await fetch(`${API}/hasta/finish_session/${sid}`, { method: 'POST' });
      return await res.json();
    } catch { return null; }
  }, [releaseCamera]);

  useEffect(() => () => {
    releaseCamera();
    const sid = sessionIdRef.current;
    if (sid) fetch(`${API}/hasta/session/${sid}`, { method: 'DELETE' }).catch(() => {});
  }, [releaseCamera]);

  return {
    videoRef, canvasRef, isTracking, elapsed, live, cameraError, mpStatus,
    startTracking, stopTracking,
  };
}
