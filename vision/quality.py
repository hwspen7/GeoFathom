"""Sensor-specific quality masks for opt-in remote-sensing workflows.

S2 L2A scene-classification flags are not ML predictions by GeoFathom.
These masks depend on the source product and acquisition processing level.
"""
import numpy as np

SENTINEL_2_L2A_BAD = frozenset((0, 1, 2, 3, 8, 9, 10, 11))
# 0 no data, 1 saturated/defective, 2 dark-area pixels,
# 3 cloud shadow, 8/9 cloud, 10 cirrus, 11 snow/ice.


def sentinel2_clear_mask(scl):
    arr=np.asarray(scl)
    if arr.ndim!=2:
        raise ValueError("Sentinel-2 SCL must be a two-dimensional raster.")
    if not np.issubdtype(arr.dtype,np.integer):
        raise ValueError("Sentinel-2 SCL requires integer class codes.")
    return (np.isin(arr,[4,5,6,7])).astype(bool)


def confusion_matrix(reference,predicted,num_classes,valid=None):
    """Exact pixelwise confusion counts; rows are truth, columns predicted."""
    truth=np.asarray(reference)
    observed=np.asarray(predicted)
    if (truth.shape!=observed.shape or truth.ndim!=2 or
            not isinstance(num_classes,int) or not 2<=num_classes<=64):
        raise ValueError("Prediction/reference shape or class count is invalid.")
    mask=(np.ones(truth.shape,bool) if valid is None else
          np.asarray(valid,bool))
    if mask.shape!=truth.shape:
        raise ValueError("Validation mask does not match label grid.")
    t=truth[mask]
    p=observed[mask]
    if (not np.issubdtype(t.dtype,np.integer)
            or not np.issubdtype(p.dtype,np.integer)
            or np.any(t<0) or np.any(p<0)
            or np.any(t>=num_classes) or np.any(p>=num_classes)):
        raise ValueError("Class labels must be integers within the manifest.")
    return np.bincount(t.astype(np.int64)*num_classes+
                       p.astype(np.int64),
                       minlength=num_classes*num_classes).reshape(
                           num_classes,num_classes)


def metrics_from_matrix(matrix,classes):
    values=np.asarray(matrix,dtype=np.int64)
    if (values.shape!=(len(classes),len(classes))
            or not np.all(values>=0)):
        raise ValueError("Invalid confusion matrix.")
    tp=np.diag(values)
    truth=values.sum(axis=1)
    predicted=values.sum(axis=0)
    union=truth+predicted-tp
    iou=np.divide(tp,union,out=np.zeros(len(classes),float),
                  where=union!=0)
    precision=np.divide(tp,predicted,out=np.zeros(len(classes),float),
                        where=predicted!=0)
    recall=np.divide(tp,truth,out=np.zeros(len(classes),float),
                     where=truth!=0)
    f1=np.divide(2*precision*recall,precision+recall,
                 out=np.zeros(len(classes),float),
                 where=(precision+recall)!=0)
    return {
        "confusion_matrix":values.tolist(),
        "classes":[{
            "name":str(classes[i]),
            "support":int(truth[i]),"predicted":int(predicted[i]),
            "iou":float(iou[i]),"precision":float(precision[i]),
            "recall":float(recall[i]),"f1":float(f1[i])
        } for i in range(len(classes))],
        "overall_accuracy":float(tp.sum()/values.sum())
                           if values.sum() else None,
        "mean_iou_present_classes":float(iou[union>0].mean())
                                   if np.any(union>0) else None,
        "valid_pixels":int(values.sum()),
        "absent_class_policy":"Excluded from mean IoU, reported as zero per class",
    }
