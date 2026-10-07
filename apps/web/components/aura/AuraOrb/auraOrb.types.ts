export type AuraVisualState =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'searching'
  | 'speaking'
  | 'done'
  | 'waiting_for_approval'
  | 'error'
  | 'degraded'
  | 'emergency_stop';

export interface AudioFrequencyBands {
  low: number; // 0.0 - 1.0 (Bass response)
  mid: number; // 0.0 - 1.0 (Vocal range)
  high: number; // 0.0 - 1.0 (Presence & sibilance)
  onset?: number; // 0.0 - 1.0 (Transient beat / speech impulse)
}

export interface AuraOrbProps {
  state?: AuraVisualState;
  audioLevel?: number; // 0.0 - 1.0
  frequencyBands?: AudioFrequencyBands;
  progress?: number; // 0.0 - 1.0 (e.g. task progress or completion)
  caption?: string | null;
  size?: number; // CSS pixel diameter (default: 200)
  className?: string;
  showCaption?: boolean;
  showStatusBadge?: boolean;
  forceCanvasFallback?: boolean;
  interactive?: boolean;
  onClick?: () => void;
}

export interface AuraStateStyleTokens {
  label: string;
  statusText: string;
  primaryColor: string; // RGB tuple e.g. "6, 182, 212"
  secondaryColor: string;
  coreGlow: string;
  particleDensity: number;
  rotationSpeed: number;
  pulseSpeed: number;
  turbulence: number;
  topology: 'sphere' | 'rings' | 'lattice' | 'wave' | 'burst' | 'frozen';
}
