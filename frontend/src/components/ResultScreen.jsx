/**
 * ResultScreen.jsx — v2.1 (Online Labs / Movement Labs theme)
 *
 * Accepts a `videoType` prop ('up-down' | 'right-left') and renders the
 * appropriate directional scores and movement breakdown for that step.
 *
 *   up-down    → shows Up Score + Down Score, pitch movement details
 *   right and-left → shows Right Score + Left Score, yaw movement details
 */

import React from 'react';
import { ScoreRing } from './ScoreRing';

export function ResultScreen({ result, studentName, videoType = 'up-down', onRetry, onNext, nextLabel }) {
  const {
    overall_score, face_visible_pct,
    // pitch axis (up-down)
    up_score, down_score,
    // yaw axis (right-left)
    right_score = 0, left_score = 0,
    feedback, grade, movement_details,
    false_start_detected, skipped_frames,
  } = result;

  const isRightLeft = videoType === 'right-left';

  // Directional score rings — swap based on video type
  const directionalScores = isRightLeft
    ? [
        { score: right_score, label: 'Right', color: '#2F9E73' },
        { score: left_score,  label: 'Left',  color: '#B9500F' },
      ]
    : [
        { score: up_score,   label: 'Up',   color: '#E5862D' },
        { score: down_score, label: 'Down', color: '#B9500F' },
      ];

  // Axis and label mapping for the movement breakdown table
  const breakdownAxis = isRightLeft ? 'yaw' : 'pitch';
  const moveLabels    = isRightLeft
    ? { positive: 'Right', negative: 'Left' }   // yaw: positive = turning right
    : { positive: 'Down',  negative: 'Up'  };   // pitch: positive = looking down

  const gradeColor = {
    'Excellent':         '#2F9E73',
    'Good':              '#E5862D',
    'Needs Improvement': '#C9781E',
    'Keep Practicing':   '#B23A3A',
    'Error':             '#B23A3A',
  }[grade] || '#8A6F6F';

  const stepLabel = isRightLeft ? 'Right-Left Head Turns' : 'Up-Down Head Nods';

  return (
    <div style={styles.wrapper}>

      {/* Step type tag */}
      <div style={{ ...styles.stepTag, color: isRightLeft ? '#2F9E73' : '#E5862D',
                    borderColor: isRightLeft ? '#2F9E73' : '#E5862D' }}>
        {isRightLeft ? '↔' : '↕'} {stepLabel}
      </div>

      {/* Grade badge */}
      <div style={{ ...styles.gradeBadge, borderColor: gradeColor, color: gradeColor }}>
        {grade === 'Excellent' ? '🏆' : grade === 'Good' ? '👍' : '💪'} {grade}
      </div>

      {studentName && (
        <p style={{ color: '#8A6F6F', fontSize: 14, marginBottom: 4 }}>
          Results for <strong style={{ color: '#2A0605' }}>{studentName}</strong>
        </p>
      )}

      {/* Score rings */}
      <div style={styles.ringsRow}>
        <ScoreRing score={overall_score}   label="Overall"      color="#2F9E73" size={110} />
        {/* Directional (Up/Down or Right/Left) score rings — hidden for now
        {directionalScores.map(({ score, label, color }) => (
          <ScoreRing key={label} score={score} label={label} color={color} size={80} />
        ))}
        */}
        <ScoreRing score={face_visible_pct} label="Face Visible" color="#E5862D" size={80} />
      </div>

      {/* False-start note */}
      {false_start_detected && skipped_frames > 0 && (
        <p style={styles.falseStartNote}>
          ℹ We noticed your first movement went the wrong way — it was skipped, and
          scoring started from your first correct movement instead.
        </p>
      )}

      {/* Feedback */}
      <div style={styles.feedbackBox}>
        <p style={styles.feedbackTitle}>FEEDBACK</p>
        {feedback.map((f, i) => (
          <p key={i} style={styles.feedbackItem}>{f}</p>
        ))}
      </div>

      {/* Movement detail breakdown — hidden for now (both up-down and right-left videos)
      {movement_details && movement_details[breakdownAxis] && movement_details[breakdownAxis].length > 0 && (
        <div style={styles.detailBox}>
          <p style={styles.feedbackTitle}>
            MOVEMENT BREAKDOWN · {isRightLeft ? 'YAW AXIS (Left-Right)' : 'PITCH AXIS (Up-Down)'}
          </p>
          <div style={styles.movesRow}>
            {movement_details[breakdownAxis]
              .slice()
              .sort((a, b) => {
                // Sort: for up-down → Up (negative) first, for right-left → Right (positive) first
                const aIsFirst = isRightLeft
                  ? a.movement_type === 'positive'
                  : a.movement_type === 'negative';
                return aIsFirst ? -1 : 1;
              })
              .map((m, i) => {
                const label      = moveLabels[m.movement_type] || m.movement_type;
                const accentColor = m.accuracy >= 80 ? '#2F9E73'
                                  : m.accuracy >= 50 ? '#C9781E'
                                  : '#B23A3A';
                const statusText = !m.found
                  ? 'Not detected'
                  : m.match_type === 'overshoot'
                    ? 'Went past teacher\'s range'
                    : m.match_type === 'undershoot'
                      ? 'Fell short of teacher\'s range'
                      : 'Good match';
                return (
                  <div key={i} style={{ ...styles.moveCard, borderColor: accentColor }}>
                    <div style={styles.moveNum}>{label} movement</div>
                    <div style={{ ...styles.moveAcc, color: accentColor }}>{m.accuracy}%</div>
                    <div style={styles.moveDetail}>
                      <span style={{ color: '#8A6F6F' }}>Teacher reps: </span>
                      {m.ref_repetitions}
                    </div>
                    <div style={styles.moveDetail}>
                      <span style={{ color: '#8A6F6F' }}>Your attempts: </span>
                      {m.stu_attempts || 0}
                    </div>
                    <div style={{ ...styles.moveDetail, color: m.found ? '#4A2E2E' : '#B23A3A' }}>
                      {statusText}
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      )}
      */}

      <div style={styles.btnRow}>
        <button onClick={onRetry} style={styles.changeBtn}>
          ↻ Try Again
        </button>
        {onNext && (
          <button onClick={onNext} style={styles.retryBtn}>
            {nextLabel || 'Next Video →'}
          </button>
        )}
      </div>
    </div>
  );
}

