"""Table-based basic, hydrological, temporal, and environmental figures."""
import math
import numpy as np
from .studio_data import FigureInputError, regular_series, linear_fit
from .studio_publication import numeric_rows

def require(ok,message):
    if not ok:raise FigureInputError(message)

def ratio(a,b):
    return np.divide(a,b,out=np.full(np.broadcast_shapes(np.shape(a),np.shape(b)),np.nan),where=np.asarray(b)!=0)

def ranks(a):
    order=np.argsort(a,kind='stable');out=np.zeros(len(a));i=0
    while i<len(a):
        j=i+1
        while j<len(a) and a[order[j]]==a[order[i]]:j+=1
        out[order[i:j]]=(i+j+1)/2;i=j
    return out

def table_matrix(table,req,rows):
    require(2<=len(req.columns)<=12,'Choose two to twelve numeric columns.')
    a,_=rows(req.columns);return np.column_stack(a)

def render_table_domain(kind,req,fig,ax,table,parameter,meta,palette,cmap,rows):
    from matplotlib.colors import Normalize
    derived=[]
    def save(headers,*arrays):
        derived.clear();derived.extend(numeric_rows(headers,*arrays))
    def xy(regular=False,ordered=True):
        a,_=rows([req.x,req.y]);x,y=a
        if ordered:
            require(len(x)>=2,'At least two observations are required.')
            if regular:require(len(x)==len(table.rows),'Regular series must retain all observations.')
            return regular_series(x,y,regular)
        return x,y
    def setxy(x,y):ax.set(xlabel=x,ylabel=y)
    def complete():
        require(meta['used_count']==len(table.rows),'Supply complete observations for this method.')
    def integer(v,limit):
        require(float(v).is_integer() and 1<=v<=limit,'Choose an integer parameter within the data length.');return int(v)
    color=palette[0]
    if kind.startswith('basic_'):
        if kind in {'basic_rank','basic_lorenz'}:
            a,_=rows([req.y]);v=np.sort(a[0])
            if kind=='basic_rank':
                v=v[::-1];rank=np.arange(1,len(v)+1);ax.plot(rank,v,marker='o' if req.show_points and len(v)<=100 else None)
                setxy('Descending rank',req.y);save(['rank',req.y],rank,v)
            else:
                require(np.all(v>=0) and v.sum()>0,'Lorenz shares require nonnegative values and positive total.')
                population=np.arange(len(v)+1)/len(v);share=np.r_[0,np.cumsum(v)/v.sum()]
                ax.plot(population,share,label='Observed');ax.plot([0,1],[0,1],'--',color='gray',label='Equal share')
                ax.set(xlim=(0,1),ylim=(0,1));ax.legend(frameon=False)
                setxy('Cumulative population fraction','Cumulative value fraction')
                meta['gini']=float(1-np.sum(np.diff(population)*(share[:-1]+share[1:])))
                save(['population_fraction','value_fraction'],population,share)
        elif kind=='basic_group_summary':
            a,c=rows([req.y],[req.group]);v=a[0];groups=c[0];names=list(dict.fromkeys(groups))
            require(len(names)<=24,'Maximum 24 groups.')
            counts=np.array([(groups==n).sum() for n in names]);means=np.array([v[groups==n].mean() for n in names])
            sd=np.array([v[groups==n].std(ddof=1) if k>1 else np.nan for n,k in zip(names,counts)])
            positions=np.arange(len(names));ax.scatter(positions,means,zorder=3)
            valid=np.isfinite(sd)
            if valid.any():ax.errorbar(positions[valid],means[valid],yerr=sd[valid],fmt='none',capsize=3)
            ax.set_xticks(positions,names,rotation=35,ha='right');setxy(req.group,req.y+' (mean ± sample SD)')
            meta['method_note']='Descriptive sample standard deviation, not a confidence interval. Singleton groups have undefined SD.'
            save(['group','count','mean','sample_sd'],names,counts,means,sd)
        elif kind in {'basic_line','basic_area','basic_running_total','basic_index'}:
            x,y=xy()
            if kind=='basic_line':ax.plot(x,y,marker='o' if req.show_points else None,markersize=3);v=y
            elif kind=='basic_area':ax.fill_between(x,0,y,alpha=.35);ax.plot(x,y);v=y
            elif kind=='basic_index':
                require(y[0]!=0,'Baseline index requires a nonzero first observation.');v=100*y/y[0];ax.plot(x,v);ax.axhline(100,color='gray',linestyle='--');meta['baseline_value']=float(y[0]);meta['baseline_x']=float(x[0])
            else:v=np.cumsum(y);ax.plot(x,v)
            setxy(req.x,'Running sum' if kind=='basic_running_total' else 'Index (first = 100)' if kind=='basic_index' else req.y);save([req.x,'value'],x,v)
        elif kind=='basic_scatter':
            x,y=xy(ordered=False);ax.scatter(x,y,s=12,alpha=.65);setxy(req.x,req.y);save([req.x,req.y],x,y)
        elif kind=='basic_category_count':
            labels=table.labels(req.group);labels=labels[labels!=''];require(len(labels)>0,'No categories.')
            names,counts=np.unique(labels,return_counts=True);require(len(names)<=50,'Maximum 50 categories.')
            ax.bar(np.arange(len(names)),counts);ax.set_xticks(range(len(names)),names,rotation=35,ha='right');setxy(req.group,'Frequency');meta['used_count']=len(labels);save([req.group,'count'],names,counts)
        elif kind=='basic_frequency_polygon':
            a,_=rows([req.y]);v=a[0];c,e=np.histogram(v,bins=min(30,max(2,int(np.sqrt(len(v))))));x=(e[:-1]+e[1:])/2
            ax.plot(x,c,marker='o');setxy(req.y,'Frequency');save(['bin_midpoint','count'],x,c)
        elif kind=='basic_table_heatmap':
            a,c=rows(req.columns,[req.x]);labels=c[0];m=np.column_stack(a);require(len(m)<=80,'Maximum 80 rows.')
            im=ax.imshow(m,aspect='auto',cmap=cmap);fig.colorbar(im,ax=ax,label='Value');ax.set_xticks(range(len(a)),req.columns,rotation=35,ha='right');ax.set_yticks(range(len(labels)),labels);save([req.x,*req.columns],labels,*a)
        elif kind=='basic_stacked_area':
            a,_=rows([req.x,*req.columns]);x,*ys=a;order=np.argsort(x);x=x[order];ys=np.array(ys)[:,order]
            require(len(x)>=2 and np.all(np.diff(x)>0) and np.all(ys>=0),'Stacked area requires unique X and nonnegative compatible series.')
            ax.stackplot(x,*ys,labels=req.columns,alpha=.8);ax.legend(frameon=False);setxy(req.x,'Combined value');save([req.x,*req.columns],x,*ys)
        else:
            a,c=rows([req.y]+([req.z] if kind=='basic_paired_change' else []),[req.x]);labels=c[0];v=a[0];require(len(v)<=50 and len(set(labels))==len(labels),'Use up to 50 unique categories.')
            pos=np.arange(len(v))
            if kind=='basic_column':ax.bar(pos,v);save([req.x,req.y],labels,v)
            elif kind=='basic_waterfall':
                start=np.r_[0,np.cumsum(v)[:-1]];ax.bar(pos,v,bottom=start,color=[palette[0] if a>=0 else palette[1] for a in v]);ax.axhline(0,color='gray');save([req.x,'increment','running_total'],labels,v,np.cumsum(v))
            elif kind=='basic_paired_change':
                for i,name in enumerate(labels):ax.plot([0,1],[v[i],a[1][i]],marker='o',label=name)
                ax.set_xticks([0,1],[req.y,req.z]);ax.set_ylabel('Value (compatible units)');save([req.x,req.y,req.z,'change'],labels,v,a[1],a[1]-v)
                if len(v)<=10:ax.legend(frameon=False,fontsize=7)
                return derived
            else:
                require(np.all(v>=0) and v.sum()>0,'Pareto frequency needs nonnegative counts and positive total.')
                idx=np.argsort(-v,kind='stable');v=v[idx];labels=labels[idx];p=100*np.cumsum(v)/v.sum()
                ax.bar(pos,v);right=ax.twinx();right.plot(pos,p,color=palette[1],marker='o');right.set_ylim(0,105);right.set_ylabel('Cumulative (%)');save([req.x,req.y,'cumulative_percent'],labels,v,p)
            ax.set_xticks(pos,labels,rotation=35,ha='right');setxy(req.x,req.y)
    elif kind.startswith('spectral_'):
        if kind=='spectral_signature':
            a,_=rows([req.x,*req.columns]);x,*ys=a;order=np.argsort(x);x=x[order];ys=np.array(ys)[:,order]
            require(np.all(np.diff(x)>0) and np.all((ys>=0)&(ys<=1)),'Use unique wavelengths and physical reflectance [0,1].')
            for name,y in zip(req.columns,ys):ax.plot(x,y,label=name)
            ax.legend(frameon=False);setxy(req.x,'Reflectance');save([req.x,*req.columns],x,*ys)
        elif kind=='spectral_band_separability':
            a,c=rows(req.columns,[req.group]);m=np.column_stack(a);labels=c[0];names=np.unique(labels)
            require(len(names)==2 and np.all((m>=0)&(m<=1)),'Select exactly two labeled classes and reflectance bands in [0,1].')
            first,second=[m[labels==label] for label in names]
            require(len(first)>=2 and len(second)>=2,'Each class needs at least two samples.')
            value=ratio((first.mean(axis=0)-second.mean(axis=0))**2,first.var(axis=0,ddof=1)+second.var(axis=0,ddof=1))
            require(np.isfinite(value).any(),'No bands with defined within-class variation.')
            ax.bar(range(len(value)),value);ax.set_xticks(range(len(value)),req.columns,rotation=35,ha='right');setxy('Band','Fisher separability')
            save(['band','fisher_separability'],req.columns,value)
        else:
            x,y=xy();require(np.all((y>=0)&(y<=1)),'Use physical reflectance [0,1].')
            if kind=='spectral_derivative':v=np.gradient(y,x);setxy(req.x,'Reflectance derivative')
            else:
                # Upper convex hull of the spectral envelope.
                hull=[]
                for i in range(len(x)):
                    while len(hull)>=2:
                        a,b=hull[-2:];cross=(x[b]-x[a])*(y[i]-y[b])-(y[b]-y[a])*(x[i]-x[b])
                        if cross<0:break
                        hull.pop()
                    hull.append(i)
                continuum=np.interp(x,x[hull],y[hull]);v=ratio(y,continuum);require(np.isfinite(v).any(),'Undefined spectral continuum.');setxy(req.x,'Continuum-removed reflectance')
            ax.plot(x,v);save([req.x,'derived'],x,v)
    elif kind.startswith('hydro_'):
        if kind=='hydro_duration':
            a,_=rows([req.y]);v=np.sort(a[0])[::-1];require(np.all(v>=0),'Discharge cannot be negative.')
            p=100*np.arange(1,len(v)+1)/(len(v)+1);ax.plot(p,v);setxy('Exceedance probability (%)',req.y);save(['exceedance_percent','discharge'],p,v)
        elif kind in {'hydro_runoff','hydro_flashiness'}:
            if kind=='hydro_runoff':
                a,_=rows([req.x,req.y,req.z]);x,y,z=a;complete();order=np.argsort(x);x,y,z=[v[order] for v in a];require(np.all(np.diff(x)>0) and np.all(y>=0) and np.all(z>=0),'Time must be unique; rainfall and discharge nonnegative.')
                ax.plot(x,y,label='Observed flow' if req.hydrology_mode=='calibrated_reservoir' else req.y)
                right=ax.twinx();right.bar(x,z,width=np.min(np.diff(x))*.65,color=palette[1],alpha=.26);right.invert_yaxis();right.set_ylabel(req.z);setxy(req.x,req.y)
                if req.hydrology_mode=='calibrated_reservoir':
                    from .studio_calibrated_models import calibrate_reservoir
                    require(len(x)>=20 and np.allclose(np.diff(x),np.diff(x)[0],rtol=1e-7,atol=1e-10),'Reservoir calibration requires regularly spaced observations.')
                    q,s,diagnostics=calibrate_reservoir(z,y,req.training_fraction)
                    n=diagnostics['training_count'];ax.plot(x,q,color=palette[2],label='Simulated flow')
                    ax.axvline(x[n],linestyle='--',color='#555555',label='Validation begins')
                    ax.legend(frameon=False);meta['calibration']=diagnostics
                    meta['method_note']='Conservative single-reservoir rainfall-runoff model; observed runoff and rainfall must both be depth per time step in identical units. Chronological holdout; initial storage zero.'
                    save([req.x,'observed_depth','rainfall_depth','simulated_depth','storage_depth','period'],x,y,z,q,s,np.where(np.arange(len(x))<n,'training','validation'))
                else:save([req.x,req.y,req.z],x,y,z)
            else:
                a,c=rows([req.x,req.y],[req.group]);complete();x,y=a;groups=c[0];require(np.all(y>=0),'Discharge cannot be negative.')
                names=[];values=[]
                for label in dict.fromkeys(groups):
                    t,q=regular_series(x[groups==label],y[groups==label],True);require(q.sum()>0,'Flashiness requires positive total flow.');names.append(label);values.append(np.abs(np.diff(q)).sum()/q.sum())
                ax.bar(range(len(names)),values);ax.set_xticks(range(len(names)),names,rotation=35);setxy(req.group,'Flashiness index');save([req.group,'flashiness'],names,values)
        else:
            x,y=xy(ordered=kind not in {'hydro_peak','hydro_rating','hydro_double_mass'});require(np.all(y>=0),'Discharge/elevation input must be nonnegative for this recipe.')
            if kind=='hydro_mass':
                v=np.r_[0,np.cumsum(np.diff(x)*(y[:-1]+y[1:])/2)];ax.plot(x,v);setxy('Time (s)','Cumulative volume (m³)');save([req.x,'volume_m3'],x,v)
            elif kind=='hydro_recession':
                valid=(y[1:]<y[:-1])&(y[:-1]>0)&(y[1:]>0);require(valid.any(),'No declining positive flows.')
                q=y[:-1][valid];decay=np.log(y[:-1][valid]/y[1:][valid])/np.diff(x)[valid];ax.scatter(q,decay,s=18);setxy('Initial discharge','Log recession rate / time');save(['initial_discharge','log_decay_rate'],q,decay)
            elif kind=='hydro_peak':
                years=np.unique(x);require(len(years)>=2,'At least two supplied years required.')
                maxima=np.sort([y[x==v].max() for v in years])[::-1];period=(len(maxima)+1)/np.arange(1,len(maxima)+1);ax.semilogx(period,maxima,marker='o');setxy('Empirical return period (years)','Annual maximum discharge');save(['return_period','annual_maximum'],period,maxima)
            elif kind=='hydro_rating':
                require(np.all(x>0) and np.all(y>0),'Power-law rating requires positive supplied stage above reference and discharge.')
                fit,_,b,c=linear_fit(np.log(x),np.log(y));xx=np.geomspace(x.min(),x.max(),100);ax.scatter(x,y,s=15);ax.plot(xx,np.exp(c)*xx**b);ax.set_xscale('log');ax.set_yscale('log');setxy(req.x,req.y);meta.update(power_exponent=b,log_coefficient=c);save([req.x,req.y,'fitted'],x,y,np.exp(fit))
            elif kind=='hydro_double_mass':
                require(np.all(x>=0),'Reference observations cannot be negative.')
                # Rows are chronological; do not sort by reference magnitude.
                a,_=rows([req.x,req.y]);u,v=np.cumsum(a[0]),np.cumsum(a[1]);ax.plot(u,v);setxy('Cumulative '+req.x,'Cumulative '+req.y);save(['reference_total','observed_total'],u,v)
            elif kind=='hydro_baseflow':
                x,y=regular_series(x,y,True);complete();quick=np.zeros(len(y))
                for i in range(1,len(y)):quick[i]=np.clip(parameter*quick[i-1]+(1+parameter)/2*(y[i]-y[i-1]),0,y[i])
                base=y-quick;ax.plot(x,y,label='Observed');ax.plot(x,base,label='Filtered baseflow');ax.legend(frameon=False);setxy(req.x,req.y);save([req.x,'flow','baseflow','quickflow'],x,y,base,quick)
            else:
                grade=-np.diff(y)/np.diff(x);ax.plot((x[:-1]+x[1:])/2,grade);setxy('River chainage','Downstream gradient');save(['chainage_mid','gradient'],(x[:-1]+x[1:])/2,grade)
    elif kind.startswith('time_') or kind.startswith('climate_'):
        if kind=='climate_wind_rose':
            a,_=rows([req.x,req.y]);direction,speed=a;require(np.all((direction>=0)&(direction<=360)&(speed>=0)),'Direction 0–360°, speed nonnegative.')
            fig.delaxes(ax);ax=fig.add_subplot(111,projection='polar');ax.set_theta_zero_location('N');ax.set_theta_direction(-1)
            dirs=np.floor(((direction+11.25)%360)/22.5).astype(int);edges=np.array([0,2,5,10,20,np.inf]);bottom=np.zeros(16)
            for i in range(len(edges)-1):
                mask=(speed>0)&(speed>=edges[i])&(speed<edges[i+1]);freq=100*np.bincount(dirs[mask],minlength=16)/len(speed)
                label=f'{edges[i]:g}–{edges[i+1]:g}';ax.bar(np.arange(16)*np.pi/8,freq,width=np.pi/8*.9,bottom=bottom,label=label,color=palette[i]);bottom+=freq
                if not derived:derived.append(['direction_deg','speed_lower','speed_upper','percent'])
                derived.extend([[j*22.5,float(edges[i]),None if not np.isfinite(edges[i+1]) else float(edges[i+1]),float(v)] for j,v in enumerate(freq)])
            ax.legend(frameon=False,bbox_to_anchor=(1.25,1));meta['calm_percent']=float(100*(speed==0).mean())
        elif kind=='climate_rain_days':
            a,c=rows([req.y],[req.group]);v=a[0];labels=c[0];require(np.all(v>=0),'Rainfall cannot be negative.')
            names=list(dict.fromkeys(labels));p=[100*np.mean(v[labels==n]>=parameter) for n in names];ax.bar(range(len(names)),p);ax.set_xticks(range(len(names)),names,rotation=35);setxy(req.group,'Wet observations (%)');save([req.group,'wet_percent'],names,p)
        elif kind=='time_crosscorr':
            a,_=rows([req.x,req.y,req.z]);complete();x,y,z=a;order=np.argsort(x);x,y,z=[v[order] for v in a];regular_series(x,y,True)
            n=integer(parameter,len(y)-2);lags=np.arange(-n,n+1);values=[]
            for k in lags:
                v,w=(y[-k:],z[:k]) if k<0 else (y[:-k],z[k:]) if k>0 else (y,z)
                values.append(np.corrcoef(v,w)[0,1] if v.std()>0 and w.std()>0 else np.nan)
            require(np.isfinite(values).any(),'No defined lag correlations.');ax.plot(lags,values,marker='o');ax.axhline(0,color='gray');setxy('Lag (samples)','Pearson correlation');save(['lag','correlation'],lags,values)
        else:
            x,y=xy(regular=kind in {'time_rolling_sd','time_rolling_quantile','time_periodogram','time_seasonal_box','climate_degree_days'})
            if kind=='time_difference':x,v=x[1:],np.diff(y);label='First difference'
            elif kind=='time_growth':x,v=x[1:],100*ratio(np.diff(y),np.abs(y[:-1]));label='Relative change (%)'
            elif kind in {'time_rolling_sd','time_rolling_quantile'}:
                n=integer(parameter,len(y));window=np.lib.stride_tricks.sliding_window_view(y,n);x=x[n-1:]
                if kind=='time_rolling_sd':v=window.std(axis=1,ddof=1);label='Rolling sample SD'
                else:
                    lo,v,hi=np.quantile(window,[.25,.5,.75],axis=1);ax.fill_between(x,lo,hi,alpha=.25);ax.plot(x,v);setxy(req.x,'Rolling median / IQR');save([req.x,'q1','median','q3'],x,lo,v,hi);return derived
            elif kind=='time_cusum':v=np.cumsum(y-y.mean());label='Cumulative centered deviation'
            elif kind=='time_ewma':
                v=np.empty_like(y);v[0]=y[0]
                for i in range(1,len(y)):v[i]=parameter*y[i]+(1-parameter)*v[i-1]
                ax.plot(x,y,alpha=.25);label='Exponentially weighted mean'
            elif kind=='time_periodogram':
                x=np.fft.rfftfreq(len(y),d=x[1]-x[0]);v=np.abs(np.fft.rfft(y-y.mean()))**2/len(y);x,v=x[1:],v[1:];label='Squared Fourier amplitude / N';ax.plot(x,v);setxy('Frequency (cycles / time unit)',label);save(['frequency','power'],x,v);return derived
            elif kind=='time_seasonal_box':
                n=integer(parameter,len(y)//2);phase=np.arange(len(y))%n;groups=[y[phase==i] for i in range(n)];ax.boxplot(groups);setxy('Phase',req.y);save(['phase','value'],phase+1,y);return derived
            elif kind=='time_trend_residual':_,v,_,_=linear_fit(x,y);label='Trend residual'
            elif kind in {'climate_anomaly','climate_warming_stripes'}:
                n=integer(parameter,len(y));ref=y[:n];v=y-ref.mean();meta['reference_count']=n;meta['reference_mean']=float(ref.mean())
                if kind=='climate_anomaly':
                    require(ref.std(ddof=1)>0,'Reference standard deviation must be positive.');v=v/ref.std(ddof=1);label='Standardized anomaly'
                else:
                    lim=max(np.max(np.abs(v)),1e-12);ax.scatter(x,np.zeros(len(x)),c=v,cmap='RdBu_r',norm=Normalize(-lim,lim),marker='s',s=80);fig.colorbar(ax.collections[0],ax=ax,label='Anomaly');ax.set_yticks([]);setxy(req.x,'');save([req.x,'anomaly'],x,v);return derived
            elif kind=='climate_degree_days':
                require(np.allclose(np.diff(x),1),'Degree-days require daily time coordinates with one-day steps.')
                heat=np.cumsum(np.maximum(parameter-y,0));cool=np.cumsum(np.maximum(y-parameter,0));ax.plot(x,heat,label='Heating');ax.plot(x,cool,label='Cooling');ax.legend(frameon=False);setxy(req.x,'Degree-days');save([req.x,'heating','cooling'],x,heat,cool);return derived
            elif kind=='climate_exceedance_days':v=np.cumsum(y>parameter);label='Cumulative exceedance count'
            else:raise FigureInputError('Unimplemented time recipe.')
            require(np.isfinite(v).any(),'No finite derived observations.');ax.plot(x,v);setxy(req.x,label);save([req.x,'derived'],x,v)
    else:
        from .studio_domain_model import render_model
        return render_model(kind,req,fig,ax,table,parameter,meta,palette,cmap,rows)
    return derived
