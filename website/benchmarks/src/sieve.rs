fn sieve(limit: usize) -> usize {
    let mut is_prime = vec![1u8; limit];
    let mut p = 2;
    while p * p < limit {
        if is_prime[p] == 1 {
            let mut k = p * p;
            while k < limit {
                is_prime[k] = 0;
                k += p;
            }
        }
        p += 1;
    }
    let mut count = 0;
    for i in 2..limit {
        if is_prime[i] == 1 {
            count += 1;
        }
    }
    count
}

fn main() {
    println!("{}", sieve(8000000));
}
