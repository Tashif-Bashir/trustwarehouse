'use client'

import { useEffect, useRef, useState } from 'react'
import type * as THREE from 'three'
import Celebration from '@/components/Celebration'
import type { AgentMetrics } from '@/lib/types'

// End-of-day "Top performer today" in 3D (owner, 15 Sep 2026: "something
// nicer with 3js"). Same trigger, timing and priority as the 2D Celebration —
// the parent mounts/unmounts this exactly as it does that one. Three.js is
// imported only when this mounts, so the ordinary board never pays for it,
// and a screen without WebGL quietly renders the 2D version instead.
//
// Scene: a gold podium step per winner under a floating medallion of their
// avatar ringed in gold, thousands of tumbling confetti pieces with depth in
// the winner's colours, a camera that drifts slowly around the podium, and a
// slow-motion beat while the appointment count rolls up.

const DURATION_MS = 30_000
const COUNT_START_S = 2.0 // when the number starts rolling
const COUNT_ROLL_S = 1.4
const CONFETTI = 2400
const GOLD = 0xf5b544

function webglOk(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}

function initialsTexture(three: typeof THREE, name: string, color: string): THREE.Texture {
  const c = document.createElement('canvas')
  c.width = c.height = 512
  const ctx = c.getContext('2d')!
  ctx.fillStyle = '#131316'
  ctx.fillRect(0, 0, 512, 512)
  ctx.fillStyle = color
  ctx.globalAlpha = 0.28
  ctx.fillRect(0, 0, 512, 512)
  ctx.globalAlpha = 1
  ctx.fillStyle = '#ffffff'
  ctx.font = '600 260px "Barlow Condensed", "Barlow", sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(name.slice(0, 1).toUpperCase(), 256, 270)
  const t = new three.CanvasTexture(c)
  t.colorSpace = three.SRGBColorSpace
  return t
}

function loadAvatar(three: typeof THREE, w: AgentMetrics): Promise<THREE.Texture> {
  return new Promise((resolve) => {
    new three.TextureLoader().load(
      `/avatars/${w.id}.jpg`,
      (t) => {
        t.colorSpace = three.SRGBColorSpace
        resolve(t)
      },
      undefined,
      () => resolve(initialsTexture(three, w.name, w.color))
    )
  })
}

