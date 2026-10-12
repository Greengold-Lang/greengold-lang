import os
import json
import shutil
import datetime
import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt

def order_best_first(variants, values, higher):
    """Left to right is best to worst. Equal values keep the original order."""
    ranked = sorted(
        range(len(variants)),
        key=lambda index: ((-values[index] if higher else values[index]), index),
    )
    return [variants[index] for index in ranked], [values[index] for index in ranked]


def safe_copy_to_latest(src_path, dst_path):
    try:
        shutil.copyfile(src_path, dst_path)
    except Exception as e:
        pass

def generate_charts(results_data, output_dir=None, timestamp_str=None):
    now = datetime.datetime.now()
    if timestamp_str is None:
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        formatted_date = now.strftime("%B %d, %Y - %H:%M:%S")
    else:
        try:
            dt = datetime.datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            formatted_date = dt.strftime("%B %d, %Y - %H:%M:%S")
        except Exception:
            formatted_date = timestamp_str

    benchmarks_dir = os.path.dirname(os.path.abspath(__file__))
    if output_dir is None:
        output_dir = os.path.join(benchmarks_dir, "reports", f"benchmark_{timestamp_str}")
        
    os.makedirs(output_dir, exist_ok=True)
    
    # Also maintain a "latest" directory for quick access
    latest_dir = os.path.join(benchmarks_dir, "reports", "latest")
    os.makedirs(latest_dir, exist_ok=True)

    # Dark slate theme. Bar colors stay saturated so they read on a dark panel.
    BG = "#0B1220"
    PANEL = "#151C2C"
    TEXT = "#E2E8F0"
    MUTED = "#94A3B8"
    GRID = "#475569"
    SPINE = "#3B475C"
    colors = {
        "C++ (GCC -O3)": "#60A5FA",                  # Blue
        "Rust (opt-level=3)": "#FB923C",             # Rust Orange
        "Greengold (Release)": "#34D399",            # Emerald
    }
    
    tasks = [t for t in [
        "fib", "collatz", "fannkuch", "mandel", "nbody", "spectral",
        "matmul", "heat", "monte", "fnv", "qsort", "dijkstra",
        "sieve", "primes", "vector", "trees", "particle", "gpumatmul",
    ] if t in results_data]
    task_metadata = {
        "fib": {
            "title": "Recursive Fibonacci (fib 41)",
            "subtitle": "Recursive fib(41)",
            "desc": "Recursive fib(41). The hot path is function calls and integer arithmetic.",
            "label": "Fibonacci (Rec 41)\n[Stack & Calls]"
        },
        "collatz": {
            "title": "Collatz Conjecture (1 to 4,000,000)",
            "subtitle": "CPU-Bound Integer Arithmetic & Tight Branching Loop",
            "desc": "Tests 64-bit integer arithmetic, division, multiplication, and CPU branch prediction across 4M numbers.",
            "label": "Collatz (4M Nums)\n[CPU & Branching]"
        },
        "sieve": {
            "title": "Sieve of Eratosthenes (8,000,000 Limit)",
            "subtitle": "Primes below 8,000,000",
            "desc": "Count the primes below 8,000,000.",
            "label": "Sieve (8M Limit)\n[Memory Locality]"
        },
        "primes": {
            "title": "Dave's Garage Primes Drag Race (1,000,000 Limit)",
            "subtitle": "Plummer's Software Drag Race Sieve Benchmark (20s Timed Loop)",
            "desc": "Dave Plummer's 1M Prime Sieve Drag Race. Counts completed passes in 20 seconds and verifies 78,498 primes.",
            "label": "Primes Drag Race\n[1M Limit]"
        },
        "vector": {
            "title": "Dynamic Heap Vector (20,000,000 Elements)",
            "subtitle": "Heap Allocation, Capacity Doubling & Vector Throughput",
            "desc": "Pushes 20M items to dynamic List/vector, sums elements, and releases heap. Measures amortized reallocation.",
            "label": "Dynamic Vector (20M)\n[Heap Realloc & Sum]"
        },
        "particle": {
            "title": "Particle Simulation 20K x 2,000 Steps (SoA vs AoS)",
            "subtitle": "20,000 particles, 2,000 steps",
            "desc": "Greengold stores the particles in soa Array and indexes them with trust inside hot fn. The C++ and Rust programs store an array of structs.",
            "label": "Particle (20K)\n[soa Array]"
        },
        "gpumatmul": {
            "title": "GPU Matmul (4096 x 2048, 8 layers, OpenCL)",
            "subtitle": "Inference-style dense layers on the GPU",
            "desc": "Eight f32 dense layers with ReLU and int8-style requantization, run by the same OpenCL kernel in all three languages. The host side differs: generating the weights, uploading them, driving the queue.",
            "label": "GPU Matmul (8 layers)\n[OpenCL]"
        },
        "fannkuch": {
            "title": "Fannkuch-Redux (n = 10)",
            "subtitle": "All permutations of 0..9, pancake flips",
            "desc": "Every permutation of ten items, repeated four times. Greengold indexes with trust inside hot fn, and the checksum uses overflow: wrap.",
            "label": "Fannkuch (n=10)\n[Permutation]"
        },
        "mandel": {
            "title": "Mandelbrot (2048 x 2048, 80 iterations)",
            "subtitle": "Escape-time count on a fixed plane",
            "desc": "2048 by 2048 pixels, at most 80 iterations. Counts pixels that stay inside the set. Greengold marks the iterator hot fn with overflow: wrap.",
            "label": "Mandelbrot (2048)\n[Complex iter]"
        },
        "nbody": {
            "title": "N-body (768 bodies, 160 steps)",
            "subtitle": "All-pairs gravity on parallel arrays",
            "desc": "768 bodies, 160 steps, softening 0.05. Greengold uses hot fn, exclusive lend, trust, and overflow: wrap.",
            "label": "N-body (160 steps)\n[All pairs]"
        },
        "spectral": {
            "title": "Spectral Norm (n = 1600, 40 iterations)",
            "subtitle": "Power iteration on an implicit matrix",
            "desc": "Forty applications of A twice, n = 1600. Greengold uses hot fn, exclusive lend, trust, and overflow: wrap.",
            "label": "Spectral (n=1600)\n[Dense matvec]"
        },
        "matmul": {
            "title": "Matrix Multiply (1216 x 1216, i-k-j)",
            "subtitle": "Naive f64 product, no blocking",
            "desc": "1216 by 1216 f64 matrices, i-k-j order. Greengold uses hot fn, exclusive lend, trust, and overflow: wrap.",
            "label": "Matmul (1216)\n[i-k-j]"
        },
        "heat": {
            "title": "Heat Stencil (1024 x 1024, 320 steps)",
            "subtitle": "Jacobi average of four neighbours",
            "desc": "1024 by 1024 grid, three hundred twenty Jacobi steps. Greengold uses hot fn, exclusive lend, trust, and overflow: wrap.",
            "label": "Heat (320 steps)\n[Stencil]"
        },
        "monte": {
            "title": "Monte Carlo Pi (120,000,000 samples)",
            "subtitle": "xorshift64* points inside the unit circle",
            "desc": "One hundred twenty million samples from xorshift64*. Counts hits inside the unit circle. Greengold keeps the generator in one hot fn with overflow: wrap.",
            "label": "Monte Carlo (120M)\n[PRNG]"
        },
        "fnv": {
            "title": "FNV-1a (8,000,000 bytes, 40 salts)",
            "subtitle": "Hash a generated byte stream",
            "desc": "FNV-1a 64 over eight million bytes, forty salted passes. Greengold hashes inside hot fn with wrapping arithmetic.",
            "label": "FNV-1a (8M)\n[Hash]"
        },
        "qsort": {
            "title": "Quicksort (8,000,000 i32)",
            "subtitle": "Iterative quicksort, insertion sort under 16",
            "desc": "Eight million i32 values. Explicit stack, insertion sort on short ranges. Greengold uses hot fn, trust, and overflow: wrap.",
            "label": "Quicksort (8M)\n[Partition]"
        },
        "dijkstra": {
            "title": "Dijkstra (4,000 nodes, 8 searches)",
            "subtitle": "Dense O(V^2) scan on an implicit graph",
            "desc": "Eight shortest-path searches on 4,000 nodes. Edge weights are computed, not stored. Greengold uses hot fn, exclusive lend, trust, and overflow: wrap.",
            "label": "Dijkstra (4K)\n[Dense scan]"
        },
        "trees": {
            "title": "Binary Trees (depth 16, 80 builds)",
            "subtitle": "Allocate a tree, walk it, free it",
            "desc": "A full binary tree of depth 16, built and counted eighty times. Greengold uses Box and a borrowing walk.",
            "label": "Trees (depth 16)\n[Alloc & walk]"
        },
    }
    
    variants = [
        "C++ (GCC -O3)",
        "Rust (opt-level=3)",
        "Greengold (Release)",
    ]
    short_labels = {
        "C++ (GCC -O3)": "C++",
        "Rust (opt-level=3)": "Rust",
        "Greengold (Release)": "Greengold",
    }

    def draw_panel(ax, names, values, formatter, title, ylabel):
        bars = ax.bar(
            range(len(names)), values,
            color=[colors[name] for name in names], width=0.55, alpha=0.92,
        )
        for bar, value in zip(bars, values):
            ax.annotate(
                formatter(value),
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 4), textcoords="offset points",
                ha="center", va="bottom", fontsize=9.5, fontweight="bold",
            )
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels([short_labels[name] for name in names], fontsize=9.5)
        peak = max(values) if values else 0
        ax.set_ylim(0, peak * 1.18 if peak > 0 else 1)
        ax.grid(axis="y", linestyle="--", color=GRID, alpha=0.45)

    # Global dark theme
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "Helvetica"]
    plt.rcParams["figure.facecolor"] = BG
    plt.rcParams["savefig.facecolor"] = BG
    plt.rcParams["savefig.edgecolor"] = BG
    plt.rcParams["axes.facecolor"] = PANEL
    plt.rcParams["axes.edgecolor"] = SPINE
    plt.rcParams["axes.linewidth"] = 0.8
    plt.rcParams["axes.axisbelow"] = True
    plt.rcParams["axes.labelcolor"] = TEXT
    plt.rcParams["axes.titlecolor"] = TEXT
    plt.rcParams["text.color"] = TEXT
    plt.rcParams["xtick.color"] = MUTED
    plt.rcParams["ytick.color"] = MUTED
    plt.rcParams["grid.color"] = GRID
    plt.rcParams["legend.facecolor"] = PANEL
    plt.rcParams["legend.edgecolor"] = SPINE
    plt.rcParams["legend.framealpha"] = 0.95
    plt.rcParams["legend.labelcolor"] = TEXT

    generated_files = {}

    # =============================================================
    # 1. PER-TEST DEDICATED IN-DEPTH PAGES / CARDS
    # =============================================================
    for task in tasks:
        meta = task_metadata.get(task, {"title": task.upper(), "subtitle": "", "desc": "", "label": task})
        fig, axes = plt.subplots(2, 2, figsize=(14, 10), dpi=300)
        fig.suptitle(f"Detailed Benchmark Analysis: {meta['title']}\nBenchmark Executed: {formatted_date}",
                     fontsize=15, fontweight="bold", y=0.98)

        # Each panel is ordered best to worst, left to right.
        row = results_data[task]
        has_passes = (task == "primes" and any(row[v].get("passes", 0) > 0 for v in variants))
        if has_passes:
            names, values = order_best_first(variants, [row[v].get("passes", 0) for v in variants], True)
            draw_panel(
                axes[0, 0], names, values,
                lambda value: f"{int(value):,} passes",
                "Total Sieve Passes in 20s — best on the left",
                "Passes Count",
            )
        else:
            names, values = order_best_first(variants, [row[v]["median_ms"] for v in variants], False)
            draw_panel(
                axes[0, 0], names, values,
                lambda value: f"{value:.2f} ms",
                "Execution Runtime (ms) — best on the left",
                "Milliseconds (ms)",
            )

        names, values = order_best_first(variants, [row[v]["peak_mem_mb"] for v in variants], False)
        draw_panel(
            axes[0, 1], names, values,
            lambda value: f"{value:.2f} MB",
            "Peak Working Set Memory (MB) — best on the left",
            "RAM (MB)",
        )
        names, values = order_best_first(variants, [row[v]["binary_size_kb"] for v in variants], False)
        draw_panel(
            axes[1, 0], names, values,
            lambda value: f"{value:.1f} KB",
            "Executable Binary Size (KB) — best on the left",
            "File Size (KB)",
        )
        names, values = order_best_first(variants, [row[v]["compile_time_s"] for v in variants], False)
        draw_panel(
            axes[1, 1], names, values,
            lambda value: f"{value:.2f}s",
            "Compilation Time (Seconds) — best on the left",
            "Compile Time (s)",
        )

        # Subtitle description box at bottom
        fig.text(0.5, 0.02, f"Benchmark Context: {meta['desc']}",
                 ha='center', fontsize=9.5, style='italic', color=MUTED,
                 bbox=dict(boxstyle="round,pad=0.5", facecolor=PANEL, edgecolor=SPINE))

        plt.tight_layout(rect=[0, 0.04, 1, 0.95])
        test_file_path = os.path.join(output_dir, f"test_{task}_{timestamp_str}.png")
        fig.savefig(test_file_path)
        safe_copy_to_latest(test_file_path, os.path.join(latest_dir, f"test_{task}.png"))
        plt.close(fig)
        generated_files[f"test_{task}"] = test_file_path

    # Save metadata JSON in the date folder
    data_json_path = os.path.join(output_dir, "benchmark_data.json")
    with open(data_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp_str,
            "date": formatted_date,
            "results": results_data
        }, f, indent=2, ensure_ascii=False)
    safe_copy_to_latest(data_json_path, os.path.join(latest_dir, "benchmark_data.json"))

    return {
        "output_dir": output_dir,
        "latest_dir": latest_dir,
        "timestamp": timestamp_str,
        "date": formatted_date,
        "files": generated_files
    }

if __name__ == "__main__":
    benchmarks_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(benchmarks_dir, "benchmark_results.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = generate_charts(data)
        print("Charts successfully generated in:", out["output_dir"])
        for k, v in out["files"].items():
            print(f" - {k}: {v}")
    else:
        print("benchmark_results.json not found!")
