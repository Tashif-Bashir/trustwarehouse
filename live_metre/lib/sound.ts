// Money sound for the sales board, synthesised with the Web Audio API — no
// audio file to host, nothing to fetch, works offline on a wall screen.
//
// Browsers refuse to play audio until the page has had a real user gesture, so
// the board shows an "enable sound" badge once after loading; one click unlocks
// it for the life of that page. (A kiosk can skip the click entirely by
// launching Chrome with --autoplay-policy=no-user-gesture-required.)

let ctx: AudioContext | null = null
let noiseBuf: AudioBuffer | null = null

// Optional real recording(s). If a file is dropped in (see
// public/sounds/README), it is used verbatim and the synthesised versions
// below become the fallback. Keyed by url so the sale ka-ching and the
// end-of-day clip can both be cached at once without stomping each other.
const fileBufs = new Map<string, AudioBuffer>()
const filePendings = new Map<string, Promise<void>>()
// Set only when the fetch/decode actually failed, so a sale that lands while
// the file is still downloading waits for it instead of firing the synth.
const fileFailedUrls = new Set<string>()
// Where the audible part of each recording ends, in seconds. Sound files are
// usually padded with silence (the supplied ka-ching is 3.02s long but stops
// making noise at 1.32s), and chaining on the full buffer length would leave
// a dead gap between repeats.
const fileEnds = new Map<string, number>()

/** Last sample above the noise floor, in seconds — i.e. the real end. */
function audibleEnd(buf: AudioBuffer): number {
  const FLOOR = 0.01
  let last = 0
  for (let ch = 0; ch < buf.numberOfChannels; ch++) {
    const d = buf.getChannelData(ch)
    for (let i = d.length - 1; i >= 0; i--) {
      if (Math.abs(d[i]) > FLOOR) {
        if (i > last) last = i
        break
      }
    }
  }
  return last > 0 ? last / buf.sampleRate : buf.duration
}

function audioCtx(): AudioContext | null {
  if (typeof window === 'undefined') return null
  if (!ctx) {
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return null
    ctx = new Ctor()
  }
  return ctx
}

export function isSoundReady(): boolean {
  return ctx?.state === 'running'
}

/**
 * Try to start audio WITHOUT a user gesture. Succeeds on a kiosk launched with
 * --autoplay-policy=no-user-gesture-required (or where the browser already
 * trusts the site), in which case the board never shows the enable-sound badge
 * and a wall screen nobody touches still rings. Resolves false on a normal
 * browser, where a click is the only way in.
 */
export function tryAutoUnlock(): Promise<boolean> {
  const c = audioCtx()
  if (!c) return Promise.resolve(false)
  if (c.state === 'running') return Promise.resolve(true)
  // Chrome quirk: outside a user gesture, resume() neither resolves nor
  // rejects — the promise stays PENDING until a gesture unblocks audio.
  // Awaiting it unconditionally meant the answer never came back, so the
  // enable-sound badge never appeared and the board sat silent with no way
  // to arm it. Race a short timeout: kiosk (autoplay allowed) resolves fast
  // and true, a normal browser times out to false and gets the badge. If the
  // parked resume() is later unblocked by any interaction, audio simply
  // starts working.
  return Promise.race([
    c.resume().then(() => c.state === 'running').catch(() => false),
    new Promise<boolean>((resolve) =>
      setTimeout(() => resolve(c.state === ('running' as AudioContextState)), 400)
    ),
  ])
}

/**
 * Call from a real user gesture (click/keypress). resume() is asynchronous —
 * checking state on the very next line still reads 'suspended', which made the
 * badge's FIRST click report failure and play nothing (it worked on a second
 * click nobody knew to make). Await the resume instead, with a timeout guard.
 */
export function unlockSound(): Promise<boolean> {
  const c = audioCtx()
  if (!c) return Promise.resolve(false)
  if (c.state === 'running') return Promise.resolve(true)
  return Promise.race([
    c.resume().then(() => true).catch(() => false),
    new Promise<boolean>((resolve) =>
      setTimeout(() => resolve(c.state === ('running' as AudioContextState)), 1000)
    ),
  ])
}

