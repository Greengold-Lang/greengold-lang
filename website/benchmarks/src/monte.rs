fn next_u64(state: &mut u64) -> u64 {
    let mut x = *state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    *state = x;
    x.wrapping_mul(2685821657736338717)
}

fn unit(state: &mut u64) -> f64 {
    let bits = next_u64(state) >> 11;
    (bits as f64) / 9007199254740992.0
}

fn main() {
    let mut state: u64 = 88172645463325252;
    let mut hits = 0i64;
    let mut i = 0i32;
    while i < 120000000 {
        let x = unit(&mut state) * 2.0 - 1.0;
        let y = unit(&mut state) * 2.0 - 1.0;
        if x * x + y * y <= 1.0 {
            hits += 1;
        }
        i += 1;
    }
    println!("{hits}");
}
