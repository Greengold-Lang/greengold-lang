// Word frequency: build a 3,000,000-word text from a 20,000-word vocabulary (skewed toward
// short indices, like real text), split it on whitespace, count each word in a hash map, and
// sort the distinct words by count (then by word). Strings, slices, hashing, and sorting.
use std::collections::HashMap;

fn main() {
    let syl = ["ka", "lo", "mi", "ne", "ru", "sa", "to", "vi"];
    let mut vocab: Vec<String> = Vec::new();
    for i in 0..20000u64 {
        let mut w = String::new();
        let mut k = i + 8;
        while k > 0 {
            w.push_str(syl[(k % 8) as usize]);
            k /= 8;
        }
        vocab.push(w);
    }
    let mut text = String::new();
    let mut seed: u64 = 42;
    for _ in 0..3000000 {
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        let a = (seed >> 33) % 20000;
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        let b = (seed >> 33) % (a + 1);
        text.push_str(&vocab[b as usize]);
        text.push(' ');
    }
    let mut counts: HashMap<&str, i64> = HashMap::new();
    for w in text.split_whitespace() {
        *counts.entry(w).or_insert(0) += 1;
    }
    let mut rows: Vec<(&str, i64)> = counts.into_iter().collect();
    rows.sort_by(|x, y| y.1.cmp(&x.1).then(x.0.cmp(y.0)));
    let last = rows[rows.len() - 1];
    println!("{} {} {} {} {} {} {}", rows.len(), rows[0].0, rows[0].1, rows[1].0, rows[1].1, last.0, last.1);
}
