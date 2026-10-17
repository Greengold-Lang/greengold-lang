# gg-infer

Runs a LLaMA-family GGUF model on the CPU, written in Greengold on `std.llama`, `std.tokenizer` and `std.sampler`.

```bash
gg run apps/gg-infer/main.gg --release --cpu native -- model.gguf -p "Once upon a time" -n 128
```

For a program you start often, build it once: `gg build apps/gg-infer/main.gg --release --cpu native -o gg-infer`.

| Option | Meaning |
|---|---|
| `-p`, `--prompt TEXT` / `-f`, `--file PATH` | the prompt |
| `-n`, `--predict N` | most tokens to generate (128) |
| `-c`, `--ctx N` | context size (the model's, at most 4096) |
| `-t`, `--threads N` | threads (one per CPU) |
| `--temp X`, `--top-k N`, `--top-p X`, `--repeat-penalty X`, `--seed N` | sampling (`--temp 0` is greedy) |
| `--no-bos`, `--special` | no beginning-of-sequence token; read `<|special|>` tokens in the prompt |
| `--info` | print what the model file contains |

**Always build with `--cpu native`** (or `--cpu x86-64-v3`): without it the 256-bit kernels are emulated with 128-bit
instructions and run several times slower.

Supported: architecture `llama`, weights `f32`, `f16`, `q4_0`, `q8_0`. Not yet supported: the K-quants (`Q4_K_M`,
`Q6_K`, ... the most common download), other architectures, chat templates. A model in an unsupported type is refused
with a message naming the tensor. The text goes to standard output and the speed to standard error.
