import { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Points, PointMaterial } from '@react-three/drei'
import { Icosahedron, MeshDistortMaterial } from '@react-three/drei'
import type { Points as PointsImpl, Mesh } from 'three'

const PARTICLE_COUNT = 700

function useParticlePositions(count: number) {
  return useMemo(() => {
    const positions = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const radius = 6 + Math.random() * 10
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(Math.random() * 2 - 1)
      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta)
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta)
      positions[i * 3 + 2] = radius * Math.cos(phi) - 6
    }
    return positions
  }, [count])
}

function Starfield() {
  const positions = useParticlePositions(PARTICLE_COUNT)
  const pointsRef = useRef<PointsImpl>(null)

  useFrame((_, delta) => {
    if (!pointsRef.current) return
    pointsRef.current.rotation.y += delta * 0.015
    pointsRef.current.rotation.x += delta * 0.004
  })

  return (
    <Points ref={pointsRef} positions={positions} stride={3} frustumCulled>
      <PointMaterial
        transparent
        color="#a78bfa"
        size={0.035}
        sizeAttenuation
        depthWrite={false}
        opacity={0.55}
      />
    </Points>
  )
}

function DriftingBlob({
  position,
  scale,
  speed,
  color,
}: {
  position: [number, number, number]
  scale: number
  speed: number
  color: string
}) {
  const meshRef = useRef<Mesh>(null)

  useFrame((state) => {
    if (!meshRef.current) return
    meshRef.current.rotation.x = state.clock.elapsedTime * speed * 0.15
    meshRef.current.rotation.y = state.clock.elapsedTime * speed * 0.1
    meshRef.current.position.y = position[1] + Math.sin(state.clock.elapsedTime * speed) * 0.4
  })

  return (
    <Icosahedron ref={meshRef} args={[scale, 1]} position={position}>
      <MeshDistortMaterial color={color} distort={0.45} speed={0.6} roughness={0.4} metalness={0.1} opacity={0.14} transparent />
    </Icosahedron>
  )
}

/** Fixed, full-viewport decorative 3D background: a slow-drifting starfield
 * plus two soft translucent blobs. Purely ambient — pointer-events-none,
 * low opacity, never competes with foreground content. */
export function AmbientBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10">
      <Canvas camera={{ position: [0, 0, 8], fov: 55 }} dpr={[1, 1.5]} gl={{ antialias: true, alpha: true }}>
        <ambientLight intensity={0.5} />
        <pointLight position={[5, 5, 5]} intensity={40} color="#c084fc" />
        <Starfield />
        <DriftingBlob position={[-4.5, 1.5, -4]} scale={1.6} speed={0.5} color="#8b5cf6" />
        <DriftingBlob position={[4.5, -2, -6]} scale={2.1} speed={0.35} color="#22d3ee" />
      </Canvas>
    </div>
  )
}
