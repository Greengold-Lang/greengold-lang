// Word frequency: build a 3,000,000-word text from a 20,000-word vocabulary (skewed toward
// short indices, like real text), split it on whitespace, count each word in a hash map, and
// sort the distinct words by count (then by word). Strings, slices, hashing, and sorting.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

int main() {
    const char* syl[] = {"ka", "lo", "mi", "ne", "ru", "sa", "to", "vi"};
    std::vector<std::string> vocab;
    for (uint64_t i = 0; i < 20000; i++) {
        std::string w;
        for (uint64_t k = i + 8; k > 0; k /= 8) w += syl[k % 8];
        vocab.push_back(w);
    }
    std::string text;
    uint64_t seed = 42;
    for (int i = 0; i < 3000000; i++) {
        seed = seed * 6364136223846793005ULL + 1442695040888963407ULL;
        uint64_t a = (seed >> 33) % 20000;
        seed = seed * 6364136223846793005ULL + 1442695040888963407ULL;
        uint64_t b = (seed >> 33) % (a + 1);
        text += vocab[b];
        text += ' ';
    }
    std::unordered_map<std::string_view, int64_t> counts;
    std::string_view t(text);
    size_t i = 0;
    while (i < t.size()) {
        while (i < t.size() && t[i] == ' ') i++;
        size_t start = i;
        while (i < t.size() && t[i] != ' ') i++;
        if (i > start) counts[t.substr(start, i - start)]++;
    }
    std::vector<std::pair<std::string_view, int64_t>> rows(counts.begin(), counts.end());
    std::sort(rows.begin(), rows.end(), [](const auto& x, const auto& y) {
        if (x.second != y.second) return x.second > y.second;
        return x.first < y.first;
    });
    auto& last = rows.back();
    printf("%zu %.*s %lld %.*s %lld %.*s %lld\n", rows.size(), (int)rows[0].first.size(), rows[0].first.data(),
           (long long)rows[0].second, (int)rows[1].first.size(), rows[1].first.data(), (long long)rows[1].second,
           (int)last.first.size(), last.first.data(), (long long)last.second);
}
