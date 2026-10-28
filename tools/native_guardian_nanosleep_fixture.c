/* Explicit trusted-local inert fixture; no runtime/build authenticity claim. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <time.h>

int main(int argc, char **argv) {
    if (argc != 2) return 64;
    char *end = NULL;
    errno = 0;
    double seconds = strtod(argv[1], &end);
    if (errno || end == argv[1] || *end || !isfinite(seconds) || seconds <= 0 || seconds > 60)
        return 64;
    struct timespec duration = {(time_t)seconds, 0};
    duration.tv_nsec = (long)((seconds - (double)duration.tv_sec) * 1000000000.0);
    while (nanosleep(&duration, &duration)) {
        if (errno != EINTR) return 65;
    }
    return 0;
}
