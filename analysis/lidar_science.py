"""Bounded metric point-cloud methods with explicit support and provenance."""
import csv
import hashlib
import io
import struct

import numpy as np
from pyproj import CRS
from scipy.spatial import cKDTree, Delaunay, QhullError

from .lidar_advanced import robust_outlier, register, normal_change, canopy_structure

from .lidar_geometry import ground_filter, tin_mesh, alpha_boundary, plane_icp, roof_planes, crown_candidates

MAX_POINTS = 100_000
MAX_BYTES = 16 * 1024 * 1024
METHODS = {
    "ground_filter": ("Progressive slope ground filter", "Local lower-envelope seeds and slope allowance; TIN interpolation within supported area."),
    "tin_mesh": ("2.5D surface TIN", "XY Delaunay triangles filtered by maximum 3D edge length; median duplicate XY elevations."),
    "alpha_boundary": ("3D alpha-complex boundary", "Regularized retained tetrahedra; no isolated alpha simplices or Poisson surface."),
    "point_plane_icp": ("Robust point-to-plane ICP", "Huber-weighted local registration; rejects unobservable six-parameter systems."),
    "roof_planes": ("RANSAC plane segmentation", "Geometric planar candidates; not semantic buildings."),
    "crown_candidates": ("CHM apex candidates", "Ground-normalized sparse CHM nonmaximum suppression and nearest-apex assignment."),
    "quality": ("Cloud quality", "Finite XYZ; exact duplicate coordinates and observed extent."),
    "voxel": ("Voxel centroid reduction", "Fixed metric grid anchored at coordinate zero; retain counts."),
    "local_geometry": ("Local PCA geometry", "3D k-nearest-neighbor covariance; normals undefined for degenerate neighborhoods."),
    "density": ("Spherical neighborhood density", "Neighbor count excluding self divided by sphere volume; no boundary correction."),
    "vertical_profile": ("Vertical height distribution", "Observed elevation histogram, not a canopy-height distribution."),
    "cloud_distance": ("Directed cloud-to-cloud distance", "Nearest 3D distance, unsigned; not evidence of statistically significant change."),
    "surface_change": ("Paired cell surface change", "Median Z per shared XY cell; unmatched cells excluded from volume."),
    "robust_outlier": ("Robust statistical outliers", "Median/MAD of mean kNN distance; flags are diagnostic, not automatic deletion."),
    "rigid_registration": ("Trimmed rigid ICP", "Point-to-point SVD rigid fit with correspondence radius; requires initial approximate alignment."),
    "normal_change": ("Local normal-projection change", "M3C2-inspired cylindrical projections; conditional pointwise uncertainty, not spatially adjusted."),
    "canopy_structure": ("Canopy height distribution", "Ground-normalized return percentiles and threshold fraction; not areal vegetation cover."),
    "ground_height": ("Ground-normalized height", "Barycentric interpolation of independently supplied ground points; no extrapolation."),
}

def metric_crs(epsg):
    crs = CRS.from_epsg(epsg)
    if not crs.is_projected or len(crs.axis_info) < 2 or any(
        abs(a.unit_conversion_factor - 1) > 1e-10 for a in crs.axis_info[:2]
    ):
        raise ValueError("Supply a projected horizontal CRS in metres.")
    return crs.to_string()

