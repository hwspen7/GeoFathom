// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import FigureGallery from './FigureGallery';
import type {PersistedTerrainResult} from './terrainResultStore';
import {plotFixture} from '../testFixtures/figureData';
const mock=vi.hoisted(()=>({getTerrainPlotData:vi.fn(),exportFigurePDF:vi.fn(),saveFigureBlob:vi.fn(),exportScenePNG:vi.fn()}));
vi.mock('./api',()=>({getTerrainPlotData:mock.getTerrainPlotData,exportFigurePDF:mock.exportFigurePDF}));
vi.mock('./figureExport',async original=>({...await original<typeof import('./figureExport')>(),saveFigureBlob:mock.saveFigureBlob,exportScenePNG:mock.exportScenePNG}));
const record={id:'result',title:'Slope map',createdAt:1,geometry:{type:'Polygon',coordinates:[]},operation:'slope_map',source:{id:'dem',name:'Survey',sha256:'a'.repeat(64)},parameters:{gradient_method:'horn'},advanced:{operation:'slope_map',plot_data:plotFixture,metrics:{},quality:{status:'provisional'}}} as unknown as PersistedTerrainResult;
beforeEach(()=>{mock.getTerrainPlotData.mockResolvedValue(plotFixture);mock.exportFigurePDF.mockResolvedValue(new Blob(['%PDF-1.4'],{type:'application/pdf'}));mock.exportScenePNG.mockResolvedValue(new Blob(['png'],{type:'image/png'}));});
afterEach(()=>{cleanup();vi.clearAllMocks();localStorage.clear();});
it('turns a slope result into an actual chart gallery with numerical table export',async()=>{
 render(<FigureGallery record={record} projectId="p" onClose={vi.fn()}/>);
 expect(screen.getByRole('img',{name:'Scientific figure: Histogram'})).toBeTruthy();
 expect(screen.getByRole('combobox',{name:'Chart type'})).toBeTruthy();
 fireEvent.change(screen.getByLabelText('Chart type'),{target:{value:'box'}});
 expect(screen.getByRole('img',{name:'Scientific figure: Box and whisker'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'CSV'}));
 await waitFor(()=>expect(mock.saveFigureBlob).toHaveBeenCalledWith(expect.any(Blob),'terrain-slope_map-box.csv'));
 fireEvent.change(screen.getByLabelText('Chart type'),{target:{value:'scatter'}});
 expect(screen.getByRole('img',{name:'Scientific figure: Elevation–result scatter'})).toBeTruthy();
 fireEvent.click(screen.getByText(/Underlying plot table/));
 expect(screen.getByRole('table').textContent).toContain('elevation_m');
});
it('styles the visible figure and creates vector PDF and physical-resolution PNG exports',async()=>{
 render(<FigureGallery record={record} projectId="p" onClose={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Style'}));
 fireEvent.change(screen.getByLabelText('Figure title'),{target:{value:'Slope distribution at the study site'}});
 fireEvent.change(screen.getByLabelText('Palette'),{target:{value:'blue'}});
 fireEvent.change(screen.getByLabelText('Font'),{target:{value:'serif'}});
 fireEvent.change(screen.getByLabelText('Width (mm)'),{target:{value:'180'}});
 fireEvent.change(screen.getByLabelText('PNG resolution'),{target:{value:'600'}});
 fireEvent.click(screen.getByRole('button',{name:'PDF'}));
 await waitFor(()=>expect(mock.exportFigurePDF).toHaveBeenCalledWith(expect.objectContaining({width_mm:180,title:'Slope distribution at the study site',primitives:expect.any(Array)})));
 expect(mock.exportFigurePDF.mock.calls[0][0]).not.toHaveProperty('note');
 fireEvent.click(screen.getByRole('button',{name:'PNG'}));
 await waitFor(()=>expect(mock.exportScenePNG).toHaveBeenCalledWith(expect.any(SVGSVGElement),expect.objectContaining({width_mm:180}),600));
});
it('saves reusable styles and exposes exact threshold area data',()=>{
 render(<FigureGallery record={{...record,advanced:{...record.advanced!,plot_data:{...plotFixture,thresholds:[{threshold_deg:15,cells_le:2,percent_le:50}]}}}} projectId="p" onClose={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Style'}));
 fireEvent.change(screen.getByLabelText('Style name'),{target:{value:'Paper style'}});fireEvent.click(screen.getByRole('button',{name:'Save style'}));
 expect(localStorage.getItem('geofathom-figure-styles:p')).toContain('Paper style');
 fireEvent.click(screen.getByRole('button',{name:'Data'}));
 fireEvent.change(screen.getByLabelText('Slope area threshold'),{target:{value:'15'}});
 expect(screen.getByRole('status').textContent).toContain('50.000%');
});
it('regenerates numerical data for an old result without silently changing its source',async()=>{
 const old={...record,advanced:{...record.advanced!,plot_data:undefined,raster:{png:'',geotiff:'',legend:[],corners:[],width:1,height:1,valid_cells:1}}} as unknown as PersistedTerrainResult;
 render(<FigureGallery record={old} projectId="p" onClose={vi.fn()}/>);
 await screen.findByRole('img',{name:'Scientific figure: Histogram'});
 expect(mock.getTerrainPlotData).toHaveBeenCalledWith(expect.objectContaining({image_id:'dem',operation:'slope_map',gradient_method:'horn'}),'a'.repeat(64),expect.any(AbortSignal));
});
it('keeps the previous chart available if PDF rendering fails',async()=>{
 mock.exportFigurePDF.mockRejectedValueOnce(new Error('PDF unavailable'));
 const close=vi.fn();render(<FigureGallery record={record} projectId="p" onClose={close}/>);
 fireEvent.click(screen.getByRole('button',{name:'PDF'}));
 expect((await screen.findByRole('alert')).textContent).toContain('PDF unavailable');
 fireEvent.click(screen.getByRole('button',{name:'Close figure library'}));expect(close).toHaveBeenCalledOnce();
});