function noise(c: AudioContext): AudioBuffer {
  if (!noiseBuf) {
    const len = Math.floor(c.sampleRate * 0.4)
    noiseBuf = c.createBuffer(1, len, c.sampleRate)
    const data = noiseBuf.getChannelData(0)
    for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1
  }
  return noiseBuf
}

// A struck-metal voice: inharmonic partials with fast exponential decay. This
// ratio set is what makes it read as metal rather than a musical beep.
function metal(
  c: AudioContext,
  out: AudioNode,
  at: number,
  base: number,
  dur: number,
  level: number,
  partials: number[]
) {
  partials.forEach((mult, i) => {
    const osc = c.createOscillator()
    const g = c.createGain()
    osc.type = 'sine'
    osc.frequency.value = base * mult
    const peak = level / (i + 1.5)
    g.gain.setValueAtTime(0.0001, at)
    g.gain.exponentialRampToValueAtTime(peak, at + 0.002)
    g.gain.exponentialRampToValueAtTime(0.0001, at + dur / (1 + i * 0.5))
    osc.connect(g).connect(out)
    osc.start(at)
    osc.stop(at + dur + 0.05)
  })
}

// One coin: a bright short ping plus a tiny noise tick for the impact.
function coin(c: AudioContext, out: AudioNode, at: number, level: number) {
  const base = 1900 + Math.random() * 2400 // coins vary in size/pitch
  metal(c, out, at, base, 0.12 + Math.random() * 0.18, level, [1, 1.94, 3.11, 4.7])

  const tick = c.createBufferSource()
  tick.buffer = noise(c)
  const hp = c.createBiquadFilter()
  hp.type = 'highpass'
  hp.frequency.value = 3500
  const g = c.createGain()
  g.gain.setValueAtTime(0.0001, at)
  g.gain.exponentialRampToValueAtTime(level * 0.5, at + 0.001)
  g.gain.exponentialRampToValueAtTime(0.0001, at + 0.03)
  tick.connect(hp).connect(g).connect(out)
  tick.start(at, Math.random() * 0.2, 0.05)
}

/**
 * A handful of coins landing and settling: pings scattered over ~0.6s, dense at
 * first then thinning out, spread across the stereo field so it sounds like
 * many coins rather than one repeated click.
 *
 * `amount` (the £ that just landed) scales how much money you hear.
 */
export function playCoins(opts: { volume?: number; amount?: number } = {}): boolean {
  const c = audioCtx()
  if (!c || c.state !== 'running') return false

  const t0 = c.currentTime + 0.02
  const master = c.createGain()
  master.gain.value = opts.volume ?? 0.35
  master.connect(c.destination)

  const amount = opts.amount ?? 0
  const count = amount >= 10_000 ? 26 : amount >= 4_000 ? 18 : 13
  const spread = amount >= 10_000 ? 0.85 : 0.6

  for (let i = 0; i < count; i++) {
    // (i/count)^1.6 clusters the first coins together and lets the tail settle
    const at = t0 + spread * Math.pow(i / count, 1.6) + Math.random() * 0.035
    const level = 0.42 * (1 - (i / count) * 0.55)

    let dest: AudioNode = master
    if (typeof c.createStereoPanner === 'function') {
      const pan = c.createStereoPanner()
      pan.pan.value = (Math.random() * 2 - 1) * 0.7
      pan.connect(master)
      dest = pan
    }
    coin(c, dest, at, level)
  }

  // faint metallic wash underneath, so the cascade sounds like a mass of coins
  const wash = c.createBufferSource()
  wash.buffer = noise(c)
  const bp = c.createBiquadFilter()
  bp.type = 'bandpass'
  bp.frequency.value = 5200
  bp.Q.value = 0.7
  const wg = c.createGain()
  wg.gain.setValueAtTime(0.0001, t0)
  wg.gain.exponentialRampToValueAtTime(0.06, t0 + 0.05)
  wg.gain.exponentialRampToValueAtTime(0.0001, t0 + spread + 0.25)
  wash.connect(bp).connect(wg).connect(master)
  wash.start(t0)
  wash.stop(t0 + spread + 0.4)

  return true
}

