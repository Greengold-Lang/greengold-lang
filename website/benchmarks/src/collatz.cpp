#include <iostream>
#include <cstdint>

int collatz(int64_t n) {
    int64_t cur = n;
    int steps = 0;
    while (cur > 1) {
        if (cur % 2 == 0) cur /= 2;
        else cur = 3 * cur + 1;
        steps++;
    }
    return steps;
}

int main() {
    int max_steps = 0;
    int64_t best_n = 0;
    for (int64_t i = 1; i < 4000000; i++) {
        int s = collatz(i);
        if (s > max_steps) {
            max_steps = s;
            best_n = i;
        }
    }
    std::cout << best_n << "\n" << max_steps << "\n";
    return 0;
}
