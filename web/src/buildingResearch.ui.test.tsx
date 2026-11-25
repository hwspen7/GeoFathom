// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import BuildingResearchPanel from './BuildingResearchPanel';
import type {VisionModel} from './api';

const api=vi.hoisted(()=>({getBuildingResearch:vi.fn(),uploadBuildingStudy:vi.fn(),queueGISJob:vi.fn(),
  getGISJob:vi.fn(),cancelGISJob:vi.fn(),installBuildingModel:vi.fn(),downloadBuildingArtifact:vi.fn()}));
vi.mock('./api',()=>api);
const dataset={id:'a'.repeat(64),counts:{train:48,validation:8,test:16},regions:{train:['Austin','Vienna'],validation:['Chicago'],test:['Kitsap','Tyrol']}};
const models=[{id:'base',task:'building_extraction',trainable:true},{id:'adapted',task:'building_extraction',trainable:true}] as VisionModel[];
const change=(label:string,value:string)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
beforeEach(()=>{vi.resetAllMocks();api.getBuildingResearch.mockResolvedValue({datasets:[dataset],training_runtime_available:true,test_policy:'validation only'});});
afterEach(cleanup);

it('keeps city roles explicit and installs the completed validation-selected model',async()=>{
  const installed=vi.fn();
  api.queueGISJob.mockResolvedValue({id:'fit',kind:'building_train',status:'completed',progress:100,result:{
    kind:'building_train',best_epoch:3,initial_validation_loss:2,selected_validation_loss:1,test_used_for_training:false,device:'cpu'}});
  api.installBuildingModel.mockResolvedValue({model_id:'trained',installed:true});
  render(<BuildingResearchPanel projectId="project" token="admin" models={models} onInstalled={installed}/>);
  await screen.findByText(/Training: Austin, Vienna/);
  change('Building training epochs','3');change('Building adaptation scope','decoder');
  fireEvent.click(screen.getByText('Train or fine-tune a model'));
  fireEvent.click(screen.getByRole('button',{name:'Train building model'}));
  await waitFor(()=>expect(api.queueGISJob).toHaveBeenCalledWith('project','building_train',{
    dataset_id:dataset.id,training:{initial_model_id:'base',mode:'decoder',epochs:3,learning_rate:.001,device:'cpu'}},'admin'));
  await screen.findByText('Test data used for training: no · device: cpu.');
  fireEvent.click(screen.getByRole('button',{name:'Install trained building model'}));
  await waitFor(()=>expect(installed).toHaveBeenCalledOnce());
  expect(api.installBuildingModel).toHaveBeenCalledWith('project','fit','admin');
});

it('defaults comparison to validation and makes final test evaluation explicit',async()=>{
  api.queueGISJob.mockResolvedValue({id:'compare',kind:'building_compare',status:'completed',progress:100,result:{
    kind:'building_compare',test_evaluated:false,validation:{base:{classes:[{name:'building',f1:.8,iou:.7,recall:.9}],objects_50:{f1:.6}}}}});
  render(<BuildingResearchPanel projectId="project" token="admin" models={models} onInstalled={vi.fn()}/>);
  await screen.findByText(/Training: Austin, Vienna/);
  fireEvent.click(screen.getByText('Compare models and validate instances'));
  fireEvent.click(screen.getByRole('button',{name:'Compare building models'}));
  await waitFor(()=>expect(api.queueGISJob).toHaveBeenCalledWith('project','building_compare',{
    dataset_id:dataset.id,model_ids:['base','adapted'],evaluate_test:false},'admin'));
  await screen.findByText('Validation results; test regions remain unscored');
  expect(screen.getByRole('cell',{name:'0.800'})).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Evaluate frozen building test regions'));
  fireEvent.click(screen.getByRole('button',{name:'Compare building models'}));
  await waitFor(()=>expect(api.queueGISJob.mock.calls.at(-1)?.[2].evaluate_test).toBe(true));
});

it('imports a verified frozen package and keeps training disabled without its dependencies',async()=>{
  api.getBuildingResearch.mockResolvedValue({datasets:[dataset],training_runtime_available:false,test_policy:'validation only'});
  api.uploadBuildingStudy.mockResolvedValue(dataset);
  render(<BuildingResearchPanel projectId="project" token="admin" models={models} onInstalled={vi.fn()}/>);
  await screen.findByText(/Training: Austin, Vienna/);
  const file=new File(['ZIP fixture'],'study.zip',{type:'application/zip'});
  fireEvent.change(screen.getByLabelText('Building study ZIP'),{target:{files:[file]}});
  await screen.findByText('Imported a verified, region-disjoint building study.');
  expect(api.uploadBuildingStudy).toHaveBeenCalledWith(file,'admin');
  fireEvent.click(screen.getByText('Train or fine-tune a model'));
  expect((screen.getByRole('button',{name:'Train building model'}) as HTMLButtonElement).disabled).toBe(true);
});