const styles = {
  wrapper:      { display:'flex', flexDirection:'column', alignItems:'center',
                  padding:'40px 24px', gap:24, maxWidth:860, margin:'0 auto',
                  fontFamily:'Poppins, sans-serif' },
  stepTag:  { border:'1px solid', borderRadius:20, padding:'4px 14px',
                  fontSize:13, fontWeight:700, letterSpacing:'0.04em' },
  gradeBadge:   { border:'2px solid', borderRadius:40, padding:'8px 24px',
                  fontSize:18, fontWeight:700, letterSpacing:'0.02em' },
  ringsRow:     { display:'flex', flexWrap:'wrap', justifyContent:'center', gap:24, alignItems:'flex-end' },
  feedbackBox:  { background:'#FFFFFF', border:'1px solid #E8DCD0', borderRadius:16,
                  padding:'24px 28px', width:'100%', maxWidth:640,
                  boxShadow:'0 2px 10px rgba(87,0,19,0.06)' },
  falseStartNote:{ background:'#C9781E18', border:'1px solid #C9781E', color:'#8A5A16',
                  borderRadius:10, padding:'10px 16px', fontSize:13, maxWidth:640, textAlign:'center' },
  feedbackTitle:{ fontSize:11, fontWeight:700, color:'#E5862D', letterSpacing:'0.12em',
                  textTransform:'uppercase', marginBottom:14, fontFamily:'Poppins, sans-serif' },
  feedbackItem: { fontSize:15, color:'#4A2E2E', lineHeight:1.7, marginBottom:8 },
  detailBox:    { background:'#FBF3EA', border:'1px solid #E8DCD0', borderRadius:16,
                  padding:'24px 28px', width:'100%', maxWidth:780 },
  movesRow:     { display:'flex', gap:12, flexWrap:'wrap' },
  moveCard:     { background:'#FFFFFF', border:'1px solid', borderRadius:10,
                  padding:'12px 16px', minWidth:150 },
  moveNum:      { fontSize:11, color:'#8A6F6F', letterSpacing:'0.06em', marginBottom:4 },
  moveAcc:      { fontSize:26, fontWeight:700, marginBottom:6 },
  moveDetail:   { fontSize:12, color:'#4A2E2E', marginBottom:2 },
  btnRow:       { display:'flex', gap:12, flexWrap:'wrap', justifyContent:'center' },
  retryBtn:     { background:'linear-gradient(135deg,#E5862D,#B9500F)', color:'#fff', border:'none',
                  borderRadius:12, padding:'14px 40px', fontSize:16, fontWeight:700, cursor:'pointer' },
  changeBtn:    { background:'#FFFFFF', color:'#570013', border:'1px solid #570013',
                  borderRadius:12, padding:'14px 28px', fontSize:16, fontWeight:600, cursor:'pointer' },
};
