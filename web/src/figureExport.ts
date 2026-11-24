import type {FigureScene,FigureSettings,PlotTable} from './figureLibrary';
import type {PlotData} from './api';
export function saveFigureBlob(blob:Blob,name:string){
 const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;link.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function encodePayload(value:unknown){
 let binary='';for(const byte of new TextEncoder().encode(JSON.stringify(value)))binary+=String.fromCharCode(byte);
 return btoa(binary);
}
/** Self-contained Matplotlib program with the exact selected table embedded. */
export function pythonFigure(table:PlotTable,settings:FigureSettings,data:PlotData,provenance:unknown):string{
 const payload=encodePayload({table,settings,summary:data.summary,box:data.box,provenance,joint:data.joint,comparison:data.distribution_comparison});
 return `"""GeoFathom scientific figure. Requires matplotlib; embedded data are unchanged.
Tables/metadata may also be exported separately as CSV/JSON.
"""
import base64
import json
import math
import matplotlib.pyplot as plt

payload = json.loads(base64.b64decode("${payload}"))
table, settings = payload["table"], payload["settings"]
rows = table["rows"]
kind = settings["kind"]
plt.rcParams.update({"font.family": "serif" if settings["font"] == "serif" else "sans-serif",
                     "font.size": settings["font_size"] / 2,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "svg.fonttype": "none", "pdf.fonttype": 42})
fig, ax = plt.subplots(figsize=(settings["width_mm"]/25.4, settings["height_mm"]/25.4),
                       subplot_kw={"projection": "polar"} if kind == "rose" else {})
color = {"mono": "#222222", "blue": "#225b87", "earth": "#826344"}[settings["palette"]]
measure = {"cells": 1, "area": 2, "percent": 3}[settings["measure"]]
if kind == "histogram":
    column = {"cells": 3, "area": 4, "percent": 5}[settings["measure"]]
    edges = [r[0] for r in rows] + [rows[-1][1]]
    ax.stairs([r[column] for r in rows], edges, fill=True, color=color, alpha=0.7)
elif kind in ("cdf", "exceedance"):
    column = 2 if kind == "cdf" else 3
    xs = [r[0] for r in rows]; ys = [r[column] for r in rows]
    span = (xs[-1]-xs[0]) if xs[-1] > xs[0] else max(abs(xs[0])*0.01, 1)
    initial = 0 if kind == "cdf" else 100
    left = xs[0]-0.03*span
    if settings["x_log"] and left <= 0: left = xs[0]
    ax.step([left]+xs+[xs[-1]+0.03*span], [initial]+ys+[ys[-1]], where="post", color=color)
elif kind == "density":
    ax.plot([r[2] for r in rows], [r[6] for r in rows], color=color)
elif kind == "box":
    box = payload["box"]
    ax.bxp([{"label": table["x_label"], "whislo": box["whisker_low"], "q1": box["q1"],
             "med": box["median"], "q3": box["q3"], "whishi": box["whisker_high"], "fliers": box.get("fliers", [])}],
           showfliers=True)
elif kind == "joint_density":
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Rectangle
    from matplotlib.colors import LogNorm
    occupied = [r for r in rows if r[4] > 0]
    patches = [Rectangle((r[0],r[2]), r[1]-r[0], r[3]-r[2]) for r in occupied]
    collection = PatchCollection(patches, cmap="Greys", norm=LogNorm(vmin=1,vmax=max(2,max(r[4] for r in occupied))))
    collection.set_array([r[4] for r in occupied])
    ax.add_collection(collection); ax.autoscale_view()
    fig.colorbar(collection, ax=ax, label="Cell count (log color)")
elif kind == "comparison_boxes":
    series = payload["comparison"]["series"]
    ax.bxp([{"label": r["label"], "whislo": r["box"]["whisker_low"], "q1": r["box"]["q1"],
             "med": r["box"]["median"], "q3": r["box"]["q3"], "whishi": r["box"]["whisker_high"],
             "fliers": r["box"].get("fliers", [])} for r in series], showfliers=True)
    ax.tick_params(axis="x", labelrotation=35)
elif kind == "comparison_cdf":
    for r in payload["comparison"]["series"]:
        ax.step([c["value"] for c in r["cdf"]],[c["percent_le"] for c in r["cdf"]],where="post",label=r["label"])
    ax.set_ylim(0,100); ax.legend(frameon=False)
elif kind in ("qq", "scatter", "regression", "bland_altman"):
    ax.scatter([r[0] for r in rows], [r[1] for r in rows], s=8, color=color)
    if kind == "scatter" and (payload.get("joint") or {}).get("identity_line"):
        lo = max(min(r[0] for r in rows), min(r[1] for r in rows))
        hi = min(max(r[0] for r in rows), max(r[1] for r in rows))
        if hi > lo: ax.plot([lo, hi], [lo, hi], "--", color="0.5", label="1:1 agreement")
        if hi > lo: ax.legend(frameon=False)
    joint = payload.get("joint") or {}
    if kind == "scatter" and joint.get("identity_line"):
        lo = min(min(r[0] for r in rows), min(r[1] for r in rows))
        hi = max(max(r[0] for r in rows), max(r[1] for r in rows))
        pad = max((hi-lo)*.05,.5) if hi==lo else (hi-lo)*.05
        ax.set_xlim(lo-pad,hi+pad); ax.set_ylim(lo-pad,hi+pad); ax.set_aspect("equal",adjustable="box")
    if kind == "regression" and joint.get("regression"):
        r = joint["regression"]
        xs = [min(v[0] for v in rows),max(v[0] for v in rows)]
        ax.plot(xs,[r["intercept"]+r["slope"]*x for x in xs],"--",color="0.5",label="All-cell least squares")
        ax.legend(frameon=False)
    if kind == "bland_altman" and joint.get("agreement"):
        r = joint["agreement"]
        for key,desc,style in [("bias","Mean difference","-"),("lower","−1.96 SD","--"),("upper","+1.96 SD","--")]:
            ax.axhline(r[key],linestyle=style,color="0.5",label=desc)
        ax.legend(frameon=False)
    summary = payload.get("summary")
    if summary and kind == "qq":
        slope = (summary["q3"]-summary["q1"])/(2*0.6744897501960817)
        ends = [rows[0][0], rows[-1][0]]
        ax.plot(ends, [(summary["q1"]+summary["q3"])/2+slope*x for x in ends], "--", color="0.5", linewidth=0.8)
elif kind.startswith("experiment_"):
    categorical = kind != "experiment_line"
    positions = list(range(len(rows))) if categorical else [r[1] for r in rows]
    values = [float("nan") if r[2] is None else r[2] for r in rows]
    if kind == "experiment_interval":
        for x, row in zip(positions, rows):
            if row[3] is not None and row[4] is not None:
                ax.vlines(x,row[3],row[4],color=color)
                ax.hlines([row[3],row[4]],x-.12,x+.12,color=color)
            if row[2] is not None: ax.scatter(x,row[2],color=color)
            if row[5] is not None: ax.scatter(x,row[5],facecolors="white",edgecolors=color)
    elif kind == "experiment_bar": ax.bar(positions,values,color=color,width=.65)
    elif kind == "experiment_dot": ax.scatter(positions,values,color=color)
    else: ax.plot(positions,values,color=color,marker="o")
    if categorical: ax.set_xticks(positions,[r[0] for r in rows],rotation=35,ha="right")
elif kind in ("class_bar", "class_dot", "metrics"):
    values = [r[1 if kind == "metrics" else measure] for r in rows]
    positions = list(range(len(rows)))
    if kind == "class_dot": ax.scatter(positions, values, s=18, color=color)
    else: ax.bar(positions, values, color=color, width=0.65)
    ax.set_xticks(positions, [r[0] for r in rows], rotation=35, ha="right")
elif kind == "rose":
    values = [r[measure] for r in rows]
    ax.set_theta_zero_location("N"); ax.set_theta_direction(-1)
    ax.bar([math.radians(r[0]) for r in rows], [math.sqrt(v) for v in values],
           width=2*math.pi/max(1,len(rows)), color=color, edgecolor="white", linewidth=0.5)
    maximum = max(values, default=1) or 1
    ticks = [maximum*i/4 for i in range(1,5)]
    ax.set_yticks([math.sqrt(t) for t in ticks], [f"{t:.3g}" for t in ticks])
else:
    ax.plot([r[0] for r in rows], [float("nan") if r[1] is None else r[1] for r in rows], color=color, marker="o" if kind in ("profile", "grade") else None, markersize=2)
if kind != "rose":
    if settings["x_log"] and kind not in ("box", "class_bar", "class_dot", "metrics", "experiment_bar", "experiment_dot", "experiment_interval", "comparison_boxes", "regression", "bland_altman") and not (kind == "scatter" and (payload.get("joint") or {}).get("identity_line")): ax.set_xscale("log")
    if settings["y_log"] and kind not in ("experiment_interval","comparison_cdf","regression","bland_altman") and not (kind == "scatter" and (payload.get("joint") or {}).get("identity_line")): ax.set_yscale("log")
    ax.set_xlabel(settings["x_label"] or table["x_label"])
    ax.set_ylabel(settings["y_label"] or table["y_label"])
ax.set_title(settings["title"])
ax.grid(settings["grid"], alpha=0.2)
fig.tight_layout()
fig.savefig("research-figure.svg")
fig.savefig("research-figure.pdf")
fig.savefig("research-figure.png", dpi=settings["dpi"])
with open("research-figure-provenance.json", "w", encoding="utf-8") as stream:
    json.dump(payload["provenance"], stream, indent=2, ensure_ascii=False)
plt.close(fig)
`;
}
function crc32(bytes:Uint8Array):number{
 let crc=0xffffffff;for(const byte of bytes){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}
 return (crc^0xffffffff)>>>0;
}
export function withPNGDpi(bytes:Uint8Array,dpi:number):Uint8Array{
 const signature=[137,80,78,71,13,10,26,10];
 if(bytes.length<33||!signature.every((b,i)=>bytes[i]===b))throw Error('Invalid PNG image.');
 const chunk=new Uint8Array(21),v=new DataView(chunk.buffer);v.setUint32(0,9);
 chunk.set([112,72,89,115],4);const pixelsPerMeter=Math.round(dpi/0.0254);
 v.setUint32(8,pixelsPerMeter);v.setUint32(12,pixelsPerMeter);chunk[16]=1;v.setUint32(17,crc32(chunk.slice(4,17)));
 const parts:Uint8Array[]=[bytes.slice(0,33),chunk];let offset=33;
 while(offset<bytes.length){
  const size=new DataView(bytes.buffer,bytes.byteOffset+offset).getUint32(0)+12;
  if(size<12||offset+size>bytes.length)throw Error('Invalid PNG chunk.');
  const type=String.fromCharCode(...bytes.slice(offset+4,offset+8));
  if(type!=='pHYs')parts.push(bytes.slice(offset,offset+size));offset+=size;
 }
 const output=new Uint8Array(parts.reduce((n,p)=>n+p.length,0));let position=0;
 for(const p of parts){output.set(p,position);position+=p.length;}return output;
}
export async function exportScenePNG(svg:SVGSVGElement,scene:FigureScene,dpi:number):Promise<Blob>{
 const width=Math.round(scene.width_mm/25.4*dpi),height=Math.round(scene.height_mm/25.4*dpi);
 if(width*height>20_000_000)throw Error('PNG exceeds 20 megapixels. Reduce figure size or DPI.');
 const copy=svg.cloneNode(true) as SVGSVGElement;copy.setAttribute('xmlns','http://www.w3.org/2000/svg');copy.setAttribute('width',String(width));copy.setAttribute('height',String(height));
 const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml'}));
 try{
  const img=await new Promise<HTMLImageElement>((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(Error('Could not render the figure.'));image.src=url;});
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  const ctx=canvas.getContext('2d');if(!ctx)throw Error('Canvas is unavailable.');ctx.drawImage(img,0,0,width,height);
  const blob=await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw Error('PNG encoding failed.');
  return new Blob([new Uint8Array(withPNGDpi(new Uint8Array(await blob.arrayBuffer()),dpi))],{type:'image/png'});
 }finally{URL.revokeObjectURL(url);}
}
