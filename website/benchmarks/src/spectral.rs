fn aval(i: usize, j: usize) -> f64 {
    let ij = i + j;
    let den = ij * (ij + 1) / 2 + i + 1;
    1.0 / (den as f64)
}

fn apply(out: &mut [f64], v: &[f64], n: usize) {
    for i in 0..n {
        let mut sum = 0.0;
        let mut j = 0usize;
        while j < n {
            sum += aval(i, j) * v[j];
            j += 1;
        }
        out[i] = sum;
    }
}

fn main() {
    let n = 1600usize;
    let mut u = vec![1.0; n];
    let mut v = vec![0.0; n];
    for _ in 0..40 {
        apply(&mut v, &u, n);
        apply(&mut u, &v, n);
    }
    let mut uv = 0.0;
    let mut vv = 0.0;
    for i in 0..n {
        uv += u[i] * v[i];
        vv += v[i] * v[i];
    }
    let norm = (uv / vv).sqrt();
    println!("{}", (norm * 1000000000.0) as i64);
}
