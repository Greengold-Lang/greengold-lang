#include <cstdint>
#include <iostream>
#include <vector>

uint32_t lcg(uint32_t s) {
    return s * 1664525u + 1013904223u;
}

uint64_t mix(const std::vector<uint8_t>& data, uint64_t salt) {
    uint64_t h = 14695981039346656037ULL ^ salt;
    for (uint8_t b : data) {
        h ^= (uint64_t)b;
        h *= 1099511628211ULL;
    }
    return h;
}

int main() {
    std::vector<uint8_t> data;
    data.reserve(8000000);
    uint32_t state = 1;
    for (int i = 0; i < 8000000; i++) {
        state = lcg(state);
        data.push_back((uint8_t)(state >> 24));
    }
    uint64_t acc = 0;
    for (int round = 0; round < 40; round++) {
        acc ^= mix(data, (uint64_t)round);
    }
    std::cout << acc << "\n";
    return 0;
}
