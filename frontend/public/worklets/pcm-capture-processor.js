/**
 * AudioWorklet processor: runs on the real-time audio thread.
 *
 * Collects mono float samples (the AudioContext runs at 16 kHz, so Chrome
 * has already resampled the device's native rate), converts each ~100 ms
 * block to LINEAR16 and transfers it to the main thread together with RMS
 * and peak levels for the operator's input meter.
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    this.chunkSamples = options.processorOptions.chunkSamples
    this.buffer = new Float32Array(this.chunkSamples)
    this.length = 0
    this.sumSquares = 0
    this.peak = 0
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true

    for (let i = 0; i < channel.length; i++) {
      const sample = channel[i]
      this.buffer[this.length++] = sample
      this.sumSquares += sample * sample
      const magnitude = sample < 0 ? -sample : sample
      if (magnitude > this.peak) this.peak = magnitude

      if (this.length === this.chunkSamples) this.flush()
    }
    return true
  }

  flush() {
    const pcm = new Int16Array(this.chunkSamples)
    for (let i = 0; i < this.chunkSamples; i++) {
      const s = Math.max(-1, Math.min(1, this.buffer[i]))
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    this.port.postMessage(
      { pcm: pcm.buffer, rms: Math.sqrt(this.sumSquares / this.chunkSamples), peak: this.peak },
      [pcm.buffer],
    )
    this.length = 0
    this.sumSquares = 0
    this.peak = 0
  }
}

registerProcessor('pcm-capture-processor', PcmCaptureProcessor)
