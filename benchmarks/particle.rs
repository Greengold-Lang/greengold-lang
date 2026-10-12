#[derive(Clone, Copy)]
struct Particle {
    x: f32,
    y: f32,
    vx: f32,
    vy: f32,
}

fn update(steps: usize) -> f32 {
    let mut ps = vec![Particle { x: 0.0, y: 0.0, vx: 1.0, vy: 2.0 }; 20000];
    for i in 0..20000 {
        ps[i].x = (i as f32) * 0.1;
        ps[i].y = (i as f32) * 0.2;
    }
    for _ in 0..steps {
        for i in 0..20000 {
            ps[i].x += ps[i].vx;
            ps[i].y += ps[i].vy;
        }
    }
    let mut total = 0.0f32;
    for i in 0..20000 {
        total += ps[i].x;
    }
    total
}

fn main() {
    println!("{}", update(2000));
}
