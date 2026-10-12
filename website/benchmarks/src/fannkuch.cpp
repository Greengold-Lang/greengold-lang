#include <iostream>

int main() {
    const int n = 10;
    int perm[12] = {};
    int perm1[12] = {};
    int count[12] = {};
    for (int i = 0; i < 10; i++) perm1[i] = i;
    int max_flips = 0;
    int checksum = 0;
    int nperm = 0;
    int passes = 0;
    int r = n;
    while (true) {
        while (r != 1) {
            count[r - 1] = r;
            r -= 1;
        }
        if (perm1[0] != 0) {
            for (int i = 0; i < 10; i++) perm[i] = perm1[i];
            int flips = 0;
            int k = perm[0];
            while (k != 0) {
                int a = 0;
                int b = k;
                while (a < b) {
                    int tmp = perm[a];
                    perm[a] = perm[b];
                    perm[b] = tmp;
                    a += 1;
                    b -= 1;
                }
                flips += 1;
                k = perm[0];
            }
            if (flips > max_flips) max_flips = flips;
            if (nperm % 2 == 0) checksum += flips;
            else checksum -= flips;
        }
        bool advanced = false;
        bool restarted = false;
        while (!advanced) {
            if (r == n) {
                passes += 1;
                if (passes == 4) {
                    std::cout << checksum << "\n" << max_flips << "\n";
                    return 0;
                }
                for (int i = 0; i < 10; i++) perm1[i] = i;
                r = n;
                nperm = 0;
                restarted = true;
                break;
            }
            int p0 = perm1[0];
            int i = 0;
            while (i < r) {
                perm1[i] = perm1[i + 1];
                i += 1;
            }
            perm1[r] = p0;
            count[r] = count[r] - 1;
            if (count[r] > 0) advanced = true;
            else r += 1;
        }
        if (!restarted) nperm += 1;
    }
}
