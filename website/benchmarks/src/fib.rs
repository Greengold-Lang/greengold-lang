use std::env;

fn fib(n: i32) -> i32 {
    if n < 2 {
        return n;
    }
    fib(n - 1) + fib(n - 2)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let n: i32 = if args.len() > 1 { args[1].parse().unwrap() } else { 41 };
    println!("{}", fib(n));
}
