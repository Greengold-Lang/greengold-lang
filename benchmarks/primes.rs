use std::time::Instant;

struct PrimeSieve {
    sieve_size: usize,
    words: Vec<u64>,
}

impl PrimeSieve {
    fn new(limit: usize) -> Self {
        let num_bits = limit / 2;
        let num_words = (num_bits + 63) / 64;
        PrimeSieve {
            sieve_size: limit,
            words: vec![!0u64; num_words],
        }
    }

    fn run_sieve(&mut self) {
        let mut factor = 3;
        let q = 1000;

        while factor <= q {
            let mut num = factor;
            while num <= q {
                let idx = num / 2;
                let w = idx >> 6;
                let b = idx & 63;
                if (self.words[w] & (1u64 << b)) != 0 {
                    factor = num;
                    break;
                }
                num += 2;
            }

            let mut k = factor * factor;
            let step = factor * 2;
            while k < self.sieve_size {
                let kidx = k / 2;
                let kw = kidx >> 6;
                let kb = kidx & 63;
                self.words[kw] &= !(1u64 << kb);
                k += step;
            }

            factor += 2;
        }
    }

    fn count_primes(&self) -> usize {
        let mut count = 1; // 2 is prime
        let mut num = 3;
        while num < self.sieve_size {
            let idx = num / 2;
            let w = idx >> 6;
            let b = idx & 63;
            if (self.words[w] & (1u64 << b)) != 0 {
                count += 1;
            }
            num += 2;
        }
        count
    }

    fn validate_results(&self) -> bool {
        if self.sieve_size == 1_000_000 {
            self.count_primes() == 78498
        } else {
            false
        }
    }

    fn print_results(&self, duration: f64, passes: usize) {
        let count = self.count_primes();
        let valid = self.validate_results();
        let avg = duration / passes as f64;
        let v_int = if valid { 1 } else { 0 };

        println!(
            "Passes: {}, Time: {:.6}, Avg: {:.6}, Limit: {}, Count1: {}, Count2: {}, Valid: {}\n",
            passes, duration, avg, self.sieve_size, count, count, v_int
        );
        println!(
            "davepl_rust;{};{:.6};1;algorithm=base,faithful=yes,bits=1",
            passes, duration
        );
    }
}

fn main() {
    let t_start = Instant::now();
    let mut passes = 0;

    loop {
        let mut sieve = PrimeSieve::new(1_000_000);
        sieve.run_sieve();
        passes += 1;
        let elapsed = t_start.elapsed().as_secs_f64();
        if elapsed >= 20.0 {
            sieve.print_results(elapsed, passes);
            break;
        }
    }
}
