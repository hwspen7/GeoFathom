"""Persisted layer cartography: safe label fields, symbol styles and zoom limits.

Layer styles are in a dedicated table, keeping older SQLite projects readable.
Only bounded, type-checked style values are accepted; no eval, HTML templates,
arbitrary MapLibre expressions or user-supplied JavaScript are persisted.
"""
import copy
import json
import math
import re
from typing import Any

from .database import StorageError, _connect, _required_project, _now

_HEX=re.compile(r"^#[0-9a-fA-F]{6}$")
_DEFAULT={
    "labels":{
        "enabled":False,"field":"name","font_size":12,
        "text_color":"#183954","halo_color":"#ffffff","halo_width":1.5,
        "min_zoom":0,"max_zoom":24,"allow_overlap":False,
    },
    "symbol":{
        "fill_opacity":0.17,"line_width":3,"point_radius":5,
        "stroke_color":"#ffffff",
    },
}


def default_style()->dict:
    return copy.deepcopy(_DEFAULT)


def _validate(changes:dict[str,Any],current:dict[str,Any])->dict:
    if not isinstance(changes,dict) or not changes:
        raise StorageError("Specify label or symbol style changes.")
    if set(changes)-{"labels","symbol"}:
        raise StorageError("Unsupported map style section.")
    updated=copy.deepcopy(current)
    for section,fields in changes.items():
        if not isinstance(fields,dict) or not fields or set(fields)-set(_DEFAULT[section]):
            raise StorageError("Unsupported map label or symbol property.")
        for name,value in fields.items():
            reference=_DEFAULT[section][name]
            if isinstance(reference,bool):
                if not isinstance(value,bool):raise StorageError(f"{name} must be boolean.")
            elif isinstance(reference,(int,float)):
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                    raise StorageError(f"{name} must be a finite number.")
                intervals={
                    "font_size":(9,28),"halo_width":(0,4),
                    "min_zoom":(0,24),"max_zoom":(0,24),
                    "fill_opacity":(0,1),"line_width":(0.5,12),
                    "point_radius":(2,20),
                }
                low,high=intervals[name]
                if value<low or value>high:raise StorageError(f"{name} is outside {low}–{high}.")
                if name=="font_size" and int(value)!=value:
                    raise StorageError("font_size must be a whole pixel value.")
            elif name=="field":
                if (not isinstance(value,str) or not 1<=len(value)<=64
                        or any(ord(ch)<32 for ch in value)):
                    raise StorageError("Label attribute field must have 1–64 printable characters.")
            elif not isinstance(value,str) or not _HEX.fullmatch(value):
                raise StorageError(f"{name} must be a #RRGGBB color.")
            updated[section][name]=value
    labels=updated["labels"]
    if labels["min_zoom"]>labels["max_zoom"]:
        raise StorageError("Minimum label zoom must not exceed maximum.")
    if labels["halo_width"]>labels["font_size"]/4:
        raise StorageError("Label halo exceeds one-quarter font size.")
    return updated


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geo_layer_cartography(
            layer_id TEXT PRIMARY KEY REFERENCES geo_layers(id) ON DELETE CASCADE,
            settings TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0
        )
    """)


def read_style_in_connection(conn,layer_id:str)->dict:
    _ensure_table(conn)
    row=conn.execute("SELECT settings,revision FROM geo_layer_cartography WHERE layer_id=?",
                     (layer_id,)).fetchone()
    if row is None:
        return {"style":default_style(),"style_revision":0}
    try:
        # Older revisions can omit future style fields.
        obj=json.loads(row["settings"])
        style=default_style()
        for section in style:
            style[section].update(obj.get(section,{}) if isinstance(obj,dict) else {})
    except (ValueError,TypeError) as error:
        raise StorageError("Stored layer cartography is invalid.") from error
    return {"style":style,"style_revision":row["revision"]}


def change_style(project_id:str,layer_id:str,changes:dict,expected_revision:int|None=None)->dict:
    from .workspace import _schema, _layer
    with _connect() as conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        _required_project(conn,project_id)
        layer=_layer(conn,project_id,layer_id)
        existing=read_style_in_connection(conn,layer_id)
        if expected_revision is not None and expected_revision!=existing["style_revision"]:
            raise StorageError("Style revision conflict. Reload the layer.")
        style=_validate(changes,existing["style"])
        revision=existing["style_revision"]+1
        conn.execute(
            "INSERT INTO geo_layer_cartography(layer_id,settings,revision) VALUES(?,?,?) "
            "ON CONFLICT(layer_id) DO UPDATE SET settings=excluded.settings,revision=excluded.revision",
            (layer_id,json.dumps(style,allow_nan=False),revision),
        )
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?",(_now(),project_id))
        return {**layer,"style":style,"style_revision":revision}
