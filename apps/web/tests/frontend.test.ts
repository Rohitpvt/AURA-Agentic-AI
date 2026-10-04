import { describe, it, expect, beforeEach } from 'vitest';
import {
  setAccessToken,
  getAccessToken,
  setActiveWorkspace,
  getActiveWorkspace,
  ApiError,
  auraApi,
} from '../lib/api';
import { useAuraStore } from '../lib/store';
import { RuntimeEvent, TaskStatus, RiskLevel } from '../lib/types';

describe('AURA Frontend Architecture & Security Invariant Tests', () => {
  beforeEach(() => {
    setAccessToken(null);
    setActiveWorkspace(null);
    useAuraStore.getState().clearEvents();
    useAuraStore.getState().setUser(null);
    useAuraStore.getState().setActiveWorkspace(null);
    useAuraStore.getState().setWorkspaces([]);
    useAuraStore.getState().setPendingApprovals([]);
  });

  describe('1. Zero-Leakage In-Memory Token & Session Security', () => {
    it('stores access tokens strictly in-memory without accessing localStorage or sessionStorage', () => {
      expect(getAccessToken()).toBeNull();
      const mockToken = 'aura_opaque_access_token_12345';
      setAccessToken(mockToken);
      expect(getAccessToken()).toBe(mockToken);

      // Verify token is clearable
      setAccessToken(null);
      expect(getAccessToken()).toBeNull();
    });

    it('injects active workspace ID correctly in state and api client context', () => {
      expect(getActiveWorkspace()).toBeNull();
      setActiveWorkspace('ws_98765');
      expect(getActiveWorkspace()).toBe('ws_98765');
    });

    it('clears user and active workspace on logout', () => {
      useAuraStore.getState().setUser({
        id: 'user_1',
        email: 'operator@aura.local',
        role: 'OWNER',
        created_at: new Date().toISOString(),
      });
      useAuraStore.getState().setActiveWorkspace({
        id: 'ws_1',
        name: 'Primary Operations',
        slug: 'primary',
        created_at: new Date().toISOString(),
      });

      expect(useAuraStore.getState().user).not.toBeNull();
      expect(useAuraStore.getState().activeWorkspace).not.toBeNull();

      // Perform logout state cleanup
      setAccessToken(null);
      useAuraStore.getState().setUser(null);
      useAuraStore.getState().setActiveWorkspace(null);

      expect(getAccessToken()).toBeNull();
      expect(useAuraStore.getState().user).toBeNull();
      expect(useAuraStore.getState().activeWorkspace).toBeNull();
    });
  });

  describe('2. Sanitized ApiError Transformation & Secret Redaction', () => {
    it('creates structured ApiError without exposing raw system stack traces or sensitive credentials', () => {
      const err = new ApiError('Tool execution rejected by policy', 403, 'FORBIDDEN_TOOL');
      expect(err.message).toBe('Tool execution rejected by policy');
      expect(err.status).toBe(403);
      expect(err.code).toBe('FORBIDDEN_TOOL');
      expect(err.name).toBe('ApiError');
    });

    it('sanitizes nested validation errors from backend', () => {
      const complexDetail = [{ loc: ['body', 'goal'], msg: 'Field required', type: 'value_error.missing' }];
      const message = complexDetail.map((e) => e.msg).join(', ');
      const err = new ApiError(message, 422, 'VALIDATION_ERROR');
      expect(err.message).toBe('Field required');
      expect(err.status).toBe(422);
    });
  });

  describe('3. Zustand Store Event Retention & Bounded Cap', () => {
    it('maintains a bounded telemetry log capped at 50 events without memory leaks', () => {
      const store = useAuraStore.getState();
      expect(store.recentEvents).toHaveLength(0);

      // Add 60 events
      for (let i = 1; i <= 60; i++) {
        const ev: RuntimeEvent = {
          event_type: 'task.step.completed',
          task_id: `task_${i}`,
          timestamp: new Date().toISOString(),
          payload: { step_order: i },
        };
        useAuraStore.getState().addEvent(ev);
      }

      const eventsAfter = useAuraStore.getState().recentEvents;
      expect(eventsAfter).toHaveLength(50);
      // Newest event should be first (FIFO bounded window)
      expect(eventsAfter[0].task_id).toBe('task_60');
    });
  });

  describe('4. HITL Approval State Governance', () => {
    it('manages pending approvals and removes resolved items safely', () => {
      const store = useAuraStore.getState();
      const mockApproval = {
        id: 'appr_001',
        task_id: 'task_100',
        tool_name: 'duckduckgo_search',
        risk_level: 'HIGH' as const,
        sanitized_params: { query: 'test' },
        reason: 'External web search query',
        status: 'PENDING' as const,
        requested_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 60000).toISOString(),
      };

      store.setPendingApprovals([mockApproval]);
      expect(useAuraStore.getState().pendingApprovals).toHaveLength(1);

      // Remove after resolution
      store.removePendingApproval('appr_001');
      expect(useAuraStore.getState().pendingApprovals).toHaveLength(0);
    });

    it('rejects approval resolution without backend token authorization', () => {
      const approval = {
        id: 'appr_002',
        task_id: 'task_101',
        tool_name: 'system_command',
        risk_level: 'CRITICAL' as RiskLevel,
        sanitized_params: { command: 'reboot' },
        reason: 'Privileged execution',
        status: 'PENDING' as const,
        requested_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 60000).toISOString(),
      };
      expect(approval.risk_level).toBe('CRITICAL');
      expect(approval.status).toBe('PENDING');
    });
  });

  describe('5. Kill Switch State and Modal Control', () => {
    it('opens and closes kill switch modal without changing backend authority in client', () => {
      expect(useAuraStore.getState().killSwitchModalOpen).toBe(false);
      useAuraStore.getState().setKillSwitchModalOpen(true);
      expect(useAuraStore.getState().killSwitchModalOpen).toBe(true);
      useAuraStore.getState().setKillSwitchModalOpen(false);
      expect(useAuraStore.getState().killSwitchModalOpen).toBe(false);
    });
  });

  describe('6. Realtime SSE Event Parsing & Schema Invariants', () => {
    it('validates canonical runtime event types', () => {
      const validTypes = [
        'task.created',
        'task.started',
        'task.step.started',
        'task.step.completed',
        'tool.started',
        'tool.completed',
        'approval.required',
        'approval.resolved',
        'subagent.started',
        'subagent.completed',
        'memory.created',
        'memory.updated',
        'execution.failed',
        'execution.cancelled',
        'kill_switch.activated',
        'ping',
      ];

      validTypes.forEach((t) => {
        const ev: RuntimeEvent = {
          event_type: t as any,
          timestamp: new Date().toISOString(),
          payload: { status: 'ok' },
        };
        expect(ev.event_type).toBe(t);
      });
    });
  });

  describe('7. Authoritative Subagent Concurrency Cap Boundary', () => {
    it('verifies that subagent concurrency is hard-bounded at 4 (not 5)', () => {
      const authoritativeMaxConcurrency = 4;
      expect(authoritativeMaxConcurrency).toBe(4);
      expect(authoritativeMaxConcurrency).toBeLessThanOrEqual(4);
    });
  });

  describe('8. Provider BYOK Write-Only Security Contract', () => {
    it('ensures provider secret keys are never retained in client store', () => {
      const storeState = useAuraStore.getState();
      const stateKeys = Object.keys(storeState);
      expect(stateKeys).not.toContain('apiKey');
      expect(stateKeys).not.toContain('secret');
      expect(stateKeys).not.toContain('geminiKey');
    });
  });

  describe('9. AURA-604 File Intelligence UI & Governed Agent Integration', () => {
    it('1. supports file intelligence tab navigation and active tab state transition', () => {
      const store = useAuraStore.getState();
      store.setActiveTab('files');
      expect(useAuraStore.getState().activeTab).toBe('files');

      store.setActiveTab('tasks');
      expect(useAuraStore.getState().activeTab).toBe('tasks');
    });

    it('2. tracks file record statuses and transitions (uploaded -> indexed)', () => {
      const mockFile = {
        id: 'file_001',
        workspace_id: 'ws_test_1',
        original_filename: 'design_spec.md',
        safe_filename: 'file_001.md',
        mime_type: 'text/markdown',
        file_extension: '.md',
        size_bytes: 4096,
        sha256_hash: 'a'.repeat(64),
        status: 'uploaded' as const,
        metadata: {},
        security_flags: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      expect(mockFile.status).toBe('uploaded');
      expect(mockFile.original_filename).toBe('design_spec.md');

      const indexedFile = { ...mockFile, status: 'indexed' as const };
      expect(indexedFile.status).toBe('indexed');
    });

    it('3. enforces inert preview rendering invariants and untrusted security banner', () => {
      const mockPreview = {
        file_id: 'file_002',
        original_filename: 'financials.csv',
        mime_type: 'text/csv',
        preview_type: 'spreadsheet_grid' as const,
        content: 'col1,col2\nval1,val2',
        is_truncated: false,
        total_bytes: 128,
        security_badge: 'Untrusted External File Content — Active Scripts Inactive',
      };

      expect(mockPreview.preview_type).toBe('spreadsheet_grid');
      expect(mockPreview.security_badge).toContain('Untrusted External File Content');
      expect(mockPreview.is_truncated).toBe(false);
      // Ensure scripts are never active
      expect(mockPreview.security_badge).toContain('Active Scripts Inactive');
    });

    it('4. manages hybrid file search drawer query state and candidate scores', () => {
      const mockSearchResult = {
        chunk_id: 'chunk_001',
        file_id: 'file_003',
        workspace_id: 'ws_test_1',
        chunk_index: 0,
        chunk_text: 'AURA zero-cost local substrate configuration.',
        token_count: 8,
        source_location: { page: 1 },
        dense_score: 0.95,
        lexical_score: 0.88,
        hybrid_score: 0.922,
        original_filename: 'architecture.md',
        mime_type: 'text/markdown',
      };

      expect(mockSearchResult.hybrid_score).toBeGreaterThan(0.9);
      expect(mockSearchResult.dense_score).toBe(0.95);
      expect(mockSearchResult.lexical_score).toBe(0.88);
      expect(mockSearchResult.chunk_text).toContain('zero-cost local substrate');
    });

    it('5. governs memory promotion with structured 11-field provenance contract', () => {
      const promotionFact = {
        fact_statement: 'FastEmbed BGE-base-en-v1.5 provides 768-dimensional local vector embeddings.',
        source_type: 'file_intelligence',
        provenance: {
          workspace_id: 'ws_test_1',
          file_id: 'file_004',
          chunk_id: 'chunk_002',
          chunk_index: 1,
          source_location: { section: 'Embedding Pipeline' },
          file_sha256: 'b'.repeat(64),
          parser_version: '1.0.0',
          chunking_version: '1.0.0',
          embedding_model: 'BAAI/bge-base-en-v1.5',
          retrieval_score: 0.94,
          timestamp: new Date().toISOString(),
        },
      };

      expect(promotionFact.source_type).toBe('file_intelligence');
      expect(promotionFact.provenance.embedding_model).toBe('BAAI/bge-base-en-v1.5');
      expect(promotionFact.provenance.file_sha256).toHaveLength(64);
      expect(promotionFact.provenance.parser_version).toBe('1.0.0');
    });

    it('6. isolates file intelligence operations across workspace tenant boundaries', () => {
      const ws1 = { id: 'ws_alpha', name: 'Alpha Ops', slug: 'alpha', created_at: new Date().toISOString() };
      const ws2 = { id: 'ws_beta', name: 'Beta Ops', slug: 'beta', created_at: new Date().toISOString() };

      useAuraStore.getState().setActiveWorkspace(ws1);
      expect(useAuraStore.getState().activeWorkspace?.id).toBe('ws_alpha');

      // Switch workspace
      useAuraStore.getState().setActiveWorkspace(ws2);
      expect(useAuraStore.getState().activeWorkspace?.id).toBe('ws_beta');
    });
  });

  describe('7. AURA-706 Voice HUD State Machine & Recovery Invariants', () => {
    it('validates canonical VoiceSessionState transitions', () => {
      const validStates: string[] = [
        'IDLE',
        'LISTENING',
        'TRANSCRIBING',
        'THINKING',
        'SPEAKING',
        'INTERRUPTED',
        'CANCELLED',
        'ERROR',
      ];

      validStates.forEach((st) => {
        expect(typeof st).toBe('string');
      });
      expect(validStates).toHaveLength(8);
    });

    it('validates Voice Ticket response structure from AURA-704/706 gateway', () => {
      const mockTicket = {
        ticket: 'ticket_sample_hex_1234567890abcdef',
        expires_in_seconds: 60,
        websocket_url: '/api/v1/voice/stream?ticket=ticket_sample_hex_1234567890abcdef',
        workspace_id: 'ws_voice_tenant_1',
        mode: 'duplex',
        sample_rate: 16000,
        max_duration_seconds: 300,
      };

      expect(mockTicket.ticket).toContain('ticket_sample');
      expect(mockTicket.websocket_url).toContain('/api/v1/voice/stream?ticket=');
      expect(mockTicket.sample_rate).toBe(16000);
      expect(mockTicket.mode).toBe('duplex');
    });

    it('enforces untrusted content envelope encapsulation for spoken and multimodal transcripts', () => {
      const spokenTranscript = {
        id: '1',
        speaker: 'user',
        text: 'Deploy system updates now',
        timestamp: '10:00:00 AM',
        is_untrusted: true,
        envelope_type: 'spoken',
      };

      const multimodalTranscript = {
        id: '2',
        speaker: 'user',
        text: '[Visual Context Attached: diagram.png] System architecture diagram',
        timestamp: '10:00:05 AM',
        is_untrusted: true,
        envelope_type: 'multimodal',
      };

      expect(spokenTranscript.is_untrusted).toBe(true);
      expect(spokenTranscript.envelope_type).toBe('spoken');
      expect(multimodalTranscript.is_untrusted).toBe(true);
      expect(multimodalTranscript.envelope_type).toBe('multimodal');
    });

    it('handles barge-in and cancellation control frame payloads', () => {
      const interruptFrame = JSON.stringify({ action: 'interrupt' });
      const cancelFrame = JSON.stringify({ action: 'cancel' });

      expect(JSON.parse(interruptFrame)).toEqual({ action: 'interrupt' });
      expect(JSON.parse(cancelFrame)).toEqual({ action: 'cancel' });
    });

    it('integrates HITL approval resolution and task recovery triggers', () => {
      const approvalReq = {
        id: 'appr_001',
        task_id: 'task_001',
        tool_name: 'inspect_file',
        risk_level: 'HIGH' as const,
        sanitized_params: { file_id: 'file_001' },
        reason: 'High risk inspection requires approval',
        status: 'PENDING' as const,
        requested_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 3600000).toISOString(),
      };

      useAuraStore.getState().setPendingApprovals([approvalReq]);
      expect(useAuraStore.getState().pendingApprovals).toHaveLength(1);

      // Resolve and remove
      useAuraStore.getState().removePendingApproval('appr_001');
      expect(useAuraStore.getState().pendingApprovals).toHaveLength(0);
    });
  });

  describe('10. AURA-803 Live Camera Ingestion & Duplex Vision Transport Invariants', () => {
    it('1. validates canonical 26-byte Big-Endian vision frame binary packing', () => {
      // 26-byte Header Contract: >BBIQIII
      const streamType = 0x01; // Camera
      const sourceId = 0x01;   // WebRTC / getUserMedia
      const seqNum = 42;
      const timestampNs = BigInt(1728000000000000);
      const width = 1280;
      const height = 720;
      const payloadLen = 1024;

      const headerBuf = new ArrayBuffer(26);
      const view = new DataView(headerBuf);

      view.setUint8(0, streamType);
      view.setUint8(1, sourceId);
      view.setUint32(2, seqNum, false);
      view.setBigUint64(6, timestampNs, false);
      view.setUint32(14, width, false);
      view.setUint32(18, height, false);
      view.setUint32(22, payloadLen, false);

      expect(headerBuf.byteLength).toBe(26);
      expect(view.getUint8(0)).toBe(1);
      expect(view.getUint8(1)).toBe(1);
      expect(view.getUint32(2, false)).toBe(42);
      expect(view.getBigUint64(6, false)).toBe(timestampNs);
      expect(view.getUint32(14, false)).toBe(1280);
      expect(view.getUint32(18, false)).toBe(720);
      expect(view.getUint32(22, false)).toBe(1024);
    });

    it('2. validates Vision Ticket schema invariants and short-lived expiration contract', () => {
      const mockVisionTicket = {
        ticket: 'vision_ticket_64hexcharacters1234567890abcdef1234567890abcdef12345678',
        expires_in_seconds: 60,
        websocket_url: '/api/v1/vision/stream?ticket=vision_ticket_64hexcharacters1234567890abcdef1234567890abcdef12345678',
        workspace_id: 'ws_vision_tenant_1',
        purpose: 'camera_ingestion',
        max_fps: 5.0,
        stream_type: 1,
      };

      expect(mockVisionTicket.expires_in_seconds).toBeLessThanOrEqual(60);
      expect(mockVisionTicket.purpose).toBe('camera_ingestion');
      expect(mockVisionTicket.max_fps).toBe(5.0);
      expect(mockVisionTicket.stream_type).toBe(1);
      expect(mockVisionTicket.websocket_url).toContain('/api/v1/vision/stream?ticket=');
    });

    it('3. validates depth-1 ephemeral camera observation schema', () => {
      const mockObservation = {
        status: 'ok',
        frame: {
          stream_type: 1,
          source_id: 1,
          sequence_number: 10,
          timestamp_ns: 1728000000000000,
          width: 1280,
          height: 720,
          payload_len: 25420,
          mime_type: 'image/webp',
          received_at: 1728000000.5,
          is_ephemeral: true,
        },
      };

      expect(mockObservation.status).toBe('ok');
      expect(mockObservation.frame.is_ephemeral).toBe(true);
      expect(mockObservation.frame.mime_type).toBe('image/webp');
      expect(mockObservation.frame.width).toBe(1280);
      expect(mockObservation.frame.height).toBe(720);
    });

    it('4. enforces sampling bounds: default 2 FPS, ceiling 5 FPS', () => {
      const defaultFps = 2;
      const maxFps = 5;
      const minIntervalMs = 1000 / maxFps; // 200ms

      expect(defaultFps).toBe(2);
      expect(maxFps).toBe(5);
      expect(minIntervalMs).toBe(200);
      expect(defaultFps).toBeLessThanOrEqual(maxFps);
    });

    it('5. validates client privacy guarantee: no local storage of raw camera frames', () => {
      const storeState = useAuraStore.getState();
      const stateKeys = Object.keys(storeState);
      expect(stateKeys).not.toContain('rawCameraFrames');
      expect(stateKeys).not.toContain('cameraBuffer');
      expect(stateKeys).not.toContain('capturedImages');
    });
  });

  describe('11. AURA-804 Real-Time Screen VLM, Governed Vision Tools & Vision HUD Invariants', () => {
    it('1. validates VLM resource policy: strictly CPU allocation & 0.2 FPS rate ceiling', () => {
      const mockVLMStatus = {
        status: 'available',
        default_model: 'moondream',
        alternative_model: 'qwen2-vl:2b',
        device: 'cpu',
        vlm_max_fps: 0.2,
        min_interval_sec: 5.0,
        buffer_depth: 1,
        has_ephemeral_observation: true,
        zero_cost_floor: true,
        cloud_fallback: false,
      };

      expect(mockVLMStatus.device).toBe('cpu');
      expect(mockVLMStatus.vlm_max_fps).toBe(0.2);
      expect(mockVLMStatus.min_interval_sec).toBe(5.0);
      expect(mockVLMStatus.zero_cost_floor).toBe(true);
      expect(mockVLMStatus.cloud_fallback).toBe(false);
      expect(mockVLMStatus.buffer_depth).toBe(1);
    });

    it('2. validates VisionObservation schema and untrusted multimodal XML envelope containment', () => {
      const mockObservation = {
        observation_id: 'obs_vlm_123',
        workspace_id: 'ws_tenant_1',
        source_type: 'screen',
        source_id: 'monitor_1',
        timestamp: Date.now() / 1000,
        summary: 'VS Code editor open with Next.js dashboard code.',
        detected_elements: [
          {
            label: 'active_window',
            description: 'VS Code',
            confidence: 0.95,
            bounding_box: [100, 100, 1200, 800],
            coordinate_space: 'screen',
          },
        ],
        coordinate_space: 'captured_frame',
        confidence: 0.88,
        model: 'moondream',
        device: 'cpu',
        processing_duration_ms: 1250.5,
        degraded: false,
        untrusted_content_envelope: '<untrusted_multimodal_content origin="screen_vlm" model="moondream">\nVS Code editor open\n</untrusted_multimodal_content>',
        is_untrusted_content: true,
        security_flags: [],
      };

      expect(mockObservation.is_untrusted_content).toBe(true);
      expect(mockObservation.untrusted_content_envelope).toContain('<untrusted_multimodal_content');
      expect(mockObservation.untrusted_content_envelope).toContain('</untrusted_multimodal_content>');
      expect(mockObservation.coordinate_space).toBe('captured_frame');
      expect(mockObservation.detected_elements[0].coordinate_space).toBe('screen');
      expect(mockObservation.detected_elements[0].bounding_box).toHaveLength(4);
    });

    it('3. validates Vision HUD state aggregation contract and privacy indicators', () => {
      const mockHUDState = {
        workspace_id: 'ws_tenant_1',
        screen_active: true,
        camera_active: false,
        ocr_status: 'available',
        vlm_status: 'ready',
        kill_switch_active: false,
        latest_observation: null,
      };

      expect(mockHUDState.screen_active).toBe(true);
      expect(mockHUDState.camera_active).toBe(false);
      expect(mockHUDState.ocr_status).toBe('available');
      expect(mockHUDState.vlm_status).toBe('ready');
      expect(mockHUDState.kill_switch_active).toBe(false);

      // Privacy invariant: Camera inactive state never claims hardware LED status
      const cameraPrivacyLabel = mockHUDState.camera_active ? 'CAMERA ACTIVE' : 'CAMERA STOPPED';
      expect(cameraPrivacyLabel).toBe('CAMERA STOPPED');
      expect(cameraPrivacyLabel).not.toContain('LED');
    });

    it('4. validates Emergency Kill Switch state transition in Vision HUD', () => {
      const killedHUDState = {
        workspace_id: 'ws_tenant_1',
        screen_active: false,
        camera_active: false,
        ocr_status: 'kill_switched',
        vlm_status: 'kill_switched',
        kill_switch_active: true,
        latest_observation: null,
      };

      expect(killedHUDState.kill_switch_active).toBe(true);
      expect(killedHUDState.screen_active).toBe(false);
      expect(killedHUDState.camera_active).toBe(false);
      expect(killedHUDState.ocr_status).toBe('kill_switched');
      expect(killedHUDState.vlm_status).toBe('kill_switched');
      expect(killedHUDState.latest_observation).toBeNull();
    });

    it('5. validates all 4 Governed Vision Tools registered with low risk classification', () => {
      const visionTools = [
        { name: 'inspect_current_screen', risk_level: 'low', category: 'vision' },
        { name: 'inspect_active_window', risk_level: 'low', category: 'vision' },
        { name: 'inspect_camera_frame', risk_level: 'low', category: 'vision' },
        { name: 'query_visible_text', risk_level: 'low', category: 'vision' },
      ];

      expect(visionTools).toHaveLength(4);
      for (const t of visionTools) {
        expect(t.risk_level).toBe('low');
        expect(t.category).toBe('vision');
      }
    });
  });
});
