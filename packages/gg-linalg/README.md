# gg-linalg

Linear algebra without the heap, for flight software and control loops.

- `vec3.gg`: `Vec3` (add, dot, cross, norm, angle, lerp).
- `quat.gg`: `Quat` unit quaternions: axis-angle and Euler conversion, composition with `*`, rotating vectors, gyro integration, slerp.
- `mat.gg`: `Mat[R, C]` with the size in the type, `matmul` (the inner sizes must agree at compile time), transpose, determinant,
  inverse (Gauss-Jordan with pivoting; `None` for a singular matrix).
- `control.gg`: `Pid` (derivative on measurement, anti-windup) and `Kalman[N, M]` (predict and update, Joseph-form covariance).

Everything is stored in arrays, so it works with `--no-std` and `--forbid-heap`. Tests: `gg test packages/gg-linalg/tests`.
Not covered: sparse matrices, decompositions beyond the inverse, an extended or unscented Kalman filter.
