import { AuraVisualState, AuraStateStyleTokens } from './auraOrb.types';
import { VoiceSessionState, TaskStatus } from '../../../lib/types';

export interface DeriveVisualStateParams {
  killSwitchActive?: boolean;
  pendingApprovalsCount?: number;
  hasErrors?: boolean;
  voiceState?: VoiceSessionState | null;
  taskStatus?: TaskStatus | null;
  isSearching?: boolean;
  isProcessing?: boolean;
  isDegraded?: boolean;
  isDone?: boolean;
}

/**
 * Authoritative UI-only mapping layer from existing AURA runtime states into visual states.
 * Enforces strict security & runtime truth priority:
 * EMERGENCY_STOP > WAITING_FOR_APPROVAL > ERROR > SPEAKING > SEARCHING > THINKING > LISTENING > DONE > DEGRADED > IDLE
 */
export function deriveVisualState(params?: DeriveVisualStateParams | null): AuraVisualState {
  const p = params || {};

  // 1. EMERGENCY_STOP: Absolute top priority. Never override with cosmetic or living animations.
  if (p.killSwitchActive) {
    return 'emergency_stop';
  }

  // 2. WAITING_FOR_APPROVAL: HITL safety boundary requiring user interaction.
  if (
    (p.pendingApprovalsCount && p.pendingApprovalsCount > 0) ||
    p.taskStatus === 'WAITING_APPROVAL'
  ) {
    return 'waiting_for_approval';
  }

  // 3. ERROR: Runtime failure or fatal fault state.
  if (
    p.hasErrors ||
    p.voiceState === 'ERROR' ||
    p.taskStatus === 'FAILED'
  ) {
    return 'error';
  }

  // 4. SPEAKING: Assistant currently vocalizing speech.
  if (p.voiceState === 'SPEAKING') {
    return 'speaking';
  }

  // 5. SEARCHING: Active external information retrieval / web or file search.
  if (p.isSearching || p.taskStatus === 'VERIFYING') {
    return 'searching';
  }

  // 6. THINKING: Cognitive synthesis, planning, or transcription processing.
  if (
    p.voiceState === 'THINKING' ||
    p.voiceState === 'TRANSCRIBING' ||
    p.taskStatus === 'PLANNING' ||
    p.taskStatus === 'IN_PROGRESS' ||
    p.isProcessing
  ) {
    return 'thinking';
  }

  // 7. LISTENING: Acoustic ingestion active, waiting for speech input.
  if (p.voiceState === 'LISTENING') {
    return 'listening';
  }

  // 8. DONE: Task completed successfully.
  if (p.isDone || p.taskStatus === 'COMPLETED') {
    return 'done';
  }

  // 9. DEGRADED: Substrate operating under reduced capabilities.
  if (p.isDegraded) {
    return 'degraded';
  }

  // 10. IDLE: Default present and waiting state.
  return 'idle';
}

/**
 * Accessible textual representation for screen readers and assistive technology.
 */
export function getStateAriaLabel(state: AuraVisualState): string {
  switch (state) {
    case 'emergency_stop':
      return 'AURA is stopped by emergency kill switch';
    case 'waiting_for_approval':
      return 'AURA is waiting for human-in-the-loop approval';
    case 'error':
      return 'AURA encountered an error';
    case 'speaking':
      return 'AURA is speaking';
    case 'searching':
      return 'AURA is searching and gathering information';
    case 'thinking':
      return 'AURA is thinking and synthesizing plan';
    case 'listening':
      return 'AURA is listening for user input';
    case 'done':
      return 'AURA completed task execution';
    case 'degraded':
      return 'AURA is operating in degraded mode';
    case 'idle':
    default:
      return 'AURA is idle and ready';
  }
}

/**
 * Visual styling tokens and parameters per visual state.
 */
