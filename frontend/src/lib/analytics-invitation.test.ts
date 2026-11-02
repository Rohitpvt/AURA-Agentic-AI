import { describe, it, expect, vi } from 'vitest';
import { offerAnalyticsChoice } from './analytics-invitation';

describe('analytics invitation', () => {
  it('is disabled and clean', () => {
    const fn = vi.fn();
    const cleanup = offerAnalyticsChoice({
      ready: true,
      sharingModalSeen: false,
      open: fn,
      markSharingModalSeen: fn,
    });
    expect(fn).not.toHaveBeenCalled();
    expect(typeof cleanup).toBe('function');
  });
});
