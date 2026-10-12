"""C++ interop: `gg bindgen --cpp` and `[native] sources` in gg.toml."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from greengold.cli import main
from greengold.cppbind import cpp_bindgen

HEADER = """#pragma once
#include <string>
#include <vector>

namespace geo {

class Counter {
public:
    explicit Counter(int start) : value_(start) {}
    ~Counter() {}
    int add(int x) { value_ += x; return value_; }
    int get() const { return value_; }
    std::string label() const { return "count=" + std::to_string(value_); }
    void rename(const std::string& name) { name_ = name; }
    double ratio(double d) const { return value_ / d; }
    template <typename T> T cast() const { return T(value_); }
    void merge(const Counter& other) { value_ += other.value_; }
private:
    int value_;
    std::string name_;
};

inline int twice(int x) { return 2 * x; }
inline std::string greet(const char* who) { return std::string("hello ") + who; }
std::vector<int> unsupported();

}
"""


def test_bindgen_cpp_output():
    module, shim = cpp_bindgen(HEADER, "counter.hpp", "counter")
    assert "void* gg_Counter_new(int start) { return new geo::Counter(start); }" in shim
    assert "delete static_cast<geo::Counter*>(self)" in shim
    assert "int gg_fn_geo_twice(int x) { return geo::twice(x); }" in shim
    assert "fn get(self: read Self) -> i32:" in module          # const method
    assert "fn add(self: lend Self, x: i32) -> i32:" in module  # changes the object
    assert "fn merge(self: lend Self, other: read Counter):" in module
    assert "fn drop(self: lend Self):" in module
    assert "# skipped: geo::unsupported" in module


@pytest.mark.skipif(shutil.which("g++") is None and shutil.which("clang++") is None, reason="no C++ compiler")
def test_package_with_cpp_sources(tmp_path, monkeypatch):
    (tmp_path / "native").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "native" / "counter.hpp").write_text(HEADER, encoding="utf-8")
    module, shim = cpp_bindgen(HEADER, "counter.hpp", "counter")
    (tmp_path / "native" / "counter_shim.cpp").write_text(shim, encoding="utf-8")
    (tmp_path / "src" / "counter.gg").write_text(module, encoding="utf-8")
    (tmp_path / "gg.toml").write_text('[package]\nname = "demo"\nversion = "0.1.0"\n\n[native]\n'
                                      'sources = ["native/counter_shim.cpp"]\nflags = ["-std=c++17"]\n', encoding="utf-8")
    (tmp_path / "src" / "main.gg").write_text(
        "import counter { Counter, twice, greet }\n\nfn main():\n    c = Counter.new(5)\n    c.add(10)\n"
        "    other = Counter.new(100)\n    c.merge(other)\n    print(c.get(), c.label(), c.ratio(2.0))\n"
        '    print(twice(21), greet("greengold"))\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    exe = tmp_path / ("demo.exe" if os.name == "nt" else "demo")
    assert main(["build", "-o", str(exe)]) == 0
    out = subprocess.run([str(exe)], capture_output=True, text=True).stdout.splitlines()
    assert out == ["115 count=115 57.5", "42 hello greengold"]
