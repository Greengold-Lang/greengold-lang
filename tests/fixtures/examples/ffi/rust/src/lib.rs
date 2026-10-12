// Rust functions callable from Greengold: `#[no_mangle]` + `extern "C"`.
// Panics must not cross C boundary; we use `panic = "abort"` in Cargo.toml.

#[no_mangle]
pub extern "C" fn rs_add(a: i32, b: i32) -> i32 {
    a + b
}

/// Replaces `n` elements of `data` slice with their squares.
///
/// # Safety
/// `data` must point to `n` valid `i32` elements.
#[no_mangle]
pub unsafe extern "C" fn rs_square_all(data: *mut i32, n: usize) {
    for i in 0..n {
        let p = data.add(i);
        *p = *p * *p;
    }
}

#[repr(C)]
pub struct Vec2 {
    pub x: f64,
    pub y: f64,
}

/// # Safety
/// `v` must point to a valid `Vec2`.
#[no_mangle]
pub unsafe extern "C" fn rs_vec2_len(v: *const Vec2) -> f64 {
    let v = &*v;
    (v.x * v.x + v.y * v.y).sqrt()
}
