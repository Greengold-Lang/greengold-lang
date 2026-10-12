fn multiply(a: &[f64], b: &[f64], c: &mut [f64], n: usize) {
    for i in 0..n {
        for k in 0..n {
            let aik = a[i * n + k];
            let mut j = 0;
            while j < n {
                let idx = i * n + j;
                c[idx] += aik * b[k * n + j];
                j += 1;
            }
        }
    }
}

fn main() {
    let n = 1216usize;
    let cells = n * n;
    let mut a = Vec::with_capacity(cells);
    let mut b = Vec::with_capacity(cells);
    let mut c = Vec::with_capacity(cells);
    for i in 0..n {
        for j in 0..n {
            a.push(((i + j) % 17) as f64);
            b.push(((i * 3 + j) % 13) as f64);
            c.push(0.0);
        }
    }
    multiply(&a, &b, &mut c, n);
    let mut sum = 0.0f64;
    for i in 0..cells {
        sum += c[i];
    }
    println!("{}", sum as i64);
    println!("{}", c[0] as i64);
    println!("{}", c[cells - 1] as i64);
}
