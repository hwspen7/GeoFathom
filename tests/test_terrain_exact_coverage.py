"""Independent set-theoretic oracles for candidate-bounded exact viewshed placement."""
from itertools import combinations
from threading import Event

import numpy as np
import pytest

from imagery.raster import RasterError
from terrain.cancellation import TerrainCancelled
from terrain.coverage_exact import exact_maximum_coverage
from terrain.p1_science import greedy_coverage


def test_exact_search_repairs_a_real_greedy_counterexample():
    # Greedy chooses A (4 cells), then B/C (+1), scoring 5.
    # Exact selects B+C and covers every one of the six cells.
    sets=[{0,1,2,3},{0,1,4},{2,3,5}]
    visible=[np.array([i in group for i in range(6)]).reshape(2,3) for group in sets]
    known=[np.ones((2,3),bool)]*3
    old,_,_=greedy_coverage(visible,known,2)
    assert old[0]==0
    selection,gains,union,audit=exact_maximum_coverage(visible,known,2)
    assert selection==[1,2]
    assert gains==[3,3] and int(union.sum())==6
    assert audit["combinations_checked"]==3
    assert audit["global_optimum_within_supplied_candidates"] is True


@pytest.mark.parametrize("n,k",[(3,1),(5,2),(8,3),(12,4)])
def test_exhaustive_optimization_matches_independent_python_set_oracle(n,k):
    rng=np.random.default_rng(15000+n*10+k)
    seen=[];known=[]
    for i in range(n):
        k_mask=rng.random((11,17))>.15
        v_mask=(rng.random((11,17))>.64)&k_mask
        known.append(k_mask)
        seen.append(v_mask)
    chosen,gains,union,audit=exact_maximum_coverage(seen,known,k)
    sets=[set(np.flatnonzero(x)) for x in seen]
    reference=[]
    optimum=-1
    for combo in combinations(range(n),k):
        size=len(set().union(*(sets[index] for index in combo)))
        if size>optimum:
            optimum=size
            reference=list(combo)
    assert chosen==reference
    assert gains==[len(set().union(*(sets[index] for index in chosen[:i+1])))-
                   len(set().union(*(sets[index] for index in chosen[:i])))
                   for i in range(k)]
    assert union.sum()==optimum
    assert audit["combinations_checked"]==audit["combinations_possible"]
    assert audit["positively_visible_cells"]==optimum


def test_unknown_other_candidate_cannot_erase_observed_visibility():
    first=np.array([[1,1,1,0]],bool)
    unknown=np.zeros_like(first)
    chosen,gains,union,audit=exact_maximum_coverage([first,unknown],
        [np.ones_like(first),unknown],1)
    assert chosen==[0] and gains==[3] and union.sum()==3
    assert audit["positively_visible_cells"]==3


def test_bounded_memory_and_strict_input_failures():
    mask=np.ones((2,3),bool)
    with pytest.raises(RasterError,match="1-12"):
        exact_maximum_coverage([mask]*13,[mask]*13,4)
    with pytest.raises(RasterError,match="match"):
        exact_maximum_coverage([mask],[np.zeros_like(mask)],1)
    with pytest.raises(RasterError,match="bounded"):
        exact_maximum_coverage([np.ones((1001,1001),bool)],
                               [np.ones((1001,1001),bool)],1)


def test_cancellation_does_not_return_partial_global_optimum():
    stopped=Event();stopped.set()
    mask=np.zeros((4,4),bool)
    with pytest.raises(TerrainCancelled):
        exact_maximum_coverage([mask]*4,[mask]*4,2,stopped)
