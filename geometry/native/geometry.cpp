#include "geometry.h"

#include <algorithm>
#include <cmath>

namespace {
bool on_segment(double x, double y, double x1, double y1,
                double x2, double y2) noexcept {
    const double dx = x2 - x1;
    const double dy = y2 - y1;
    const double cross = (x - x1) * dy - (y - y1) * dx;
    const double scale = std::max(1.0, std::abs(dx) + std::abs(dy));
    if (std::abs(cross) > 1e-12 * scale) {
        return false;
    }
    const double dot = (x - x1) * (x - x2) + (y - y1) * (y - y2);
    return dot <= 0.0;
}
}  // namespace

extern "C" int gf_contains_ring(const double* xy, std::size_t count,
                                  double x, double y) noexcept {
    if (!xy || count < 3 || !std::isfinite(x) || !std::isfinite(y)) {
        return 0;
    }
    bool inside = false;
    for (std::size_t i = 0, j = count - 1; i < count; j = i++) {
        const double xi = xy[2 * i];
        const double yi = xy[2 * i + 1];
        const double xj = xy[2 * j];
        const double yj = xy[2 * j + 1];
        if (!std::isfinite(xi) || !std::isfinite(yi) ||
            !std::isfinite(xj) || !std::isfinite(yj)) {
            return 0;
        }
        if (on_segment(x, y, xi, yi, xj, yj)) {
            return 0;
        }
        if ((yi > y) != (yj > y)) {
            const double crossing = xi + (y - yi) * (xj - xi) / (yj - yi);
            if (x < crossing) {
                inside = !inside;
            }
        }
    }
    return inside ? 1 : 0;
}

extern "C" int gf_bbox_overlaps(const double* a, const double* b) noexcept {
    if (!a || !b) {
        return 0;
    }
    for (int i = 0; i < 4; ++i) {
        if (!std::isfinite(a[i]) || !std::isfinite(b[i])) {
            return 0;
        }
    }
    if (a[0] > a[2] || a[1] > a[3] || b[0] > b[2] || b[1] > b[3]) {
        return 0;
    }
    return (a[0] <= b[2] && b[0] <= a[2] &&
            a[1] <= b[3] && b[1] <= a[3]) ? 1 : 0;
}
