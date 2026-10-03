'use client';

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuraStore } from '../lib/store';
import { RuntimeEvent } from '../lib/types';
import { getAccessToken } from '../lib/api';

export function useSSEStream() {
  const queryClient = useQueryClient();
  const activeWorkspace = useAuraStore((s) => s.activeWorkspace);
  const addEvent = useAuraStore((s) => s.addEvent);
  const [isConnected, setIsConnected] = useState(false);
  const [lastHeartbeat, setLastHeartbeat] = useState<Date | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    let isSubscribed = true;
    let retryCount = 0;

    const connect = () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      const wsId = activeWorkspace?.id;
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';
      const url = `${baseUrl}/agent/events/stream${wsId ? `?workspace_id=${wsId}` : ''}`;

      try {
        const es = new EventSource(url, { withCredentials: true });
        eventSourceRef.current = es;

        es.onopen = () => {
          if (!isSubscribed) return;
          setIsConnected(true);
          retryCount = 0;
        };

        es.onmessage = (event) => {
          if (!isSubscribed) return;
          try {
            const parsed: RuntimeEvent = JSON.parse(event.data);
            if (parsed.event_type === 'ping') {
              setLastHeartbeat(new Date());
              return;
            }

            addEvent(parsed);

            // Invalidate affected query keys
            if (parsed.event_type.startsWith('task.')) {
              queryClient.invalidateQueries({ queryKey: ['tasks'] });
              if (parsed.task_id) {
                queryClient.invalidateQueries({ queryKey: ['task', parsed.task_id] });
              }
            } else if (parsed.event_type.startsWith('approval.')) {
              queryClient.invalidateQueries({ queryKey: ['approvals'] });
            } else if (parsed.event_type.startsWith('memory.')) {
              queryClient.invalidateQueries({ queryKey: ['memory'] });
            } else if (parsed.event_type === 'kill_switch.activated') {
              queryClient.invalidateQueries({ queryKey: ['tasks'] });
              queryClient.invalidateQueries({ queryKey: ['approvals'] });
              queryClient.invalidateQueries({ queryKey: ['agent-health'] });
            }
          } catch (e) {
            console.error('Failed to parse SSE event data:', e);
          }
        };

        es.onerror = () => {
          if (!isSubscribed) return;
          setIsConnected(false);
          es.close();

          // Exponential backoff reconnect
          const backoff = Math.min(1000 * Math.pow(2, retryCount), 10000);
          retryCount++;
          retryTimeoutRef.current = setTimeout(() => {
            if (isSubscribed) {
              connect();
            }
          }, backoff);
        };
      } catch (err) {
        setIsConnected(false);
      }
    };

    connect();

    return () => {
      isSubscribed = false;
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [activeWorkspace?.id, queryClient, addEvent]);

  return { isConnected, lastHeartbeat };
}
