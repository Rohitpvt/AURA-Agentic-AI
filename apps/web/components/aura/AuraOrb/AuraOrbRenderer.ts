import { AuraVisualState, AudioFrequencyBands } from './auraOrb.types';
import { STATE_TOKENS } from './auraOrbStateMap';

interface Particle {
  theta: number; // azimuthal angle [0, 2pi]
  phi: number; // polar angle [-pi/2, pi/2]
  baseRadius: number;
  currentRadius: number;
  phase: number;
  speed: number;
  size: number;
  ringIndex: number;
  colorMix: number;
}

export class AuraOrbRenderer {
  private canvas: HTMLCanvasElement;
  private gl: WebGLRenderingContext | null = null;
  private ctx2d: CanvasRenderingContext2D | null = null;
  private isWebGL = false;

  private width = 200;
  private height = 200;
  private dpr = 1;

  private animFrameId: number | null = null;
  private lastTime = 0;
  private totalTime = 0;
  private isDestroyed = false;
  private isPaused = false;

  // Visual & Physics State
  private currentState: AuraVisualState = 'idle';
  private targetState: AuraVisualState = 'idle';
  private transitionProgress = 1.0; // 0 -> 1

  // Audio Telemetry
  private audioLevel = 0;
  private targetAudioLevel = 0;
  private frequencyBands: AudioFrequencyBands = { low: 0, mid: 0, high: 0, onset: 0 };
  private syntheticAudioTime = 0;

  // Particle System
  private particles: Particle[] = [];
  private particleCount = 1200;

  // Interpolated Visual Parameters
  private currentPrimary = [6, 182, 212];
  private currentSecondary = [59, 130, 246];
  private targetPrimary = [6, 182, 212];
  private targetSecondary = [59, 130, 246];

  private rotationX = 0;
  private rotationY = 0;
  private rotationSpeed = 0.3;
  private pulseSpeed = 0.6;
  private turbulence = 0.15;

  // Reduced motion preference
  private prefersReducedMotion = false;

  // WebGL specifics
  private program: WebGLProgram | null = null;
  private positionBuffer: WebGLBuffer | null = null;
  private colorBuffer: WebGLBuffer | null = null;
  private sizeBuffer: WebGLBuffer | null = null;

  // Event handlers for cleanup
  private handleVisibilityChange: () => void;
  private mediaQueryList: MediaQueryList | null = null;
  private handleMotionChange: (e: MediaQueryListEvent) => void;

