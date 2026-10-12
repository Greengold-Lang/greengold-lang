// Inference-style matrix products on the GPU through OpenCL: 4096 token vectors of width 2048 go through 8
// dense layers (f32 weights, ReLU, then requantized to integers 0..127 as an int8 model does).
// OpenCL is loaded at run time, so no crate and no extra library is needed.
use std::ffi::c_void;
use std::process::exit;

const TOKENS: usize = 4096;
const WIDTH: usize = 2048;
const LAYERS: usize = 8;
const TILE: usize = 16;

const KERNEL: &str = "#define TILE 16
__kernel void layer(__global const float* x, __global const float* w, __global float* y, int k, int n) {
    __local float xs[TILE][TILE];
    __local float ws[TILE][TILE];
    int col = get_global_id(0);
    int row = get_global_id(1);
    int lc = get_local_id(0);
    int lr = get_local_id(1);
    float acc = 0.0f;
    for (int t = 0; t < k; t += TILE) {
        xs[lr][lc] = x[row * k + t + lc];
        ws[lr][lc] = w[(t + lr) * n + col];
        barrier(CLK_LOCAL_MEM_FENCE);
        for (int i = 0; i < TILE; i++)
            acc += xs[lr][i] * ws[i][lc];
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    y[row * n + col] = fmin(floor(fmax(acc, 0.0f) / 32.0f), 127.0f);
}
\0";

type H = *mut c_void;

#[cfg(windows)]
extern "system" {
    fn LoadLibraryA(name: *const u8) -> H;
    fn GetProcAddress(lib: H, name: *const u8) -> H;
}

#[cfg(unix)]
extern "C" {
    fn dlopen(name: *const u8, flags: i32) -> H;
    fn dlsym(lib: H, name: *const u8) -> H;
}

#[cfg(windows)]
unsafe fn open_opencl() -> H {
    LoadLibraryA(b"OpenCL.dll\0".as_ptr())
}

#[cfg(target_os = "macos")]
unsafe fn open_opencl() -> H {
    dlopen(b"/System/Library/Frameworks/OpenCL.framework/OpenCL\0".as_ptr(), 2)
}

#[cfg(all(unix, not(target_os = "macos")))]
unsafe fn open_opencl() -> H {
    dlopen(b"libOpenCL.so.1\0".as_ptr(), 2)
}

unsafe fn sym(lib: H, name: &[u8]) -> H {
    #[cfg(windows)]
    let p = GetProcAddress(lib, name.as_ptr());
    #[cfg(unix)]
    let p = dlsym(lib, name.as_ptr());
    if p.is_null() {
        eprintln!("OpenCL function missing");
        exit(1);
    }
    p
}

fn check(code: i32, what: &str) {
    if code != 0 {
        eprintln!("{} failed: {}", what, code);
        exit(1);
    }
}

// The same linear congruential generator as the Greengold and C++ versions.
fn next(state: &mut u64) -> u64 {
    *state = (*state * 1103515245 + 12345) % 2147483648;
    *state >> 16
}

fn main() {
    unsafe {
        let lib = open_opencl();
        if lib.is_null() {
            eprintln!("OpenCL is not installed");
            exit(1);
        }
        let get_platforms: extern "system" fn(u32, *mut H, *mut u32) -> i32 =
            std::mem::transmute(sym(lib, b"clGetPlatformIDs\0"));
        let get_devices: extern "system" fn(H, u64, u32, *mut H, *mut u32) -> i32 =
            std::mem::transmute(sym(lib, b"clGetDeviceIDs\0"));
        let create_context: extern "system" fn(*const c_void, u32, *const H, H, H, *mut i32) -> H =
            std::mem::transmute(sym(lib, b"clCreateContext\0"));
        let create_queue: extern "system" fn(H, H, u64, *mut i32) -> H =
            std::mem::transmute(sym(lib, b"clCreateCommandQueue\0"));
        let create_program: extern "system" fn(H, u32, *const *const u8, *const usize, *mut i32) -> H =
            std::mem::transmute(sym(lib, b"clCreateProgramWithSource\0"));
        let build_program: extern "system" fn(H, u32, *const H, *const u8, H, H) -> i32 =
            std::mem::transmute(sym(lib, b"clBuildProgram\0"));
        let create_kernel: extern "system" fn(H, *const u8, *mut i32) -> H =
            std::mem::transmute(sym(lib, b"clCreateKernel\0"));
        let create_buffer: extern "system" fn(H, u64, usize, *const c_void, *mut i32) -> H =
            std::mem::transmute(sym(lib, b"clCreateBuffer\0"));
        let set_arg: extern "system" fn(H, u32, usize, *const c_void) -> i32 =
            std::mem::transmute(sym(lib, b"clSetKernelArg\0"));
        let enqueue_kernel: extern "system" fn(H, H, u32, *const usize, *const usize, *const usize, u32,
                                               *const c_void, H) -> i32 =
            std::mem::transmute(sym(lib, b"clEnqueueNDRangeKernel\0"));
        let read_buffer: extern "system" fn(H, H, u32, usize, usize, *mut c_void, u32, *const c_void, H) -> i32 =
            std::mem::transmute(sym(lib, b"clEnqueueReadBuffer\0"));
        let finish: extern "system" fn(H) -> i32 = std::mem::transmute(sym(lib, b"clFinish\0"));

        let null: H = std::ptr::null_mut();
        let mut platform: H = null;
        let mut device: H = null;
        let mut count: u32 = 0;
        let mut err: i32 = 0;
        check(get_platforms(1, &mut platform, &mut count), "clGetPlatformIDs");
        check(get_devices(platform, 4, 1, &mut device, &mut count), "clGetDeviceIDs (GPU)");
        let context = create_context(std::ptr::null(), 1, &device, null, null, &mut err);
        check(err, "clCreateContext");
        let queue = create_queue(context, device, 0, &mut err);
        check(err, "clCreateCommandQueue");

        let source = KERNEL.as_ptr();
        let program = create_program(context, 1, &source, std::ptr::null(), &mut err);
        check(err, "clCreateProgramWithSource");
        check(build_program(program, 1, &device, std::ptr::null(), null, null), "clBuildProgram");
        let kernel = create_kernel(program, b"layer\0".as_ptr(), &mut err);
        check(err, "clCreateKernel");

        let mut state: u64 = 1;
        let mut x: Vec<f32> = Vec::with_capacity(TOKENS * WIDTH);
        for _ in 0..TOKENS * WIDTH {
            x.push((next(&mut state) % 128) as f32);
        }
        let bytes = TOKENS * WIDTH * 4;
        // CL_MEM_READ_WRITE | CL_MEM_COPY_HOST_PTR
        let mut cur = create_buffer(context, 33, bytes, x.as_ptr() as *const c_void, &mut err);
        check(err, "clCreateBuffer");
        let mut out = create_buffer(context, 1, bytes, std::ptr::null(), &mut err);
        check(err, "clCreateBuffer");

        let global: [usize; 2] = [WIDTH, TOKENS];
        let local: [usize; 2] = [TILE, TILE];
        let k = WIDTH as i32;
        let n = WIDTH as i32;
        for _ in 0..LAYERS {
            let mut w: Vec<f32> = Vec::with_capacity(WIDTH * WIDTH);
            for _ in 0..WIDTH * WIDTH {
                w.push(((next(&mut state) % 5) as i64 - 2) as f32);
            }
            // CL_MEM_READ_ONLY | CL_MEM_COPY_HOST_PTR
            let weights = create_buffer(context, 36, WIDTH * WIDTH * 4, w.as_ptr() as *const c_void, &mut err);
            check(err, "clCreateBuffer");
            check(set_arg(kernel, 0, 8, &cur as *const H as *const c_void), "clSetKernelArg");
            check(set_arg(kernel, 1, 8, &weights as *const H as *const c_void), "clSetKernelArg");
            check(set_arg(kernel, 2, 8, &out as *const H as *const c_void), "clSetKernelArg");
            check(set_arg(kernel, 3, 4, &k as *const i32 as *const c_void), "clSetKernelArg");
            check(set_arg(kernel, 4, 4, &n as *const i32 as *const c_void), "clSetKernelArg");
            check(enqueue_kernel(queue, kernel, 2, std::ptr::null(), global.as_ptr(), local.as_ptr(), 0,
                                 std::ptr::null(), null), "clEnqueueNDRangeKernel");
            check(finish(queue), "clFinish");
            std::mem::swap(&mut cur, &mut out);
        }

        let mut y = vec![0.0f32; TOKENS * WIDTH];
        check(read_buffer(queue, cur, 1, 0, bytes, y.as_mut_ptr() as *mut c_void, 0, std::ptr::null(), null),
              "clEnqueueReadBuffer");

        let mut sum: i64 = 0;
        let mut active: i64 = 0;
        for i in 0..TOKENS * WIDTH {
            let v = y[i] as i64;
            sum += v;
            if v != 0 {
                active += 1;
            }
        }
        println!("{}", sum);
        println!("{}", active);
        println!("{}", y[TOKENS * WIDTH / 2 + 7] as i64);
    }
}
