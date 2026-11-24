import type {PlotData} from '../src/api';
export const plotFixture:PlotData={schema:'test',kind:'continuous',operation:'slope_map',quantity:'Slope angle',unit:'degree',valid_cells:4,cell_area_m2:100,population:'all_finite_exported_raster_cells',notes:[],metrics:{product_min:0,product_max:30,cut_m3:100,fill_m3:50,product_valid_cells:4},
 classes:[{label:'0–15°',cells:2,area_m2:200,percent:50,color:'#aaa'},{label:'15–30°',cells:2,area_m2:200,percent:50,color:'#333'}],
 histograms:{'10':[{lower:0,upper:15,midpoint:7.5,cells:2,area_m2:200,percent:50,density:1/30,cumulative_pct:50},{lower:15,upper:30,midpoint:22.5,cells:2,area_m2:200,percent:50,density:1/30,cumulative_pct:100}]},
 cdf:[{value:0,cells_le:1,percent_le:25},{value:10,cells_le:2,percent_le:50},{value:20,cells_le:3,percent_le:75},{value:30,cells_le:4,percent_le:100}],
 quantiles:[{probability:0,value:0},{probability:.25,value:7.5},{probability:.5,value:15},{probability:.75,value:22.5},{probability:1,value:30}],
 normal_qq:[{probability:.1,normal_quantile:-1.28,observed_quantile:3},{probability:.5,normal_quantile:0,observed_quantile:15},{probability:.9,normal_quantile:1.28,observed_quantile:27}],
 summary:{minimum:0,maximum:30,mean:15,population_std:11.1803398875,q1:7.5,median:15,q3:22.5,iqr:15},
 box:{whisker_low:0,q1:7.5,median:15,q3:22.5,whisker_high:30,lower_outliers:0,upper_outliers:0},
 joint:{x_quantity:'Elevation',x_unit:'m',y_quantity:'Slope angle',y_unit:'degree',population_cells:4,sample_cells:2,sampling:'every_kth_valid_cell_in_grid_order',pearson_r:1,samples:[{x:100,y:0},{x:120,y:20}],density_cells:[{x_lower:100,x_upper:110,y_lower:0,y_upper:15,cells:2,area_m2:200},{x_lower:110,x_upper:120,y_lower:15,y_upper:30,cells:2,area_m2:200}],notes:[]}};
