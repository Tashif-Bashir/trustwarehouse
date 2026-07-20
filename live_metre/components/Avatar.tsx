'use client'

import { useState } from 'react'

// Agent avatar: tries a real photo from /avatars/<id>.jpg (drop files into
// live_metre/public/avatars/ — lily.jpg, sue.jpg, alicja.jpg, alisha.jpg);
// falls back to an initials badge in the agent's team colour.
export default function Avatar({
  id,
  name,
  color,
  size = 44,
}: {
  id: string
  name: string
  color: string
  size?: number
}) {
  const [photoFailed, setPhotoFailed] = useState(false)

  const ring = {
    width: size,
    height: size,
    border: `2px solid ${color}`,
    boxShadow: `0 0 12px color-mix(in srgb, ${color} 30%, transparent)`,
  }

  if (!photoFailed) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={`/avatars/${id}.jpg`}
        alt={name}
        className="shrink-0 rounded-full object-cover"
        style={ring}
        onError={() => setPhotoFailed(true)}
      />
    )
  }

  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full font-display font-semibold"
      style={{
        ...ring,
        backgroundColor: `color-mix(in srgb, ${color} 28%, #131316)`,
        color: `color-mix(in srgb, ${color} 70%, white)`,
        fontSize: size * 0.42,
      }}
    >
      {name.slice(0, 1).toUpperCase()}
    </div>
  )
}
