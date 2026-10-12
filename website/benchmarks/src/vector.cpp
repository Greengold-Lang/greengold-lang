#include <iostream>
#include <vector>
#include <cstdint>

int main() {
    std::vector<int64_t> v;
    for (int64_t i = 0; i < 20000000; i++) {
        v.push_back(i);
    }
    int64_t total = 0;
    for (auto x : v) {
        total += x;
    }
    std::cout << v.size() << "\n" << total << "\n";
    return 0;
}
