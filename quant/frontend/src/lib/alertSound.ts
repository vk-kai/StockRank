// 套利背离提示音(WebAudio,无需音频文件;首次需用户手势激活,面板里有"测试提示音"按钮)
let audioCtx: AudioContext | null = null;

const SOUND_KEY = "tz_arb_sound_enabled";

export function isArbSoundEnabled(): boolean {
  try {
    return localStorage.getItem(SOUND_KEY) !== "0";
  } catch {
    return true;
  }
}

export function setArbSoundEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(SOUND_KEY, enabled ? "1" : "0");
  } catch {}
}

function ensureCtx(): AudioContext | null {
  try {
    if (!audioCtx) {
      const AC = window.AudioContext || (window as any).webkitAudioContext;
      if (!AC) return null;
      audioCtx = new AC();
    }
    if (audioCtx.state === "suspended") {
      audioCtx.resume().catch(() => {});
    }
    return audioCtx;
  } catch {
    return null;
  }
}

function beep(freq: number, offsetSeconds: number, duration = 0.12): void {
  const ctx = ensureCtx();
  if (!ctx) return;
  try {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    const start = ctx.currentTime + offsetSeconds;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.06, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration + 0.02);
  } catch {}
}

/** 买向(买点/盘前偏多) 880Hz 三短音;卖向 587Hz 三短音 */
export function playArbAlertSound(direction: string): void {
  if (!isArbSoundEnabled()) return;
  const freq = direction.includes("buy") ? 880 : 587;
  beep(freq, 0);
  beep(freq, 0.18);
  beep(freq, 0.36);
}

/** 面板里的测试按钮(用户手势,顺带激活 AudioContext) */
export function testArbAlertSound(): void {
  setArbSoundEnabled(true);
  playArbAlertSound("buy");
}
