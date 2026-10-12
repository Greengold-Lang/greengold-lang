#include <iostream>
#include <memory>

struct Tree {
    bool leaf;
    int value;
    std::unique_ptr<Tree> left;
    std::unique_ptr<Tree> right;
};

std::unique_ptr<Tree> build(int d) {
    auto t = std::make_unique<Tree>();
    if (d == 0) {
        t->leaf = true;
        t->value = 1;
        return t;
    }
    t->leaf = false;
    t->value = 0;
    t->left = build(d - 1);
    t->right = build(d - 1);
    return t;
}

int count(const Tree& t) {
    if (t.leaf) return t.value;
    return count(*t.left) + count(*t.right);
}

int main() {
    int total = 0;
    for (int i = 0; i < 80; i++) {
        auto t = build(16);
        total += count(*t);
    }
    std::cout << total << "\n";
    return 0;
}
