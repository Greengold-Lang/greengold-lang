#include <cmath>
#include <cstdint>
#include <iostream>
#include <vector>

void advance(std::vector<double>& x, std::vector<double>& y, std::vector<double>& z,
             std::vector<double>& vx, std::vector<double>& vy, std::vector<double>& vz,
             std::vector<double>& mass, size_t n) {
    for (size_t i = 0; i < n; i++) {
        for (size_t j = i + 1; j < n; j++) {
            double dx = x[i] - x[j];
            double dy = y[i] - y[j];
            double dz = z[i] - z[j];
            double dist2 = dx * dx + dy * dy + dz * dz + 0.05;
            double inv = 1.0 / std::sqrt(dist2);
            double scale = inv * inv * inv * 0.01;
            double mi = mass[i];
            double mj = mass[j];
            vx[i] -= dx * mj * scale;
            vy[i] -= dy * mj * scale;
            vz[i] -= dz * mj * scale;
            vx[j] += dx * mi * scale;
            vy[j] += dy * mi * scale;
            vz[j] += dz * mi * scale;
        }
    }
    for (size_t k = 0; k < n; k++) {
        x[k] += vx[k] * 0.01;
        y[k] += vy[k] * 0.01;
        z[k] += vz[k] * 0.01;
    }
}

int main() {
    const size_t n = 768;
    std::vector<double> x(n), y(n), z(n), vx(n), vy(n), vz(n), mass(n);
    for (size_t i = 0; i < n; i++) {
        double ang = (double)i * 0.17;
        x[i] = std::cos(ang) * (1.0 + (double)(i % 9) * 0.03);
        y[i] = std::sin(ang) * (1.0 + (double)(i % 5) * 0.02);
        z[i] = (double)(i % 7) * 0.02;
        vx[i] = std::sin(ang) * 0.01;
        vy[i] = std::cos(ang) * 0.01;
        mass[i] = 0.2 + (double)(i % 5) * 0.15;
    }
    for (int step = 0; step < 160; step++) advance(x, y, z, vx, vy, vz, mass, n);
    double sx = 0.0, sy = 0.0, sz = 0.0;
    for (size_t i = 0; i < n; i++) {
        sx += x[i];
        sy += y[i];
        sz += z[i];
    }
    std::cout << (long long)(sx * 1000.0) << "\n";
    std::cout << (long long)(sy * 1000.0) << "\n";
    std::cout << (long long)(sz * 1000.0) << "\n";
    return 0;
}
