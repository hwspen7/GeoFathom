"""Project jobs for optical cubes using opaque managed-image identifiers."""
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from typing import Literal

from analysis.science_raster import require
from storage.snapshots import copy_verified
from .remote_managed import DiskBand, DiskQuality, result_path


class Acquisition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.-]+$')
    datetime: AwareDatetime
    sensor: str = Field(min_length=1, max_length=100)
    bands: dict[str, DiskBand] = Field(min_length=1, max_length=12)
    quality: list[DiskQuality] = Field(default_factory=list, max_length=8)


class CubeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_image_id: UUID
    acquisitions: list[Acquisition] = Field(min_length=2, max_length=64)
    resampling: Literal['nearest', 'bilinear'] = 'bilinear'
    harmonization: str = Field(default='', max_length=4000)
    tile: int = Field(default=256, ge=32, le=1024)
    disk_budget_mb: int = Field(default=8192, ge=64, le=65536)
    snapshot_mb: int = Field(default=1024, ge=64, le=8192)


def validate(payload):
    from .remote_cube import acquisition_times
    body = CubeInput.model_validate(payload)
    acquisition_times(body.model_dump(mode='json')['acquisitions'])
    roles = set(body.acquisitions[0].bands)
    require(all(set(a.bands) == roles for a in body.acquisitions), 'All dates require the same spectral roles.')
    require(all(set(q.roles) <= roles for a in body.acquisitions for q in a.quality), 'Unknown quality target role.')
    require(len({a.id for a in body.acquisitions}) == len(body.acquisitions), 'Acquisition IDs must be unique.')
    require(len({a.sensor for a in body.acquisitions}) == 1 or len(body.harmonization.strip()) >= 20,
            'Document cross-sensor harmonization before building this cube.')
    return body


def run_managed(payload, job_id, progress, check):
    from .store import image_file
    from .remote_cube import build_cube
    body = validate(payload)
    ids = {str(body.target_image_id)}
    for a in body.acquisitions:
        ids.update(str(b.image_id) for b in a.bands.values())
        ids.update(str(q.image_id) for q in a.quality)
    originals = {uid: image_file(uid) for uid in sorted(ids)}
    size = sum(p.stat().st_size for p in originals.values())
    require(size <= body.snapshot_mb * 1024**2, 'Cube snapshot budget exceeded.')
    output = result_path(job_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    require(shutil.disk_usage(output.parent).free > size + 64*1024**2, 'Insufficient snapshot disk space.')
    with TemporaryDirectory(prefix='cube-input-'+str(job_id)+'-', dir=output.parent) as directory:
        snapshots = {}
        for uid, source in originals.items():
            check()
            target = Path(directory) / (uid+'.tif')
            copy_verified(source, target)
            snapshots[uid] = str(target)
        def spec(item):
            data = item.model_dump(mode='json')
            data['path'] = snapshots[data.pop('image_id')]
            return data
        config = {'target_path': snapshots[str(body.target_image_id)],
            'acquisitions': [{**a.model_dump(mode='json', exclude={'bands', 'quality'}),
                'bands': {r: spec(b) for r, b in a.bands.items()}, 'quality': [spec(q) for q in a.quality]}
                for a in body.acquisitions], 'resampling': body.resampling, 'harmonization': body.harmonization,
            'tile': body.tile, 'disk_budget_mb': body.disk_budget_mb}
        try:
            receipt = build_cube(config, output, progress, check)
            check()
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        # Local paths belong in CLI receipts only, never in browser job results.
        mapping = {p: uid for uid, p in snapshots.items()}
        receipt['source_sha256'] = {mapping[p]: h for p, h in receipt['source_sha256'].items()}
        for entry in receipt['band_layout']:
            for q in entry['quality']:
                q['image_id'] = mapping[q.pop('path')]
        return receipt
