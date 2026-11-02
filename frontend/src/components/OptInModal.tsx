import { useEffect } from 'react';

interface OptInModalProps {
  onClose: () => void;
}

export function OptInModal({ onClose }: OptInModalProps) {
  useEffect(() => {
    onClose();
  }, [onClose]);
  return null;
}