  constructor(canvas: HTMLCanvasElement, forceCanvasFallback = false) {
    this.canvas = canvas;
    this.dpr = typeof window !== 'undefined' ? Math.min(window.devicePixelRatio || 1, 2) : 1;

    // Check prefers-reduced-motion
    if (typeof window !== 'undefined' && window.matchMedia) {
      this.mediaQueryList = window.matchMedia('(prefers-reduced-motion: reduce)');
      this.prefersReducedMotion = this.mediaQueryList.matches;
      this.handleMotionChange = (e: MediaQueryListEvent) => {
        this.prefersReducedMotion = e.matches;
      };
      this.mediaQueryList.addEventListener('change', this.handleMotionChange);
    } else {
      this.handleMotionChange = () => {};
    }

    // Visibility Listener
    this.handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        this.isPaused = true;
      } else {
        this.isPaused = false;
        this.lastTime = performance.now();
        if (!this.animFrameId && !this.isDestroyed) {
          this.loop(this.lastTime);
        }
      }
    };
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', this.handleVisibilityChange);
    }

    // Initialize Context
    if (!forceCanvasFallback) {
      try {
        this.gl = (canvas.getContext('webgl', {
          alpha: true,
          antialias: true,
          premultipliedAlpha: false,
          preserveDrawingBuffer: false,
        }) ||
          canvas.getContext('experimental-webgl', {
            alpha: true,
            antialias: true,
          })) as WebGLRenderingContext | null;

        if (this.gl) {
          this.isWebGL = this.initWebGL();
        }
      } catch {
        this.isWebGL = false;
      }
    }

    if (!this.isWebGL) {
      this.ctx2d = canvas.getContext('2d');
    }

    this.initParticles();
    this.lastTime = performance.now();
    this.loop(this.lastTime);
  }

  public setSize(width: number, height: number): void {
    if (width <= 0 || height <= 0) return;
    this.width = width;
    this.height = height;
    this.canvas.width = Math.floor(width * this.dpr);
    this.canvas.height = Math.floor(height * this.dpr);

    if (this.gl) {
      this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    }
  }

  public updateState(
    state: AuraVisualState,
    audioLevel?: number,
    frequencyBands?: AudioFrequencyBands
  ): void {
    if (state !== this.targetState) {
      this.currentState = this.targetState;
      this.targetState = state;
      this.transitionProgress = 0;

      const tokens = STATE_TOKENS[state];
      this.targetPrimary = tokens.primaryColor.split(',').map((s) => parseFloat(s.trim()));
      this.targetSecondary = tokens.secondaryColor.split(',').map((s) => parseFloat(s.trim()));
    }

    if (typeof audioLevel === 'number') {
      this.targetAudioLevel = Math.max(0, Math.min(1, audioLevel));
    }
    if (frequencyBands) {
      this.frequencyBands = {
        low: Math.max(0, Math.min(1, frequencyBands.low)),
        mid: Math.max(0, Math.min(1, frequencyBands.mid)),
        high: Math.max(0, Math.min(1, frequencyBands.high)),
        onset: frequencyBands.onset ? Math.max(0, Math.min(1, frequencyBands.onset)) : 0,
      };
    }
  }

  private initParticles(): void {
    this.particles = [];
    const baseCount = Math.floor(Math.min(2200, Math.max(700, this.width * 5)));
    this.particleCount = baseCount;

    // Golden spiral sphere distribution (Fibonacci Sphere)
    const goldenRatio = (1 + Math.sqrt(5)) / 2;
    for (let i = 0; i < this.particleCount; i++) {
      const phi = Math.asin(1 - (2 * (i + 0.5)) / this.particleCount);
      const theta = (2 * Math.PI * i) / goldenRatio;
      const baseRadius = 0.55 + (Math.random() * 0.1 - 0.05);

      this.particles.push({
        theta,
        phi,
        baseRadius,
        currentRadius: baseRadius,
        phase: Math.random() * Math.PI * 2,
        speed: 0.5 + Math.random() * 0.8,
        size: 1.5 + Math.random() * 2.2,
        ringIndex: i % 5,
        colorMix: Math.random(),
      });
    }
  }

  private initWebGL(): boolean {
    const gl = this.gl;
    if (!gl) return false;

    const vsSource = `
      attribute vec3 aPosition;
      attribute vec4 aColor;
      attribute float aSize;
      
      uniform mat4 uMatrix;
      uniform float uDpr;
      
      varying vec4 vColor;
      
      void main() {
        gl_Position = uMatrix * vec4(aPosition, 1.0);
        gl_PointSize = max(1.5, aSize * uDpr * (1.2 / (gl_Position.z + 2.0)));
        vColor = aColor;
      }
    `;

    const fsSource = `
      precision mediump float;
      varying vec4 vColor;
      
      void main() {
        vec2 coord = gl_PointCoord - vec2(0.5);
        float dist = length(coord);
        if (dist > 0.5) {
          discard;
        }
        float alpha = smoothstep(0.5, 0.05, dist) * vColor.a;
        gl_FragColor = vec4(vColor.rgb, alpha);
      }
    `;

    const vs = this.compileShader(gl.VERTEX_SHADER, vsSource);
    const fs = this.compileShader(gl.FRAGMENT_SHADER, fsSource);
    if (!vs || !fs) return false;

    const program = gl.createProgram();
    if (!program) return false;

    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);

    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      return false;
    }

    this.program = program;
    this.positionBuffer = gl.createBuffer();
    this.colorBuffer = gl.createBuffer();
    this.sizeBuffer = gl.createBuffer();

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE); // Additive luminous blending
    gl.disable(gl.DEPTH_TEST);

    return true;
  }

  private compileShader(type: number, source: string): WebGLShader | null {
    const gl = this.gl;
    if (!gl) return null;
    const shader = gl.createShader(type);
    if (!shader) return null;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  private loop = (now: number): void => {
    if (this.isDestroyed) return;

    if (this.isPaused) {
      this.animFrameId = null;
      return;
    }

    const dt = Math.min((now - this.lastTime) / 1000, 0.1);
    this.lastTime = now;

    this.update(dt);
    this.render();

    this.animFrameId = requestAnimationFrame(this.loop);
  };

  private update(dt: number): void {
    // If reduced motion, clamp velocity drastically
    const effectiveDt = this.prefersReducedMotion ? dt * 0.08 : dt;

    // Smooth transition
    if (this.transitionProgress < 1.0) {
      this.transitionProgress = Math.min(1.0, this.transitionProgress + dt * 3.0);
      for (let i = 0; i < 3; i++) {
        this.currentPrimary[i] +=
          (this.targetPrimary[i] - this.currentPrimary[i]) * Math.min(1, dt * 6.0);
        this.currentSecondary[i] +=
          (this.targetSecondary[i] - this.currentSecondary[i]) * Math.min(1, dt * 6.0);
      }
    }

    const targetTokens = STATE_TOKENS[this.targetState];
    this.rotationSpeed += (targetTokens.rotationSpeed - this.rotationSpeed) * Math.min(1, dt * 4);
    this.pulseSpeed += (targetTokens.pulseSpeed - this.pulseSpeed) * Math.min(1, dt * 4);
    this.turbulence += (targetTokens.turbulence - this.turbulence) * Math.min(1, dt * 4);

    // Audio level spring
    this.audioLevel += (this.targetAudioLevel - this.audioLevel) * Math.min(1, dt * 10);

    // Emergency Stop freezes all physics
    if (this.targetState === 'emergency_stop') {
      this.rotationSpeed = 0;
      this.pulseSpeed = 0;
      this.turbulence = 0;
    } else {
      this.totalTime += effectiveDt;
      this.syntheticAudioTime += effectiveDt;
    }

    // Continuous rotation
    this.rotationY += this.rotationSpeed * effectiveDt;
    this.rotationX = Math.sin(this.totalTime * 0.5) * 0.25;

    // Fallback synthetic speech oscillation if state is speaking with zero audio
    let effectiveAudio = this.audioLevel;
    let effectiveLow = this.frequencyBands.low;
    let effectiveMid = this.frequencyBands.mid;
    let effectiveHigh = this.frequencyBands.high;

    if (this.targetState === 'speaking' && this.audioLevel < 0.05) {
      const synthetic =
        0.35 +
        0.3 * Math.sin(this.syntheticAudioTime * 6.0) * Math.cos(this.syntheticAudioTime * 3.5);
      effectiveAudio = Math.max(0.15, synthetic);
      effectiveLow = 0.4 * Math.sin(this.syntheticAudioTime * 4.0);
      effectiveMid = 0.5 * Math.cos(this.syntheticAudioTime * 8.0);
      effectiveHigh = 0.3 * Math.sin(this.syntheticAudioTime * 12.0);
    }

    // Update Particle Coordinates & Radii
    const time = this.totalTime;
    const topo = targetTokens.topology;

    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];

      let r = p.baseRadius;

      switch (topo) {
        case 'sphere':
          // Organic breathing & gentle surface harmonic
          r +=
            Math.sin(time * this.pulseSpeed + p.phase) * 0.04 * this.turbulence +
            Math.sin(p.theta * 3 + time * 1.5) * 0.02;
          if (this.targetState === 'listening') {
            r += effectiveAudio * 0.18 * Math.sin(p.phi * 4 + time * 4);
          }
          break;

        case 'lattice':
          // Thinking state: structured crystalline alignment
          const latticeMod = Math.sin(p.theta * 4) * Math.cos(p.phi * 4);
          r = 0.52 + latticeMod * 0.12 * this.turbulence + Math.sin(time * 3 + p.phase) * 0.03;
          break;

        case 'rings':
          // Searching / Approval: concentric equatorial & polar scanning bands
          const isEquatorial = Math.abs(p.phi) < 0.35;
          const bandOffset = isEquatorial
            ? Math.sin(p.theta * 6 + time * 5) * 0.08
            : Math.cos(p.theta * 3 - time * 2) * 0.04;
          r = 0.5 + bandOffset + (isEquatorial ? 0.1 : 0);
          break;

        case 'wave':
          // Speaking & Error: dynamic harmonic pulsation
          const waveHarmonic =
            Math.sin(p.theta * 5 + time * 8) * (0.05 + effectiveMid * 0.12) +
            Math.cos(p.phi * 6 + time * 6) * (0.04 + effectiveLow * 0.15) +
            (Math.random() - 0.5) * effectiveHigh * 0.08;
          r = 0.54 + waveHarmonic + effectiveAudio * 0.15;
          break;

        case 'burst':
          // Done state: settled outward luminescence
          r = 0.58 + Math.sin(time * 0.8 + p.phase) * 0.03;
          break;

        case 'frozen':
        default:
          // Emergency Halt: sharp, locked geometric shell
          r = 0.52 + (i % 2 === 0 ? 0.05 : -0.03);
          break;
      }

      p.currentRadius = r;
    }
  }

  private render(): void {
    if (this.isWebGL && this.gl && this.program) {
      this.renderWebGL();
    } else if (this.ctx2d) {
      this.renderCanvas2D();
    }
  }

  private renderWebGL(): void {
    const gl = this.gl!;
    const program = this.program!;

    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    gl.useProgram(program);

    // Setup 3D rotation matrix
    const cosY = Math.cos(this.rotationY);
    const sinY = Math.sin(this.rotationY);
    const cosX = Math.cos(this.rotationX);
    const sinX = Math.sin(this.rotationX);

    // Simple orthographic / perspective matrix
    const aspect = this.width / Math.max(1, this.height);
    const scale = 1.0;
    const matrix = new Float32Array([
      (cosY * scale) / aspect,
      sinX * sinY * scale,
      -cosX * sinY * scale,
      0,
      0,
      cosX * scale,
      sinX * scale,
      0,
      (sinY * scale) / aspect,
      -sinX * cosY * scale,
      cosX * cosY * scale,
      0,
      0,
      0,
      0,
      1,
    ]);

    const uMatrix = gl.getUniformLocation(program, 'uMatrix');
    const uDpr = gl.getUniformLocation(program, 'uDpr');
    gl.uniformMatrix4fv(uMatrix, false, matrix);
    gl.uniform1f(uDpr, this.dpr);

    // Populate buffers
    const positions = new Float32Array(this.particleCount * 3);
    const colors = new Float32Array(this.particleCount * 4);
    const sizes = new Float32Array(this.particleCount);

    const pr = this.currentPrimary[0] / 255;
    const pg = this.currentPrimary[1] / 255;
    const pb = this.currentPrimary[2] / 255;

    const sr = this.currentSecondary[0] / 255;
    const sg = this.currentSecondary[1] / 255;
    const sb = this.currentSecondary[2] / 255;

    for (let i = 0; i < this.particleCount; i++) {
      const p = this.particles[i];
      const r = p.currentRadius;

      // Spherical -> Cartesian
      const x = r * Math.cos(p.phi) * Math.sin(p.theta);
      const y = r * Math.sin(p.phi);
      const z = r * Math.cos(p.phi) * Math.cos(p.theta);

      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;

      // Particle Color
      const mix = p.colorMix;
      colors[i * 4] = pr * (1 - mix) + sr * mix;
      colors[i * 4 + 1] = pg * (1 - mix) + sg * mix;
      colors[i * 4 + 2] = pb * (1 - mix) + sb * mix;
      // Fade back particles slightly for depth
      const depthAlpha = Math.max(0.2, Math.min(1.0, (z + 0.8) / 1.5));
      colors[i * 4 + 3] = depthAlpha * (this.targetState === 'degraded' ? 0.4 : 0.85);

      sizes[i] = p.size;
    }

    // Bind Attributes
    const aPosition = gl.getAttribLocation(program, 'aPosition');
    gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(aPosition);
    gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);

    const aColor = gl.getAttribLocation(program, 'aColor');
    gl.bindBuffer(gl.ARRAY_BUFFER, this.colorBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, colors, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(aColor);
    gl.vertexAttribPointer(aColor, 4, gl.FLOAT, false, 0, 0);

    const aSize = gl.getAttribLocation(program, 'aSize');
    gl.bindBuffer(gl.ARRAY_BUFFER, this.sizeBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, sizes, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(aSize);
    gl.vertexAttribPointer(aSize, 1, gl.FLOAT, false, 0, 0);

    gl.drawArrays(gl.POINTS, 0, this.particleCount);
  }

  private renderCanvas2D(): void {
    const ctx = this.ctx2d!;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const radiusScale = Math.min(cx, cy) * 0.85;

    ctx.clearRect(0, 0, w, h);

    // Draw central ambient glow
    const glowGrad = ctx.createRadialGradient(cx, cy, radiusScale * 0.1, cx, cy, radiusScale);
    const pr = Math.round(this.currentPrimary[0]);
    const pg = Math.round(this.currentPrimary[1]);
    const pb = Math.round(this.currentPrimary[2]);
    glowGrad.addColorStop(0, `rgba(${pr}, ${pg}, ${pb}, 0.25)`);
    glowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');

    ctx.fillStyle = glowGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, radiusScale, 0, Math.PI * 2);
    ctx.fill();

    // 3D rotation projection
    const cosY = Math.cos(this.rotationY);
    const sinY = Math.sin(this.rotationY);
    const cosX = Math.cos(this.rotationX);
    const sinX = Math.sin(this.rotationX);

    ctx.globalCompositeOperation = 'lighter';

    const sr = Math.round(this.currentSecondary[0]);
    const sg = Math.round(this.currentSecondary[1]);
    const sb = Math.round(this.currentSecondary[2]);

    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];
      const r = p.currentRadius * radiusScale;

      // 3D coordinates
      const x0 = r * Math.cos(p.phi) * Math.sin(p.theta);
      const y0 = r * Math.sin(p.phi);
      const z0 = r * Math.cos(p.phi) * Math.cos(p.theta);

      // Rotate Y
      const x1 = x0 * cosY + z0 * sinY;
      const z1 = -x0 * sinY + z0 * cosY;

      // Rotate X
      const y2 = y0 * cosX - z1 * sinX;
      const z2 = y0 * sinX + z1 * cosX;

      // Project
      const px = cx + x1;
      const py = cy + y2;
      const depthAlpha = Math.max(0.15, Math.min(0.9, (z2 + radiusScale) / (radiusScale * 2)));

      const mix = p.colorMix;
      const red = Math.round(pr * (1 - mix) + sr * mix);
      const green = Math.round(pg * (1 - mix) + sg * mix);
      const blue = Math.round(pb * (1 - mix) + sb * mix);

      ctx.fillStyle = `rgba(${red}, ${green}, ${blue}, ${depthAlpha})`;
      ctx.beginPath();
      ctx.arc(px, py, p.size * (this.dpr * 0.8), 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalCompositeOperation = 'source-over';
  }

  public destroy(): void {
    this.isDestroyed = true;

    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }

    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    }

    if (this.mediaQueryList && this.handleMotionChange) {
      this.mediaQueryList.removeEventListener('change', this.handleMotionChange);
    }

    if (this.gl) {
      if (this.positionBuffer) this.gl.deleteBuffer(this.positionBuffer);
      if (this.colorBuffer) this.gl.deleteBuffer(this.colorBuffer);
      if (this.sizeBuffer) this.gl.deleteBuffer(this.sizeBuffer);
      if (this.program) this.gl.deleteProgram(this.program);
      this.gl = null;
    }

    this.particles = [];
  }
}
