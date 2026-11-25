#include "geometry.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

namespace {
struct Point { double x, y; };

Point point_at(const double* xy, std::size_t index) noexcept {
    return {xy[2 * index], xy[2 * index + 1]};
}

bool finite(Point p) noexcept {
    return std::isfinite(p.x) && std::isfinite(p.y);
}

double squared_distance(Point p, Point q) noexcept {
    const double dx = p.x - q.x;
    const double dy = p.y - q.y;
    return dx * dx + dy * dy;
}

Point projected(Point p, Point a, Point b) noexcept {
    const double dx = b.x - a.x;
    const double dy = b.y - a.y;
    const double length2 = dx * dx + dy * dy;
    if (length2 == 0.0) return a;
    const double t = std::clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / length2, 0.0, 1.0);
    return {a.x + t * dx, a.y + t * dy};
}

double cross(Point a, Point b, Point c) noexcept {
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
}

bool on_segment(Point a, Point b, Point p) noexcept {
    return std::abs(cross(a, b, p)) < 1e-10 &&
        p.x >= std::min(a.x,b.x) - 1e-10 && p.x <= std::max(a.x,b.x) + 1e-10 &&
        p.y >= std::min(a.y,b.y) - 1e-10 && p.y <= std::max(a.y,b.y) + 1e-10;
}

int sign(double x) noexcept { return x > 1e-10 ? 1 : (x < -1e-10 ? -1 : 0); }

bool intersects(Point a, Point b, Point c, Point d) noexcept {
    const int o1 = sign(cross(a, b, c)), o2 = sign(cross(a, b, d));
    const int o3 = sign(cross(c, d, a)), o4 = sign(cross(c, d, b));
    if (o1 != o2 && o3 != o4) return true;
    return (o1 == 0 && on_segment(a, b, c))
        || (o2 == 0 && on_segment(a, b, d))
        || (o3 == 0 && on_segment(c, d, a))
        || (o4 == 0 && on_segment(c, d, b));
}
} // namespace

// XY coordinates must already be in a local metric projection; this kernel
// deliberately never confuses longitude degrees with distances in meters.
extern "C" int gf_snap_point(
    const double* xy, std::size_t count, int closed,
    double x, double y, double tolerance, double* output) noexcept {
    if (!xy || !output || count < 1 || count > 20000 ||
        !std::isfinite(x) || !std::isfinite(y) ||
        !std::isfinite(tolerance) || tolerance < 0) return -1;
    const Point click{x,y};
    for (std::size_t i=0; i<count; ++i)
        if (!finite(point_at(xy,i))) return -1;
    double best = tolerance * tolerance;
    int kind = 0;
    Point nearest = click;
    // Prefer exact vertices on ties over points lying on a segment.
    for (std::size_t i=0; i<count; ++i) {
        const Point current = point_at(xy,i);
        const double distance = squared_distance(click,current);
        if (distance <= best) {
            best = distance;
            nearest = current;
            kind = 1;
        }
    }
    const std::size_t edges = kind == 0 ? (closed ? count : count - 1) : 0;
    for (std::size_t i=0; i<edges; ++i) {
        const Point current = projected(click,point_at(xy,i),point_at(xy,(i+1)%count));
        const double distance = squared_distance(click,current);
        if (distance < best - 1e-12) {
            best = distance;
            nearest = current;
            kind = 2;
        }
    }
    output[0] = nearest.x;
    output[1] = nearest.y;
    output[2] = std::sqrt(best);
    return kind;
}

// Detects planar non-adjacent segment intersections of a closed ring.
// Shapely is still the authoritative geographic topology validator.
extern "C" int gf_ring_self_intersects(
    const double* xy, std::size_t count) noexcept {
    if (!xy || count < 3 || count > 4096) return -1;
    for (std::size_t i=0; i<count; ++i) {
        if (!finite(point_at(xy,i)) ||
            squared_distance(point_at(xy,i),point_at(xy,(i+1)%count)) == 0.0)
            return -1;
    }
    for (std::size_t i=0; i<count; ++i) {
        const Point a = point_at(xy,i);
        const Point b = point_at(xy,(i+1)%count);
        for (std::size_t j=i+1; j<count; ++j) {
            if (j == i+1 || (i==0 && j==count-1)) continue;
            if (intersects(a,b,point_at(xy,j),point_at(xy,(j+1)%count)))
                return 1;
        }
    }
    return 0;
}

// Ramer-Douglas-Peucker simplification of an open coordinate sequence.
// Returns retained index count; caller owns output indices of capacity count.
extern "C" int gf_simplify_line(
    const double* xy, std::size_t count, double tolerance,
    std::size_t* indices) noexcept {
    if (!xy || !indices || count < 2 || count > 20000 ||
        !std::isfinite(tolerance) || tolerance < 0) return -1;
    for (std::size_t i=0; i<count; ++i)
        if (!finite(point_at(xy,i))) return -1;
    try {
        std::vector<unsigned char> keep(count,0);
        keep[0] = keep[count-1] = 1;
        std::vector<std::pair<std::size_t,std::size_t>> stack{{0,count-1}};
        const double tolerance2 = tolerance*tolerance;
        while (!stack.empty()) {
            const auto [first,last] = stack.back();
            stack.pop_back();
            const Point a=point_at(xy,first), b=point_at(xy,last);
            double furthest=tolerance2;
            std::size_t candidate=last;
            for (std::size_t i=first+1; i<last; ++i) {
                const double distance=squared_distance(point_at(xy,i),projected(point_at(xy,i),a,b));
                if (distance > furthest) { furthest=distance; candidate=i; }
            }
            if (candidate<last) {
                keep[candidate]=1;
                stack.emplace_back(first,candidate);
                stack.emplace_back(candidate,last);
            }
        }
        int size=0;
        for (std::size_t i=0; i<count; ++i)
            if (keep[i]) indices[size++]=i;
        return size;
    } catch (...) { return -1; }
}
