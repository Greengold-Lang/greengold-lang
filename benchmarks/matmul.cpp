#include <cstdint>
#include <iostream>
#include <vector>

void multiply(std::vector<double>& a, std::vector<double>& b, std::vector<double>& c, size_t n) {
    for (size_t i = 0; i < n; i++) {
        for (size_t k = 0; k < n; k++) {
            double aik = a[i * n + k];
            for (size_t j = 0; j < n; j++) {
                c[i * n + j] += aik * b[k * n + j];
            }
        }
    }
}

int main() {
    const size_t n = 1216;
    const size_t cells = n * n;
    std::vector<double> a, b, c;
    a.reserve(cells);
    b.reserve(cells);
    c.reserve(cells);
    for (size_t i = 0; i < n; i++) {
        for (size_t j = 0; j < n; j++) {
            a.push_back((double)((i + j) % 17));
            b.push_back((double)((i * 3 + j) % 13));
            c.push_back(0.0);
        }
    }
    multiply(a, b, c, n);
    double sum = 0.0;
    for (size_t i = 0; i < cells; i++) sum += c[i];
    std::cout << (long long)sum << "\n";
    std::cout << (long long)c[0] << "\n";
    std::cout << (long long)c[cells - 1] << "\n";
    return 0;
}
