fn main() {
    let n = 10;
    let mut perm = [0i32; 12];
    let mut perm1 = [0i32; 12];
    let mut count = [0i32; 12];
    for i in 0..10 {
        perm1[i] = i as i32;
    }
    let mut max_flips = 0i32;
    let mut checksum = 0i32;
    let mut nperm = 0i32;
    let mut passes = 0i32;
    let mut r = n;
    loop {
        while r != 1 {
            count[(r - 1) as usize] = r;
            r -= 1;
        }
        if perm1[0] != 0 {
            for i in 0..10 {
                perm[i] = perm1[i];
            }
            let mut flips = 0i32;
            let mut k = perm[0];
            while k != 0 {
                let mut a = 0i32;
                let mut b = k;
                while a < b {
                    perm.swap(a as usize, b as usize);
                    a += 1;
                    b -= 1;
                }
                flips += 1;
                k = perm[0];
            }
            if flips > max_flips {
                max_flips = flips;
            }
            if nperm % 2 == 0 {
                checksum += flips;
            } else {
                checksum -= flips;
            }
        }
        let mut advanced = false;
        let mut restarted = false;
        while !advanced {
            if r == n {
                passes += 1;
                if passes == 4 {
                    println!("{checksum}");
                    println!("{max_flips}");
                    return;
                }
                for i in 0..10 {
                    perm1[i] = i as i32;
                }
                r = n;
                nperm = 0;
                restarted = true;
                break;
            }
            let p0 = perm1[0];
            let mut i = 0i32;
            while i < r {
                perm1[i as usize] = perm1[(i + 1) as usize];
                i += 1;
            }
            perm1[r as usize] = p0;
            count[r as usize] = count[r as usize] - 1;
            if count[r as usize] > 0 {
                advanced = true;
            } else {
                r += 1;
            }
        }
        if !restarted {
            nperm += 1;
        }
    }
}
