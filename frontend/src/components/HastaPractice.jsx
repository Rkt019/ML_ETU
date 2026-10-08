/**
 * HastaPractice.jsx — Asamyuta Hasta (single-hand mudra) practice
 *
 *   - Pick a mudra (28 mudras, Katakamukha has two variants)
 *   - Teacher panel shows that mudra's part of Wrist.mp4: a still of the
 *     held pose by default, "Watch Teacher" plays the segment
 *   - Student panel: webcam with the detected hand drawn on top and a live
 *     match % against the chosen mudra
 *   - An attempt lasts ATTEMPT_SECONDS (or until Stop); the result shows the
 *     best ~1 second, per-finger scores and feedback
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { ScoreRing } from './ScoreRing';
import { useHandTracker } from '../hooks/useHandTracker';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';
// const API = 'https://mletu-production.up.railway.app';

const ATTEMPT_SECONDS = 60;

const FINGER_RINGS = [
  { key: 'thumb',  label: 'Thumb' },
  { key: 'index',  label: 'Index' },
  { key: 'middle', label: 'Middle' },
  { key: 'ring',   label: 'Ring' },
  { key: 'pinky',  label: 'Little' },
];

function scoreColor(score) {
  if (score >= 80) return '#2F9E73';
  if (score >= 50) return '#E5862D';
  return '#B23A3A';
}

export function HastaPractice({ onComplete, completeLabel }) {
  const [mudras,     setMudras]     = useState([]);
  const [index,      setIndex]      = useState(0);
  const [videoSrc,   setVideoSrc]   = useState(null);
  const [loadError,  setLoadError]  = useState('');
  const [result,     setResult]     = useState(null);
  const [starting,   setStarting]   = useState(false);
  const [finishing,  setFinishing]  = useState(false);
  const [teacherPlaying, setTeacherPlaying] = useState(false);

  const teacherRef   = useRef(null);
  const resultRef    = useRef(null);
  const finishingRef = useRef(false);

  const {
    videoRef: webcamRef, canvasRef, isTracking, elapsed, live, cameraError, mpStatus,
    startTracking, stopTracking,
  } = useHandTracker();

  const mudra   = mudras[index];
  const holdMid = mudra ? (mudra.hold_start + mudra.hold_end) / 2 : 0;
  const isLast  = index === mudras.length - 1;

  useEffect(() => {
    fetch(`${API}/hasta/mudras`)
      .then(r => { if (!r.ok) throw new Error(`status ${r.status}`); return r.json(); })
      .then(setMudras)
      .catch(() => setLoadError('⚠ Could not load mudra list. Is the backend running with the hasta templates?'));
  }, []);

  // Download the whole teacher video once: the backend does not serve byte
  // ranges, and without them Chrome cannot seek to each mudra's start time.
  useEffect(() => {
    let url = null;
    let cancelled = false;
    fetch(`${API}/video/hasta`)
      .then(r => { if (!r.ok) throw new Error(`status ${r.status}`); return r.blob(); })
      .then(blob => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setVideoSrc(url);
      })
      .catch(() => !cancelled && setLoadError('⚠ Could not load the teacher video (reference/Wrist.mp4).'));
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, []);

  const showPose = useCallback(() => {
    const vid = teacherRef.current;
    if (!vid || !mudra || vid.readyState < 1) return;
    vid.pause();
    vid.currentTime = holdMid;
  }, [mudra, holdMid]);

  const playTeacher = useCallback(() => {
    const vid = teacherRef.current;
    if (!vid || !mudra) return;
    vid.currentTime = mudra.start;
    vid.play().catch(() => {});
  }, [mudra]);

  useEffect(() => {
    setResult(null);
    showPose();
  }, [index, videoSrc, showPose]);

  useEffect(() => {
    if (result && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [result]);

  const handleTeacherTime = useCallback(() => {
    const vid = teacherRef.current;
    if (!vid || !mudra || vid.paused) return;
    if (vid.currentTime >= mudra.end - 0.15) {
      if (isTracking) vid.currentTime = mudra.start;
      else showPose();
    }
  }, [mudra, isTracking, showPose]);

  const finishAttempt = useCallback(async () => {
    if (finishingRef.current) return;
    finishingRef.current = true;
    setFinishing(true);
    const res = await stopTracking();
    showPose();
    setResult(res && res.overall_score !== undefined
      ? res
      : { error: res?.error || 'Could not compute a score. Please try again.' });
    setFinishing(false);
    finishingRef.current = false;
  }, [stopTracking, showPose]);

  useEffect(() => {
    if (isTracking && elapsed >= ATTEMPT_SECONDS) finishAttempt();
  }, [isTracking, elapsed, finishAttempt]);

  const handleStart = useCallback(async () => {
    if (!mudra) return;
    setResult(null);
    setStarting(true);
    const ok = await startTracking(mudra.name);
    setStarting(false);
    if (ok) playTeacher();
  }, [mudra, startTracking, playTeacher]);

  const goTo = useCallback((i) => {
    if (isTracking || !mudras.length) return;
    setIndex(Math.max(0, Math.min(mudras.length - 1, i)));
  }, [isTracking, mudras.length]);

  const startDisabled = !mudra || isTracking || starting || finishing || mpStatus === 'error';
  const secondsLeft   = Math.max(0, Math.ceil(ATTEMPT_SECONDS - elapsed));

  return (
    <div>
      {/* MUDRA PICKER */}
      <div style={styles.pickerBar}>
        <button onClick={() => goTo(index - 1)} disabled={isTracking || index === 0}
                style={{ ...styles.navBtn, opacity: (isTracking || index === 0) ? 0.4 : 1 }}>◀</button>
        <select
          value={index}
          onChange={e => goTo(Number(e.target.value))}
          disabled={isTracking || !mudras.length}
          style={styles.select}
        >
          {mudras.map((m, i) => (
            <option key={m.name} value={i}>{m.id}. {m.display} — {m.meaning}</option>
          ))}
        </select>
        <button onClick={() => goTo(index + 1)} disabled={isTracking || isLast}
                style={{ ...styles.navBtn, opacity: (isTracking || isLast) ? 0.4 : 1 }}>▶</button>
        {mudra && (
          <div style={styles.mudraTitle}>
            <span style={styles.mudraName}>{mudra.display}</span>
            <span style={styles.mudraMeaning}>“{mudra.meaning}” · {mudra.id} of {mudras.length}</span>
          </div>
        )}
      </div>

      {/* VIDEO GRID */}
      <div style={styles.grid}>
        <div style={styles.videoBox}>
          <div style={styles.videoLabel}>Teacher · {mudra ? mudra.display : '…'}</div>
          <video
            ref={teacherRef}
            src={videoSrc || undefined}
            onLoadedMetadata={showPose}
            onTimeUpdate={handleTeacherTime}
            onPlay={() => setTeacherPlaying(true)}
            onPause={() => setTeacherPlaying(false)}
            style={styles.video}
            muted
            playsInline
          />
          {!videoSrc && !loadError && <div style={styles.overlayMsg}>Loading teacher video…</div>}
          <div style={styles.controls}>
            <button onClick={teacherPlaying ? showPose : playTeacher} disabled={isTracking || !videoSrc}
                    style={{ ...styles.ctrlBtn, opacity: (isTracking || !videoSrc) ? 0.4 : 1 }}>
              {teacherPlaying ? '⏸ Show Pose' : '▶ Watch Teacher'}
            </button>
          </div>
        </div>

        <div style={styles.videoBox}>
          <div style={styles.videoLabel}>You</div>
          <div style={styles.camWrap}>
            <video ref={webcamRef} autoPlay muted playsInline style={{ ...styles.video, ...styles.mirror }} />
            <canvas ref={canvasRef} style={{ ...styles.canvas, ...styles.mirror }} />
            {cameraError && <div style={styles.overlayMsg}>{cameraError}</div>}
            {!cameraError && !isTracking && (
              <div style={styles.overlayMsg}>
                {mpStatus === 'loading' ? 'Loading hand model…' : '📷 Click Start Practice and copy the teacher\'s mudra'}
              </div>
            )}
            {isTracking && (
              <div style={styles.livePanel}>
                {live?.visible ? (
                  <>
                    <div style={styles.liveRow}>
                      <span>Match</span>
                      <strong style={{ color: scoreColor(live.score) }}>{Math.round(live.score)}%</strong>
                    </div>
                    <div style={styles.liveTrack}>
                      <div style={{ ...styles.liveBar, width: `${live.score}%`, background: scoreColor(live.score) }} />
                    </div>
                    {live.best_matches?.[0] && live.best_matches[0].name !== mudra.name && (
                      <div style={styles.liveHint}>Looks like: {live.best_matches[0].display}</div>
                    )}
                  </>
                ) : (
                  <div style={styles.liveHint}>✋ Show your hand to the camera</div>
                )}
                <div style={styles.timer}>{secondsLeft}s</div>
              </div>
            )}
          </div>
          <div style={styles.controls}>
            <button onClick={handleStart} disabled={startDisabled}
                    style={{ ...styles.ctrlBtn, ...styles.ctrlBtnPrimary,
                             opacity: startDisabled ? 0.4 : 1, cursor: startDisabled ? 'not-allowed' : 'pointer' }}>
              {starting ? 'Starting…' : `▶ Start Practice (${ATTEMPT_SECONDS}s)`}
            </button>
            <button onClick={finishAttempt} disabled={!isTracking}
                    style={{ ...styles.ctrlBtn, ...styles.ctrlBtnDanger,
                             opacity: !isTracking ? 0.4 : 1, cursor: !isTracking ? 'not-allowed' : 'pointer' }}>
              ■ Stop
            </button>
          </div>
        </div>
      </div>

      <div style={styles.footer}>
        <span style={{ color: isTracking ? '#2F9E73' : '#8A6F6F' }}>
          {isTracking ? '● Tracking your hand (MediaPipe)' : finishing ? 'Calculating score…' : '○ Ready'}
        </span>
        <span style={{ color: '#8A6F6F' }}>Hold the mudra steady with your hand facing the camera</span>
      </div>

      {mpStatus === 'error' && (
        <p style={styles.error}>⚠ Hand model failed to load. Check your internet connection and refresh.</p>
      )}
      {loadError && <p style={styles.error}>{loadError}</p>}

      {/* RESULT */}
      <div ref={resultRef}>
        {result?.error && (
          <div style={styles.resultWrap}>
            <p style={{ color: '#B23A3A' }}>{result.error}</p>
            <button onClick={() => setResult(null)} style={styles.secondaryBtn}>↻ Try Again</button>
          </div>
        )}
        {result && !result.error && (
          <div style={styles.resultWrap}>
            <div style={{ ...styles.gradeBadge, borderColor: scoreColor(result.overall_score),
                          color: scoreColor(result.overall_score) }}>
              {result.grade === 'Excellent' ? '🏆' : result.grade === 'Good' ? '👍' : '💪'} {result.grade}
            </div>
            <p style={{ color: '#8A6F6F', margin: 0 }}>
              {result.display} · held correctly for <strong style={{ color: '#2A0605' }}>{result.hold_seconds}s</strong>
            </p>

            <div style={styles.ringsRow}>
              <ScoreRing score={result.overall_score} label="Overall" color="#2F9E73" size={110} />
              <ScoreRing score={result.hand_visible_pct} label="Hand Visible" color="#E5862D" size={80} />
              <ScoreRing score={result.parts.orientation} label="Palm Direction" color="#B9500F" size={80} />
            </div>
            <div style={styles.ringsRow}>
              {FINGER_RINGS.map(({ key, label }) => (
                <ScoreRing key={key} score={result.finger_scores[key]} label={label}
                           color={scoreColor(result.finger_scores[key])} size={70} />
              ))}
            </div>

            <div style={styles.feedbackBox}>
              <p style={styles.feedbackTitle}>FEEDBACK</p>
              {result.feedback.map((f, i) => <p key={i} style={styles.feedbackItem}>{f}</p>)}
            </div>

            <div style={styles.btnRow}>
              <button onClick={() => setResult(null)} style={styles.secondaryBtn}>↻ Try Again</button>
              {isLast
                ? onComplete && <button onClick={onComplete} style={styles.primaryBtn}>{completeLabel || 'Complete & Next →'}</button>
                : <button onClick={() => goTo(index + 1)} style={styles.primaryBtn}>Next: {mudras[index + 1].display} →</button>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const styles = {
  pickerBar:   { display:'flex', alignItems:'center', gap:10, padding:'16px 32px 0', flexWrap:'wrap' },
  navBtn:      { background:'#FFFFFF', color:'#570013', border:'1px solid #E8DCD0', borderRadius:10,
                 padding:'8px 14px', fontSize:14, fontWeight:700, cursor:'pointer' },
  select:      { background:'#FBF3EA', border:'1px solid #E8DCD0', borderRadius:10, padding:'8px 12px',
                 fontSize:14, color:'#2A0605', fontFamily:'Poppins, sans-serif', minWidth:260 },
  mudraTitle:  { display:'flex', flexDirection:'column', marginLeft:12 },
  mudraName:   { fontSize:22, fontWeight:700, color:'#570013', fontFamily:'Playfair Display, serif' },
  mudraMeaning:{ fontSize:13, color:'#8A6F6F' },

  grid:        { display:'grid', gridTemplateColumns:'1fr 1fr', gap:20, padding:'16px 32px 24px' },
  videoBox:    { position:'relative', borderRadius:16, overflow:'hidden', background:'#000',
                 border:'1px solid #E8DCD0', display:'flex', flexDirection:'column' },
  videoLabel:  { position:'absolute', top:12, left:14, zIndex:10, background:'#00000080', color:'#FFFDF8',
                 padding:'4px 10px', borderRadius:6, fontSize:12, fontWeight:600, letterSpacing:'0.05em' },
  video:       { width:'100%', display:'block', aspectRatio:'16/9', objectFit:'cover', background:'#000' },
  camWrap:     { position:'relative' },
  canvas:      { position:'absolute', inset:0, width:'100%', height:'100%', objectFit:'cover', pointerEvents:'none' },
  mirror:      { transform:'scaleX(-1)' },
  overlayMsg:  { position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center',
                 color:'#F3E7DC', fontSize:14, textAlign:'center', padding:20, background:'#00000070',
                 pointerEvents:'none' },
  livePanel:   { position:'absolute', left:12, right:12, bottom:12, background:'#2A0605D9', borderRadius:12,
                 padding:'10px 14px', color:'#F3E7DC', fontSize:14 },
  liveRow:     { display:'flex', justifyContent:'space-between', alignItems:'baseline', fontSize:16, paddingRight:48 },
  liveTrack:   { height:8, background:'#FFFFFF22', borderRadius:4, marginTop:6, marginRight:48, overflow:'hidden' },
  liveBar:     { height:'100%', transition:'width 0.15s linear' },
  liveHint:    { marginTop:6, fontSize:13, color:'#F3B072' },
  timer:       { position:'absolute', right:14, top:10, fontSize:22, fontWeight:700, color:'#FFFDF8' },

  controls:    { display:'flex', alignItems:'center', gap:8, padding:'10px 14px', background:'#2A0605' },
  ctrlBtn:     { background:'#3C1210', color:'#F3E7DC', border:'1px solid #6B1A1A', borderRadius:8,
                 padding:'8px 16px', fontSize:13, fontWeight:600, cursor:'pointer', fontFamily:'Poppins, sans-serif' },
  ctrlBtnPrimary:{ background:'linear-gradient(135deg,#E5862D,#B9500F)', color:'#fff', border:'none' },
  ctrlBtnDanger: { background:'#3A1414', color:'#E88484', border:'1px solid #B23A3A55' },

  footer:      { margin:'0 32px 20px', background:'#FFFFFF', border:'1px solid #E8DCD0', borderRadius:12,
                 padding:'14px 24px', display:'flex', justifyContent:'space-between', alignItems:'center',
                 fontSize:14, flexWrap:'wrap', gap:8 },
  error:       { color:'#B23A3A', fontSize:13, textAlign:'center' },

  resultWrap:  { display:'flex', flexDirection:'column', alignItems:'center', padding:'32px 24px', gap:20,
                 maxWidth:860, margin:'0 auto', fontFamily:'Poppins, sans-serif' },
  gradeBadge:  { border:'2px solid', borderRadius:40, padding:'8px 24px', fontSize:18, fontWeight:700 },
  ringsRow:    { display:'flex', flexWrap:'wrap', justifyContent:'center', gap:24, alignItems:'flex-end' },
  feedbackBox: { background:'#FFFFFF', border:'1px solid #E8DCD0', borderRadius:16, padding:'24px 28px',
                 width:'100%', maxWidth:640, boxShadow:'0 2px 10px rgba(87,0,19,0.06)' },
  feedbackTitle:{ fontSize:11, fontWeight:700, color:'#E5862D', letterSpacing:'0.12em', marginBottom:14 },
  feedbackItem:{ fontSize:15, color:'#4A2E2E', lineHeight:1.7, marginBottom:8 },
  btnRow:      { display:'flex', gap:12, flexWrap:'wrap', justifyContent:'center' },
  primaryBtn:  { background:'linear-gradient(135deg,#E5862D,#B9500F)', color:'#fff', border:'none',
                 borderRadius:12, padding:'14px 40px', fontSize:16, fontWeight:700, cursor:'pointer' },
  secondaryBtn:{ background:'#FFFFFF', color:'#570013', border:'1px solid #570013', borderRadius:12,
                 padding:'14px 28px', fontSize:16, fontWeight:600, cursor:'pointer' },
};
