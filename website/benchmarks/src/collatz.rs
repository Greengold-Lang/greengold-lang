fn collatz(n: i64) -> i32 {
    let mut cur = n;
    let mut steps = 0;
    while cur > 1 {
        if cur % 2 == 0 {
            cur /= 2;
        } else {
            cur = 3 * cur + 1;
        }
        steps += 1;
    }
    steps
}

fn main() {
    let mut max_steps = 0;
    let mut best_n = 0;
    for i in 1..4000000i64 {
        let s = collatz(i);
        if s > max_steps {
            max_steps = s;
            best_n = i;
        }
    }
    println!("{}\n{}", best_n, max_steps);
}
