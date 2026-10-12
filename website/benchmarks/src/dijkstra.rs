fn weight(i: usize, j: usize) -> i32 {
    if i == j {
        return 0;
    }
    ((i * 131 + j * 17) % 97 + 1) as i32
}

fn search(dist: &mut [i32], used: &mut [u8], n: usize) -> i64 {
    let inf = 1000000000i32;
    for i in 0..n {
        dist[i] = inf;
        used[i] = 0;
    }
    dist[0] = 0;
    let mut placed = 0usize;
    while placed < n {
        let mut best = 0usize;
        let mut best_d = inf;
        let mut found = false;
        for i in 0..n {
            if used[i] == 0 && dist[i] < best_d {
                best_d = dist[i];
                best = i;
                found = true;
            }
        }
        if !found {
            placed = n;
        } else {
            used[best] = 1;
            placed += 1;
            for j in 0..n {
                if used[j] == 0 && best != j {
                    let alt = dist[best] + weight(best, j);
                    if alt < dist[j] {
                        dist[j] = alt;
                    }
                }
            }
        }
    }
    let mut sum = 0i64;
    for i in 0..n {
        sum += dist[i] as i64;
    }
    sum
}

fn main() {
    let n = 4000usize;
    let mut dist = vec![0i32; n];
    let mut used = vec![0u8; n];
    let mut total = 0i64;
    for _ in 0..8 {
        total += search(&mut dist, &mut used, n);
    }
    println!("{total}");
}
