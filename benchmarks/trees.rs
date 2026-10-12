enum Tree {
    Leaf(i32),
    Node(Box<Tree>, Box<Tree>),
}

fn build(d: i32) -> Tree {
    if d == 0 {
        return Tree::Leaf(1);
    }
    Tree::Node(Box::new(build(d - 1)), Box::new(build(d - 1)))
}

fn count(t: &Tree) -> i32 {
    match t {
        Tree::Leaf(v) => *v,
        Tree::Node(left, right) => count(left) + count(right),
    }
}

fn main() {
    let mut total = 0i32;
    for _ in 0..80 {
        let t = build(16);
        total += count(&t);
    }
    println!("{total}");
}
