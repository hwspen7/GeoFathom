"""Two-track radar line-of-sight displacement decomposition and uncertainty."""
import numpy as np

LOS_IDS={"insar_east_displacement","insar_up_displacement","insar_east_sd","insar_up_sd","insar_east_up_correlation","insar_geometry_condition"}

def decompose(v,p,kind):
    """Solve for east/up using local ENU look vectors and a declared north prior.

    LOS values are positive toward the sensor. Sensor-facing azimuth is
    clockwise from true north; incidence is measured from local vertical.
    North is prescribed, not retrieved. The north error is independent of
    the two LOS measurement errors; look-vector errors are not modeled.
    """
    good=np.logical_and.reduce([np.isfinite(z) for z in v.values()])
    good &= (v["first_sd"]>0)&(v["second_sd"]>0)
    t1,t2,a1,a2=[np.deg2rad(v[k]) for k in ("first_incidence","second_incidence","first_azimuth","second_azimuth")]
    e1,e2=np.sin(t1)*np.sin(a1),np.sin(t2)*np.sin(a2)
    n1,n2=np.sin(t1)*np.cos(a1),np.sin(t2)*np.cos(a2)
    u1,u2=np.cos(t1),np.cos(t2)
    determinant=e1*u2-e2*u1
    # For a 2x2 matrix, kappa_2=lambda_max(A^T A)/abs(det A).
    trace=e1*e1+e2*e2+u1*u1+u2*u2
    maximum=.5*(trace+np.sqrt(np.maximum(0.,trace*trace-4*determinant*determinant)))
    condition=np.divide(maximum,np.abs(determinant),out=np.full(trace.shape,np.inf),where=np.abs(determinant)>1e-12)
    valid=good&np.isfinite(condition)&(condition<=p["max_condition"])
    out=np.full(trace.shape,np.nan)
    if kind=="insar_geometry_condition":
        # Preserve finite, poorly conditioned values as geometry diagnostics.
        diag=good&np.isfinite(condition);out[diag]=condition[diag]
    else:
        d=determinant[valid]
        a,b,c,f=u2[valid]/d,-u1[valid]/d,-e2[valid]/d,e1[valid]/d
        l1=v["first_los"][valid]-n1[valid]*p["north_m"]
        l2=v["second_los"][valid]-n2[valid]*p["north_m"]
        east=a*l1+b*l2;up=c*l1+f*l2
        s1=v["first_sd"][valid];s2=v["second_sd"][valid];ns=p["north_sd_m"]**2
        v11=s1*s1+ns*n1[valid]**2;v22=s2*s2+ns*n2[valid]**2
        v12=p["los_correlation"]*s1*s2+ns*n1[valid]*n2[valid]
        ve=np.maximum(0,a*a*v11+b*b*v22+2*a*b*v12)
        vu=np.maximum(0,c*c*v11+f*f*v22+2*c*f*v12)
        ceu=a*c*v11+b*f*v22+(a*f+b*c)*v12
        correlation=np.divide(ceu,np.sqrt(ve*vu),out=np.full(ve.shape,np.nan),where=(ve>0)&(vu>0))
        products={"insar_east_displacement":east,"insar_up_displacement":up,"insar_east_sd":np.sqrt(ve),
                  "insar_up_sd":np.sqrt(vu),"insar_east_up_correlation":np.clip(correlation,-1,1)}
        out[valid]=products[kind]
    return out,{"valid_geometry_cells":int(valid.sum()),"missing_or_invalid_input_cells":int((~good).sum()),
        "ill_conditioned_cells":int((good&~valid).sum()),"max_condition":p["max_condition"],
        "north_m":p["north_m"],"north_sd_m":p["north_sd_m"],"los_correlation":p["los_correlation"],
        "assumption":"same epoch interval and spatial reference; LOS positive toward sensor; local ENU geometry; north prescribed; conditional error propagation, not unconstrained 3D displacement"}
