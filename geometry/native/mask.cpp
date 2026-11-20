#include "geometry.h"

#include <algorithm>
#include <cstddef>
#include <cstring>
#include <vector>

extern "C" int gf_seeded_rgb_region(
    const unsigned char* rgb, int width, int height,
    int seed_x, int seed_y, int tolerance,
    unsigned char* mask) noexcept {
    if (!rgb || !mask || width <= 0 || height <= 0 ||
        width > 1024 || height > 1024 ||
        seed_x < 0 || seed_y < 0 ||
        seed_x >= width || seed_y >= height ||
        tolerance < 0 || tolerance > 255) {
        return -1;
    }

    try {
        const int size = width * height;
        std::memset(mask, 0, static_cast<std::size_t>(size));
        const int seed = seed_y * width + seed_x;
        const int r = rgb[3 * seed];
        const int g = rgb[3 * seed + 1];
        const int b = rgb[3 * seed + 2];
        // Region grows against the original seed color. It cannot drift across
        // a gradual gradient into unrelated features.
        std::vector<int> queue;
        queue.reserve(static_cast<std::size_t>(std::min(size, 4096)));
        queue.push_back(seed);
        mask[seed] = 1;
        std::size_t head = 0;
        while (head < queue.size()) {
            const int current = queue[head++];
            const int x = current % width;
            const int y = current / width;
            const int neighbors[4] = {
                x > 0 ? current - 1 : -1,
                x + 1 < width ? current + 1 : -1,
                y > 0 ? current - width : -1,
                y + 1 < height ? current + width : -1,
            };
            for (int neighbor : neighbors) {
                if (neighbor < 0 || mask[neighbor]) {
                    continue;
                }
                const int offset = neighbor * 3;
                if (std::abs(static_cast<int>(rgb[offset]) - r) > tolerance ||
                    std::abs(static_cast<int>(rgb[offset + 1]) - g) > tolerance ||
                    std::abs(static_cast<int>(rgb[offset + 2]) - b) > tolerance) {
                    continue;
                }
                mask[neighbor] = 1;
                queue.push_back(neighbor);
            }
        }
        return static_cast<int>(queue.size());
    } catch (...) {
        return -1;
    }
}
