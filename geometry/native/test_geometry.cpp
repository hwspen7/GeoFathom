#include "geometry.h"

#include <cassert>
#include <iostream>
#include <vector>

int main() {
    // A simple square in longitude/latitude, with the closing point included.
    constexpr double ring[] = {
        0.0, 0.0, 2.0, 0.0, 2.0, 2.0, 0.0, 2.0, 0.0, 0.0
    };
    assert(gf_contains_ring(ring, 5, 1.0, 1.0) == 1);
    assert(gf_contains_ring(ring, 5, 3.0, 1.0) == 0);
    assert(gf_contains_ring(ring, 5, 0.0, 1.0) == 0);
    assert(gf_contains_ring(nullptr, 5, 1.0, 1.0) == 0);

    constexpr double a[] = {0.0, 0.0, 2.0, 2.0};
    constexpr double adjacent[] = {2.0, 1.0, 4.0, 3.0};
    constexpr double remote[] = {3.0, 3.0, 4.0, 4.0};
    assert(gf_bbox_overlaps(a, adjacent) == 1);
    assert(gf_bbox_overlaps(a, remote) == 0);
    assert(gf_bbox_overlaps(nullptr, remote) == 0);
    std::cout << "GeoFathom native geometry checks passed" << std::endl;
    // The selected 3x3 block must remain isolated from its background.
    std::vector<unsigned char> rgb(8 * 8 * 3, 0);
    for (int y = 2; y < 5; ++y) {
        for (int x = 2; x < 5; ++x) {
            const int p = 3 * (y * 8 + x);
            rgb[p] = 150;
            rgb[p + 1] = 90;
            rgb[p + 2] = 40;
        }
    }
    std::vector<unsigned char> mask(8 * 8);
    assert(gf_seeded_rgb_region(rgb.data(), 8, 8, 3, 3, 5, mask.data()) == 9);
    assert(mask[3 * 8 + 3] == 1);
    assert(mask[0] == 0);
    assert(gf_seeded_rgb_region(rgb.data(), 8, 8, -1, 3, 5, mask.data()) == -1);
    assert(gf_seeded_rgb_region(nullptr, 8, 8, 3, 3, 5, mask.data()) == -1);
    return 0;
}