/** Classic till ka-ching — kept as an alternative style. */
export function playCashRegister(opts: { volume?: number; amount?: number } = {}): boolean {
  const c = audioCtx()
  if (!c || c.state !== 'running') return false

  const t = c.currentTime + 0.02
  const master = c.createGain()
  master.gain.value = opts.volume ?? 0.35
  master.connect(c.destination)

  const src = c.createBufferSource()
  src.buffer = noise(c)
  const bp = c.createBiquadFilter()
  bp.type = 'bandpass'
  bp.frequency.value = 420
  bp.Q.value = 0.9
  const ng = c.createGain()
  ng.gain.setValueAtTime(0.0001, t)
  ng.gain.exponentialRampToValueAtTime(0.22, t + 0.008)
  ng.gain.exponentialRampToValueAtTime(0.0001, t + 0.13)
  src.connect(bp).connect(ng).connect(master)
  src.start(t)
  src.stop(t + 0.3)

  const BELL = [1, 2.76, 5.4, 8.93]
  metal(c, master, t + 0.01, 1180, 0.75, 0.5, BELL)
  metal(c, master, t + 0.11, 1560, 0.9, 0.42, BELL)
  if ((opts.amount ?? 0) >= 10_000) metal(c, master, t + 0.23, 2100, 1.0, 0.3, BELL)

  // drawer sliding open then stopping — the "…chunk" that follows the ching
  const slide = c.createBufferSource()
  slide.buffer = noise(c)
  const sf = c.createBiquadFilter()
  sf.type = 'bandpass'
  sf.frequency.setValueAtTime(1400, t + 0.18)
  sf.frequency.exponentialRampToValueAtTime(600, t + 0.42)
  sf.Q.value = 1.2
  const sg = c.createGain()
  sg.gain.setValueAtTime(0.0001, t + 0.18)
  sg.gain.exponentialRampToValueAtTime(0.1, t + 0.24)
  sg.gain.exponentialRampToValueAtTime(0.0001, t + 0.46)
  slide.connect(sf).connect(sg).connect(master)
  slide.start(t + 0.18)
  slide.stop(t + 0.5)

  metal(c, master, t + 0.44, 210, 0.16, 0.32, [1, 1.7, 2.4]) // drawer stop

  return true
}

/**
 * Fetch + decode the optional sound file once. Safe to call repeatedly; a
 * missing file (404) or unsupported codec just leaves the synth fallback in
 * place. Must run after unlockSound() so an AudioContext exists.
 */
export function primeSaleFile(url?: string | null): void {
  const c = audioCtx()
  if (!c || !url || fileBufs.has(url) || filePendings.has(url)) return
  const pending = fetch(url)
    .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(String(r.status)))))
    .then((buf) => c.decodeAudioData(buf))
    .then((decoded) => {
      fileBufs.set(url, decoded)
      fileEnds.set(url, audibleEnd(decoded))
    })
    .catch(() => {
      /* no file, or undecodable — synthesised sound (or silence) stays in charge */
      fileFailedUrls.add(url)
    })
  filePendings.set(url, pending)
}

export function hasSaleFile(url: string): boolean {
  return fileBufs.has(url)
}

export interface FileSoundHandle {
  /** Fade out over fadeMs then stop the source. Safe to call more than once. */
  stop(fadeMs: number): void
}

const NOOP_HANDLE: FileSoundHandle = { stop() {} }

