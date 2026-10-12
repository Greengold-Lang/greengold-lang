"""Stdlib additions required before the Greengold compiler can be self-hosted."""
import subprocess
import sys

from tests.helpers import ROOT, run_gg_source


def test_intern_dedup_and_stable_copy(tmp_path):
    src = """import std.intern
import std.string

fn main():
    tab = intern.intern_new()
    a = tab.put("hello")
    b = tab.put("world")
    c = tab.put("hello")
    owned = string.from("hello")
    d = tab.put(owned.as_str())
    owned.clear()
    print(a, b, c, d, tab.len())
    print(tab.text(a))
    print(tab.text(b))
    e = tab.put("")
    f = tab.put("")
    print(e, f, tab.text(e).len, tab.len())
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["0 1 0 0 2", "hello", "world", "2 2 0 3"]


def test_args_returns_program_arguments(tmp_path):
    src_path = tmp_path / "args.gg"
    src_path.write_text(
        "import std.process\n\nfn main():\n    xs = process.args()\n    print(xs.len)\n    print(xs[1])\n    print(xs[2])\n",
        encoding="utf-8",
    )
    exe = tmp_path / ("args.exe" if sys.platform == "win32" else "args")
    built = subprocess.run(
        [sys.executable, "-m", "greengold", "build", str(src_path), "-o", str(exe)],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=120,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(exe), "alpha", "beta"], capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == ["3", "alpha", "beta"]


def test_eprint_writes_stderr(tmp_path):
    src = """fn main():
    eprint("err")
    print("out")
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["out"]
    assert r.stderr.splitlines() == ["err"]


def test_process_run_and_directory(tmp_path):
    src = """import std.fs
import std.process
import std.string
import std.time

fn main():
    py = List[str]()
    py.push("python")
    py.push("-c")
    py.push("import sys; sys.stdout.write(chr(79)); sys.stdout.write(chr(85)); sys.stdout.write(chr(84)); sys.stderr.write(chr(69)); sys.stderr.write(chr(82)); sys.stderr.write(chr(82)); raise SystemExit(4)")
    match consume process.process_run(py):
        Valid(r):
            print(r.code)
            print(r.out.as_str())
            print(r.err.as_str())
        None:
            print("spawn-failed")
    match consume process.env_get("TEMP"):
        Valid(root):
            leaf = string.from("gg_std_")
            leaf.append_i64(time.clock_ticks())
            dest = fs.path_join(root.as_str(), leaf.as_str())
            print(fs.make_dir(dest.as_str()))
            print(fs.is_dir(dest.as_str()))
            file = fs.path_join(dest.as_str(), "note.txt")
            print(fs.write_string_to_file(file.as_str(), "hello"))
            match consume fs.read_file_to_string(file.as_str()):
                Valid(s):
                    print(s.as_str())
                None:
                    print("read-failed")
            moved = fs.path_join(dest.as_str(), "note2.txt")
            print(fs.rename_file(file.as_str(), moved.as_str()))
            match consume fs.list_dir(dest.as_str()):
                Valid(listing):
                    print(listing.as_str())
                None:
                    print("list-failed")
            print(fs.remove_file(moved.as_str()))
            rm = List[str]()
            rm.push("rmdir")
            rm.push(dest.as_str())
            match consume process.process_run(rm):
                Valid(done):
                    print(done.code)
                None:
                    print("rmdir-failed")
        None:
            print("no-temp")
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "4",
        "OUT",
        "ERR",
        "true",
        "true",
        "true",
        "hello",
        "true",
        "note2.txt",
        "true",
        "0",
    ]


def test_path_helpers(tmp_path):
    src = """import std.fs

fn main():
    print(fs.path_join("src", "main.gg"))
    print(fs.path_join("src/", "main.gg"))
    print(fs.path_join("src", "/abs.gg"))
    print(fs.path_join("", "main.gg"))
    print(fs.path_join("C:/proj", "a.gg"))
    print(fs.path_parent("src/main.gg"))
    print(fs.path_parent("src/"))
    print(fs.path_parent("a/b/"))
    print(fs.path_parent("main.gg"))
    print(fs.path_parent("/main.gg"))
    print(fs.path_parent("C:/proj/a.gg"))
    print(fs.path_name("src/main.gg"))
    print(fs.path_name("src/"))
    print(fs.path_ext("src/main.gg"))
    print(fs.path_ext("archive.tar.gz"))
    print(fs.path_ext(".gitignore"))
    print(fs.path_ext("Makefile"))
"""
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "src/main.gg",
        "src/main.gg",
        "/abs.gg",
        "main.gg",
        "C:/proj/a.gg",
        "src",
        "",
        "a",
        "",
        "/",
        "C:/proj",
        "main.gg",
        "src",
        ".gg",
        ".gz",
        "",
        "",
    ]
