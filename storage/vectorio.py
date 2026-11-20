"""Bounded GIS vector import/export with GDAL/OGR and CRS validation.

Import never trusts an uploaded path, ZIP member path or dataset CRS. Vector
coordinates are converted to WGS84 and revalidated before database insertion.
"""
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pyogrio
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from geometry.measure import GeometryError, measure_geometry


class VectorIOError(ValueError):
    pass


_DRIVERS = {
    ".geojson":"GeoJSON",
    ".gpkg":"GPKG",
    ".kml":"KML",
    ".gpx":"GPX",
    ".zip":"ESRI Shapefile",
}
_MAX_BYTES=25*1024*1024
_MAX_EXPANDED=80*1024*1024


def _input_file(root:Path, name:str,blob:bytes)->Path:
    suffix=Path(name).suffix.lower()
    if suffix not in _DRIVERS:
        raise VectorIOError("Supported imports: GeoJSON, GPKG, KML, GPX and zipped Shapefile.")
    if not 0<len(blob)<=_MAX_BYTES:
        raise VectorIOError("Vector upload must be between 1 byte and 25 MB.")
    if suffix==".zip":
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            entries=archive.infolist()
            if len(entries)>30 or sum(item.file_size for item in entries)>_MAX_EXPANDED:
                raise VectorIOError("Shapefile archive exceeds limits.")
            allowed={".shp",".shx",".dbf",".prj",".cpg"}
            stems=set()
            for member in entries:
                relative=Path(member.filename)
                if (member.is_dir() or len(relative.parts)!=1 or
                    relative.name.startswith(".") or member.flag_bits & 0x1 or
                    (member.external_attr>>16)&0o170000 == 0o120000 or
                    relative.suffix.lower() not in allowed):
                    raise VectorIOError("ZIP must contain only flat, unencrypted Shapefile components.")
                stems.add(relative.stem.lower())
            if len(stems)!=1:
                raise VectorIOError("A ZIP must contain exactly one Shapefile layer.")
            shp=next((member for member in entries if member.filename.lower().endswith(".shp")),None)
            if shp is None:
                raise VectorIOError("Shapefile .shp component is missing.")
            for member in entries:
                target=root/Path(member.filename).name
                target.write_bytes(archive.read(member))
            return root/Path(shp.filename).name
    target=root/("uploaded"+suffix)
    target.write_bytes(blob)
    return target


def read_vector(name:str,blob:bytes)->dict:
    with tempfile.TemporaryDirectory(prefix="geofathom-vector-") as temporary:
        path=_input_file(Path(temporary),name,blob)
        try:
            info=pyogrio.read_info(path)
            if info["driver"] not in set(_DRIVERS.values()) | {"LIBKML"}:
                raise VectorIOError("Unsupported GDAL vector driver.")
            if info.get("features",0)>100:
                raise VectorIOError("Import at most 100 features per file.")
            meta,fids,geometries,fields=pyogrio.raw.read(path,max_features=101,force_2d=True)
        except (pyogrio.errors.DataSourceError,pyogrio.errors.DataLayerError,ValueError) as error:
            raise VectorIOError("GDAL could not read the uploaded vector dataset.") from error
        if len(geometries)>100:
            raise VectorIOError("Input has more than 100 features.")
        if not meta.get("crs"):
            raise VectorIOError("Source CRS is missing. Import cannot guess its coordinates.")
        try:
            origin=CRS.from_user_input(meta["crs"])
            transform_coords=Transformer.from_crs(origin,"EPSG:4326",always_xy=True).transform
        except Exception as error:
            raise VectorIOError("Vector source CRS could not be transformed to WGS84.") from error
        entries=[]
        for index,wkb in enumerate(geometries):
            if wkb is None: continue
            try:
                geom=transform(transform_coords,shapely.from_wkb(wkb))
                geojson=mapping(geom)
                measure_geometry(geojson)
            except (GeometryError,ValueError,TypeError) as error:
                raise VectorIOError(f"Invalid feature {index+1}: {error}") from error
            props={}
            for field,values in zip(meta.get("fields",[]),fields):
                item=values[index]
                if isinstance(item,np.generic):item=item.item()
                if item is not None:
                    if not isinstance(item,(str,int,float,bool)):
                        item=str(item)
                    props[str(field)[:64]]=item
            entries.append({
                "geometry":geojson,"properties":props,
                "name":str(props.get("name") or f"Imported feature {index+1}")[:200],
                "source":f"{info['driver']} imported file; source CRS {origin.to_string()}",
            })
        return {"features":entries,"source_crs":origin.to_string(),
                "count":len(entries),"driver":info["driver"]}


def write_vector(collection:dict, format_name:str)->tuple[bytes,str,str]:
    suffix={
        "geojson":".geojson","gpkg":".gpkg","kml":".kml",
        "gpx":".gpx","shapefile":".zip",
    }.get(format_name)
    if not suffix:raise VectorIOError("Unsupported vector export format.")
    features=collection.get("features",[])
    if not features:raise VectorIOError("There are no features to export.")
    if len(features)>10000:raise VectorIOError("Export at most 10,000 features.")
    if format_name=="geojson":
        return json.dumps(collection,ensure_ascii=False).encode(),"application/geo+json","geofathom.geojson"
    shapes=[]
    records=[]
    for feature in features:
        geom=feature["geometry"]
        measure_geometry(geom)
        if format_name=="gpx" and geom["type"] not in {"Point","LineString","MultiLineString"}:
            raise VectorIOError("GPX export supports points and tracks, not polygons.")
        shapes.append(shapely.to_wkb(shape(geom)))
        props=feature.get("properties") or {}
        records.append({"name":str(props.get("name",""))[:200],
                        "source":str(props.get("source",""))[:200]})
    geometries=np.array(shapes,dtype=object)
    field_data=[np.array([row[field] for row in records],dtype=object) for field in ("name","source")]
    with tempfile.TemporaryDirectory(prefix="geofathom-export-") as temp:
        root=Path(temp)
        driver="ESRI Shapefile" if format_name=="shapefile" else _DRIVERS[suffix]
        output=root/("features.shp" if format_name=="shapefile" else "geofathom"+suffix)
        try:
            pyogrio.raw.write(
                output,geometries,field_data,["name","source"],
                driver=driver,crs="EPSG:4326",geometry_type="Unknown",
            )
        except Exception as error:
            raise VectorIOError(f"GDAL could not export {format_name}: {error}") from error
        if format_name=="shapefile":
            payload=io.BytesIO()
            with zipfile.ZipFile(payload,"w",compression=zipfile.ZIP_DEFLATED) as archive:
                for member in root.glob("features.*"):
                    archive.write(member,member.name)
            return payload.getvalue(),"application/zip","geofathom-shapefile.zip"
        return output.read_bytes(),"application/octet-stream",output.name
