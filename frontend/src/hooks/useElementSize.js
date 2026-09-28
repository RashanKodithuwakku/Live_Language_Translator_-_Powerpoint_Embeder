import { useLayoutEffect, useState } from 'react'

/** Content-box size of the element in `ref`, kept current via ResizeObserver. */
export function useElementSize(ref) {
  const [size, setSize] = useState({ width: 0, height: 0 })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize((prev) =>
        Math.round(prev.width) === Math.round(width) && Math.round(prev.height) === Math.round(height)
          ? prev
          : { width, height },
      )
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])

  return size
}

/** Largest box of `aspect` (width / height) that fits inside `width`×`height`. */
export function fitAspect(width, height, aspect) {
  if (!width || !height) return { width: 0, height: 0 }
  return width / height > aspect
    ? { width: Math.floor(height * aspect), height: Math.floor(height) }
    : { width: Math.floor(width), height: Math.floor(width / aspect) }
}
