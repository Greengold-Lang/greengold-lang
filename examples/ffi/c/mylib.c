/* Greengold FFI example: a small C library. */
#include <stdlib.h>
#include <string.h>

typedef struct Vec2 {
    double x;
    double y;
} Vec2;

int my_add(int a, int b) { return a + b; }

/* sum of array: pointer + length */
long long my_sum(const int *data, size_t n) {
    long long s = 0;
    for (size_t i = 0; i < n; i++) s += data[i];
    return s;
}

/* multiply array in-place by 2 */
void my_double_all(int *data, size_t n) {
    for (size_t i = 0; i < n; i++) data[i] *= 2;
}

/* take struct by pointer and mutate it */
void vec2_scale(Vec2 *v, double k) {
    v->x *= k;
    v->y *= k;
}

double vec2_dot(const Vec2 *a, const Vec2 *b) { return a->x * b->x + a->y * b->y; }

/* returns a C-owned string */
const char *my_greeting(void) { return "Hello from C!"; }

/* returns malloc'd memory; caller frees with `my_free` */
int *my_alloc_ints(size_t n) {
    int *p = (int *)malloc(n * sizeof(int));
    for (size_t i = 0; i < n; i++) p[i] = (int)(i * i);
    return p;
}

void my_free(void *p) { free(p); }
