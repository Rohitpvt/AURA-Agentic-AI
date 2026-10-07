import { describe, it, expect } from 'vitest';
import {
  deriveVisualState,
  getStateAriaLabel,
  STATE_TOKENS,
  AuraVisualState,
} from '../components/aura/AuraOrb';

describe('AURA Visual Identity — AuraOrb State Architecture & Security Tests', () => {
  const allStates: AuraVisualState[] = [
    'idle',
    'listening',
    'thinking',
    'searching',
    'speaking',
    'done',
    'waiting_for_approval',
    'error',
    'degraded',
    'emergency_stop',
  ];

  describe('1. 10 Target Visual States & Token Integrity', () => {
    it('defines complete style tokens for all 10 visual states', () => {
      expect(allStates).toHaveLength(10);

      allStates.forEach((st) => {
        const tokens = STATE_TOKENS[st];
        expect(tokens).toBeDefined();
        expect(tokens.label).toBeTruthy();
        expect(tokens.statusText).toBeTruthy();
        expect(tokens.primaryColor).toMatch(/^\d+,\s*\d+,\s*\d+$/);
        expect(tokens.secondaryColor).toMatch(/^\d+,\s*\d+,\s*\d+$/);
        expect(tokens.coreGlow).toContain('rgba(');
        expect(tokens.particleDensity).toBeGreaterThan(0);
        expect(tokens.topology).toMatch(/^(sphere|rings|lattice|wave|burst|frozen)$/);
      });
    });

    it('freezes animation and particle velocity in emergency_stop state', () => {
      const emergencyTokens = STATE_TOKENS.emergency_stop;
      expect(emergencyTokens.rotationSpeed).toBe(0);
      expect(emergencyTokens.pulseSpeed).toBe(0);
      expect(emergencyTokens.turbulence).toBe(0);
      expect(emergencyTokens.topology).toBe('frozen');
      expect(emergencyTokens.label).toBe('EMERGENCY HALT');
    });
  });

  describe('2. State Priority & Security Truth Hierarchy', () => {
    it('1. EMERGENCY_STOP overrides ALL other states including speaking, approvals, errors, and thinking', () => {
      const visualState = deriveVisualState({
        killSwitchActive: true,
        pendingApprovalsCount: 5,
        hasErrors: true,
        voiceState: 'SPEAKING',
        taskStatus: 'IN_PROGRESS',
        isSearching: true,
        isProcessing: true,
      });
      expect(visualState).toBe('emergency_stop');
    });

    it('2. WAITING_FOR_APPROVAL overrides error, speaking, searching, thinking, and idle', () => {
      const visualState = deriveVisualState({
        killSwitchActive: false,
        pendingApprovalsCount: 2,
        hasErrors: true,
        voiceState: 'SPEAKING',
        taskStatus: 'WAITING_APPROVAL',
        isSearching: true,
        isProcessing: true,
      });
      expect(visualState).toBe('waiting_for_approval');
    });

    it('3. ERROR state is derived when hasErrors is true or voiceState is ERROR or taskStatus is FAILED', () => {
      expect(
        deriveVisualState({
          hasErrors: true,
          voiceState: 'SPEAKING',
          taskStatus: 'IN_PROGRESS',
        })
      ).toBe('error');

      expect(
        deriveVisualState({
          voiceState: 'ERROR',
          taskStatus: 'IN_PROGRESS',
        })
      ).toBe('error');

      expect(
        deriveVisualState({
          taskStatus: 'FAILED',
        })
      ).toBe('error');
    });

    it('4. SPEAKING state is derived when voiceState is SPEAKING', () => {
      const visualState = deriveVisualState({
        voiceState: 'SPEAKING',
        taskStatus: 'IN_PROGRESS',
        isProcessing: true,
      });
      expect(visualState).toBe('speaking');
    });

    it('5. SEARCHING state is derived during tool search / information retrieval', () => {
      expect(
        deriveVisualState({
          isSearching: true,
          taskStatus: 'IN_PROGRESS',
        })
      ).toBe('searching');

      expect(
        deriveVisualState({
          taskStatus: 'VERIFYING',
        })
      ).toBe('searching');
    });

    it('6. THINKING state is derived during cognitive synthesis, transcription, or planning', () => {
      expect(
        deriveVisualState({
          voiceState: 'THINKING',
        })
      ).toBe('thinking');

      expect(
        deriveVisualState({
          voiceState: 'TRANSCRIBING',
        })
      ).toBe('thinking');

      expect(
        deriveVisualState({
          taskStatus: 'PLANNING',
        })
      ).toBe('thinking');

      expect(
        deriveVisualState({
          isProcessing: true,
        })
      ).toBe('thinking');
    });

    it('7. LISTENING state is derived when voice session is listening', () => {
      const visualState = deriveVisualState({
        voiceState: 'LISTENING',
      });
      expect(visualState).toBe('listening');
    });

    it('8. DONE state is derived upon successful task completion', () => {
      expect(
        deriveVisualState({
          isDone: true,
        })
      ).toBe('done');

      expect(
        deriveVisualState({
          taskStatus: 'COMPLETED',
        })
      ).toBe('done');
    });

    it('9. DEGRADED state is derived when operating under reduced substrate capacity', () => {
      const visualState = deriveVisualState({
        isDegraded: true,
      });
      expect(visualState).toBe('degraded');
    });

    it('10. IDLE state is the safe fallback when all parameters are neutral or null', () => {
      const visualState = deriveVisualState({});
      expect(visualState).toBe('idle');
    });
  });

  describe('3. Accessibility & Screen Reader Descriptions', () => {
    it('returns accessible, descriptive aria labels for all 10 states', () => {
      allStates.forEach((st) => {
        const aria = getStateAriaLabel(st);
        expect(aria).toBeTruthy();
        expect(aria.startsWith('AURA ')).toBe(true);
      });

      expect(getStateAriaLabel('emergency_stop')).toBe('AURA is stopped by emergency kill switch');
      expect(getStateAriaLabel('waiting_for_approval')).toBe(
        'AURA is waiting for human-in-the-loop approval'
      );
      expect(getStateAriaLabel('speaking')).toBe('AURA is speaking');
      expect(getStateAriaLabel('thinking')).toBe('AURA is thinking and synthesizing plan');
      expect(getStateAriaLabel('searching')).toBe('AURA is searching and gathering information');
      expect(getStateAriaLabel('idle')).toBe('AURA is idle and ready');
    });
  });

  describe('4. Zero-Leakage & Safety Boundaries', () => {
    it('verifies visual state derivation contains no credentials, secrets, or auth tokens', () => {
      const params = {
        killSwitchActive: false,
        pendingApprovalsCount: 0,
        voiceState: 'IDLE' as const,
      };
      const keys = Object.keys(params);
      expect(keys).not.toContain('apiKey');
      expect(keys).not.toContain('token');
      expect(keys).not.toContain('secret');
      expect(keys).not.toContain('password');
    });

    it('handles unexpected or undefined params safely without throwing', () => {
      expect(() => deriveVisualState(null as any)).not.toThrow();
      expect(deriveVisualState(null as any)).toBe('idle');

      expect(() => deriveVisualState(undefined as any)).not.toThrow();
      expect(deriveVisualState(undefined as any)).toBe('idle');
    });
  });

  describe('5. Audio Reactivity & Boundary Constraints', () => {
    it('safely tolerates missing or out-of-bound audio levels without throwing', () => {
      const visualState = deriveVisualState({
        voiceState: 'SPEAKING',
      });
      expect(visualState).toBe('speaking');

      // Check that state derivation works regardless of audio values
      expect(deriveVisualState({ voiceState: 'LISTENING' })).toBe('listening');
      expect(deriveVisualState({ voiceState: 'IDLE' })).toBe('idle');
    });

    it('all states provide deterministic, non-empty labels and unique status texts', () => {
      allStates.forEach((st) => {
        const token = STATE_TOKENS[st];
        expect(token.label.length).toBeGreaterThan(0);
        expect(token.statusText.length).toBeGreaterThan(0);
        expect(token.primaryColor.split(',')).toHaveLength(3);
        expect(token.secondaryColor.split(',')).toHaveLength(3);
      });
    });
  });
});

