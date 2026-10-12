#include <iostream>

int fib(int n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}

int main(int argc, char** argv) {
    int n = argc > 1 ? std::stoi(argv[1]) : 41;
    std::cout << fib(n) << "\n";
    return 0;
}
