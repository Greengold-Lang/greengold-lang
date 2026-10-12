fn advance(
    x: &mut [f64], y: &mut [f64], z: &mut [f64],
    vx: &mut [f64], vy: &mut [f64], vz: &mut [f64],
    mass: &[f64], n: usize,
) {
    let mut i = 0usize;
    while i < n {
        let mut j = i + 1;
        while j < n {
            let dx = x[i] - x[j];
            let dy = y[i] - y[j];
            let dz = z[i] - z[j];
            let dist2 = dx * dx + dy * dy + dz * dz + 0.05;
            let inv = 1.0 / dist2.sqrt();
            let scale = inv * inv * inv * 0.01;
            let mi = mass[i];
            let mj = mass[j];
            vx[i] -= dx * mj * scale;
            vy[i] -= dy * mj * scale;
            vz[i] -= dz * mj * scale;
            vx[j] += dx * mi * scale;
            vy[j] += dy * mi * scale;
            vz[j] += dz * mi * scale;
            j += 1;
        }
        i += 1;
    }
    for k in 0..n {
        x[k] += vx[k] * 0.01;
        y[k] += vy[k] * 0.01;
        z[k] += vz[k] * 0.01;
    }
}

fn main() {
    let n = 768usize;
    let mut x = vec![0.0; n];
    let mut y = vec![0.0; n];
    let mut z = vec![0.0; n];
    let mut vx = vec![0.0; n];
    let mut vy = vec![0.0; n];
    let mut vz = vec![0.0; n];
    let mut mass = vec![0.0; n];
    for i in 0..n {
        let ang = (i as f64) * 0.17;
        x[i] = ang.cos() * (1.0 + ((i % 9) as f64) * 0.03);
        y[i] = ang.sin() * (1.0 + ((i % 5) as f64) * 0.02);
        z[i] = ((i % 7) as f64) * 0.02;
        vx[i] = ang.sin() * 0.01;
        vy[i] = ang.cos() * 0.01;
        mass[i] = 0.2 + ((i % 5) as f64) * 0.15;
    }
    for _ in 0..160 {
        advance(&mut x, &mut y, &mut z, &mut vx, &mut vy, &mut vz, &mass, n);
    }
    let mut sx = 0.0;
    let mut sy = 0.0;
    let mut sz = 0.0;
    for i in 0..n {
        sx += x[i];
        sy += y[i];
        sz += z[i];
    }
    println!("{}", (sx * 1000.0) as i64);
    println!("{}", (sy * 1000.0) as i64);
    println!("{}", (sz * 1000.0) as i64);
}
