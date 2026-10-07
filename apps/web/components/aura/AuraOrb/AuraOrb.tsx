'use client';

import React, { useEffect, useRef } from 'react';
import { AuraOrbProps } from './auraOrb.types';
import { AuraOrbRenderer } from './AuraOrbRenderer';
import { getStateAriaLabel, STATE_TOKENS } from './auraOrbStateMap';
import './auraOrb.css';

export const AuraOrb: React.FC<AuraOrbProps> = ({
  state = 'idle',
  audioLevel,
  frequencyBands,
  caption,
  size = 200,
  className = '',
  showCaption = true,
  showStatusBadge = false,
  forceCanvasFallback = false,
  interactive = false,
  onClick,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<AuraOrbRenderer | null>(null);

  // Initialize Renderer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const renderer = new AuraOrbRenderer(canvas, forceCanvasFallback);
    rendererRef.current = renderer;
    renderer.setSize(size, size);
    renderer.updateState(state, audioLevel, frequencyBands);

    // ResizeObserver for dynamic responsiveness
    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined' && containerRef.current) {
      resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const { width, height } = entry.contentRect;
          if (width > 0 && height > 0) {
            const minDim = Math.min(width, height);
            const targetDim = size || minDim;
            renderer.setSize(targetDim, targetDim);
          }
        }
      });
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      renderer.destroy();
      rendererRef.current = null;
    };
  }, [forceCanvasFallback]);

  // Update State & Audio in Active Renderer
  useEffect(() => {
    if (rendererRef.current) {
      rendererRef.current.updateState(state, audioLevel, frequencyBands);
    }
  }, [state, audioLevel, frequencyBands]);

  // Update Size
  useEffect(() => {
    if (rendererRef.current) {
      rendererRef.current.setSize(size, size);
    }
  }, [size]);

  const ariaLabel = getStateAriaLabel(state);
  const tokens = STATE_TOKENS[state] || STATE_TOKENS.idle;

  return (
    <div
      ref={containerRef}
      className={`aura-orb-container ${interactive ? 'cursor-pointer' : ''} ${className}`}
      onClick={onClick}
      style={{ width: size, minHeight: size }}
      role="region"
      aria-label="AURA Cognitive Visual Presence"
    >
      {/* Visual Canvas Wrapper with Ambient Backdrop Glow */}
      <div
        className="aura-orb-canvas-wrapper"
        style={{ width: size, height: size }}
      >
        {/* State-driven ambient glow */}
        <div className={`aura-orb-glow-backdrop aura-orb-glow-${state}`} />

        {/* Core Particle Canvas (WebGL with Canvas 2D fallback) */}
        <canvas
          ref={canvasRef}
          className="relative z-10 block"
          style={{ width: size, height: size }}
          aria-hidden="true"
        />
      </div>

      {/* Accessible Screen Reader State Text */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {ariaLabel}
      </div>

      {/* Optional Status Badge */}
      {showStatusBadge && (
        <div
          className="mt-3 inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border text-[10px] font-mono font-semibold tracking-wider uppercase z-20 backdrop-blur-md"
          style={{
            borderColor: `rgba(${tokens.primaryColor}, 0.4)`,
            backgroundColor: `rgba(${tokens.primaryColor}, 0.12)`,
            color: `rgb(${tokens.primaryColor})`,
          }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full animate-pulse"
            style={{ backgroundColor: `rgb(${tokens.primaryColor})` }}
          />
          <span>{tokens.label}</span>
        </div>
      )}

      {/* Optional Spoken Caption (Speaking Orb Concept) */}
      {showCaption && caption && (
        <div className="aura-orb-caption z-20">
          <span>{caption}</span>
        </div>
      )}
    </div>
  );
};
