"""LLVM IR -> object file / bitcode / executable (llvmlite or an outside clang, and the system linker)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import llvm_tools


class LLVMError(Exception):
    pass


@lru_cache(maxsize=None)
def has_llvmlite() -> bool:
    try:
        import llvmlite.binding  # noqa: F401
    except ImportError:
        return False
    return True


PREFERRED_LLVM = 22  # llvmlite 0.50; older LLVMs optimize some loops clearly worse


def llvmlite_major() -> int:
    import llvmlite.binding as llvm
    return llvm.llvm_version_info[0]


def backend() -> str:
    """`llvmlite` (the LLVM built into llvmlite) or `clang` (an outside LLVM, see llvm_tools).
    Without GG_BACKEND: llvmlite when its LLVM is PREFERRED_LLVM or newer, else whichever LLVM is newer."""
    want = os.environ.get("GG_BACKEND", "").strip().lower()
    if want in ("clang", "llvm", "external"):
        return "clang"
    if want == "llvmlite":
        return "llvmlite"
    if not has_llvmlite():
        return "clang"
    mine = llvmlite_major()
    if mine >= PREFERRED_LLVM:
        return "llvmlite"
    outside = llvm_tools.find()
    return "clang" if outside is not None and outside[1] > mine else "llvmlite"


def describe_backend() -> str:
    if backend() == "clang":
        return f"outside LLVM: {llvm_tools.describe()}"
    import llvmlite
    import llvmlite.binding as llvm
    return f"llvmlite {llvmlite.__version__} (LLVM {'.'.join(map(str, llvm.llvm_version_info))}, built in)"


def _prepare(ir_text: str, release: bool) -> str:
    if release and os.environ.get("GG_RECUR_INLINE", "1") != "0":
        from .recur_inline import recur_inline
        ir_text = recur_inline(ir_text)
    return ir_text


def parse_module(ir_text: str, triple: str | None = None) -> Any:
    import llvmlite.binding as llvm
    from .codegen_llvm import init_llvm
    init_llvm()
    try:
        mod = llvm.parse_assembly(ir_text)
        mod.verify()
    except RuntimeError as exc:
        raise LLVMError(f"generated LLVM IR is invalid (compiler error):\n{exc}") from None
    return mod


_CPU: dict[str, str] = {"cpu": "", "features": ""}


def set_cpu(cpu: str | None = None, features: str | None = None) -> None:
    """Picks the machine the code is made for: `cpu` is a LLVM CPU name (`haswell`, `znver3`, `apple-m1`) or
    `native` (the CPU running the compiler); `features` is a list like `+avx2,+fma,-avx512f`.
    Without it the code runs on any CPU of the target (x86-64 baseline: SSE2, no AVX/FMA)."""
    _CPU["cpu"] = (cpu or os.environ.get("GG_CPU", "")).strip()
    _CPU["features"] = (features or os.environ.get("GG_FEATURES", "")).strip()


def _cpu_spec() -> tuple[str, str]:
    cpu, feats = _CPU["cpu"], _CPU["features"]
    if not cpu and not feats:  # not set by the command line: the environment may still ask
        cpu, feats = os.environ.get("GG_CPU", "").strip(), os.environ.get("GG_FEATURES", "").strip()
    return cpu, feats


def cpu_key() -> str:
    """Identifies the chosen CPU for the build cache; `native` includes the host CPU name."""
    cpu, feats = _cpu_spec()
    return f"cpu={host_cpu_name() if cpu == 'native' else cpu};features={feats}"


def host_cpu_name() -> str:
    import llvmlite.binding as llvm
    from .codegen_llvm import init_llvm
    init_llvm()
    return llvm.get_host_cpu_name()


def cpu_options(triple: str) -> tuple[str, str]:
    """(cpu name, feature string) for LLVM; `native` expands to the host CPU and the features it has."""
    cpu, feats = _cpu_spec()
    if cpu == "native":
        import llvmlite.binding as llvm
        from .codegen_llvm import init_llvm
        init_llvm()
        cpu = llvm.get_host_cpu_name()
        host = llvm.get_host_cpu_features().flatten()
        feats = ",".join(x for x in (host, feats) if x)
    return cpu, feats


def target_machine(triple: str, release: bool) -> Any:
    import llvmlite.binding as llvm
    from .codegen_llvm import init_llvm
    init_llvm()
    target = llvm.Target.from_triple(triple)
    reloc = "default" if "windows" in triple else "pic"
    cpu, feats = cpu_options(triple)
    return target.create_target_machine(cpu=cpu, features=feats, opt=3 if release else 0, reloc=reloc,
                                        codemodel="default")


def optimize(mod: Any, tm: Any, release: bool) -> None:
    import llvmlite.binding as llvm
    if hasattr(llvm, "create_pass_builder"):  # llvmlite 0.45+: LLVM's new pass manager (the legacy one is gone)
        pto = llvm.create_pipeline_tuning_options(speed_level=3 if release else 0)
        if release:
            pto.loop_vectorization = True
            pto.slp_vectorization = True
            pto.loop_unrolling = True
            # The inlining threshold stays LLVM's -O3 default: with llvmlite 0.50 a threshold of 275 left
            # even two-line functions (a list `push`) out of line.
        pb = llvm.create_pass_builder(tm, pto)
        mpm = pb.getModulePassManager()
        if not release and hasattr(mpm, "add_global_dead_code_eliminate_pass"):
            # Library functions that the program never calls are all in the module; drop them so a program
            # that does not use `std.math` does not need libm (a `--no-std` link has no libm to give).
            mpm.add_global_dead_code_eliminate_pass()
        mpm.run(mod, pb)
        return
    pmb = llvm.create_pass_manager_builder()
    pmb.opt_level = 3 if release else 0
    if release:
        pmb.loop_vectorize = True
        pmb.slp_vectorize = True
        pmb.inlining_threshold = 275
    pm = llvm.create_module_pass_manager()
    tm.add_analysis_passes(pm)
    pmb.populate(pm)
    pm.run(mod)


def compile_ir(ir_text: str, triple: str, release: bool) -> tuple[Any, Any]:
    """llvmlite only: the parsed and optimized module and its target machine."""
    mod = parse_module(_prepare(ir_text, release))
    tm = target_machine(triple, release)
    optimize(mod, tm, release)
    return mod, tm


def _outside(fn, ir_text: str, triple: str, release: bool):
    try:
        return fn(_prepare(ir_text, release), triple, release)
    except llvm_tools.ToolError as err:
        raise LLVMError(str(err)) from None


def optimized_ir(ir_text: str, triple: str, release: bool) -> str:
    if backend() == "clang":
        return _outside(llvm_tools.optimized_ir, ir_text, triple, release)
    mod, _ = compile_ir(ir_text, triple, release)
    return str(mod)


def bitcode(ir_text: str, triple: str, release: bool) -> bytes:
    if backend() == "clang":
        return _outside(llvm_tools.bitcode, ir_text, triple, release)
    mod, _ = compile_ir(ir_text, triple, release)
    return mod.as_bitcode()


def object_code(ir_text: str, triple: str, release: bool) -> bytes:
    if backend() == "clang":
        return _outside(llvm_tools.object_code, ir_text, triple, release)
    mod, tm = compile_ir(ir_text, triple, release)
    return tm.emit_object(mod)


def link_args(links: list[str] | None) -> list[str]:
    """Converts `--link`/`--link-path`/`--link-file` inputs to linker flags.

    Items starting with `-` (`-L/dir`, `-lfoo`, `-framework`) or looking like a file path
    (`.a`, `.o`, `.lib`, `.so`, `.dll`, `.dylib` or containing path separators) are passed as is;
    plain names become `-l<name>`. The `GG_LINK_ARGS` environment variable is appended raw.
    """
    import shlex
    out: list[str] = []
    for lib in links or []:
        looks_like_file = (os.sep in lib or "/" in lib
                           or lib.lower().endswith((".a", ".o", ".obj", ".lib", ".so", ".dll", ".dylib")))
        out.append(lib if lib.startswith("-") or looks_like_file else f"-l{lib}")
    extra = os.environ.get("GG_LINK_ARGS")
    if extra:
        out += shlex.split(extra, posix=(os.name != "nt"))
    return out


def find_linker(triple: str) -> list[str] | None:
    """Linker command (prefix): `$CC`, gcc/cc/clang, or else `zig cc` (see `targets.zig_path`); `GG_LINKER=zig`
    picks zig first. On Windows, `-target` is added to clang for mingw targets."""
    env_cc = os.environ.get("CC")
    if env_cc and shutil.which(env_cc):
        return [shutil.which(env_cc)]  # type: ignore[list-item]
    from .targets import zig_linker
    if os.environ.get("GG_LINKER") == "zig":
        return zig_linker(triple)
    names = ("gcc", "cc", "clang") if sys.platform != "darwin" else ("clang", "cc", "gcc")
    for name in names:
        path = shutil.which(name)
        if path:
            if name == "clang" and "windows" in triple:
                return [path, "-target", triple]
            return [path]
    return zig_linker(triple)


def _uses_openssl(obj_path: Path) -> bool:
    """True when the program calls OpenSSL (std.tls on Linux and macOS); only then is `-lssl` needed."""
    try:
        return b"SSL_CTX_new" in Path(obj_path).read_bytes()
    except OSError:
        return False


def _openssl_link_args() -> list[str]:
    """`-lssl -lcrypto`, plus the Homebrew library folders on macOS (OpenSSL is not in the system's)."""
    args: list[str] = []
    if sys.platform == "darwin":
        for d in ("/opt/homebrew/opt/openssl@3/lib", "/usr/local/opt/openssl@3/lib",
                  "/opt/homebrew/opt/openssl/lib", "/usr/local/opt/openssl/lib"):
            if os.path.isdir(d):
                args.append(f"-L{d}")
    return args + ["-lssl", "-lcrypto"]


def link_executable(obj_path: Path, exe_path: Path, triple: str, links: list[str] | None = None,
                    freestanding: bool = False, debug: bool = False) -> int:
    cmd = find_linker(triple)
    if cmd is None:
        print("Error: no linker found. Install gcc or clang, or run `pip install ziglang` (zig cc links with "
              "nothing else installed). `gg toolchain` shows what was found.", file=sys.stderr)
        return 2
    cmd = cmd + [str(obj_path), "-o", str(exe_path)]
    if freestanding:
        cmd += ["-nostdlib", "-static"]
    else:
        if "windows" not in triple:
            cmd.append("-lm")
        cmd += link_args(links)
        if "windows" in triple:
            cmd.append("-lws2_32")  # sockets (std.net); unused libraries add nothing
            cmd.append("-lsecur32")  # TLS (std.tls uses SChannel)
            cmd.append("-Wl,--no-insert-timestamp")  # the same sources give the same bytes
        elif _uses_openssl(obj_path):
            cmd += _openssl_link_args()
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Error: linking failed:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        if "-lssl" in cmd and ("-lssl" in result.stderr or "-lcrypto" in result.stderr):
            print("Hint: https and TLS (std.tls) need the OpenSSL library on this system: install libssl-dev "
                  "(Debian, Ubuntu), openssl-devel (Fedora), or `brew install openssl` (macOS).", file=sys.stderr)
        return 1
    if debug and "apple" in triple:
        # The linker leaves the DWARF in the object file, which is deleted; dsymutil copies it into exe.dSYM
        # so lldb can find the lines and variables.
        dsymutil = shutil.which("dsymutil")
        if dsymutil:
            subprocess.run([dsymutil, str(exe_path)], capture_output=True, text=True)
    return 0
