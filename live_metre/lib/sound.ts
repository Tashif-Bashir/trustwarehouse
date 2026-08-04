// Money sound for the sales board, synthesised with the Web Audio API — no
// audio file to host, nothing to fetch, works offline on a wall screen.
//
// Browsers refuse to play audio until the page has had a real user gesture, so
// the board shows an "enable sound" badge once after loading; one click unlocks
// it for the life of that page. (A kiosk can skip the click entirely by
// launching Chrome with --autoplay-policy=no-user-gesture-required.)

let ctx: AudioContext | null = null
let noiseBuf: AudioBuffer | null = null

// Optional real recording. If a file is dropped in (see public/sounds/README),
// it is used verbatim and the synthesised versions below become the fallback.
let fileBuf: AudioBuffer | null = null
let filePending: Promise<void> | null = null
// Set only when the fetch/decode actually failed, so a sale that lands while
// the file is still downloading waits for it instead of firing the synth.
let fileFailed = false

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

/** Call from a real user gesture (click/keypress). Returns true once running. */
export function unlockSound(): boolean {
  const c = audioCtx()
  if (!c) return false
  if (c.state === 'suspended') void c.resume()
  return c.state === 'running'
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
  if (!c || !url || fileBuf || filePending) return
  filePending = fetch(url)
    .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(String(r.status)))))
    .then((buf) => c.decodeAudioData(buf))
    .then((decoded) => {
      fileBuf = decoded
    })
    .catch(() => {
      /* no file, or undecodable — synthesised sound stays in charge */
      fileFailed = true
    })
}

export function hasSaleFile(): boolean {
  return fileBuf !== null
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
    if (!fileBuf) return false
    // The recording is only ~3s. Chain it a few times on the audio clock so a
    // sale lands with a proper run of the till rather than a single blip. A
    // small overlap stops each repeat sounding like a restart.
    const times = Math.max(1, Math.round(opts.repeat ?? 1))
    const step = Math.max(0.05, fileBuf.duration - 0.12)
    for (let i = 0; i < times; i++) {
      const src = c.createBufferSource()
      src.buffer = fileBuf
      const g = c.createGain()
      // ease the tail off slightly so a long chain doesn't feel mechanical
      g.gain.value = (opts.volume ?? 0.35) * (i === 0 ? 1 : 0.92 ** i)
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
  if (opts.file && !fileFailed && filePending) {
    filePending.then(() => {
      if (!playFile()) playSynth()
    })
    return true
  }

  return playSynth()
}
