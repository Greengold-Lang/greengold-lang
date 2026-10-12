#include <cstdint>
#include <iostream>

uint64_t next_u64(uint64_t& state) {
    uint64_t x = state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    state = x;
    return x * 2685821657736338717ULL;
}

double unit(uint64_t& state) {
    uint64_t bits = next_u64(state) >> 11;
    return (double)bits / 9007199254740992.0;
}

int main() {
    uint64_t state = 88172645463325252ULL;
    long long hits = 0;
    for (int i = 0; i < 120000000; i++) {
        double x = unit(state) * 2.0 - 1.0;
        double y = unit(state) * 2.0 - 1.0;
        if (x * x + y * y <= 1.0) hits += 1;
    }
    std::cout << hits << "\n";
    return 0;
}
