import os
import sys
import time
import ctypes
from ctypes import wintypes
import subprocess
import statistics
import json
import shutil
import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from plotter import generate_charts

class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('PageFaultCount', wintypes.DWORD),
        ('PeakWorkingSetSize', ctypes.c_size_t),
        ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t),
        ('PeakPagefileUsage', ctypes.c_size_t),
    ]

def compile_target(name, lang, cmd):
    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True)
    compile_time = time.perf_counter() - t0
    if res.returncode != 0:
        print(f"Compilation failed for {name} ({lang}):\n{res.stderr}")
        return False, 0.0
    return True, compile_time

def run_executable(exe_path, iterations=5):
    times = []
    peak_mems = []
    output = None
    
    for i in range(iterations):
        t0 = time.perf_counter()
        p = subprocess.Popen([exe_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        pid = p.pid
        h_process = ctypes.windll.kernel32.OpenProcess(0x0410, False, pid)
        
        stdout, stderr = p.communicate()
        elapsed = (time.perf_counter() - t0) * 1000.0 # ms
        
        mem_mb = 0.0
        if h_process:
            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(pmc)
            if ctypes.windll.psapi.GetProcessMemoryInfo(h_process, ctypes.byref(pmc), pmc.cb):
                mem_mb = pmc.PeakWorkingSetSize / (1024 * 1024)
            ctypes.windll.kernel32.CloseHandle(h_process)
            
        times.append(elapsed)
        peak_mems.append(mem_mb)
        if output is None:
            output = stdout.strip()
            
    median_time = statistics.median(times)
    mean_time = statistics.mean(times)
    max_mem = max(peak_mems)
    return {
        "median_ms": median_time,
        "mean_ms": mean_time,
        "peak_mem_mb": max_mem,
        "output": output
    }

def main():
    benchmarks_dir = os.path.dirname(os.path.abspath(__file__))
    start_time = datetime.datetime.now()
    timestamp_str = start_time.strftime("%Y%m%d_%H%M%S")
    
    all_tasks = [
        "fib", "collatz", "fannkuch", "mandel", "nbody", "spectral",
        "matmul", "heat", "monte", "fnv", "qsort", "dijkstra",
        "sieve", "primes", "vector", "trees", "particle", "wordfreq", "jsonparse", "gpumatmul",
    ]
    selected_tasks = []
    iterations = 5
    explicit_iterations = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--iterations", "-n") and i + 1 < len(args):
            try:
                iterations = int(args[i + 1])
                explicit_iterations = True
            except ValueError:
                pass
            i += 2
        elif arg.lower() in all_tasks:
            selected_tasks.append(arg.lower())
            i += 1
        elif arg in ("--help", "-h"):
            print("Usage: python run_benchmarks.py [tasks...] [-n iterations]")
            print(f"Available tasks: {', '.join(all_tasks)}")
            return
        else:
            i += 1
    tasks = selected_tasks if selected_tasks else all_tasks
    created_exes = []
    results = {}
    
    print("=" * 65)
    print("  Greengold vs C++ vs Rust — Automated Benchmark Suite")
    print(f"  Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)
    
    try:
        for task in tasks:
            print(f"\n---> TASK: {task.upper()}")
            results[task] = {}
            task_iters = iterations if explicit_iterations else (1 if task == "primes" else iterations)
            
            targets = {
                "C++ (GCC -O3)": {
                    "cmd": ["g++", "-O3", os.path.join(benchmarks_dir, f"{task}.cpp"), "-o", os.path.join(benchmarks_dir, f"{task}_cpp.exe")],
                    "exe": os.path.join(benchmarks_dir, f"{task}_cpp.exe")
                },
                "Rust (opt-level=3)": {
                    "cmd": ["rustc", "-C", "opt-level=3", os.path.join(benchmarks_dir, f"{task}.rs"), "-o", os.path.join(benchmarks_dir, f"{task}_rust.exe")],
                    "exe": os.path.join(benchmarks_dir, f"{task}_rust.exe")
                },
                "Greengold (Release)": {
                    "cmd": [sys.executable, "-m", "greengold", "build", os.path.join(benchmarks_dir, f"{task}.gg"), "--release", "-o", os.path.join(benchmarks_dir, f"{task}_gg.exe")],
                    "exe": os.path.join(benchmarks_dir, f"{task}_gg.exe")
                }
            }
            
            for name, info in targets.items():
                print(f"  Compiling: {name:<32} ...", end=" ", flush=True)
                ok, comp_time = compile_target(task, name, info["cmd"])
                if not ok:
                    continue
                created_exes.append(info["exe"])
                
                exe_size_kb = os.path.getsize(info["exe"]) / 1024.0
                print(f"Done ({comp_time:.2f}s, {exe_size_kb:.1f} KB)")
                
                print(f"  Running ({task_iters} iterations) ...", end=" ", flush=True)
                run_stats = run_executable(info["exe"], iterations=task_iters)
                print(f"Time: {run_stats['median_ms']:.2f} ms | RAM: {run_stats['peak_mem_mb']:.2f} MB")
                
                extra_data = {}
                if task == "primes" and run_stats["output"]:
                    import re
                    m_passes = re.search(r'Passes:\s*(\d+)', run_stats["output"])
                    m_valid = re.search(r'Valid:\s*(\d+|true|Pass)', run_stats["output"], re.IGNORECASE)
                    m_tag = re.search(r'([a-zA-Z0-9_\-]+;\d+;[0-9.]+;\d+;[^\n\r]+)', run_stats["output"])
                    p_val = int(m_passes.group(1)) if m_passes else 0
                    dur_s = run_stats["median_ms"] / 1000.0
                    pps = (p_val / dur_s) if dur_s > 0 else 0
                    valid_val = m_valid.group(1) if m_valid else "Unknown"
                    tag_str = m_tag.group(1) if m_tag else ""
                    extra_data = {
                        "passes": p_val,
                        "passes_per_sec": pps,
                        "valid": valid_val,
                        "drag_race_tag": tag_str
                    }
                    print(f"    ↳ [Plummer Drag Race] Passes: {p_val:,} | {pps:.1f} passes/sec | Valid: {valid_val} (78,498 primes)")
                    if tag_str:
                        print(f"    ↳ Output Tag: {tag_str}")
                
                results[task][name] = {
                    "compile_time_s": comp_time,
                    "binary_size_kb": exe_size_kb,
                    "median_ms": run_stats["median_ms"],
                    "mean_ms": run_stats["mean_ms"],
                    "peak_mem_mb": run_stats["peak_mem_mb"],
                    "output": run_stats["output"],
                    **extra_data
                }
                
        # Save results to json
        json_path = os.path.join(benchmarks_dir, "benchmark_results.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
            
        # Automatically generate charts categorized by timestamp
        print("\n" + "=" * 65)
        print("  Generating Visual PNG Charts (English)...")
        print("=" * 65)
        chart_info = generate_charts(results, timestamp_str=timestamp_str)
        data_json_src = os.path.join(chart_info["output_dir"], "benchmark_data.json")
        data_json_dst = os.path.join(chart_info["latest_dir"], "benchmark_data.json")
        if os.path.exists(data_json_src):
            shutil.copyfile(data_json_src, data_json_dst)
        print(f"Charts saved to directory: {chart_info['output_dir']}")
        for name, path in chart_info["files"].items():
            print(f"  - [{name}]: {os.path.basename(path)}")
            
        print("\nLatest charts and benchmark_data.json updated in: benchmarks/reports/latest/")
        
    finally:
        # Clean up temporary executables
        for exe in created_exes:
            if os.path.exists(exe):
                try:
                    os.remove(exe)
                except Exception:
                    pass

if __name__ == "__main__":
    main()
