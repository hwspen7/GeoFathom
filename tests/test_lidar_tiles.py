import numpy as np
import pytest
from scipy.spatial import cKDTree
from analysis.lidar_tiles import tiled_radius_summary

def test_tiled_neighborhood_matches_global_tree_including_duplicates():
    rng=np.random.default_rng(28)
    p=np.vstack((rng.uniform(-2,2,(250,3)),[[.99,0,0],[1.01,0,0],[1.01,0,0]]))
    table,m=tiled_radius_summary([p[:100],p[100:]],1.,.4)
    exact=cKDTree(p).query_ball_point(p,.4,return_length=True)-1
    assert m["directed_neighbor_pairs"]==int(exact.sum())
    assert m["mean_neighbors"]==pytest.approx(exact.mean())
    keys=np.floor(p).astype(int)
    for row in table:
        local=exact[np.all(keys==np.floor(row[:3]),axis=1)]
        assert row[3]==len(local)
        assert row[4]==pytest.approx(local.mean())
        assert row[5]==local.min() and row[6]==local.max()

def test_tiled_neighborhood_rejects_invalid_radius_and_budget():
    p=np.zeros((4,3))
    with pytest.raises(ValueError):tiled_radius_summary([p],1.,2.)
    with pytest.raises(ValueError):tiled_radius_summary([p],1.,.5,point_limit=3)
