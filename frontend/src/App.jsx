/**
 * App.jsx — v3.0 — Single-page flow
 *
 * Everything lives on ONE page now (no IDLE → WATCH → ASSESS screen
 * switching). On this single page:
 *   - Pick a step (chip selector)
 *   - Teacher video has its own Play / Pause / Restart controls
 *   - Student camera has its own Start / Stop controls
 *   - Starting the camera is only allowed after the teacher video has
 *     been watched through at least once
 *   - Starting the camera restarts the teacher video and plays it
 *     alongside your camera capture; the assessment auto-finishes when
 *     the teacher video ends, or you can hit Stop early
 *   - The result appears inline, right below, on the same page
 *   - A "Next Video →" button on the result advances to the next step
 *
 * No LLM is used anywhere — all feedback text comes from the backend's
 * deterministic rule-based scoring.
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { ResultScreen } from './components/ResultScreen';
import { usePoseTracker } from './hooks/usePoseTracker';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Where "Complete & Next" sends the learner once they finish the final step.
const COMPLETE_REDIRECT_URL =
  'https://www.figma.com/proto/4vUFMybJnuYVRmXnYexH6L/natyashastra-web?node-id=73-3&t=8MPWCKApXh15bUah-0&scaling=scale-down&content-scaling=fixed&page-id=0%3A1&starting-point-node-id=29%3A15';

// ── Video steps, in the order "Next Video" cycles through ──────────────────────
const VIDEO_OPTIONS = [
  {
    type:  'up-down',
    label: 'Up-Down',
    icon:  '↕',
    color: '#E5862D',
    instruction: 'Nod your head up and down',
  },
  {
    type:  'right-left',
    label: 'Right-Left',
    icon:  '↔',
    color: '#2F9E73',
    instruction: 'Turn your head right and left',
  },
];

export default function App() {
  const [videoIndex,     setVideoIndex]     = useState(0);
  const [studentName,    setStudentName]    = useState('');
  const [result,         setResult]         = useState(null);
  const [progress,       setProgress]       = useState(0);
  const [refInfo,        setRefInfo]        = useState(null);
  const [status,         setStatus]         = useState('');
  const [videoMeta,      setVideoMeta]      = useState({});   // {type -> refInfo}
  const [hasWatchedOnce, setHasWatchedOnce] = useState(false);
  const [teacherPlaying, setTeacherPlaying] = useState(false);
  const [starting,       setStarting]       = useState(false);
  const [finishing,      setFinishing]      = useState(false);

  const teacherVideoRef  = useRef(null);
  const resultSectionRef = useRef(null);

  const current   = VIDEO_OPTIONS[videoIndex];
  const videoType = current.type;

  const {
    videoRef: webcamRef,
    isTracking,
    frameCount,
    cameraError,
    mpStatus,
    startTracking,
    stopTracking,
  } = usePoseTracker();

  // ── Fetch /videos list once on mount ────────────────────────────────────────
  useEffect(() => {
    fetch(`${API}/videos`)
      .then(r => r.json())
      .then(list => {
        const map = {};
        list.forEach(v => { map[v.video_type] = v; });
        setVideoMeta(map);
      })
      .catch(() =>
        setStatus('⚠ Cannot reach backend. Start the FastAPI server first.')
      );
  }, []);

  // ── Fetch refInfo whenever the selected step changes ────────────────────────
  useEffect(() => {
    let cancelled = false;
    setRefInfo(null);

    const load = (attempt = 0) => {
      fetch(`${API}/reference_info?video_type=${videoType}`)
        .then(r => { if (!r.ok) throw new Error(`status ${r.status}`); return r.json(); })
        .then(data => { if (!cancelled) setRefInfo(data); })
        .catch(() => {
          if (cancelled) return;
          // Transient backend hiccups (cold start, brief network blip)
          // shouldn't permanently lose this — retry a couple of times.
          // Not fetching it isn't fatal (Start Camera no longer depends on
          // it), it's just used to cap sampling to the clip's duration.
          if (attempt < 2) {
            setTimeout(() => load(attempt + 1), 1500);
          } else {
            setStatus(`⚠ Could not load reference info for '${videoType}' — scoring will still work.`);
          }
        });
    };
    load();

    return () => { cancelled = true; };
  }, [videoType]);

  // ── Reset per-step state whenever the step changes ──────────────────────────
  useEffect(() => {
    setResult(null);
    setStatus('');
    setProgress(0);
    setHasWatchedOnce(false);
    setTeacherPlaying(false);
    const vid = teacherVideoRef.current;
    if (vid) { vid.pause(); vid.currentTime = 0; }
  }, [videoType]);

  // ── Scroll result into view ──────────────────────────────────────────────────
  useEffect(() => {
    if (result && resultSectionRef.current) {
      resultSectionRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [result]);

  // ── Teacher video controls ──────────────────────────────────────────────────
  const handlePlayPause = useCallback(() => {
    const vid = teacherVideoRef.current;
    if (!vid) return;
    if (vid.paused) { vid.play().catch(() => {}); } else { vid.pause(); }
  }, []);

  const handleRestartVideo = useCallback(() => {
    const vid = teacherVideoRef.current;
    if (!vid) return;
    vid.currentTime = 0;
    if (!vid.paused) vid.play().catch(() => {});
  }, []);

  const handleTeacherPlay  = useCallback(() => setTeacherPlaying(true),  []);
  const handleTeacherPause = useCallback(() => setTeacherPlaying(false), []);

  const handleTimeUpdate = useCallback(() => {
    const vid = teacherVideoRef.current;
    if (vid && vid.duration) {
      setProgress(Math.round((vid.currentTime / vid.duration) * 100));
    }
  }, []);

  // ── Finish assessment (shared by "video ended" and manual Stop) ────────────
  const finishAssessment = useCallback(async () => {
    setFinishing(true);
    setStatus('Calculating score…');
    const res = await stopTracking();
    const vid = teacherVideoRef.current;
    if (vid) vid.pause();
    setResult(res || false);
    setStatus('');
    setFinishing(false);
  }, [stopTracking]);

  const handleTeacherEnded = useCallback(() => {
    setHasWatchedOnce(true);
    setTeacherPlaying(false);
    if (isTracking) finishAssessment();
  }, [isTracking, finishAssessment]);

  // ── Camera controls ─────────────────────────────────────────────────────────
  const handleStartCamera = useCallback(async () => {
    if (!hasWatchedOnce) {
      setStatus('Please watch the teacher video fully at least once first.');
      return;
    }
    setStarting(true);
    setStatus('Starting camera…');
    // Cap frame capture to the teacher video's own duration so sampling never
    // runs past the reference clip. refInfo is best-effort here — if it
    // hasn't loaded yet we simply don't cap; "video ended" still stops
    // tracking, exactly as before. Reference availability itself is no
    // longer required to unlock the button — the backend already validates
    // it in /start_session and reports a clear error if something is wrong.
    const ok = await startTracking(videoType, refInfo?.duration);
    setStarting(false);
    if (!ok) { setStatus(''); return; }

    setResult(null);
    setProgress(0);
    setStatus('');

    const vid = teacherVideoRef.current;
    if (vid) {
      vid.currentTime = 0;
      setTimeout(() => vid.play().catch(() => {}), 250);
    }
  }, [hasWatchedOnce, refInfo, startTracking, videoType]);

  const handleStopCamera = useCallback(() => {
    if (!isTracking) return;
    finishAssessment();
  }, [isTracking, finishAssessment]);

  // ── Retry / Next ─────────────────────────────────────────────────────────────
  const handleRetrySame = useCallback(() => {
    setResult(null);
    setStatus('');
    setProgress(0);
    const vid = teacherVideoRef.current;
    if (vid) { vid.pause(); vid.currentTime = 0; }
  }, []);

  const handleNextVideo = useCallback(() => {
    const isLastStep = videoIndex === VIDEO_OPTIONS.length - 1;
    if (isLastStep) {
      // Final step complete — send the learner onward instead of looping back.
      window.location.href = COMPLETE_REDIRECT_URL;
      return;
    }
    setVideoIndex(i => (i + 1) % VIDEO_OPTIONS.length);
    // per-step state reset happens in the `videoType` effect above
  }, [videoIndex]);

  const handleSelectVideo = useCallback((idx) => {
    if (isTracking) return; // don't allow switching mid-assessment
    setVideoIndex(idx);
  }, [isTracking]);

  const teacherVideoSrc = `${API}/video/teacher/${videoType}`;

  const startCameraDisabled = isTracking || starting || finishing || !hasWatchedOnce;
  const isLastStep = videoIndex === VIDEO_OPTIONS.length - 1;
  const nextIndex = (videoIndex + 1) % VIDEO_OPTIONS.length;
  const nextButtonLabel = isLastStep
    ? 'Complete & Next →'
    : `Next: ${VIDEO_OPTIONS[nextIndex].icon} ${VIDEO_OPTIONS[nextIndex].label} →`;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={styles.app}>

      {/* HEADER */}
      <header style={styles.header}>
        <div style={styles.logo}>
          <img src="/assets/olabs-logo.png" alt="Online Labs" style={styles.olabsLogo} />
          <span style={styles.logoText}>DanceAssess</span>
          <span style={styles.logoBadge}>Movement Labs</span>
        </div>

        <div style={styles.headerRight}>
          {isTracking && (
            <div style={styles.liveChip}>
              <span style={styles.liveDot} />
              LIVE · {frameCount} frames
            </div>
          )}
          <div style={styles.partnerLogos}>
            <img src="/assets/cdac-logo.png" alt="C-DAC" style={styles.cdacLogo} />
            <img
              src="/assets/maverick-nrithyodaya-logo.png"
              alt="Maverick Foundation × Nrithyodaya"
              style={styles.partnerLogo}
            />
          </div>
        </div>
      </header>

      {/* STEP SELECTOR */}
      <div style={styles.stepBar}>
        {VIDEO_OPTIONS.map((opt, idx) => {
          const isActive = idx === videoIndex;
          const meta      = videoMeta[opt.type];
          const available = !meta || meta.available;
          return (
            <button
              key={opt.type}
              onClick={() => available && handleSelectVideo(idx)}
              disabled={isTracking || !available}
              style={{
                ...styles.stepChip,
                borderColor: isActive ? opt.color : '#E8DCD0',
                color:       isActive ? opt.color : '#8A6F6F',
                background:  isActive ? `${opt.color}18` : 'transparent',
                opacity:     available ? 1 : 0.4,
                cursor:      (isTracking || !available) ? 'not-allowed' : 'pointer',
              }}
            >
              {opt.icon} {opt.label}
            </button>
          );
        })}

        <div style={styles.nameRow}>
          <input
            type="text"
            placeholder="Your name (optional)"
            value={studentName}
            onChange={e => setStudentName(e.target.value)}
            style={styles.nameInput}
          />
        </div>
      </div>

      {/* VIDEO GRID */}
      <div style={styles.assessLayout}>

        {/* Teacher video */}
        <div style={styles.videoBox}>
          <div style={styles.videoLabel}>Teacher · {current.label}</div>
          <video
            ref={teacherVideoRef}
            src={teacherVideoSrc}
            onEnded={handleTeacherEnded}
            onPlay={handleTeacherPlay}
            onPause={handleTeacherPause}
            onTimeUpdate={handleTimeUpdate}
            style={styles.video}
            playsInline
          />
          <div style={styles.progressTrack}>
            <div style={{ ...styles.progressBar, width: `${progress}%` }} />
          </div>
          <div style={styles.videoControls}>
            <button
              onClick={handlePlayPause}
              disabled={isTracking}
              style={{ ...styles.ctrlBtn, opacity: isTracking ? 0.4 : 1 }}
            >
              {teacherPlaying ? '⏸ Pause' : '▶ Play'}
            </button>
            <button
              onClick={handleRestartVideo}
              disabled={isTracking}
              style={{ ...styles.ctrlBtn, opacity: isTracking ? 0.4 : 1 }}
            >
              ⏮ Restart
            </button>
            {hasWatchedOnce && (
              <span style={styles.watchedTag}>✓ Watched</span>
            )}
          </div>
        </div>

        {/* Student camera */}
        <div style={styles.videoBox}>
          <div style={styles.videoLabel}>You</div>
          <video
            ref={webcamRef}
            autoPlay
            muted
            playsInline
            style={{ ...styles.video, transform: 'scaleX(-1)' }}
          />
          {cameraError && (
            <div style={styles.cameraError}>{cameraError}</div>
          )}
          {!cameraError && !isTracking && !result && (
            <div style={styles.cameraLoading}>
              📷 Camera will start once you click Start Camera
            </div>
          )}
          <div style={styles.videoControls}>
            <button
              onClick={handleStartCamera}
              disabled={startCameraDisabled}
              style={{
                ...styles.ctrlBtn,
                ...styles.ctrlBtnPrimary,
                opacity: startCameraDisabled ? 0.4 : 1,
                cursor:  startCameraDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              {starting ? 'Starting…' : '▶ Start Camera'}
            </button>
            <button
              onClick={handleStopCamera}
              disabled={!isTracking}
              style={{
                ...styles.ctrlBtn,
                ...styles.ctrlBtnDanger,
                opacity: !isTracking ? 0.4 : 1,
                cursor:  !isTracking ? 'not-allowed' : 'pointer',
              }}
            >
              ■ Stop
            </button>
          </div>
          {startCameraDisabled && (
            <div style={styles.disabledReason}>
              Start Camera disabled because:{' '}
              {[
                isTracking      && 'a session is already tracking',
                starting        && 'camera is currently starting',
                finishing       && 'finishing the previous attempt',
                !hasWatchedOnce && 'the teacher video hasn\'t been marked "Watched" yet',
              ].filter(Boolean).join(' · ') || 'unknown — please report this'}
            </div>
          )}
        </div>
      </div>

      {/* STATUS FOOTER */}
      <div style={styles.assessFooter}>
        <span style={{ color: isTracking ? '#2F9E73' : '#8A6F6F' }}>
          {isTracking
            ? `● Tracking ${frameCount} frames (MediaPipe)`
            : !hasWatchedOnce
              ? '○ Watch the teacher video fully once to unlock Start Camera'
              : '○ Ready — click Start Camera when you are'}
        </span>
        <span style={{ color: '#8A6F6F' }}>{current.instruction}</span>
      </div>

      {mpStatus === 'error' && (
        <p style={{ color: '#B23A3A', fontSize: 13, textAlign: 'center' }}>
          ⚠ AI pose model failed to load. Check your internet connection and refresh.
        </p>
      )}

      {(status || cameraError) && (
        <p style={{ color: cameraError ? '#B23A3A' : '#C9781E', fontSize: 14,
                    textAlign: 'center', maxWidth: 500, margin: '4px auto' }}>
          {cameraError || status}
        </p>
      )}

      {/* RESULT (inline, same page) */}
      <div ref={resultSectionRef}>
        {result && (
          <ResultScreen
            result={result}
            studentName={studentName}
            videoType={videoType}
            onRetry={handleRetrySame}
            onNext={handleNextVideo}
            nextLabel={nextButtonLabel}
          />
        )}
        {result === false && (
          <div style={styles.centered}>
            <p style={{ color: '#B23A3A', marginBottom: 20 }}>
              Could not compute score — make sure your face was visible throughout.
            </p>
            <button onClick={handleRetrySame} style={styles.primaryBtn}>Try Again</button>
          </div>
        )}
      </div>

    </div>
  );
}

