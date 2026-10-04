/**
 * AudioWorklet: capture at the AudioContext rate, anti-alias downsample to
 * 16 kHz LINEAR16 in ~100 ms chunks. A simple 5-tap low-pass is applied
 * before decimation when the context is above 16 kHz. Stereo inputs use
 * the left, right or summed channel ('auto' picks whichever holds the voice).
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const opt = options.processorOptions || {}
    this.targetRate = opt.targetRate || 16000
    this.chunkSamples = opt.chunkSamples || 1600 // at target rate
    this.ratio = sampleRate / this.targetRate
    this.buffer = new Float32Array(this.chunkSamples)
    this.length = 0
    this.sumSquares = 0
    this.peak = 0
    this.phase = 0
    // 5-tap low-pass coefficients (approx box + emphasis on centre)
    this.lp = [0.1, 0.2, 0.4, 0.2, 0.1]
    this.lpState = [0, 0, 0, 0]
    this.channels = opt.channelMode || 'auto' // auto | left | right | sum
    this.active = this.channels === 'auto' ? 'sum' : this.channels
    // ~1 s smoothed channel energies and cross-correlation for 'auto'
    this.eL = 0
    this.eR = 0
    this.eLR = 0
    this.decideCountdown = 0
  }

  // A USB mixer often carries the mic on one side only (the other side is
  // just noise), and a polarity-flipped pair cancels when summed. Pick the
  // channel that actually holds the voice.
  updateAuto(L, R) {
    const a = 0.0005
    for (let i = 0; i < L.length; i++) {
      this.eL += a * (L[i] * L[i] - this.eL)
      this.eR += a * (R[i] * R[i] - this.eR)
      this.eLR += a * (L[i] * R[i] - this.eLR)
    }
    this.decideCountdown -= L.length
    if (this.decideCountdown > 0) return
    this.decideCountdown = sampleRate / 2
    let next = 'sum'
    if (this.eL > 10 * this.eR) next = 'left'
    else if (this.eR > 10 * this.eL) next = 'right'
    else if (this.eLR / Math.sqrt(this.eL * this.eR + 1e-20) < -0.3) next = 'left'
    if (next !== this.active) {
      this.active = next
      this.port.postMessage({ channel: next })
    }
  }

  lowpass(sample) {
    const x = sample
    const y =
      this.lp[0] * x +
      this.lp[1] * this.lpState[0] +
      this.lp[2] * this.lpState[1] +
      this.lp[3] * this.lpState[2] +
      this.lp[4] * this.lpState[3]
    this.lpState[3] = this.lpState[2]
    this.lpState[2] = this.lpState[1]
    this.lpState[1] = this.lpState[0]
    this.lpState[0] = x
    return y
  }

  pickSample(inputs, i) {
    const chans = inputs[0]
    if (!chans || !chans.length) return 0
    if (chans.length === 1) return chans[0][i] || 0
    const L = chans[0][i] || 0
    const R = chans[1] ? chans[1][i] || 0 : L
    if (this.active === 'left') return L
    if (this.active === 'right') return R
    return (L + R) * 0.5
  }

  process(inputs) {
    const chans = inputs[0]
    if (!chans || !chans[0]) return true
    const n = chans[0].length
    if (this.channels === 'auto' && chans.length > 1) this.updateAuto(chans[0], chans[1])

    if (this.ratio <= 1.01) {
      for (let i = 0; i < n; i++) {
        this.pushSample(this.pickSample(inputs, i))
      }
      return true
    }

    for (let i = 0; i < n; i++) {
      const filtered = this.lowpass(this.pickSample(inputs, i))
      this.phase += 1
      if (this.phase >= this.ratio) {
        this.phase -= this.ratio
        this.pushSample(filtered)
      }
    }
    return true
  }

  pushSample(sample) {
    this.buffer[this.length++] = sample
    this.sumSquares += sample * sample
    const magnitude = sample < 0 ? -sample : sample
    if (magnitude > this.peak) this.peak = magnitude
    if (this.length === this.chunkSamples) this.flush()
  }

  flush() {
    const pcm = new Int16Array(this.chunkSamples)
    for (let i = 0; i < this.chunkSamples; i++) {
      const s = Math.max(-1, Math.min(1, this.buffer[i]))
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    this.port.postMessage(
      {
        pcm: pcm.buffer,
        rms: Math.sqrt(this.sumSquares / this.chunkSamples),
        peak: this.peak,
        t: currentTime,
      },
      [pcm.buffer],
    )
    this.length = 0
    this.sumSquares = 0
    this.peak = 0
  }
}

registerProcessor('pcm-capture-processor', PcmCaptureProcessor)
