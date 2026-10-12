fn mandel(cx: f64, cy: f64) -> i32 {
    let mut x = 0.0;
    let mut y = 0.0;
    let mut n = 0i32;
    while n < 80 {
        let xx = x * x;
        let yy = y * y;
        if xx + yy > 4.0 {
            return n;
        }
        y = 2.0 * x * y + cy;
        x = xx - yy + cx;
        n += 1;
    }
    80
}

fn main() {
    let width = 2048usize;
    let height = 2048usize;
    let mut inside = 0i32;
    for row in 0..height {
        let cy = -1.0 + 2.0 * (row as f64) / (height as f64);
        for col in 0..width {
            let cx = -1.5 + 2.0 * (col as f64) / (width as f64);
            if mandel(cx, cy) == 80 {
                inside += 1;
            }
        }
    }
    println!("{inside}");
}
