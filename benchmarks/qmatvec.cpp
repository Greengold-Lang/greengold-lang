// Quantized matrix-vector product (int8 weights x int8 vector, 64 passes); same algorithm as qmatvec.gg.
#include <cstdint>
#include <cstdio>
#include <vector>
int main() {
    const size_t ROWS = 4096, COLS = 4096, PASSES = 64;
    std::vector<int8_t> w(ROWS * COLS), x(COLS);
    std::vector<int32_t> y(ROWS, 0);
    uint64_t state = 12345;
    for (size_t i = 0; i < ROWS * COLS; i++) {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        w[i] = (int8_t)((int64_t)((state >> 33) % 255) - 127);
    }
    for (size_t i = 0; i < COLS; i++) x[i] = (int8_t)((int64_t)((i * 37) % 255) - 127);
    int64_t total = 0;
    for (size_t p = 0; p < PASSES; p++) {
        for (size_t r = 0; r < ROWS; r++) {
            const int8_t* row = &w[r * COLS];
            int32_t acc = 0;
            for (size_t c = 0; c < COLS; c++) acc += (int32_t)row[c] * (int32_t)x[c];
            y[r] = acc;
        }
        total += y[p % ROWS];
    }
    int64_t sum = 0;
    for (size_t i = 0; i < ROWS; i++) sum += y[i];
    printf("%lld\n%lld\n", (long long)total, (long long)sum);
}
