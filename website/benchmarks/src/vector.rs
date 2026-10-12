fn main() {
    let mut v = Vec::new();
    for i in 0..20000000i64 {
        v.push(i);
    }
    let mut total: i64 = 0;
    for x in &v {
        total += x;
    }
    println!("{}\n{}", v.len(), total);
}
