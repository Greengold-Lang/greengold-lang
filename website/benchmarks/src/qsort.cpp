#include <cstdint>
#include <iostream>
#include <vector>

uint32_t lcg(uint32_t s) {
    return s * 1664525u + 1013904223u;
}

void swap_at(std::vector<int32_t>& a, size_t i, size_t j) {
    int32_t tmp = a[i];
    a[i] = a[j];
    a[j] = tmp;
}

void insertion(std::vector<int32_t>& a, size_t lo, size_t hi) {
    if (hi < lo + 2) return;
    for (size_t i = lo + 1; i < hi; i++) {
        size_t j = i;
        while (j > lo) {
            if (a[j] < a[j - 1]) {
                swap_at(a, j, j - 1);
                j -= 1;
            } else break;
        }
    }
}

size_t partition(std::vector<int32_t>& a, size_t lo, size_t hi) {
    size_t mid = lo + (hi - lo) / 2;
    swap_at(a, mid, hi - 1);
    int32_t pivot = a[hi - 1];
    size_t store = lo;
    for (size_t j = lo; j < hi - 1; j++) {
        if (a[j] < pivot) {
            swap_at(a, store, j);
            store += 1;
        }
    }
    swap_at(a, store, hi - 1);
    return store;
}

void qsort_range(std::vector<int32_t>& a) {
    size_t n = a.size();
    if (n < 2) return;
    std::vector<size_t> slo, shi;
    slo.push_back(0);
    shi.push_back(n);
    while (!slo.empty()) {
        size_t lo = slo.back(); slo.pop_back();
        size_t hi = shi.back(); shi.pop_back();
        if (hi - lo < 16) insertion(a, lo, hi);
        else {
            size_t p = partition(a, lo, hi);
            if (p > lo) { slo.push_back(lo); shi.push_back(p); }
            if (p + 1 < hi) { slo.push_back(p + 1); shi.push_back(hi); }
        }
    }
}

int main() {
    std::vector<int32_t> a;
    a.reserve(8000000);
    uint32_t state = 1;
    for (int i = 0; i < 8000000; i++) {
        state = lcg(state);
        a.push_back((int32_t)(state & 2147483647u));
    }
    qsort_range(a);
    long long sum = 0;
    int bad = 0;
    for (size_t i = 0; i < a.size(); i++) {
        sum += (long long)a[i];
        if (i > 0 && a[i] < a[i - 1]) bad = 1;
    }
    std::cout << a[0] << "\n" << a[4000000] << "\n" << a[7999999] << "\n" << sum << "\n" << bad << "\n";
    return 0;
}
