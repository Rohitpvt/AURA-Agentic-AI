import { describe, it, expect, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { OptInModal } from './OptInModal';

describe('OptInModal', () => {
  it('renders nothing when bloatware modal is removed', () => {
    const html = renderToStaticMarkup(<OptInModal onClose={vi.fn()} />);
    expect(html).toBe('');
  });
});
