// Structure of arrays: one Vec per field, the layout `soa Array[Particle, N]` gives Greengold.
// The loops use zip so the compiler needs no bounds checks.
const N: usize = 20000;

fn update(steps: usize) -> f32 {
    let mut x = vec![0.0f32; N];
    let mut y = vec![0.0f32; N];
    let vx = vec![1.0f32; N];
    let vy = vec![2.0f32; N];
    for i in 0..N {
        x[i] = (i as f32) * 0.1;
        y[i] = (i as f32) * 0.2;
    }
    for _ in 0..steps {
        for (a, b) in x.iter_mut().zip(vx.iter()) {
            *a += *b;
        }
        for (a, b) in y.iter_mut().zip(vy.iter()) {
            *a += *b;
        }
    }
    let mut total = 0.0f32;
    for a in x.iter() {
        total += *a;
    }
    total
}

fn main() {
    println!("{}", update(2000));
}
