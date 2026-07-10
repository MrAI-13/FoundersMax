import { useRef, type ComponentRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { MeshDistortMaterial, Sphere } from '@react-three/drei'
import { Color, type Mesh } from 'three'
import type { AudioLevels } from '../lib/useVoiceSession'
import type { VoiceStatus } from '../lib/types'

interface VoiceOrbProps {
  levelsRef: React.RefObject<AudioLevels>
  status: VoiceStatus
  size?: number
}

const STATUS_COLOR: Record<VoiceStatus, string> = {
  idle: '#8b5cf6',
  connecting: '#8b5cf6',
  ready: '#8b5cf6',
  listening: '#f59e0b',
  thinking: '#8b5cf6',
  speaking: '#22d3ee',
  error: '#ef4444',
}

const STATUS_SPEED: Record<VoiceStatus, number> = {
  idle: 0.6,
  connecting: 0.8,
  ready: 0.6,
  listening: 1.4,
  thinking: 2.6,
  speaking: 1.8,
  error: 0.4,
}

type DistortMaterialInstance = ComponentRef<typeof MeshDistortMaterial>

function OrbMesh({ levelsRef, status }: VoiceOrbProps) {
  const meshRef = useRef<Mesh>(null)
  const materialRef = useRef<DistortMaterialInstance>(null)
  const currentColor = useRef(new Color(STATUS_COLOR.idle))

  useFrame((state, delta) => {
    const mesh = meshRef.current
    const material = materialRef.current
    if (!mesh || !material) return

    const levels = levelsRef.current
    const level = status === 'listening' ? (levels?.input ?? 0) : status === 'speaking' ? (levels?.output ?? 0) : 0
    const boosted = Math.min(1, level * 6)
    const idleBreath = status === 'idle' || status === 'ready' ? Math.sin(state.clock.elapsedTime * 1.2) * 0.04 : 0

    const targetScale = 1 + boosted * 0.4 + idleBreath
    const scale = mesh.scale.x + (targetScale - mesh.scale.x) * 0.2
    mesh.scale.setScalar(scale)

    mesh.rotation.y += delta * (status === 'thinking' ? 0.8 : 0.2)
    mesh.rotation.x += delta * 0.06

    material.distort = 0.3 + boosted * 0.55

    currentColor.current.lerp(new Color(STATUS_COLOR[status]), 0.08)
    material.color.copy(currentColor.current)
    material.emissive.copy(currentColor.current)
    material.emissiveIntensity = 0.35 + boosted * 0.65
  })

  return (
    <Sphere ref={meshRef} args={[1.2, 96, 96]}>
      <MeshDistortMaterial
        ref={materialRef}
        roughness={0.15}
        metalness={0.3}
        distort={0.3}
        speed={STATUS_SPEED[status]}
      />
    </Sphere>
  )
}

export function VoiceOrb({ levelsRef, status, size = 208 }: VoiceOrbProps) {
  return (
    <div style={{ width: size, height: size }} className="relative">
      <Canvas camera={{ position: [0, 0, 3.6], fov: 42 }} dpr={[1, 2]} gl={{ antialias: true, alpha: true }}>
        <ambientLight intensity={0.7} />
        <pointLight position={[3, 3, 4]} intensity={90} color="#ffffff" />
        <pointLight position={[-3, -2, -2]} intensity={50} color="#8b5cf6" />
        <OrbMesh levelsRef={levelsRef} status={status} />
      </Canvas>
    </div>
  )
}
