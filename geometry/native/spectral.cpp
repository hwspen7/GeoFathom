#include "geometry.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>

namespace {
// Keep bounded C ABI calls independent of platform integer width. The
// high-level raster reader uses even smaller tile/window limits.
constexpr std::size_t kMaxPixels = 16U * 1024U * 1024U;
constexpr double kDenominatorEpsilon = 1e-9;
}

extern "C" GEOFATHOM_API int gf_spectral_normalized_difference(
    const float* first, const float* second, const unsigned char* valid,
    std::size_t count, float* out_index, unsigned char* out_valid) noexcept {
    if (!first || !second || !valid || !out_index || !out_valid ||
        count == 0 || count > kMaxPixels) return -1;
    int accepted = 0;
    for (std::size_t i = 0; i < count; ++i) {
        out_index[i] = 0.0f;
        out_valid[i] = 0;
        if (!valid[i] || !std::isfinite(first[i]) ||
            !std::isfinite(second[i])) continue;
        const double a = static_cast<double>(first[i]);
        const double b = static_cast<double>(second[i]);
        const double denominator = a + b;
        if (!std::isfinite(denominator) ||
            std::abs(denominator) <= kDenominatorEpsilon) continue;
        const double difference = (a - b) / denominator;
        if (!std::isfinite(difference)) continue;
        out_index[i] = static_cast<float>(
            std::clamp(difference, -1.0, 1.0));
        out_valid[i] = 1;
        ++accepted;
    }
    return accepted;
}

extern "C" GEOFATHOM_API int gf_spectral_change(
    const float* before_index, const unsigned char* before_valid,
    const float* after_index, const unsigned char* after_valid,
    std::size_t count, float threshold, unsigned char* out_class) noexcept {
    if (!before_index || !before_valid || !after_index || !after_valid ||
        !out_class || count == 0 || count > kMaxPixels ||
        !std::isfinite(threshold) || threshold <= 0.0f ||
        threshold >= 1.0f) return -1;
    int changed = 0;
    for (std::size_t i = 0; i < count; ++i) {
        out_class[i] = 0;
        if (!before_valid[i] || !after_valid[i] ||
            !std::isfinite(before_index[i]) ||
            !std::isfinite(after_index[i])) continue;
        const double delta = static_cast<double>(after_index[i]) -
                             static_cast<double>(before_index[i]);
        if (delta >= threshold) {
            out_class[i] = 1;  // Gain.
            ++changed;
        } else if (delta <= -threshold) {
            out_class[i] = 2;  // Loss.
            ++changed;
        }
    }
    return changed;
}
