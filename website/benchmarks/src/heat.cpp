#include <cstdint>
#include <iostream>
#include <vector>

void jacobi(const std::vector<double>& cur, std::vector<double>& nxt, size_t n) {
    size_t last = n - 1;
    for (size_t i = 1; i < last; i++) {
        for (size_t j = 1; j < last; j++) {
            size_t idx = i * n + j;
            nxt[idx] = 0.25 * (cur[(i - 1) * n + j] + cur[(i + 1) * n + j]
                             + cur[i * n + (j - 1)] + cur[i * n + (j + 1)]);
        }
    }
}

int main() {
    const size_t n = 1024;
    const size_t cells = n * n;
    std::vector<double> a, b(cells, 0.0);
    a.reserve(cells);
    for (size_t i = 0; i < n; i++) {
        for (size_t j = 0; j < n; j++) a.push_back((double)((i * 13 + j * 7) % 19));
    }
    for (int step = 0; step < 160; step++) {
        jacobi(a, b, n);
        jacobi(b, a, n);
    }
    double sum = 0.0;
    for (size_t i = 0; i < cells; i++) sum += a[i];
    std::cout << (long long)(sum * 1000.0) << "\n";
    return 0;
}