def read_cloud(data, name):
    """Read strict XYZ CSV or uncompressed LAS coordinates; never silently sample."""
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Point-cloud file is empty or exceeds 16 MiB.")
    if name.lower().endswith(".las"):
        if len(data) < 227 or data[:4] != b"LASF" or data[24] != 1 or data[25] not in (2, 3, 4):
            raise ValueError("Expected uncompressed LAS 1.2–1.4.")
        header, offset = struct.unpack_from("<HI", data, 94)
        version = data[25]
        if header < {2:227, 3:235, 4:375}[version] or offset < header or offset > len(data):
            raise ValueError("Invalid LAS header or point-data offset.")
        fmt = data[104]
        lengths = (20,28,26,34,57,63,30,36,38,59,67)
        length, count = struct.unpack_from("<HI", data, 105)
        if fmt >= len(lengths) or (version < 4 and fmt >= 6) or (version == 2 and fmt >= 4) or length < lengths[fmt]:
            raise ValueError("Compressed or unsupported LAS point record.")
        if version == 4:
            extended = struct.unpack_from("<Q", data, 247)[0]
            if extended:
                count = extended
        if not 0 < count <= MAX_POINTS or offset + count * length > len(data):
            raise ValueError("Invalid LAS point count, truncated file, or 100,000-point limit exceeded.")
        scales = np.array(struct.unpack_from("<3d", data, 131))
        offsets = np.array(struct.unpack_from("<3d", data, 155))
        if not np.isfinite(scales).all() or np.any(scales <= 0) or not np.isfinite(offsets).all():
            raise ValueError("Invalid LAS coordinate scale or offset.")
        xyz = np.ndarray((count,3), dtype="<i4", buffer=data, offset=offset, strides=(length,4)).astype(float)
        xyz = xyz * scales + offsets
        source = "LAS 1." + str(version) + " XYZ"
    elif name.lower().endswith(".csv"):
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig")), strict=True)
        header = next(reader, [])
        fields = [s.strip().lower() for s in header]
        if any(fields.count(k) != 1 for k in ("x","y","z")):
            raise ValueError("CSV requires unique x,y,z columns.")
        ix = [fields.index(k) for k in ("x","y","z")]
        rows = []
        for row in reader:
            if not row:
                continue
            if len(row) != len(fields) or len(rows) >= MAX_POINTS:
                raise ValueError("Invalid CSV row or 100,000-point limit exceeded.")
            rows.append([float(row[i]) for i in ix])
        xyz = np.asarray(rows, dtype=float)
        source = "XYZ CSV"
    else:
        raise ValueError("Use an uncompressed .las or XYZ .csv file; LAZ is not supported.")
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not len(xyz) or not np.isfinite(xyz).all() or np.max(np.abs(xyz)) > 1e9:
        raise ValueError("XYZ coordinates must be finite, nonempty, and within ±1e9 metres.")
    return xyz, {"format":source, "sha256":hashlib.sha256(data).hexdigest(), "points":len(xyz)}

def _grid(p, size, dimensions):
    return np.floor(p[:,:dimensions] / size).astype(np.int64)

def _groups(p, size, dimensions):
    keys, inverse, counts = np.unique(_grid(p,size,dimensions), axis=0, return_inverse=True, return_counts=True)
    return keys, inverse, counts

def _median_cells(p, size):
    keys, inverse, counts = _groups(p,size,2)
    order = np.argsort(inverse, kind="stable")
    groups = np.split(p[order,2], np.cumsum(counts)[:-1])
    return {tuple(key):(float(np.median(z)),int(n)) for key,z,n in zip(keys,groups,counts)}

def _local_geometry(p, k):
    if len(p) < k:
        raise ValueError("Cloud has fewer points than the requested neighborhood.")
    tree = cKDTree(p)
    result = np.full((len(p), 7), np.nan)
    for start in range(0,len(p),4096):
        stop = min(start+4096,len(p))
        _, idx = tree.query(p[start:stop], k=k)
        samples = p[idx]
        centered = samples - samples.mean(axis=1,keepdims=True)
        cov = np.einsum("nki,nkj->nij",centered,centered) / k
        values, vectors = np.linalg.eigh(cov)
        values = np.maximum(values,0)
        valid = (values[:,2] > 0) & (values[:,1]-values[:,0] > values[:,2]*1e-12)
        n = vectors[:,:,0]
        # Deterministic orientation: prefer positive Z, then Y, then X.
        dominant = np.where(np.abs(n[:,2])>1e-12,n[:,2],np.where(np.abs(n[:,1])>1e-12,n[:,1],n[:,0]))
        n = n * np.where(dominant < 0,-1,1)[:,None]
        a,b,c = values[valid].T
        result[start:stop][valid] = np.column_stack((n[valid],np.sqrt(a),(b-a)/c,a/(a+b+c),(c-b)/c))
    return result

def _ground(p, reference, max_edge):
    xy, inverse = np.unique(reference[:,:2],axis=0,return_inverse=True)
    if len(xy) < 3:
        raise ValueError("Ground reference needs three non-collinear XY points.")
    order = np.argsort(inverse,kind="stable")
    counts = np.bincount(inverse)
    z = np.array([np.median(a) for a in np.split(reference[order,2],np.cumsum(counts)[:-1])])
    origin = xy.mean(axis=0)
    try:
        tri = Delaunay(xy-origin)
    except QhullError as exc:
        raise ValueError("Ground reference cannot form a nondegenerate TIN.") from exc
    q = p[:,:2]-origin
    simplex = tri.find_simplex(q)
    ground = np.full(len(p),np.nan)
    ii = np.flatnonzero(simplex>=0)
    s = simplex[ii]
    v = xy[tri.simplices[s]]
    edge = np.max(np.linalg.norm(v-np.roll(v,1,axis=1),axis=2),axis=1)
    ii, s = ii[edge<=max_edge], s[edge<=max_edge]
    transform = tri.transform[s]
    bary = np.einsum("nij,nj->ni",transform[:,:2],q[ii]-transform[:,2])
    weights = np.column_stack((bary,1-bary.sum(axis=1)))
    ground[ii] = np.sum(z[tri.simplices[s]]*weights,axis=1)
    return ground

