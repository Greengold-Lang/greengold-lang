fn lcg(s: u32) -> u32 {
    s.wrapping_mul(1664525).wrapping_add(1013904223)
}

fn mix(data: &[u8], salt: u64) -> u64 {
    let mut h = 14695981039346656037u64 ^ salt;
    for b in data {
        h = (h ^ (*b as u64)).wrapping_mul(1099511628211);
    }
    h
}

fn main() {
    let mut data = Vec::with_capacity(8000000);
    let mut state = 1u32;
    for _ in 0..8000000 {
        state = lcg(state);
        data.push((state >> 24) as u8);
    }
    let mut acc = 0u64;
    for round in 0..40u64 {
        acc ^= mix(&data, round);
    }
    println!("{acc}");
}
