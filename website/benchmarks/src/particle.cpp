#include <iostream>
#include <vector>

struct Particle {
    float x, y, vx, vy;
};

float update(size_t steps) {
    std::vector<Particle> ps(20000);
    for (size_t i = 0; i < 20000; i++) {
        ps[i].x = (float)i * 0.1f;
        ps[i].y = (float)i * 0.2f;
        ps[i].vx = 1.0f;
        ps[i].vy = 2.0f;
    }
    for (size_t step = 0; step < steps; step++) {
        for (size_t i = 0; i < 20000; i++) {
            ps[i].x += ps[i].vx;
            ps[i].y += ps[i].vy;
        }
    }
    float total = 0.0f;
    for (size_t i = 0; i < 20000; i++) {
        total += ps[i].x;
    }
    return total;
}

int main() {
    std::cout << update(2000) << "\n";
    return 0;
}