def _serialize(columns, table):
    def row(values):
        return [float(v) if np.isfinite(v) else None for v in values]
    out = io.StringIO()
    writer = csv.writer(out,lineterminator="\n")
    writer.writerow(columns)
    for values in table:
        writer.writerow([format(v,".17g") if v is not None else "" for v in row(values)])
    # The figure source is a deterministic, evenly spaced sample of result rows.
    indices = np.linspace(0,len(table)-1,min(10_000,len(table)),dtype=int) if len(table) else []
    figure = io.StringIO()
    fw = csv.writer(figure,lineterminator="\n")
    fw.writerow(columns)
    for i in indices:
        fw.writerow(row(table[i]))
    return out.getvalue(), figure.getvalue(), [row(r) for r in table[:100]]

def analyze(operation, p, reference=None, *, k=16, size=1., radius=2., max_edge=10., trim_fraction=.8, max_iterations=60, tolerance=1e-5,
            registration_sigma=.05, min_neighbors=5, threshold=3.5):
    if operation not in METHODS:
        raise ValueError("Unknown point-cloud operation.")
    if not 3 <= k <= 64 or not all(np.isfinite(v) and .001 <= v <= 1e6 for v in (size,radius,max_edge)):
        raise ValueError("Invalid metric analysis parameters.")
    columns = ["x_m","y_m","z_m"]
    metrics = {"input_points":len(p)}
    if not (np.isfinite(threshold) and 0 <= threshold <= 1e6 and np.isfinite(registration_sigma) and 0 <= registration_sigma <= 1e6 and 3 <= min_neighbors <= 1000):
        raise ValueError("Invalid diagnostic or uncertainty parameters.")
    if operation in ("cloud_distance","surface_change","ground_height","rigid_registration","normal_change","canopy_structure","point_plane_icp","crown_candidates") and reference is None:
        raise ValueError("This method needs a reference cloud in the same CRS and vertical datum.")
    if operation == "ground_filter":
        table,info=ground_filter(p,size,radius,threshold)
        columns += ["ground_z_m","height_m","ground_flag"]
        metrics.update(info)
    elif operation in ("tin_mesh","alpha_boundary"):
        table,info=tin_mesh(p,max_edge) if operation=="tin_mesh" else alpha_boundary(p,radius)
        columns=[f"{axis}{i}_m" for i in (1,2,3) for axis in ("x","y","z")]+["surface_area_m2"]
        if operation=="tin_mesh":columns+=["projected_area_m2"]
        metrics.update(info)
    elif operation == "point_plane_icp":
        table,info=plane_icp(p,reference,k,radius,trim_fraction,max_iterations,tolerance)
        columns += ["residual_m","signed_plane_residual_m","inlier_flag"]
        metrics.update(info)
    elif operation == "roof_planes":
        table,info=roof_planes(p,threshold,min_neighbors,max_iterations,k)
        columns += ["plane_id","residual_m","normal_x","normal_y","normal_z"]
        metrics.update(info)
    elif operation == "crown_candidates":
        table,info=crown_candidates(p,_ground(p,reference,max_edge),size,radius,threshold)
        columns += ["height_m","candidate_id","apex_height_m"]
        metrics.update(info)
    elif operation == "quality":
        table = p
        metrics.update(unique_points=len(np.unique(p,axis=0)),minimum_xyz_m=p.min(axis=0).tolist(),
                       maximum_xyz_m=p.max(axis=0).tolist(),median_z_m=float(np.median(p[:,2])))
    elif operation == "voxel":
        _, inverse, counts = _groups(p,size,3)
        table = np.column_stack([np.bincount(inverse,weights=p[:,i])/counts for i in range(3)]+[counts])
        columns += ["count"]
        metrics.update(output_points=len(table),voxel_m=size)
    elif operation == "local_geometry":
        geom = _local_geometry(p,k)
        columns += ["normal_x","normal_y","normal_z","roughness_m","planarity","curvature","linearity"]
        table = np.column_stack((p,geom))
        metrics.update(valid_neighborhoods=int(np.isfinite(geom[:,0]).sum()),neighbors=k)
    elif operation == "density":
        count = cKDTree(p).query_ball_point(p,radius,return_length=True)-1
        table = np.column_stack((p,count,count/(4*np.pi*radius**3/3)))
        columns += ["neighbors","density_per_m3"]
        metrics.update(radius_m=radius,median_neighbors=float(np.median(count)))
    elif operation == "vertical_profile":
        lo = np.floor(p[:,2]/size).astype(np.int64)
        bins, counts = np.unique(lo,return_counts=True)
        table = np.column_stack(((bins+.5)*size,counts,counts/len(p)))
        columns = ["z_bin_center_m","count","fraction"]
        metrics.update(bin_width_m=size,occupied_bins=len(bins),p05_p50_p95_m=np.quantile(p[:,2],[.05,.5,.95]).tolist())
    elif operation == "cloud_distance":
        d,_ = cKDTree(reference).query(p)
        table = np.column_stack((p,d))
        columns += ["distance_m"]
        metrics.update(reference_points=len(reference),rmse_m=float(np.sqrt(np.mean(d*d))),median_m=float(np.median(d)),p95_m=float(np.quantile(d,.95)))
    elif operation == "surface_change":
        a,b = _median_cells(p,size),_median_cells(reference,size)
        keys = sorted(a.keys() & b.keys())
        if not keys:
            raise ValueError("No shared occupied XY cells.")
        table = np.array([[(i+.5)*size,(j+.5)*size,b[i,j][0],a[i,j][0],
                           a[i,j][0]-b[i,j][0],a[i,j][1],b[i,j][1]] for i,j in keys])
        columns = ["x_m","y_m","reference_z_m","current_z_m","delta_z_m","current_count","reference_count"]
        dz = table[:,4]
        metrics.update(shared_cells=len(keys),current_only_cells=len(a)-len(keys),reference_only_cells=len(b)-len(keys),
                       common_area_m2=len(keys)*size**2,net_volume_m3=float(dz.sum()*size**2),
                       gain_volume_m3=float(np.maximum(dz,0).sum()*size**2),loss_volume_m3=float(-np.minimum(dz,0).sum()*size**2))
    elif operation == "robust_outlier":
        values, info = robust_outlier(p,k,threshold)
        table = np.column_stack((p,values))
        columns += ["mean_knn_distance_m","robust_z","outlier_flag"]
        metrics.update(info)
    elif operation == "rigid_registration":
        table, info = register(p,reference,radius,trim_fraction,max_iterations,tolerance)
        columns += ["residual_m","inlier_flag"]
        metrics.update(info)
    elif operation == "normal_change":
        _, inverse, counts = _groups(reference,size,3)
        cores = np.column_stack([np.bincount(inverse,weights=reference[:,i])/counts for i in range(3)])
        table, info = normal_change(p,reference,cores,k,radius,max_edge,registration_sigma,min_neighbors)
        columns += ["normal_x","normal_y","normal_z","current_count","reference_count","signed_change_m","lod95_m","lower95_m","upper95_m","above_lod"]
        metrics.update(info)
    elif operation == "canopy_structure":
        ground = _ground(p,reference,max_edge)
        table, info = canopy_structure(p,ground,size,threshold)
        columns = ["x_m","y_m","count","p05_m","p25_m","p50_m","p75_m","p95_m","mean_height_m","sd_height_m","return_fraction_above_threshold"]
        metrics.update(info)
    else:
        ground = _ground(p,reference,max_edge)
        height = p[:,2]-ground
        table = np.column_stack((p,ground,height))
        columns += ["ground_z_m","height_m"]
        valid = np.isfinite(height)
        metrics.update(valid_points=int(valid.sum()),unsupported_points=int((~valid).sum()),max_triangle_edge_m=max_edge,
                       median_height_m=float(np.median(height[valid])) if valid.any() else None)
    data, figure, rows = _serialize(columns,table)
    return {"operation":operation,"columns":columns,"rows":rows,"row_count":len(table),"csv":data,"figure_csv":figure,
            "metrics":metrics,"assumption":METHODS[operation][1]}
