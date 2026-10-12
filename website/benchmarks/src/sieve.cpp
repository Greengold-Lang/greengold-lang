#include <iostream>
#include <vector>
#include <cstdint>

size_t sieve(size_t limit) {
    std::vector<uint8_t> is_prime(limit, 1);
    size_t p = 2;
    while (p * p < limit) {
        if (is_prime[p] == 1) {
            size_t k = p * p;
            while (k < limit) {
                is_prime[k] = 0;
                k += p;
            }
        }
        p++;
    }
    size_t count = 0;
    for (size_t i = 2; i < limit; i++) {
        if (is_prime[i] == 1) count++;
    }
    return count;
}

int main() {
    std::cout << sieve(8000000) << "\n";
    return 0;
}
