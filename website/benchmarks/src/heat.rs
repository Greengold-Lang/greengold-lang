fn jacobi(cur: &[f64], nxt: &mut [f64], n: usize) {
    let last = n - 1;
    for i in 1..last {
        for j in 1..last {
            let idx = i * n + j;
            nxt[idx] = 0.25 * (cur[(i - 1) * n + j] + cur[(i + 1) * n + j]
                + cur[i * n + (j - 1)] + cur[i * n + (j + 1)]);
        }
    }
}

fn main() {
    let n = 1024usize;
    let cells = n * n;
    let mut a = Vec::with_capacity(cells);
    let mut b = vec![0.0; cells];
    for i in 0..n {
        for j in 0..n {
            a.push(((i * 13 + j * 7) % 19) as f64);
        }
    }
    for _ in 0..160 {
        jacobi(&a, &mut b, n);
        jacobi(&b, &mut a, n);
    }
    let mut sum = 0.0;
    for i in 0..cells {
        sum += a[i];
    }
    println!("{}", (sum * 1000.0) as i64);
}
