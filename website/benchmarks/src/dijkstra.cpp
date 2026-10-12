#include <cstdint>
#include <iostream>
#include <vector>

int weight(size_t i, size_t j) {
    if (i == j) return 0;
    return (int)((i * 131 + j * 17) % 97 + 1);
}

long long search(std::vector<int>& dist, std::vector<uint8_t>& used, size_t n) {
    const int inf = 1000000000;
    for (size_t i = 0; i < n; i++) {
        dist[i] = inf;
        used[i] = 0;
    }
    dist[0] = 0;
    size_t placed = 0;
    while (placed < n) {
        size_t best = 0;
        int best_d = inf;
        bool found = false;
        for (size_t i = 0; i < n; i++) {
            if (used[i] == 0) {
                if (dist[i] < best_d) {
                    best_d = dist[i];
                    best = i;
                    found = true;
                }
            }
        }
        if (!found) {
            placed = n;
        } else {
            used[best] = 1;
            placed += 1;
            for (size_t j = 0; j < n; j++) {
                if (used[j] == 0 && best != j) {
                    int alt = dist[best] + weight(best, j);
                    if (alt < dist[j]) dist[j] = alt;
                }
            }
        }
    }
    long long sum = 0;
    for (size_t i = 0; i < n; i++) sum += (long long)dist[i];
    return sum;
}

int main() {
    const size_t n = 4000;
    std::vector<int> dist(n);
    std::vector<uint8_t> used(n);
    long long total = 0;
    for (int round = 0; round < 8; round++) total += search(dist, used, n);
    std::cout << total << "\n";
    return 0;
}