/**
 * Play a file-backed clip with NO synthesised fallback — for sounds like the
 * end-of-day takeover that must FAIL SOFT: if the clip is missing or won't
 * decode, this stays silent rather than reaching for the ka-ching. Shares the
 * fetch/decode/priming pipeline (and its per-url cache) with playSaleSound.
 *
 * Returns a handle so a long clip (the EOD track outlasts the ~45s takeover)
 * can be faded out and stopped by the caller instead of playing to the end
 * unattended — a plain fire-and-forget start() left it running under the
 * board after the takeover unmounted.
 */
export function playFileSound(url: string, opts: { volume?: number } = {}): FileSoundHandle {
  const c = audioCtx()

  let stopped = false
  let active: { src: AudioBufferSourceNode; gain: GainNode } | null = null

  const stop = (fadeMs: number) => {
    if (stopped) return // guard double-stop
    stopped = true
    if (!active || !c) return // never started (missing file / still deciding) — nothing to stop
    const { src, gain } = active
    const now = c.currentTime
    const fadeSec = Math.max(0, fadeMs) / 1000
    try {
      gain.gain.cancelScheduledValues(now)
      gain.gain.setValueAtTime(gain.gain.value, now)
      gain.gain.linearRampToValueAtTime(0, now + fadeSec)
      src.stop(now + fadeSec)
    } catch {
      // already ended/stopped — nothing to do
    }
  }

  if (!c || c.state !== 'running') return NOOP_HANDLE

  primeSaleFile(url)

  const fire = (buf: AudioBuffer) => {
    if (stopped) return // stop() already called before the decode/prime resolved
    const src = c.createBufferSource()
    src.buffer = buf
    const g = c.createGain()
    g.gain.value = opts.volume ?? 0.35
    src.connect(g).connect(c.destination)
    src.start()
    active = { src, gain: g }
  }

  const buf = fileBufs.get(url)
  if (buf) {
    fire(buf)
    return { stop }
  }
  // Still decoding (or just failed) — wait for the in-flight fetch, but never
  // fall back to a synthesised sound; a missing clip stays silent.
  const pending = filePendings.get(url)
  if (!fileFailedUrls.has(url) && pending) {
    pending.then(() => {
      const decoded = fileBufs.get(url)
      if (decoded) fire(decoded)
    })
  }
  return { stop }
}

/** Play the real recording if one is loaded, else the configured synth style. */
export function playSaleSound(
  opts: {
    volume?: number
    amount?: number
    style?: 'coins' | 'register'
    file?: string | null
    repeat?: number
  } = {}
): boolean {
  const c = audioCtx()
  if (!c || c.state !== 'running') return false

  primeSaleFile(opts.file)

  const playFile = (): boolean => {
    const buf = opts.file ? fileBufs.get(opts.file) : undefined
    if (!buf) return false
    // Chain the recording so a sale lands with a proper run of the till. Space
    // the repeats by where the audio ACTUALLY ends, not the buffer length, or
    // the file's trailing silence shows up as a gap between them.
    const times = Math.max(1, Math.round(opts.repeat ?? 1))
    const step = Math.max(0.05, (fileEnds.get(opts.file as string) || buf.duration) - 0.02)
    for (let i = 0; i < times; i++) {
      const src = c.createBufferSource()
      src.buffer = buf
      const g = c.createGain()
      g.gain.value = opts.volume ?? 0.35
      src.connect(g).connect(c.destination)
      src.start(c.currentTime + i * step)
    }
    return true
  }
  const playSynth = () =>
    opts.style === 'register' ? playCashRegister(opts) : playCoins(opts)

  if (playFile()) return true

  // The decode is asynchronous, so the FIRST sale (and the badge's test play)
  // would otherwise always get the synth stand-in even though a real recording
  // is sitting there. Wait for the decode instead — it is a local file and the
  // delay is imperceptible. Only a genuine failure falls back to the synth.
  const pending = opts.file ? filePendings.get(opts.file) : undefined
  if (opts.file && !fileFailedUrls.has(opts.file) && pending) {
    pending.then(() => {
      if (!playFile()) playSynth()
    })
    return true
  }

  return playSynth()
}
