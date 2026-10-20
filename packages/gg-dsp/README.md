# gg-dsp

Signal processing on slices of `f64`, with no allocation inside: radix-2 `fft`/`ifft`, Hann/Hamming/Blackman windows, `goertzel_power`,
`Biquad` IIR filters (low-pass, high-pass, band-pass, notch), a streaming `Fir[N]` with a windowed-sinc design, and a `MovingAverage[N]`.

The FFT computes its twiddle factors with `std.math`; for bit-identical results on every machine swap in `std.dmath`. Not included: real-input
FFT shortcuts, non-power-of-two lengths, polyphase resampling, Parks-McClellan design. Tests: `gg test packages/gg-dsp/tests`.
