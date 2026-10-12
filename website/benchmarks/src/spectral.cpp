#include <cmath>
#include <cstdint>
#include <iostream>
#include <vector>

double aval(size_t i, size_t j) {
    size_t ij = i + j;
    size_t den = ij * (ij + 1) / 2 + i + 1;
    return 1.0 / (double)den;
}

void apply(std::vector<double>& out, const std::vector<double>& v, size_t n) {
    for (size_t i = 0; i < n; i++) {
        double sum = 0.0;
        for (size_t j = 0; j < n; j++) sum += aval(i, j) * v[j];
        out[i] = sum;
    }
}

int main() {
    const size_t n = 1600;
    std::vector<double> u(n, 1.0), v(n, 0.0);
    for (int iter = 0; iter < 40; iter++) {
        apply(v, u, n);
        apply(u, v, n);
    }
    double uv = 0.0, vv = 0.0;
    for (size_t i = 0; i < n; i++) {
        uv += u[i] * v[i];
        vv += v[i] * v[i];
    }
    double norm = std::sqrt(uv / vv);
    std::cout << (long long)(norm * 1000000000.0) << "\n";
    return 0;
}
