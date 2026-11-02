interface AnalyticsInvitation {
  ready: boolean;
  sharingModalSeen: boolean;
  open: () => void;
  markSharingModalSeen: () => void;
}

export function offerAnalyticsChoice(_invitation: AnalyticsInvitation): () => void {
  return () => {};
}