export const STATE_TOKENS: Record<AuraVisualState, AuraStateStyleTokens> = {
  idle: {
    label: 'IDLE',
    statusText: 'Present & Ready',
    primaryColor: '6, 182, 212', // Cyan
    secondaryColor: '59, 130, 246', // Blue
    coreGlow: 'rgba(6, 182, 212, 0.4)',
    particleDensity: 1.0,
    rotationSpeed: 0.3,
    pulseSpeed: 0.6,
    turbulence: 0.15,
    topology: 'sphere',
  },
  listening: {
    label: 'LISTENING',
    statusText: 'Awaiting Speech',
    primaryColor: '56, 189, 248', // Sky Blue
    secondaryColor: '6, 182, 212',
    coreGlow: 'rgba(56, 189, 248, 0.55)',
    particleDensity: 1.1,
    rotationSpeed: 0.4,
    pulseSpeed: 1.2,
    turbulence: 0.35,
    topology: 'sphere',
  },
  thinking: {
    label: 'THINKING',
    statusText: 'Synthesizing...',
    primaryColor: '139, 92, 246', // Violet
    secondaryColor: '192, 132, 252', // Lavender
    coreGlow: 'rgba(139, 92, 246, 0.6)',
    particleDensity: 1.2,
    rotationSpeed: 0.9,
    pulseSpeed: 1.5,
    turbulence: 0.5,
    topology: 'lattice',
  },
  searching: {
    label: 'SEARCHING',
    statusText: 'Gathering Intel',
    primaryColor: '6, 182, 212', // Cyan
    secondaryColor: '129, 140, 248', // Indigo
    coreGlow: 'rgba(6, 182, 212, 0.55)',
    particleDensity: 1.15,
    rotationSpeed: 1.2,
    pulseSpeed: 1.8,
    turbulence: 0.4,
    topology: 'rings',
  },
  speaking: {
    label: 'SPEAKING',
    statusText: 'Vocalizing Output',
    primaryColor: '16, 185, 129', // Emerald
    secondaryColor: '6, 182, 212', // Cyan
    coreGlow: 'rgba(16, 185, 129, 0.65)',
    particleDensity: 1.3,
    rotationSpeed: 0.7,
    pulseSpeed: 2.0,
    turbulence: 0.6,
    topology: 'wave',
  },
  done: {
    label: 'DONE',
    statusText: 'Execution Complete',
    primaryColor: '16, 185, 129', // Emerald
    secondaryColor: '52, 211, 153',
    coreGlow: 'rgba(16, 185, 129, 0.5)',
    particleDensity: 1.0,
    rotationSpeed: 0.2,
    pulseSpeed: 0.4,
    turbulence: 0.1,
    topology: 'burst',
  },
  waiting_for_approval: {
    label: 'WAITING APPROVAL',
    statusText: 'HITL Confirmation Required',
    primaryColor: '245, 158, 11', // Amber
    secondaryColor: '251, 191, 36',
    coreGlow: 'rgba(245, 158, 11, 0.6)',
    particleDensity: 1.05,
    rotationSpeed: 0.35,
    pulseSpeed: 0.9,
    turbulence: 0.2,
    topology: 'rings',
  },
  error: {
    label: 'ERROR',
    statusText: 'Execution Disturbance',
    primaryColor: '239, 68, 68', // Red
    secondaryColor: '244, 63, 94', // Rose
    coreGlow: 'rgba(239, 68, 68, 0.65)',
    particleDensity: 0.9,
    rotationSpeed: 0.5,
    pulseSpeed: 1.4,
    turbulence: 0.8,
    topology: 'wave',
  },
  degraded: {
    label: 'DEGRADED',
    statusText: 'Low Substrate Capacity',
    primaryColor: '100, 116, 139', // Slate
    secondaryColor: '71, 85, 105',
    coreGlow: 'rgba(100, 116, 139, 0.3)',
    particleDensity: 0.7,
    rotationSpeed: 0.15,
    pulseSpeed: 0.3,
    turbulence: 0.1,
    topology: 'sphere',
  },
  emergency_stop: {
    label: 'EMERGENCY HALT',
    statusText: 'Authority Locked',
    primaryColor: '239, 68, 68', // Crimson Red
    secondaryColor: '185, 28, 28', // Dark Crimson
    coreGlow: 'rgba(239, 68, 68, 0.75)',
    particleDensity: 1.0,
    rotationSpeed: 0.0,
    pulseSpeed: 0.0,
    turbulence: 0.0,
    topology: 'frozen',
  },
};
