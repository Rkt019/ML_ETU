/**
 * ScoreRing.jsx
 * Animated SVG ring showing a 0–100 score.
 */
import React, { useEffect, useRef } from 'react';

export function ScoreRing({ score = 0, size = 140, label = 'Overall', color = '#E5862D' }) {
  const circleRef = useRef(null);
  const textRef   = useRef(null);

  const r           = (size - 16) / 2;
  const circumf     = 2 * Math.PI * r;
  const offset      = circumf * (1 - score / 100);

  useEffect(() => {
    if (!circleRef.current) return;
    // Animate stroke-dashoffset
    circleRef.current.style.transition = 'stroke-dashoffset 1.2s cubic-bezier(0.22, 1, 0.36, 1)';
    circleRef.current.style.strokeDashoffset = offset;
  }, [offset]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        {/* Track */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke="#E8DCD0" strokeWidth={10}
        />
        {/* Progress */}
        <circle
          ref={circleRef}
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke={color}
          strokeWidth={10}
          strokeLinecap="round"
          strokeDasharray={circumf}
          strokeDashoffset={circumf}  /* starts empty; useEffect animates */
          style={{ filter: `drop-shadow(0 0 6px ${color}80)` }}
        />
        {/* Score text — counter-rotated so it reads normally */}
        <text
          x="50%" y="50%"
          textAnchor="middle" dominantBaseline="middle"
          style={{
            transform: `rotate(90deg)`,
            transformOrigin: `${size / 2}px ${size / 2}px`,
            fill: '#2A0605',
            fontSize: size * 0.22,
            fontFamily: 'Poppins, sans-serif',
            fontWeight: 700,
          }}
        >
          {Math.round(score)}%
        </text>
      </svg>
      <span style={{ fontSize: 13, color: '#8A6F6F', fontWeight: 500, letterSpacing: '0.05em' }}>
        {label}
      </span>
    </div>
  );
}
