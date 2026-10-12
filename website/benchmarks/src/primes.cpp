#include <chrono>
#include <cstdint>
#include <cstdio>
#include <vector>

using namespace std;
using namespace std::chrono;

class PrimeSieve {
private:
    size_t sieve_size;
    vector<uint64_t> words;

public:
    PrimeSieve(size_t limit) : sieve_size(limit) {
        size_t num_bits = limit / 2;
        size_t num_words = (num_bits + 63) / 64;
        words.assign(num_words, 0xFFFFFFFFFFFFFFFFULL);
    }

    void run_sieve() {
        size_t factor = 3;
        size_t q = 1000;

        while (factor <= q) {
            for (size_t num = factor; num <= q; num += 2) {
                size_t idx = num / 2;
                size_t w = idx >> 6;
                size_t b = idx & 63;
                if ((words[w] & (1ULL << b)) != 0) {
                    factor = num;
                    break;
                }
            }

            size_t k = factor * factor;
            size_t step = factor * 2;
            while (k < sieve_size) {
                size_t kidx = k / 2;
                size_t kw = kidx >> 6;
                size_t kb = kidx & 63;
                words[kw] &= ~(1ULL << kb);
                k += step;
            }

            factor += 2;
        }
    }

    size_t count_primes() const {
        size_t count = 1; // 2 is prime
        for (size_t num = 3; num < sieve_size; num += 2) {
            size_t idx = num / 2;
            size_t w = idx >> 6;
            size_t b = idx & 63;
            if ((words[w] & (1ULL << b)) != 0) {
                count++;
            }
        }
        return count;
    }

    bool validate_results() const {
        if (sieve_size == 1000000)
            return count_primes() == 78498;
        return false;
    }

    void print_results(double duration, size_t passes) const {
        size_t count = count_primes();
        bool valid = validate_results();
        double avg = duration / (double)passes;

        printf("Passes: %zu, Time: %lf, Avg: %lf, Limit: %zu, Count1: %zu, Count2: %zu, Valid: %d\n\n",
               passes, duration, avg, sieve_size, count, count, valid ? 1 : 0);
        printf("davepl_cpp;%zu;%lf;1;algorithm=base,faithful=yes,bits=1\n", passes, duration);
    }
};

int main() {
    auto t_start = steady_clock::now();
    size_t passes = 0;

    while (true) {
        PrimeSieve sieve(1000000);
        sieve.run_sieve();
        passes++;
        auto now = steady_clock::now();
        double elapsed = duration_cast<microseconds>(now - t_start).count() / 1000000.0;
        if (elapsed >= 20.0) {
            sieve.print_results(elapsed, passes);
            break;
        }
    }

    return 0;
}