const styles = {
  app: { minHeight:'100vh', background:'#FFFDF8', fontFamily:'Poppins, sans-serif', color:'#4A2E2E' },

  // Navbar — deep maroon, matches site header
  header: { display:'flex', alignItems:'center', justifyContent:'space-between',
            padding:'10px 32px', background:'#570013', borderBottom:'1px solid #6B1A1A' },
  logo:   { display:'flex', alignItems:'center', gap:10 },
  olabsLogo:{ height:44, width:'auto', display:'block' },
  logoText: { fontSize:18, fontWeight:700, letterSpacing:'-0.01em', color:'#FFFDF8',
              fontFamily:'Playfair Display, serif' },
  logoBadge:{ fontSize:10, fontWeight:700, background:'#E5862D22', color:'#E5862D',
              border:'1px solid #E5862D', borderRadius:4, padding:'2px 6px', letterSpacing:'0.1em' },
  headerRight:{ display:'flex', alignItems:'center', gap:20 },
  partnerLogos:{ display:'flex', alignItems:'center', gap:14, background:'#FFFDF8',
              borderRadius:8, padding:'6px 14px' },
  cdacLogo: { height:38, width:'auto', display:'block' },
  partnerLogo:{ height:32, width:'auto', display:'block' },
  liveChip: { display:'flex', alignItems:'center', gap:8, background:'#2F9E7320',
              border:'1px solid #2F9E73', borderRadius:20, padding:'5px 14px', fontSize:13, color:'#2F9E73' },
  liveDot:  { width:7, height:7, borderRadius:'50%', background:'#2F9E73', display:'inline-block' },

  centered: { display:'flex', flexDirection:'column', alignItems:'center', padding:'40px 24px', gap:20 },

  // Step selector chips — orange when active, on cream background
  stepBar: { display:'flex', alignItems:'center', gap:12, padding:'18px 32px',
             background:'#FFFFFF', borderBottom:'1px solid #E8DCD0', flexWrap:'wrap' },
  stepChip: { border:'2px solid', borderRadius:20, padding:'8px 18px', fontSize:14, fontWeight:700,
              background:'transparent', fontFamily:'Poppins, sans-serif' },
  nameRow:  { marginLeft:'auto', minWidth:220 },
  nameInput:{ width:'100%', background:'#FBF3EA', border:'1px solid #E8DCD0', borderRadius:10,
              padding:'8px 14px', fontSize:14, color:'#2A0605',
              fontFamily:'Poppins, sans-serif', outline:'none', boxSizing:'border-box' },

  assessLayout: { display:'grid', gridTemplateColumns:'1fr 1fr', gap:20, padding:'24px 32px',
                  background:'#FFFDF8' },
  videoBox:     { position:'relative', borderRadius:16, overflow:'hidden',
                  background:'#000', border:'1px solid #E8DCD0', display:'flex', flexDirection:'column' },
  videoLabel:   { position:'absolute', top:12, left:14, zIndex:10, background:'#00000080',
                  color:'#FFFDF8', padding:'4px 10px', borderRadius:6, fontSize:12, fontWeight:600,
                  letterSpacing:'0.05em' },
  video:        { width:'100%', display:'block', aspectRatio:'16/9', objectFit:'cover', background:'#000' },
  progressTrack:{ height:4, background:'#E8DCD0' },
  progressBar:  { height:'100%', background:'linear-gradient(90deg,#E5862D,#B9500F)', transition:'width 0.3s ease' },
  cameraError:  { position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center',
                  background:'#00000090', color:'#F3B072', textAlign:'center', padding:20, fontSize:14,
                  pointerEvents:'none' },
  cameraLoading:{ position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center',
                  color:'#D9CFC4', fontSize:13, textAlign:'center', padding:20, background:'#00000060',
                  pointerEvents:'none' },

  videoControls:{ display:'flex', alignItems:'center', gap:8, padding:'10px 14px', background:'#2A0605' },
  ctrlBtn:      { background:'#3C1210', color:'#F3E7DC', border:'1px solid #6B1A1A',
                  borderRadius:8, padding:'8px 16px', fontSize:13, fontWeight:600, cursor:'pointer',
                  fontFamily:'Poppins, sans-serif' },
  ctrlBtnPrimary:{ background:'linear-gradient(135deg,#E5862D,#B9500F)', color:'#fff', border:'none' },
  ctrlBtnDanger:{ background:'#3A1414', color:'#E88484', border:'1px solid #B23A3A55' },
  watchedTag:   { marginLeft:'auto', fontSize:12, color:'#4EC090', fontWeight:600 },
  disabledReason:{ padding:'6px 14px', fontSize:12, color:'#C9781E', background:'#FBF3EA' },

  assessFooter: { margin:'0 32px 20px', background:'#FFFFFF', border:'1px solid #E8DCD0', borderRadius:12,
                  padding:'14px 24px', display:'flex', justifyContent:'space-between',
                  alignItems:'center', fontSize:14, flexWrap:'wrap', gap:8 },

  primaryBtn:  { background:'linear-gradient(135deg,#E5862D,#B9500F)', color:'#fff', border:'none',
                 borderRadius:12, padding:'16px 44px', fontSize:17, fontWeight:700,
                 letterSpacing:'0.01em', cursor:'pointer' },
};