"""Exact bounded maximum-coverage placement for scientific viewsheds.

For up to twelve precomputed observer candidates and four selected sites, enumerate
every candidate combination. This provides a *certificate of global optimality
within the supplied candidate set* (not continuous/geographic optimality).
NoData never becomes invisible and positively confirmed visibility is retained
even if a different candidate has an unknown ray.
"""
from itertools import combinations
from math import comb

import numpy as np

from imagery.raster import RasterError
from .cancellation import checkpoint

_POPCOUNT=np.array([int(i).bit_count() for i in range(256)],dtype=np.uint8)


def exact_maximum_coverage(visible_masks,known_masks,max_sites,cancel=None):
    """Return (chosen indices, marginal gains, visible union, audit receipt).

    Optimizes the number of distinct cells *positively observed* by at least
    one selected candidate. Non-visible/unknown are never treated as positives.
    The objective does not require unselected candidates to have known rays.
    """
    n=len(visible_masks)
    if not 1<=n<=12 or len(known_masks)!=n or not isinstance(max_sites,int) or not 1<=max_sites<=min(4,n):
        raise RasterError("Exact site placement requires 1-12 candidates and 1-4 selected sites.")
    shape=np.asarray(visible_masks[0]).shape
    if len(shape)!=2 or np.prod(shape)>1_000_000:
        raise RasterError("Exact site placement requires a bounded aligned 2-D visibility grid.")
    packed=[]
    for visible,known in zip(visible_masks,known_masks):
        seen=np.asarray(visible,dtype=bool)
        available=np.asarray(known,dtype=bool)
        if seen.shape!=shape or available.shape!=shape or np.any(seen&~available):
            raise RasterError("Visibility masks must match and every visible ray must be known.")
        packed.append(np.packbits(seen.ravel()))
    packed=np.stack(packed)
    best=-1
    selected=None
    combinations_checked=0
    for combo in combinations(range(n),max_sites):
        if combinations_checked%64==0:
            checkpoint(cancel)
        union=np.bitwise_or.reduce(packed[list(combo)],axis=0)
        objective=int(_POPCOUNT[union].sum(dtype=np.int64))
        # itertools.combinations is lexicographically sorted: ties select
        # the earliest combination, reproducibly and without heuristics.
        if objective>best:
            best=objective
            selected=combo
        combinations_checked+=1
    assert selected is not None
    union_packed=np.zeros(packed.shape[1],dtype=np.uint8)
    gains=[]
    for index in selected:
        next_union=np.bitwise_or(union_packed,packed[index])
        gain=int(_POPCOUNT[next_union].sum(dtype=np.int64)-
                 _POPCOUNT[union_packed].sum(dtype=np.int64))
        gains.append(gain)
        union_packed=next_union
    visible=np.unpackbits(union_packed,count=int(np.prod(shape))).reshape(shape).astype(bool)
    checkpoint(cancel)
    audit={
        "candidate_count":n,
        "selected_site_count":max_sites,
        "combinations_checked":combinations_checked,
        "combinations_possible":comb(n,max_sites),
        "positively_visible_cells":best,
        "global_optimum_within_supplied_candidates":True,
        "objective":"union_of_positively_visible_known_cells",
        "tie_break":"lexicographic_candidate_indices",
    }
    if combinations_checked!=audit["combinations_possible"] or sum(gains)!=best:
        raise RasterError("Site optimization audit failed its exhaustive conservation check.")
    return list(selected),gains,visible,audit
