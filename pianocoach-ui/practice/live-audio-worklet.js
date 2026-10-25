class PracticeCapture extends AudioWorkletProcessor {
  constructor() { super(); this.samples = new Float32Array(1024); this.used = 0; this.startFrame = 0; }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (let i = 0; i < input.length; i++) {
      if (!this.used) this.startFrame = currentFrame + i;
      this.samples[this.used++] = input[i];
      if (this.used === this.samples.length) {
        this.port.postMessage({samples:this.samples, frame:this.startFrame}, [this.samples.buffer]);
        this.samples = new Float32Array(1024); this.used = 0;
      }
    }
    return true;
  }
}
registerProcessor('practice-capture', PracticeCapture);
