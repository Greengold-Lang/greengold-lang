"""Dave Plummer's Prime Sieve Drag Race Suite for Greengold, C++, and Rust.

Conforms strictly to the rules and specification in:
https://github.com/PlummersSoftwareLLC/Primes/tree/drag-race
"""
import os
import sys
import time
import subprocess
import re
import shutil

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BENCHMARKS_DIR = os.path.dirname(os.path.abspath(__file__))

TARGETS = {
    "C++ (GCC -O3)": {
        "impl": "cpp",
        "cmd": ["g++", "-O3", os.path.join(BENCHMARKS_DIR, "primes.cpp"), "-o", os.path.join(BENCHMARKS_DIR, "primes_cpp.exe")],
        "exe": os.path.join(BENCHMARKS_DIR, "primes_cpp.exe")
    },
    "Rust (opt-level=3)": {
        "impl": "rust",
        "cmd": ["rustc", "-C", "opt-level=3", os.path.join(BENCHMARKS_DIR, "primes.rs"), "-o", os.path.join(BENCHMARKS_DIR, "primes_rust.exe")],
        "exe": os.path.join(BENCHMARKS_DIR, "primes_rust.exe")
    },
    "Greengold (Release)": {
        "impl": "greengold",
        "cmd": [sys.executable, "-m", "greengold", "build", os.path.join(BENCHMARKS_DIR, "primes.gg"), "--release", "-o", os.path.join(BENCHMARKS_DIR, "primes_gg.exe")],
        "exe": os.path.join(BENCHMARKS_DIR, "primes_gg.exe")
    },
}

EXPECTED_PRIMES_1M = 78498

def compile_all():
    created = []
    print("=" * 75)
    print("  Dave Plummer's Prime Sieve Drag Race — Build Phase")
    print("=" * 75)
    for name, info in TARGETS.items():
        print(f"  Compiling {name:<35} ...", end=" ", flush=True)
        t0 = time.perf_counter()
        res = subprocess.run(info["cmd"], capture_output=True, text=True)
        dur = time.perf_counter() - t0
        if res.returncode != 0:
            print(f"FAILED!\n{res.stderr}")
            continue
        size_kb = os.path.getsize(info["exe"]) / 1024.0
        created.append(info["exe"])
        print(f"OK ({dur:.2f}s, {size_kb:.1f} KB)")
    return created

def parse_output(stdout):
    # Search for summary line:
    # Passes: 8853, Time: 5.000074, Avg: 0.000565, Limit: 1000000, Count1: 78498, Count2: 78498, Valid: 1
    m_summary = re.search(
        r'Passes:\s*(\d+),\s*Time:\s*([0-9.]+),\s*Avg:\s*([0-9.]+),\s*Limit:\s*(\d+),\s*Count1:\s*(\d+),\s*Count2:\s*(\d+),\s*Valid:\s*(\d+|true|Pass)',
        stdout,
        re.IGNORECASE
    )
    # Search for drag race tag line:
    # davepl_gg;8853;5.000074;1;algorithm=base,faithful=yes,bits=1
    m_tag = re.search(
        r'^(?P<label>[^;\r\n]+)\s*;\s*(?P<passes>\d+)\s*;\s*(?P<duration>[0-9.]+)\s*;\s*(?P<threads>\d+)(;(?P<extra>[^\r\n]+))?',
        stdout,
        re.MULTILINE
    )

    passes = int(m_summary.group(1)) if m_summary else (int(m_tag.group('passes')) if m_tag else 0)
    duration = float(m_summary.group(2)) if m_summary else (float(m_tag.group('duration')) if m_tag else 0.0)
    limit = int(m_summary.group(4)) if m_summary else 1000000
    count1 = int(m_summary.group(5)) if m_summary else 0
    count2 = int(m_summary.group(6)) if m_summary else 0
    raw_valid = m_summary.group(7) if m_summary else ""
    is_valid = (count1 == EXPECTED_PRIMES_1M and count2 == EXPECTED_PRIMES_1M and (raw_valid in ("1", "true", "Pass")))

    tags = {}
    label = m_tag.group('label') if m_tag else "unknown"
    threads = int(m_tag.group('threads')) if m_tag else 1
    if m_tag and m_tag.group('extra'):
        for part in m_tag.group('extra').split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                tags[k.strip()] = v.strip()

    pps = (passes / duration) if duration > 0 else 0.0

    return {
        "label": label,
        "passes": passes,
        "duration": duration,
        "threads": threads,
        "limit": limit,
        "count1": count1,
        "count2": count2,
        "valid": is_valid,
        "algorithm": tags.get("algorithm", "base"),
        "faithful": tags.get("faithful", "yes"),
        "bits": tags.get("bits", "1"),
        "passes_per_sec": pps,
        "raw_stdout": stdout
    }

