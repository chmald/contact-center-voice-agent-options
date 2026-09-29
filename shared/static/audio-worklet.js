class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetSampleRate = options.processorOptions?.targetSampleRate ?? 24000;
    this.chunkFrames = Math.floor(this.targetSampleRate * ((options.processorOptions?.chunkMs ?? 100) / 1000));
    this.pending = [];
    this.sourceOffset = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;

    const ratio = sampleRate / this.targetSampleRate;
    while (this.sourceOffset < input.length) {
      const sample = input[Math.floor(this.sourceOffset)];
      this.pending.push(Math.max(-1, Math.min(1, sample)));
      this.sourceOffset += ratio;
    }
    this.sourceOffset -= input.length;

    while (this.pending.length >= this.chunkFrames) {
      const chunk = this.pending.splice(0, this.chunkFrames);
      const pcm = new Int16Array(chunk.length);
      for (let i = 0; i < chunk.length; i += 1) {
        pcm[i] = chunk[i] < 0 ? chunk[i] * 32768 : chunk[i] * 32767;
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
