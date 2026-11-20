#include "geometry.h"

#include <cassert>
#include <iostream>

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
    return 0;
}
