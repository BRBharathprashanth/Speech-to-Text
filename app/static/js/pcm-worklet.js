/**
 * AudioWorkletProcessor that downsamples microphone Float32 audio to
 * 16 kHz mono signed 16-bit PCM frames for WebSocket streaming.
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const processorOptions = (options && options.processorOptions) || {};
    this.targetSampleRate = processorOptions.targetSampleRate || 16000;
    this.chunkSizeSamples = processorOptions.chunkSizeSamples || 3200; // 200 ms @ 16 kHz
    this.ratio = sampleRate / this.targetSampleRate;
    this.sampleCursor = 0;
    this.lastSample = 0;
    this.hasLastSample = false;
    this.buffer = new Int16Array(this.chunkSizeSamples);
    this.bufferIndex = 0;
    this.stopped = false;

    this.port.onmessage = (event) => {
      if (event.data && event.data.type === "flush") {
        this._flush();
      } else if (event.data && event.data.type === "stop") {
        this._flush();
        this.stopped = true;
      }
    };
  }

  _appendSample(floatSample) {
    const clamped = Math.max(-1, Math.min(1, floatSample));
    const int16 = clamped < 0 ? Math.round(clamped * 32768) : Math.round(clamped * 32767);
    this.buffer[this.bufferIndex++] = int16;
    if (this.bufferIndex >= this.chunkSizeSamples) {
      this._flush();
    }
  }

  _flush() {
    if (this.bufferIndex === 0) {
      return;
    }
    const slice = this.buffer.slice(0, this.bufferIndex);
    this.port.postMessage(slice.buffer, [slice.buffer]);
    this.bufferIndex = 0;
  }

  process(inputs) {
    if (this.stopped) {
      return false;
    }
    const input = inputs[0];
    if (!input || input.length === 0) {
      return true;
    }

    // Mix down to mono if multiple input channels are present.
    const channelCount = input.length;
    const frameLength = input[0].length;
    const mono = new Float32Array(frameLength);
    for (let ch = 0; ch < channelCount; ch++) {
      const channelData = input[ch];
      for (let i = 0; i < frameLength; i++) {
        mono[i] += channelData[i] / channelCount;
      }
    }

    if (this.ratio === 1) {
      for (let i = 0; i < mono.length; i++) {
        this._appendSample(mono[i]);
      }
      return true;
    }

    // Linear interpolation resampler preserving phase across render quanta.
    while (this.sampleCursor < mono.length) {
      const idx = Math.floor(this.sampleCursor);
      const frac = this.sampleCursor - idx;
      const s0 = idx === 0 && this.hasLastSample && this.sampleCursor < 0 ? this.lastSample : mono[idx];
      const s1 = idx + 1 < mono.length ? mono[idx + 1] : mono[idx];
      const interpolated = s0 + (s1 - s0) * frac;
      this._appendSample(interpolated);
      this.sampleCursor += this.ratio;
    }

    this.sampleCursor -= mono.length;
    this.lastSample = mono[mono.length - 1];
    this.hasLastSample = true;
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