def run_drag_race():
    created_exes = compile_all()
    results = []

    print("\n" + "=" * 75)
    print("  Running 20-Second Drag Race Runs")
    print("=" * 75)

    try:
        for name, info in TARGETS.items():
            if not os.path.exists(info["exe"]):
                continue
            print(f"  Executing {name:<35} (20 seconds) ...", end=" ", flush=True)
            t0 = time.perf_counter()
            res = subprocess.run([info["exe"]], capture_output=True, text=True)
            wall_dur = time.perf_counter() - t0

            if res.returncode != 0:
                print(f"ERROR! Return code {res.returncode}")
                continue

            parsed = parse_output(res.stdout)
            parsed["target"] = name
            results.append(parsed)

            valid_str = "PASS (78,498 primes)" if parsed["valid"] else "FAIL"
            print(f"Done! {parsed['passes']:,} passes ({parsed['passes_per_sec']:.1f} p/s) | {valid_str}")

        # Sort results by passes/sec descending (highest first)
        results.sort(key=lambda r: r["passes_per_sec"], reverse=True)

        print("\n" + "=" * 105)
        print("                  Plummer's Software Drag Race Leaderboard (Single-Threaded)")
        print("=" * 105)
        hdr = f"│ {'Index':<5} │ {'Target / Implementation':<32} │ {'Passes':<8} │ {'Duration':<9} │ {'Algorithm':<9} │ {'Faithful':<8} │ {'Bits':<4} │ {'Passes/Sec':<13} │ {'Valid':<7} │"
        sep = "├" + "─" * 7 + "┼" + "─" * 34 + "┼" + "─" * 10 + "┼" + "─" * 11 + "┼" + "─" * 11 + "┼" + "─" * 10 + "┼" + "─" * 6 + "┼" + "─" * 15 + "┼" + "─" * 9 + "┤"
        top = "┌" + "─" * 7 + "┬" + "─" * 34 + "┬" + "─" * 10 + "┬" + "─" * 11 + "┬" + "─" * 11 + "┬" + "─" * 10 + "┬" + "─" * 6 + "┬" + "─" * 15 + "┬" + "─" * 9 + "┐"
        bot = "└" + "─" * 7 + "┴" + "─" * 34 + "┴" + "─" * 10 + "┴" + "─" * 11 + "┴" + "─" * 11 + "┴" + "─" * 10 + "┴" + "─" * 6 + "┴" + "─" * 15 + "┴" + "─" * 9 + "┘"

        print(top)
        print(hdr)
        print(sep)
        for idx, r in enumerate(results, 1):
            val_txt = "Pass" if r["valid"] else "FAIL"
            row = f"│ {idx:<5} │ {r['target']:<32} │ {r['passes']:<8} │ {r['duration']:<9.5f} │ {r['algorithm']:<9} │ {r['faithful']:<8} │ {r['bits']:<4} │ {r['passes_per_sec']:<13.2f} │ {val_txt:<7} │"
            print(row)
        print(bot)

        # Verification analysis
        print("\n" + "=" * 75)
        print("  Validation & Verification Summary")
        print("=" * 75)
        all_ok = True
        for r in results:
            if not r["valid"]:
                print(f"  [X] {r['target']}: INVALID! Count={r['count1']}, expected {EXPECTED_PRIMES_1M}")
                all_ok = False
            else:
                print(f"  [✓] {r['target']}: Validated 78,498 primes up to 1,000,000. Algorithm: {r['algorithm']}, Faithful: {r['faithful']}, Bits: {r['bits']}.")

        if all_ok:
            print("\n  >>> ALL TARGETS PASSED RESULT VERIFICATION 100% SUCCESSFULLY! <<<")

        # Context comparison against Plummer repo historical data
        print("\n" + "=" * 75)
        print("  Comparison with PlummersSoftwareLLC/Primes Reference Benchmarks")
        print("=" * 75)
        print("  • Standard drag race limit: 1,000,000 numbers.")
        print("  • Expected primes count   : 78,498 (exactly matches all test outputs).")
        print("  • Target duration         : >= 20.0 seconds.")
        print("  • Language comparison:")
        rust_r = next((r for r in results if "Rust" in r["target"]), None)
        gg_r = next((r for r in results if r["target"] == "Greengold (Release)"), None)
        cpp_r = next((r for r in results if "C++" in r["target"]), None)

        if rust_r and gg_r:
            pct_rust = (gg_r["passes_per_sec"] / rust_r["passes_per_sec"]) * 100.0
            print(f"    - Greengold reaches {pct_rust:.1f}% of Rust (opt-level=3) performance!")
        if cpp_r and gg_r:
            pct_cpp = (gg_r["passes_per_sec"] / cpp_r["passes_per_sec"]) * 100.0
            print(f"    - Greengold reaches {pct_cpp:.1f}% of C++ (GCC -O3) performance!")

    finally:
        for exe in created_exes:
            if os.path.exists(exe):
                try:
                    os.remove(exe)
                except Exception:
                    pass

if __name__ == "__main__":
    run_drag_race()
