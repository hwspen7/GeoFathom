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


def context_tiles_for_window(source_width, source_height, size, halo, left, top, width, height):
    """Source-anchored overlap-save tiles clipped to a requested output window.

    Read windows and input padding are identical to full-scene inference.
    Only the retained core is clipped; core offsets are relative to the output.
    """
    if (any(type(x) is not int for x in
            (source_width, source_height, size, halo, left, top, width, height))
            or min(source_width, source_height, size, width, height) < 1
            or not 0 <= halo < size/2 or left < 0 or top < 0
            or left+width > source_width or top+height > source_height):
        raise ValueError("Invalid source-anchored context window.")
    stride = size-2*halo
    for row in range(top//stride*stride, top+height, stride):
        for col in range(left//stride*stride, left+width, stride):
            y0, x0 = max(top, row), max(left, col)
            y1 = min(top+height, row+stride)
            x1 = min(left+width, col+stride)
            read_top, read_left = row-halo, col-halo
            y, x = max(0, read_top), max(0, read_left)
            bottom = min(source_height, read_top+size)
            right = min(source_width, read_left+size)
            yield ContextTile(Window(x0-left, y0-top, x1-x0, y1-y0),
                              Window(x, y, right-x, bottom-y),
                              y-read_top, x-read_left,
                              (slice(y0-read_top, y1-read_top),
                               slice(x0-read_left, x1-read_left)))
