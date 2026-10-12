fn lcg(s: u32) -> u32 {
    s.wrapping_mul(1664525).wrapping_add(1013904223)
}

fn swap_at(a: &mut [i32], i: usize, j: usize) {
    let tmp = a[i];
    a[i] = a[j];
    a[j] = tmp;
}

fn insertion(a: &mut [i32], lo: usize, hi: usize) {
    if hi < lo + 2 {
        return;
    }
    let mut i = lo + 1;
    while i < hi {
        let mut j = i;
        while j > lo {
            if a[j] < a[j - 1] {
                swap_at(a, j, j - 1);
                j -= 1;
            } else {
                break;
            }
        }
        i += 1;
    }
}

fn partition(a: &mut [i32], lo: usize, hi: usize) -> usize {
    let mid = lo + (hi - lo) / 2;
    swap_at(a, mid, hi - 1);
    let pivot = a[hi - 1];
    let mut store = lo;
    let mut j = lo;
    while j < hi - 1 {
        if a[j] < pivot {
            swap_at(a, store, j);
            store += 1;
        }
        j += 1;
    }
    swap_at(a, store, hi - 1);
    store
}

fn qsort_range(a: &mut [i32]) {
    let n = a.len();
    if n < 2 {
        return;
    }
    let mut slo = vec![0usize];
    let mut shi = vec![n];
    while !slo.is_empty() {
        let lo = slo.pop().unwrap();
        let hi = shi.pop().unwrap();
        if hi - lo < 16 {
            insertion(a, lo, hi);
        } else {
            let p = partition(a, lo, hi);
            if p > lo {
                slo.push(lo);
                shi.push(p);
            }
            if p + 1 < hi {
                slo.push(p + 1);
                shi.push(hi);
            }
        }
    }
}

fn main() {
    let mut a = Vec::with_capacity(8000000);
    let mut state = 1u32;
    for _ in 0..8000000 {
        state = lcg(state);
        a.push((state & 2147483647u32) as i32);
    }
    qsort_range(&mut a);
    let mut sum = 0i64;
    let mut bad = 0i32;
    for i in 0..a.len() {
        sum += a[i] as i64;
        if i > 0 && a[i] < a[i - 1] {
            bad = 1;
        }
    }
    println!("{}", a[0]);
    println!("{}", a[4000000]);
    println!("{}", a[7999999]);
    println!("{sum}");
    println!("{bad}");
}
