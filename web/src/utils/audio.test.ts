import { describe, expect, it } from 'vitest'

import { floatToInt16, resampleTo16k, rms } from './audio'

describe('audio utilities', () => {
  it('clips float samples when converting to PCM16', () => {
    expect(Array.from(floatToInt16(new Float32Array([-2, -0.5, 0, 0.5, 2])))).toEqual([
      -32768, -16384, 0, 16383, 32767,
    ])
  })

  it('computes RMS', () => {
    expect(rms(new Float32Array([1, -1, 1, -1]))).toBe(1)
  })

  it('downsamples 48kHz using bounded window averages', () => {
    const output = resampleTo16k(new Float32Array([0, 1, 2, 3, 4, 5]), 48000)
    expect(Array.from(output)).toEqual([1, 4])
  })

  it('does not read beyond the final sample for non-integer ratios', () => {
    const output = resampleTo16k(new Float32Array(441).fill(0.25), 44100)
    expect(output).toHaveLength(160)
    expect(Array.from(output).every((sample) => sample === 0.25)).toBe(true)
  })
})
