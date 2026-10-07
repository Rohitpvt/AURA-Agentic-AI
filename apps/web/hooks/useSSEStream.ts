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
  const abortControllerRef = useRef<AbortController | null>(null);
  const retryTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    let isSubscribed = true;
    let retryCount = 0;

    const connect = async () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const wsId = activeWorkspace?.id;
      if (!wsId) {
        setIsConnected(false);
        return;
      }

      const token = getAccessToken();
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';
      const url = `${baseUrl}/agent/events/stream?workspace_id=${wsId}`;

      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      try {
        const headers: Record<string, string> = {
          Accept: 'text/event-stream',
        };
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
        }

        const response = await fetch(url, {
          method: 'GET',
          headers,
          signal: abortController.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error(`SSE stream connection failed with status ${response.status}`);
        }

        if (!isSubscribed) return;
        setIsConnected(true);
        retryCount = 0;

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (isSubscribed) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop() || '';

          for (const block of lines) {
            if (!block.trim()) continue;

            const eventLines = block.split('\n');
            let eventType = 'message';
            let eventData = '';

            for (const line of eventLines) {
              if (line.startsWith('event:')) {
                eventType = line.replace('event:', '').trim();
              } else if (line.startsWith('data:')) {
                eventData = line.replace('data:', '').trim();
              } else if (line.startsWith(':')) {
                // Heartbeat keepalive comment
                setLastHeartbeat(new Date());
              }
            }

            if (eventData) {
              try {
                const parsed = JSON.parse(eventData);
                if (
                  eventType === 'ping' ||
                  parsed.event_type === 'ping' ||
                  parsed.status === 'connected'
                ) {
                  setLastHeartbeat(new Date());
                  continue;
                }

                const runtimeEv = parsed as RuntimeEvent;
                addEvent(runtimeEv);

                // Invalidate affected query keys
                if (runtimeEv.event_type?.startsWith('task.')) {
                  queryClient.invalidateQueries({ queryKey: ['tasks'] });
                  if (runtimeEv.task_id) {
                    queryClient.invalidateQueries({ queryKey: ['task', runtimeEv.task_id] });
                  }
                } else if (runtimeEv.event_type?.startsWith('approval.')) {
                  queryClient.invalidateQueries({ queryKey: ['approvals'] });
                } else if (runtimeEv.event_type?.startsWith('memory.')) {
                  queryClient.invalidateQueries({ queryKey: ['memory'] });
                } else if (runtimeEv.event_type === 'kill_switch.activated') {
                  queryClient.invalidateQueries({ queryKey: ['tasks'] });
                  queryClient.invalidateQueries({ queryKey: ['approvals'] });
                  queryClient.invalidateQueries({ queryKey: ['agent-health'] });
                }
              } catch (e) {
                // Ignore parsing errors on non-json stream frames
              }
            }
          }
        }
      } catch (err: any) {
        if (err.name === 'AbortError') return;
        if (!isSubscribed) return;
        setIsConnected(false);

        // Exponential backoff reconnect
        const backoff = Math.min(1000 * Math.pow(2, retryCount), 10000);
        retryCount++;
        retryTimeoutRef.current = setTimeout(() => {
          if (isSubscribed) {
            connect();
          }
        }, backoff);
      }
    };

    connect();

    return () => {
      isSubscribed = false;
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, [activeWorkspace?.id, queryClient, addEvent]);

  return { isConnected, lastHeartbeat };
}
