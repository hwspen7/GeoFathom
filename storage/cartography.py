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
        "priority":50,"offset_x":0,"offset_y":0,
        "prefix":"","suffix":"","placement":"auto",
        "callout":False,
        "rule_field":"","rule_operator":"equals","rule_value":"",
    },
    "symbol":{
        "fill_opacity":0.17,"line_width":3,"point_radius":5,
        "stroke_color":"#ffffff",
        "category_field":"",
        "category_colors":{},
        "graduated_field":"","graduated_breaks":[],"graduated_colors":[],
        "graduated_method":"quantile",
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
                    "priority":(0,100),"offset_x":(-10,10),"offset_y":(-10,10),
                }
                low,high=intervals[name]
                if value<low or value>high:raise StorageError(f"{name} is outside {low}–{high}.")
                if name=="font_size" and int(value)!=value:
                    raise StorageError("font_size must be a whole pixel value.")
            elif name in {"prefix","suffix"}:
                if not isinstance(value,str) or len(value)>24 or any(ord(ch)<32 for ch in value):
                    raise StorageError("Label prefix/suffix must be short printable text.")
            elif name=="placement":
                if value not in {"auto","point","line"}:
                    raise StorageError("Label placement must be auto, point or line.")
            elif name=="rule_operator":
                if value not in {"equals","contains","gte","lte","exists"}:
                    raise StorageError("Unsupported label rule operator.")
            elif name=="rule_value":
                if not isinstance(value,str) or len(value)>120 or any(ord(c)<32 for c in value):
                    raise StorageError("Label rule value must be short plain text.")
            elif name=="graduated_method":
                if value not in {"equal_interval","quantile","jenks"}:
                    raise StorageError("Unsupported graduated classification method.")
            elif name=="graduated_breaks":
                if not isinstance(value,list) or len(value)>8 or any(
                    not isinstance(x,(int,float)) or isinstance(x,bool) or
                    not math.isfinite(x) for x in value
                ) or any(a>=b for a,b in zip(value,value[1:])):
                    raise StorageError("Graduated break values must be strictly increasing finite numbers.")
            elif name=="graduated_colors":
                if not isinstance(value,list) or len(value)>9 or any(
                    not isinstance(x,str) or not _HEX.fullmatch(x) for x in value
                ):
                    raise StorageError("Graduated colors must be #RRGGBB entries.")
            elif name in {"field","category_field","graduated_field","rule_field"}:
                if (not isinstance(value,str) or
                        (name=="field" and not 1<=len(value)<=64) or
                        (name in {"category_field","graduated_field","rule_field"} and len(value)>64) or
                        any(ord(ch)<32 for ch in value)):
                    raise StorageError("Attribute field must have at most 64 printable characters.")
            elif name=="category_colors":
                if not isinstance(value,dict) or len(value)>20:
                    raise StorageError("Category palette supports at most 20 values.")
                for category,color in value.items():
                    if (not isinstance(category,str) or not 1<=len(category)<=80
                            or any(ord(ch)<32 for ch in category)
                            or not isinstance(color,str) or not _HEX.fullmatch(color)):
                        raise StorageError("Category values and colors are invalid.")
            elif not isinstance(value,str) or not _HEX.fullmatch(value):
                raise StorageError(f"{name} must be a #RRGGBB color.")
            updated[section][name]=value
    symbol=updated["symbol"]
    if symbol["graduated_colors"] and len(symbol["graduated_colors"])!=len(symbol["graduated_breaks"])+1:
        raise StorageError("Graduated color count must equal the number of breaks + 1.")
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
