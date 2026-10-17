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

Supported: architectures `llama` (LLaMA 1/2/3, TinyLlama, Mistral, ...) and `qwen3` (Qwen3, DeepSeek-R1 distilled onto Qwen3),
weights `f32`, `f16`, `q4_0`, `q8_0`, `Q4_K` and `Q6_K` (so `Q4_K_M` files work). Not yet supported: other architectures,
the `Q2_K`/`Q3_K`/`Q5_K` types, chat templates (write the template into the prompt and use `--special`). A model in an
unsupported type is refused with a message naming the tensor. The text goes to standard output and the speed to
standard error.

On Windows, text typed on the command line passes through the ANSI code page; for a prompt with non-ASCII characters
(such as the `<｜User｜>` tokens of DeepSeek) put it in a file and use `-f`.

Example with a chat model (`prompt.txt` holds `<｜begin▁of▁sentence｜><｜User｜>What is 17 times 23?<｜Assistant｜><think>` and a newline):

```bash
gg-infer DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf -f prompt.txt --special --no-bos --temp 0 -n 400
```
