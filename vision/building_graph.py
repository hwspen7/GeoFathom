"""Deterministic component-local region adjacency optimization."""
import numpy as np

from .building_refinement import compact_ids, joint_ridge


def adjacency(labels, probability, ridge):
    """Accumulate four-neighbor interface length, wall strength and support."""
    n = int(labels.max())+1
    codes, walls, confidence = [], [], []
    perimeter = np.zeros(n, np.int64)
    padded = np.pad(labels, 1)
    for a,b,p,q,r,s in ((labels[:-1],labels[1:],probability[:-1],probability[1:],ridge[:-1],ridge[1:]),
                        (labels[:,:-1],labels[:,1:],probability[:,:-1],probability[:,1:],ridge[:,:-1],ridge[:,1:])):
        use = (a>0)&(b>0)&(a!=b)
        codes.append(np.minimum(a[use],b[use]).astype(np.int64)*n+np.maximum(a[use],b[use]))
        walls.append(np.maximum(r[use],s[use]))
        confidence.append(np.minimum(p[use],q[use]))
    for dy,dx in ((0,1),(2,1),(1,0),(1,2)):
        neighbor=padded[dy:dy+labels.shape[0],dx:dx+labels.shape[1]]
        edge=(labels>0)&(labels!=neighbor)
        perimeter+=np.bincount(labels[edge],minlength=n)
    keys,inv,length=np.unique(np.concatenate(codes),return_inverse=True,return_counts=True)
    wall=np.concatenate(walls)
    return perimeter, [(int(key//n),int(key%n),int(k),float(w),float(s),float(c))
        for key,k,w,s,c in zip(keys,length,np.bincount(inv,weights=wall)/length,
            np.bincount(inv,weights=(wall>=.65))/length,
            np.bincount(inv,weights=np.concatenate(confidence))/length)]


def optimize_regions(labels, probability, ridge, *, rounds=4):
    """Multi-round disjoint merges with recomputed region geometry and evidence.

    Local greedy objective, not a global optimum. Strong wall support vetoes a
    merge; low-confidence interfaces and detached roofs cannot be joined.
    """
    ids=compact_ids(labels)
    p=np.asarray(probability,np.float32); b=np.asarray(ridge,np.float32)
    if (p.shape!=ids.shape or b.shape!=ids.shape or not 1<=rounds<=8 or
            not np.isfinite(p).all() or not np.isfinite(b).all() or
            np.any((p<0)|(p>1)) or np.any((b<0)|(b>1))):
        raise ValueError("Invalid region graph fields.")
    for _ in range(rounds):
        area=np.bincount(ids.ravel())
        perimeter,edges=adjacency(ids,p,b)
        choices=[]
        for a,c,length,wall,strong,confidence in edges:
            if length<2 or wall>.35 or strong>.10 or confidence<.45:
                continue
            small,large=sorted((a,c),key=lambda j:(area[j],j))
            ratio=area[small]/area[large]
            compact=lambda A,P: 4*np.pi*A/max(P*P,1)
            before=max(compact(area[a],perimeter[a]),compact(area[c],perimeter[c]))
            after=compact(area[a]+area[c],perimeter[a]+perimeter[c]-2*length)
            contact=length/max(min(perimeter[a],perimeter[c]),1)
            # Larger fragments require a measurable compactness improvement;
            # narrow necks cannot justify merging even when model walls are weak.
            if contact<.10 or (ratio>.25 and (after-before<.04 or contact<.22)):
                continue
            if ratio<=.25 and after<before-.12:
                continue
            score=contact*(1-wall)*confidence + .3*(after-before)
            choices.append((-score,small,large))
        if not choices:
            break
        parent=np.arange(len(area),dtype=np.int32); used=set()
        for _,a,c in sorted(choices):
            if a not in used and c not in used:
                parent[a]=c; used.update((a,c))
        ids=compact_ids(parent[ids])
    if not np.array_equal(ids>0,np.asarray(labels)>0):
        raise ValueError("Region graph changed foreground support.")
    return ids


def graph_partition(foreground, probability, boundary=None, distance=None, *, seed_distance=6,
                    boundary_weight=1., max_instances=20000):
    """Shared bounded partition for research and disk-backed production."""
    from .building_instances import separate_instances
    ridge=joint_ridge(probability,boundary,distance,foreground)
    seeds=separate_instances(foreground,probability,ridge,distance,
        seed_distance=seed_distance,boundary_weight=boundary_weight,
        max_instances=max_instances,adaptive=True)
    return optimize_regions(seeds,probability,ridge)