export default function Celebration3D({ winners }: { winners: AgentMetrics[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [fallback, setFallback] = useState(false)
  const [count, setCount] = useState(0)
  const [countDone, setCountDone] = useState(false)
  const appts = winners[0].appointmentsBooked

  // The appointment number rolls up on a beat, in step with the scene's
  // slow-motion moment (see timeScale below).
  useEffect(() => {
    let raf = 0
    const t0 = performance.now()
    const tick = () => {
      const s = (performance.now() - t0) / 1000
      const p = Math.min(1, Math.max(0, (s - COUNT_START_S) / COUNT_ROLL_S))
      const eased = 1 - Math.pow(1 - p, 3)
      setCount(Math.round(eased * appts))
      if (p >= 1) {
        setCountDone(true)
        return
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [appts])

  // The board underneath is taller than the screen; hide its scrollbar while
  // the takeover owns the screen (same as the rep week takeover).
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  useEffect(() => {
    if (!webglOk()) {
      setFallback(true)
      return
    }
    let disposed = false
    let cleanup: (() => void) | null = null

    ;(async () => {
      let three: typeof THREE
      try {
        three = await import('three')
      } catch {
        setFallback(true)
        return
      }
      const canvas = canvasRef.current
      if (!canvas || disposed) return

      const renderer = new three.WebGLRenderer({ canvas, antialias: true, alpha: true })
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
      renderer.setSize(window.innerWidth, window.innerHeight, false)
      renderer.toneMapping = three.ACESFilmicToneMapping
      renderer.toneMappingExposure = 1.05
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type = three.PCFSoftShadowMap

      const scene = new three.Scene()
      scene.fog = new three.Fog(0x0a0a0c, 14, 30)
      const camera = new three.PerspectiveCamera(38, window.innerWidth / window.innerHeight, 0.1, 60)

      // ── Light: warm key from above-front, a rim in the winner's colour,
      //    a soft fill so the dark side of the podium still reads.
      scene.add(new three.AmbientLight(0xffffff, 0.35))
      const key = new three.SpotLight(0xfff1d6, 260, 30, Math.PI / 5, 0.5, 1.6)
      key.position.set(3, 9, 6)
      key.castShadow = true
      key.shadow.mapSize.set(1024, 1024)
      scene.add(key)
      const rim = new three.PointLight(new three.Color(winners[0].color), 90, 20, 1.8)
      rim.position.set(-5, 3, -3)
      scene.add(rim)
      const fill = new three.PointLight(0x8ea4ff, 12, 25, 1.8)
      fill.position.set(6, 1.5, -4)
      scene.add(fill)

      // ── Floor: dark, slightly glossy, catches the light pool and shadows.
      const floor = new three.Mesh(
        new three.CircleGeometry(16, 64),
        new three.MeshStandardMaterial({ color: 0x141418, roughness: 0.62, metalness: 0.25 })
      )
      floor.rotation.x = -Math.PI / 2
      floor.receiveShadow = true
      scene.add(floor)

      // ── Podium + medallion per winner. Two winners share the stage.
      const gold = new three.MeshStandardMaterial({ color: GOLD, roughness: 0.28, metalness: 0.9 })
      const spacing = 3.4
      const x0 = -((winners.length - 1) * spacing) / 2
      const medallions: THREE.Group[] = []
      const rings: THREE.Mesh[] = []
      const textures = await Promise.all(winners.map((w) => loadAvatar(three, w)))
      if (disposed) return
      winners.forEach((w, i) => {
        const x = x0 + i * spacing
        const step = new three.Mesh(new three.CylinderGeometry(1.15, 1.3, 0.55, 64), gold)
        step.position.set(x, 0.275, 0)
        step.castShadow = step.receiveShadow = true
        scene.add(step)
        const base = new three.Mesh(
          new three.CylinderGeometry(1.5, 1.6, 0.16, 64),
          new three.MeshStandardMaterial({ color: 0x2a2a30, roughness: 0.5, metalness: 0.5 })
        )
        base.position.set(x, 0.08, 0)
        base.receiveShadow = true
        scene.add(base)

        const group = new three.Group()
        group.position.set(x, 2.15, 0)
        const disc = new three.Mesh(
          new three.CircleGeometry(0.95, 64),
          new three.MeshStandardMaterial({ map: textures[i], roughness: 0.6, metalness: 0.05 })
        )
        disc.castShadow = true
        group.add(disc)
        const back = new three.Mesh(new three.CircleGeometry(0.95, 64), gold)
        back.rotation.y = Math.PI
        back.position.z = -0.01
        group.add(back)
        const ring = new three.Mesh(new three.TorusGeometry(1.02, 0.07, 24, 96), gold)
        ring.castShadow = true
        group.add(ring)
        const halo = new three.Mesh(
          new three.RingGeometry(1.12, 1.3, 96),
          new three.MeshBasicMaterial({
            color: new three.Color(w.color),
            transparent: true,
            opacity: 0.35,
            side: three.DoubleSide,
          })
        )
        group.add(halo)
        scene.add(group)
        medallions.push(group)
        rings.push(ring)
      })

      // ── Confetti: one instanced mesh, per-piece colour, physics in JS.
      const palette = [...winners.map((w) => new three.Color(w.color)), new three.Color(GOLD),
        new three.Color(GOLD), new three.Color(0xffffff)]
      const piece = new three.PlaneGeometry(0.13, 0.065)
      const confetti = new three.InstancedMesh(
        piece,
        new three.MeshStandardMaterial({ roughness: 0.5, metalness: 0.3, side: three.DoubleSide }),
        CONFETTI
      )
      confetti.castShadow = false
      const pos = new Float32Array(CONFETTI * 3)
      const vel = new Float32Array(CONFETTI)
      const rot = new Float32Array(CONFETTI * 3)
      const spin = new Float32Array(CONFETTI * 3)
      const sway = new Float32Array(CONFETTI * 2)
      const dummy = new three.Object3D()
      const respawn = (k: number, fromTop: boolean) => {
        pos[k * 3] = (Math.random() - 0.5) * 20
        pos[k * 3 + 1] = fromTop ? 9 + Math.random() * 6 : Math.random() * 15
        pos[k * 3 + 2] = (Math.random() - 0.5) * 10 - 1
        vel[k] = 1.1 + Math.random() * 1.7
        rot[k * 3] = Math.random() * Math.PI
        rot[k * 3 + 1] = Math.random() * Math.PI
        rot[k * 3 + 2] = Math.random() * Math.PI
        spin[k * 3] = (Math.random() - 0.5) * 6
        spin[k * 3 + 1] = (Math.random() - 0.5) * 6
        spin[k * 3 + 2] = (Math.random() - 0.5) * 4
        sway[k * 2] = Math.random() * Math.PI * 2
        sway[k * 2 + 1] = 0.6 + Math.random() * 1.2
      }
      for (let k = 0; k < CONFETTI; k++) {
        respawn(k, false)
        confetti.setColorAt(k, palette[k % palette.length])
      }
      scene.add(confetti)

      const onResize = () => {
        renderer.setSize(window.innerWidth, window.innerHeight, false)
        camera.aspect = window.innerWidth / window.innerHeight
        camera.updateProjectionMatrix()
      }
      window.addEventListener('resize', onResize)

      const t0 = performance.now()
      let last = t0
      let raf = 0
      const target = new three.Vector3(0, 1.4, 0)
      const frame = () => {
        const now = performance.now()
        const s = (now - t0) / 1000
        let dt = Math.min(0.05, (now - last) / 1000)
        last = now
        // Slow-motion beat while the number rolls up, easing back to full speed.
        const inBeat = s > COUNT_START_S - 0.2 && s < COUNT_START_S + COUNT_ROLL_S
        const timeScale = inBeat ? 0.22 : Math.min(1, 0.22 + (s - (COUNT_START_S + COUNT_ROLL_S)) * 0.9)
        dt *= s < COUNT_START_S - 0.2 ? 1 : Math.max(0.22, timeScale)

        for (let k = 0; k < CONFETTI; k++) {
          pos[k * 3 + 1] -= vel[k] * dt
          pos[k * 3] += Math.sin(s * sway[k * 2 + 1] + sway[k * 2]) * 0.35 * dt
          rot[k * 3] += spin[k * 3] * dt
          rot[k * 3 + 1] += spin[k * 3 + 1] * dt
          rot[k * 3 + 2] += spin[k * 3 + 2] * dt
          if (pos[k * 3 + 1] < -0.5) respawn(k, true)
          dummy.position.set(pos[k * 3], pos[k * 3 + 1], pos[k * 3 + 2])
          dummy.rotation.set(rot[k * 3], rot[k * 3 + 1], rot[k * 3 + 2])
          dummy.updateMatrix()
          confetti.setMatrixAt(k, dummy.matrix)
        }
        confetti.instanceMatrix.needsUpdate = true

        // Medallions bob and face the camera; rings turn.
        medallions.forEach((g, i) => {
          g.position.y = 2.15 + Math.sin(s * 1.3 + i) * 0.08
          g.lookAt(camera.position.x, g.position.y + 0.2, camera.position.z)
        })
        rings.forEach((r) => {
          r.rotation.z += 0.35 * dt
        })

        // Camera: slow drift around the podium, a little rise over the 30 s.
        const entrance = Math.min(1, s / 1.6)
        const ease = 1 - Math.pow(1 - entrance, 3)
        const a = Math.sin(s * 0.22) * 0.45
        // Pull back as the stage widens so every podium stays in frame.
        const fit = 9.5 + (winners.length - 1) * 2.6
        const r = fit - ease * 2.2
        camera.position.set(Math.sin(a) * r, 2.3 + ease * 0.5 + Math.sin(s * 0.3) * 0.15, Math.cos(a) * r)
        camera.lookAt(target)

        renderer.render(scene, camera)
        raf = requestAnimationFrame(frame)
      }
      raf = requestAnimationFrame(frame)

      cleanup = () => {
        cancelAnimationFrame(raf)
        window.removeEventListener('resize', onResize)
        scene.traverse((o) => {
          const m = o as THREE.Mesh
          if (m.geometry) m.geometry.dispose()
          const mat = m.material as THREE.Material | THREE.Material[] | undefined
          if (Array.isArray(mat)) mat.forEach((x) => x.dispose())
          else mat?.dispose()
        })
        textures.forEach((t) => t.dispose())
        renderer.dispose()
      }
    })()

    return () => {
      disposed = true
      cleanup?.()
    }
  }, [winners])

  if (fallback) return <Celebration winners={winners} />

  // Name spacing tracks the podium spacing on screen: wider stage, wider gap.
  const spacingPx = winners.length > 2 ? 'clamp(180px, 17vw, 330px)' : 'clamp(220px, 22vw, 420px)'
  return (
    <div className="celebration fixed inset-0 z-50 overflow-hidden">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />

      {/* Text stays HTML so it is razor sharp on the wall screen. */}
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center">
        <div
          className="fade-up mt-[7vh] font-display text-3xl font-medium uppercase tracking-[0.35em] text-neutral-400"
          style={{ animationDelay: '250ms' }}
        >
          {winners.length > 1 ? 'Joint top performers today' : 'Top performer today'}
        </div>

        <div className="mt-auto mb-[9vh] flex flex-col items-center gap-4">
          <div className="flex items-end justify-center" style={{ gap: spacingPx }}>
            {winners.map((w, i) => (
              <div
                key={w.id}
                className="fade-up font-display text-6xl font-semibold uppercase tracking-wide"
                style={{ animationDelay: `${600 + i * 120}ms`, color: '#fff', textShadow: `0 0 28px ${w.color}66` }}
              >
                {w.name}
              </div>
            ))}
          </div>
          <div
            className={`fade-up font-display text-[7rem] font-semibold leading-none text-amber-400 ${
              countDone ? 'celebration3d-land' : ''
            }`}
            style={{ animationDelay: `${COUNT_START_S * 1000 - 300}ms`, textShadow: '0 0 30px rgba(251,191,36,0.55)' }}
          >
            {count}
            <span className="ml-4 text-4xl font-medium text-neutral-300">
              appointment{appts === 1 ? '' : 's'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
