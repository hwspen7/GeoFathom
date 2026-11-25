"""Overlap-save planning: infer with context, retain each core once."""
from dataclasses import dataclass
from rasterio.windows import Window

@dataclass(frozen=True)
class ContextTile:
    core: Window
    read: Window
    input_row: int
    input_col: int
    crop: tuple

def context_tiles(width,height,size,halo=0):
    if any(type(x) is not int for x in (width,height,size,halo)) or (
            min(width,height,size)<1 or not 0<=halo<size/2):
        raise ValueError("Invalid contextual tile dimensions.")
    stride=size-2*halo
    for row in range(0,height,stride):
        for col in range(0,width,stride):
            h=min(stride,height-row)
            w=min(stride,width-col)
            top,left=row-halo,col-halo
            y,x=max(0,top),max(0,left)
            bottom,right=min(height,top+size),min(width,left+size)
            yield ContextTile(Window(col,row,w,h),
                Window(x,y,right-x,bottom-y),y-top,x-left,
                (slice(halo,halo+h),slice(halo,halo+w)))
