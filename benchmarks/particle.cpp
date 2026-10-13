#include <iostream>
#include <vector>

// Structure of arrays: one vector per field, the layout `soa Array[Particle, N]` gives Greengold.
constexpr size_t N = 20000;

float update(size_t steps) {
    std::vector<float> x(N), y(N), vx(N, 1.0f), vy(N, 2.0f);
    for (size_t i = 0; i < N; i++) {
        x[i] = (float)i * 0.1f;
        y[i] = (float)i * 0.2f;
    }
    for (size_t step = 0; step < steps; step++) {
        for (size_t i = 0; i < N; i++) {
            x[i] += vx[i];
            y[i] += vy[i];
        }
    }
    float total = 0.0f;
    for (size_t i = 0; i < N; i++) {
        total += x[i];
    }
    return total;
}

int main() {
    std::cout << update(2000) << "\n";
    return 0;
}
