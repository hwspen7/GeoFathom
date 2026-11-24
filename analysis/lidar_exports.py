"""Indexed triangle and georeferenced observed-cell exports."""
import base64
import io
import numpy as np

def mesh_obj(table):
    vertices,inv=np.unique(table[:,:9].reshape(-1,3),axis=0,return_inverse=True)
    faces=inv.reshape(-1,3)+1
    out=io.StringIO()
    out.write("# GeoFathom projected XYZ metres; CRS in companion receipt\n")
    for v in vertices:out.write("v "+" ".join(format(x,".17g") for x in v)+"\n")
    for f in faces:out.write("f "+" ".join(str(int(i)) for i in f)+"\n")
    return out.getvalue()

def raster_grid(table,columns,field,size,epsg):
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    x=table[:,columns.index("x_m")];y=table[:,columns.index("y_m")]
    value=table[:,columns.index(field)]
    ix=np.floor(x/size).astype(np.int64);iy=np.floor(y/size).astype(np.int64)
    width=int(ix.max())-int(ix.min())+1;height=int(iy.max())-int(iy.min())+1
    if width*height>2_000_000:return None
    data=np.full((height,width),np.nan,dtype=np.float64)
    data[iy.max()-iy,ix-ix.min()]=value
    transform=from_origin(float(ix.min()*size),float((iy.max()+1)*size),size,size)
    with MemoryFile() as mem:
        with mem.open(driver="GTiff",width=width,height=height,count=1,dtype="float64",crs=f"EPSG:{epsg}",
                transform=transform,nodata=np.nan,compress="deflate") as ds:
            ds.write(data,1);ds.set_band_description(1,field)
        return base64.b64encode(mem.read()).decode("ascii")
