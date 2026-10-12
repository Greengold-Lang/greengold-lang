// Inference-style matrix products on the GPU through OpenCL: 4096 token vectors of width 2048 go through 8
// dense layers (f32 weights, ReLU, then requantized to integers 0..127 as an int8 model does).
// OpenCL is loaded at run time, so nothing extra is linked and no OpenCL headers are needed.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

static const size_t TOKENS = 4096;
static const size_t WIDTH = 2048;
static const size_t LAYERS = 8;
static const size_t TILE = 16;

static const char* KERNEL = R"(#define TILE 16
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
)";

typedef void* H;
typedef int32_t (*GetPlatformIDs)(uint32_t, H*, uint32_t*);
typedef int32_t (*GetDeviceIDs)(H, uint64_t, uint32_t, H*, uint32_t*);
typedef H (*CreateContext)(const void*, uint32_t, const H*, void*, void*, int32_t*);
typedef H (*CreateCommandQueue)(H, H, uint64_t, int32_t*);
typedef H (*CreateProgramWithSource)(H, uint32_t, const char**, const size_t*, int32_t*);
typedef int32_t (*BuildProgram)(H, uint32_t, const H*, const char*, void*, void*);
typedef H (*CreateKernel)(H, const char*, int32_t*);
typedef H (*CreateBuffer)(H, uint64_t, size_t, void*, int32_t*);
typedef int32_t (*SetKernelArg)(H, uint32_t, size_t, const void*);
typedef int32_t (*EnqueueNDRangeKernel)(H, H, uint32_t, const size_t*, const size_t*, const size_t*, uint32_t,
                                        const void*, void*);
typedef int32_t (*EnqueueReadBuffer)(H, H, uint32_t, size_t, size_t, void*, uint32_t, const void*, void*);
typedef int32_t (*Finish)(H);

static void* lib;

static void* sym(const char* name) {
#ifdef _WIN32
    void* p = (void*)GetProcAddress((HMODULE)lib, name);
#else
    void* p = dlsym(lib, name);
#endif
    if (!p) {
        fprintf(stderr, "OpenCL function missing: %s\n", name);
        exit(1);
    }
    return p;
}

static void check(int32_t code, const char* what) {
    if (code != 0) {
        fprintf(stderr, "%s failed: %d\n", what, code);
        exit(1);
    }
}

// The same linear congruential generator as the Greengold and Rust versions.
static uint64_t next(uint64_t& state) {
    state = (state * 1103515245 + 12345) % 2147483648ULL;
    return state >> 16;
}

int main() {
#ifdef _WIN32
    lib = (void*)LoadLibraryA("OpenCL.dll");
#elif defined(__APPLE__)
    lib = dlopen("/System/Library/Frameworks/OpenCL.framework/OpenCL", RTLD_NOW);
#else
    lib = dlopen("libOpenCL.so.1", RTLD_NOW);
#endif
    if (!lib) {
        fprintf(stderr, "OpenCL is not installed\n");
        return 1;
    }
    auto get_platforms = (GetPlatformIDs)sym("clGetPlatformIDs");
    auto get_devices = (GetDeviceIDs)sym("clGetDeviceIDs");
    auto create_context = (CreateContext)sym("clCreateContext");
    auto create_queue = (CreateCommandQueue)sym("clCreateCommandQueue");
    auto create_program = (CreateProgramWithSource)sym("clCreateProgramWithSource");
    auto build_program = (BuildProgram)sym("clBuildProgram");
    auto create_kernel = (CreateKernel)sym("clCreateKernel");
    auto create_buffer = (CreateBuffer)sym("clCreateBuffer");
    auto set_arg = (SetKernelArg)sym("clSetKernelArg");
    auto enqueue_kernel = (EnqueueNDRangeKernel)sym("clEnqueueNDRangeKernel");
    auto read_buffer = (EnqueueReadBuffer)sym("clEnqueueReadBuffer");
    auto finish = (Finish)sym("clFinish");

    H platform = nullptr, device = nullptr;
    uint32_t count = 0;
    int32_t err = 0;
    check(get_platforms(1, &platform, &count), "clGetPlatformIDs");
    check(get_devices(platform, 4, 1, &device, &count), "clGetDeviceIDs (GPU)");
    H context = create_context(nullptr, 1, &device, nullptr, nullptr, &err);
    check(err, "clCreateContext");
    H queue = create_queue(context, device, 0, &err);
    check(err, "clCreateCommandQueue");

    H program = create_program(context, 1, &KERNEL, nullptr, &err);
    check(err, "clCreateProgramWithSource");
    check(build_program(program, 1, &device, nullptr, nullptr, nullptr), "clBuildProgram");
    H kernel = create_kernel(program, "layer", &err);
    check(err, "clCreateKernel");

    uint64_t state = 1;
    std::vector<float> x;
    x.reserve(TOKENS * WIDTH);
    for (size_t i = 0; i < TOKENS * WIDTH; i++)
        x.push_back((float)(next(state) % 128));
    size_t bytes = TOKENS * WIDTH * 4;
    // CL_MEM_READ_WRITE | CL_MEM_COPY_HOST_PTR
    H cur = create_buffer(context, 33, bytes, x.data(), &err);
    check(err, "clCreateBuffer");
    H out = create_buffer(context, 1, bytes, nullptr, &err);
    check(err, "clCreateBuffer");

    size_t global[2] = {WIDTH, TOKENS};
    size_t local[2] = {TILE, TILE};
    int32_t k = (int32_t)WIDTH, n = (int32_t)WIDTH;
    for (size_t l = 0; l < LAYERS; l++) {
        std::vector<float> w;
        w.reserve(WIDTH * WIDTH);
        for (size_t i = 0; i < WIDTH * WIDTH; i++)
            w.push_back((float)((int64_t)(next(state) % 5) - 2));
        // CL_MEM_READ_ONLY | CL_MEM_COPY_HOST_PTR
        H weights = create_buffer(context, 36, WIDTH * WIDTH * 4, w.data(), &err);
        check(err, "clCreateBuffer");
        check(set_arg(kernel, 0, 8, &cur), "clSetKernelArg");
        check(set_arg(kernel, 1, 8, &weights), "clSetKernelArg");
        check(set_arg(kernel, 2, 8, &out), "clSetKernelArg");
        check(set_arg(kernel, 3, 4, &k), "clSetKernelArg");
        check(set_arg(kernel, 4, 4, &n), "clSetKernelArg");
        check(enqueue_kernel(queue, kernel, 2, nullptr, global, local, 0, nullptr, nullptr), "clEnqueueNDRangeKernel");
        check(finish(queue), "clFinish");
        H swap = cur;
        cur = out;
        out = swap;
    }

    std::vector<float> y(TOKENS * WIDTH, 0.0f);
    check(read_buffer(queue, cur, 1, 0, bytes, y.data(), 0, nullptr, nullptr), "clEnqueueReadBuffer");

    int64_t sum = 0, active = 0;
    for (size_t i = 0; i < TOKENS * WIDTH; i++) {
        int64_t v = (int64_t)y[i];
        sum += v;
        if (v != 0) active++;
    }
    printf("%lld\n%lld\n%lld\n", (long long)sum, (long long)active, (long long)y[TOKENS * WIDTH / 2 + 7]);
    return 0;
}
