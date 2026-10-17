// Quantized matrix-vector product (int8 weights x int8 vector, 64 passes); same algorithm as qmatvec.gg.
fn main() {
    const ROWS: usize = 4096;
    const COLS: usize = 4096;
    const PASSES: usize = 64;
    let mut w = vec![0i8; ROWS * COLS];
    let mut x = vec![0i8; COLS];
    let mut y = vec![0i32; ROWS];
    let mut state: u64 = 12345;
    for v in w.iter_mut() {
        state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        *v = (((state >> 33) % 255) as i64 - 127) as i8;
    }
    for (i, v) in x.iter_mut().enumerate() {
        *v = (((i * 37) % 255) as i64 - 127) as i8;
    }
    let mut total: i64 = 0;
    for p in 0..PASSES {
        for r in 0..ROWS {
            let row = &w[r * COLS..(r + 1) * COLS];
            let mut acc: i32 = 0;
            for c in 0..COLS {
                acc += row[c] as i32 * x[c] as i32;
            }
            y[r] = acc;
        }
        total += y[p % ROWS] as i64;
    }
    let sum: i64 = y.iter().map(|&v| v as i64).sum();
    println!("{}\n{}", total, sum);
}
