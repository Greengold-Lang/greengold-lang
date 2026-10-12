#include <iostream>

int mandel(double cx, double cy) {
    double x = 0.0;
    double y = 0.0;
    int n = 0;
    while (n < 80) {
        double xx = x * x;
        double yy = y * y;
        if (xx + yy > 4.0) return n;
        y = 2.0 * x * y + cy;
        x = xx - yy + cx;
        n += 1;
    }
    return 80;
}

int main() {
    const int width = 2048;
    const int height = 2048;
    int inside = 0;
    for (int row = 0; row < height; row++) {
        double cy = -1.0 + 2.0 * (double)row / (double)height;
        for (int col = 0; col < width; col++) {
            double cx = -1.5 + 2.0 * (double)col / (double)width;
            if (mandel(cx, cy) == 80) inside += 1;
        }
    }
    std::cout << inside << "\n";
    return 0;
}
